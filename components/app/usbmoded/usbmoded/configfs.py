"""configfs / sysfs 低层原语。

本模块只封装对 configfs 与 sysfs 的读写，不含任何 USB function 的知识，
也不含 gadget 生命周期逻辑 —— 后者分别属于 L2 原子能力层与 L1 的
gadget 编排部分。

对应 race-checklist.md 知识 #6（幂等写）。
"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
from pathlib import Path

CONFIGFS_ROOT = Path("/sys/kernel/config")
USB_GADGET_ROOT = CONFIGFS_ROOT / "usb_gadget"


class ConfigfsError(Exception):
    """configfs 操作失败。

    与「属性不存在」区分开：不存在由调用方用 exists() 判断，
    本异常表示实际的读写失败。
    """


def read_attr(path: Path) -> str | None:
    """读取属性，去掉尾部换行。

    属性不存在或不可读时返回 None —— configfs 下大量属性是可选的，
    调用方普遍需要「读不到就当没有」的语义，用异常表达会让调用点充满
    try/except。真正的读失败（如 EIO）仍然抛出。
    """
    try:
        return path.read_text().rstrip("\n")
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENODEV, errno.EACCES):
            return None
        raise ConfigfsError(f"读取属性失败：{path}: {exc}") from exc


def _payload(value: str) -> str:
    """把待写入的值转成 configfs 能正确解析的字节串。

    **空字符串必须写成换行符。** configfs 的 store 回调按写入长度解析内容，
    0 字节写入不会触发回调，"清空属性"这类操作会**静默失效** —— 属性看起来
    写过了，实际纹丝不动。

    这不是理论问题：ROCK 5B 实测，`UDC` 属性写 "" 后回读仍是原 controller
    名，gadget 根本没有解绑。旧 shell 实现用 `echo ""`（输出一个换行符）
    恰好绕过了它。内核在 store 里会剥掉结尾的 \n 得到空串，所以写 "\n"
    与语义上的"清空"等价。

    受影响的操作：解绑 UDC、清空 mass_storage 的 lun.0/file，以及任何
    把属性置空的场景。
    """
    return value if value != "" else "\n"


def write_attr(path: Path, value: str) -> bool:
    """幂等写属性。返回 True 表示实际发生了写入。

    知识 #6：写前先读取比对，值相同则跳过。

    空字符串会被写成换行符，见 _payload —— 0 字节写入不会触发 configfs 的
    store 回调，"清空属性"会静默失效。

    configfs / sysfs 上的属性写入不是无副作用的 —— 即便写入相同的值，
    gadget 框架也可能触发 soft-disconnect 与主机重新枚举。配合「每次
    USB 状态变化都触发重配」的 udev 规则，这会形成无限重置环。因此所有
    属性写入都必须经过本函数，不得直接 write_text。
    """
    current = read_attr(path)
    if current is not None and current == value:
        return False
    try:
        path.write_text(_payload(value))
    except OSError as exc:
        raise ConfigfsError(f"写入属性失败：{path} = {value!r}: {exc}") from exc
    return True


def write_attr_bytes(path: Path, value: bytes) -> bool:
    """幂等写二进制属性。返回 True 表示实际发生了写入。

    用于 HID 的 report_desc、UVC 的 guidFormat 这类二进制描述符。
    幂等语义与 write_attr 相同（知识 #6）。
    """
    try:
        current = path.read_bytes()
    except (FileNotFoundError, OSError):
        current = None
    if current is not None and current == value:
        return False
    try:
        path.write_bytes(value)
    except OSError as exc:
        raise ConfigfsError(f"写入二进制属性失败：{path}: {exc}") from exc
    return True


def write_attr_checked(path: Path, value: str) -> None:
    """写属性并回读校验，不符则抛出。

    知识 #2 的通用形式。写 sysfs 属性时，write() 的返回值不一定反映
    kernel 端的写失败 —— UDC 绑定是最典型的例子（DWC2/DWC3 均如此）。
    对那些「写失败必须立即发现」的属性使用本函数而非 write_attr。
    """
    write_attr(path, value)
    actual = read_attr(path)
    if actual != value:
        raise ConfigfsError(
            f"属性回读校验失败：{path} 期望 {value!r} 实际 {actual!r}"
        )


def ensure_dir(path: Path) -> bool:
    """创建 configfs 目录。返回 True 表示本次创建。

    在 configfs 下创建目录即是让内核实例化对象（如 function 实例），
    因此「已存在」是正常情况而非错误。
    """
    if path.is_dir():
        return False
    try:
        path.mkdir(parents=True)
    except FileExistsError:
        return False
    except OSError as exc:
        raise ConfigfsError(f"创建 configfs 目录失败：{path}: {exc}") from exc
    return True


def remove_dir(path: Path) -> bool:
    """移除 configfs 目录。返回 True 表示本次移除。

    configfs 目录只能用 rmdir 移除，且必须先解除其上的所有引用
    （如 config 下指向它的符号链接），否则返回 EBUSY。
    """
    if not path.is_dir():
        return False
    try:
        path.rmdir()
    except OSError as exc:
        raise ConfigfsError(f"移除 configfs 目录失败：{path}: {exc}") from exc
    return True


def symlink(target: Path, link: Path) -> bool:
    """建立指向 function 实例的符号链接。返回 True 表示本次建立。

    在 configfs 下，config 目录中的符号链接表示「该配置启用此 function」。
    建立链接会触发 function 的 bind，移除会触发 unbind。
    """
    if link.is_symlink() or link.exists():
        return False
    try:
        link.symlink_to(target)
    except OSError as exc:
        raise ConfigfsError(f"建立 configfs 链接失败：{link} -> {target}: {exc}") from exc
    return True


def remove_symlink(link: Path) -> bool:
    """移除符号链接。返回 True 表示本次移除。

    警告：移除指向 FunctionFS 实例的链接会触发 functionfs_unbind，
    使 private_data 置空、ffs_ready 此后永久返回 -EINVAL，持有 endpoint
    文件描述符的 daemon（如 adbd）彻底失效。枚举恢复与断连恢复路径
    MUST NOT 调用本函数 —— 见 race-checklist.md 知识 #4 与 #8。
    """
    if not link.is_symlink():
        return False
    try:
        link.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ConfigfsError(f"移除 configfs 链接失败：{link}: {exc}") from exc
    return True


def is_configfs_mounted() -> bool:
    """判断 configfs 是否已挂载且 gadget 框架可用。"""
    return USB_GADGET_ROOT.is_dir()


def _is_mountpoint(path: Path) -> bool:
    try:
        return path.is_mount()
    except OSError:
        return False


def ensure_configfs() -> None:
    """确保 configfs 已挂载且内核 gadget 框架可用。

    与既有 shell 实现的 usb_ensure_gadget_framework 保持等价：先尝试加载
    模块，再兜底挂载 configfs，仍不可用才报错。

    正常路径下 configfs 由 systemd 的 sys-kernel-config.mount 挂载，服务
    unit 已声明对它的依赖；这里的加载与挂载是兜底，覆盖 unit 依赖未生效
    或被手工调用的场景。

    走到最后仍不可用说明内核缺少 CONFIGFS_FS 或 USB_LIBCOMPOSITE，属于
    构建配置问题而非运行时竞态，因此明确报错、不重试。
    """
    if USB_GADGET_ROOT.is_dir():
        return

    # 加载 usb_f_fs 会连带引入 libcomposite，后者才是注册 usb_gadget 目录的
    # 模块。内核内建时 modprobe 失败属正常，忽略返回码。
    modprobe = shutil.which("modprobe")
    if modprobe:
        subprocess.run(
            [modprobe, "usb_f_fs"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not _is_mountpoint(CONFIGFS_ROOT):
        CONFIGFS_ROOT.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["mount", "-t", "configfs", "none", str(CONFIGFS_ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and not USB_GADGET_ROOT.is_dir():
            raise ConfigfsError(
                f"configfs 挂载失败：{CONFIGFS_ROOT}: {result.stderr.strip()}"
            )

    if USB_GADGET_ROOT.is_dir():
        return

    raise ConfigfsError(
        f"内核 USB gadget 框架未注册（{USB_GADGET_ROOT} 不存在）——"
        " 确认 usb_f_fs / libcomposite 已加载或内建"
    )


def list_dir(path: Path) -> list[str]:
    """列出目录项，目录不存在时返回空列表。"""
    try:
        return sorted(os.listdir(path))
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as exc:
        raise ConfigfsError(f"列出目录失败：{path}: {exc}") from exc
