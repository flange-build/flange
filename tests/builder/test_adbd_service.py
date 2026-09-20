"""adbd / usbmoded systemd 服务配置测试。

三层架构重构后，原 usbdevice.service 一个 unit 的职责拆成两个：
  - usbmoded.service       —— gadget 管理服务，承担模块 / ConfigFS 的启动时序
  - usbmoded-adbd.service  —— 只跑 adbd 二进制，承担 adb shell 的运行环境
"""

from pathlib import Path


ADBD_SERVICE = Path("components/app/adbd/systemd/usbmoded-adbd.service")
GADGET_SERVICE = Path("components/app/usbmoded/systemd/usbmoded.service")
CONFIGFS = Path("components/app/usbmoded/usbmoded/configfs.py")
ROOT_BASHRC = Path("components/rootfs/overlay/root/.bashrc")


def test_adbd_service_exports_runtime_environment():
    """adbd 服务必须导出 shell 所需的运行环境。

    adbd 是 adb shell 的父进程，环境只能由跑 adbd 的这个 unit 注入。
    """

    lines = ADBD_SERVICE.read_text(encoding="utf-8").splitlines()
    assert "Environment=TERM=xterm" in lines
    assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" in lines


def test_adbd_shell_uses_linux_tmpdir():
    """adbd 交互 shell 必须覆盖其内建的 Android 临时目录。"""

    assert "export TMPDIR=/tmp" in ROOT_BASHRC.read_text().splitlines()


def test_gadget_service_waits_for_modules_and_configfs():
    """gadget 服务必须在模块加载与 ConfigFS 挂载之后启动。"""
    lines = GADGET_SERVICE.read_text(encoding="utf-8").splitlines()
    after = next(line for line in lines if line.startswith("After="))

    assert "Requires=sys-kernel-config.mount" in lines
    assert set(after.removeprefix("After=").split()) == {
        "systemd-modules-load.service",
        "sys-kernel-config.mount",
        "local-fs.target",
    }


def test_adbd_service_is_driven_by_usbmoded():
    """adbd unit 不得自行编排 gadget 时序 —— 启停完全由 usbmoded 的 adb 能力驱动。

    FunctionFS 要求 daemon 在 gadget 绑定 UDC 之前打开 ep0，这个顺序无法
    用 systemd 依赖表达；一旦这里声明了 After/Requires=usbmoded.service，
    systemd 就会抢在 prepare 阶段之前拉起 adbd。
    """
    lines = ADBD_SERVICE.read_text(encoding="utf-8").splitlines()

    assert not [line for line in lines if line.startswith(("After=", "Requires=", "Wants="))]
    # 没有 [Install] 段 → 不会被 enable，只能由 usbmoded 显式 start。
    assert "[Install]" not in lines


def test_configfs_self_heals_modular_gadget_framework():
    """ConfigFS 存在但 gadget framework 未注册时应自愈并明确报错。

    原 shell 实现的 usb_ensure_gadget_framework 迁移到 configfs.py。
    """
    text = CONFIGFS.read_text(encoding="utf-8")

    assert '"usb_f_fs"' in text
    assert "内核 USB gadget 框架未注册" in text
