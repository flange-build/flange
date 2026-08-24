"""deb 打包核心引擎 — 将文件树与控制元数据组合为标准 .deb 归档包。

.deb 格式为 ar 归档，内含三个成员：
  - debian-binary:   格式版本号（"2.0\\n"）
  - control.tar.gz:  控制文件包（control、conffiles、postinst、prerm 等）
  - data.tar.gz:     实际安装文件树

本模块使用 Python 标准库 tarfile 构建 tar.gz，使用纯 Python 实现的 ar 写入器
组合 .deb，无需依赖系统 ar 命令（避免 macOS/Linux ar 差异问题）。
"""

from __future__ import annotations

import io
import re
import tarfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from builder.app_spec import AppSpec


# ---------------------------------------------------------------------------
# 架构映射表：config 架构 → deb 架构
# ---------------------------------------------------------------------------

_ARCH_MAP: Dict[str, str] = {
    "aarch64": "arm64",
    "armhf":   "armhf",
    "x86_64":  "amd64",
    "i386":    "i386",
    "riscv64": "riscv64",
}


class DebBuildError(RuntimeError):
    """deb 构建失败时抛出。"""


# ---------------------------------------------------------------------------
# 安全校验
# ---------------------------------------------------------------------------

_SAFE_SHELL_RE = re.compile(r'^[a-zA-Z0-9._@:/-]+$')


def _validate_shell_safe(value: str, context: str) -> None:
    """校验值不包含 shell 元字符，防止脚本注入。

    参数：
        value:   待校验的字符串
        context: 错误提示上下文描述
    抛出：
        DebBuildError: 若 value 包含不安全字符
    """
    if not _SAFE_SHELL_RE.match(value):
        raise DebBuildError(f"{context} 包含不安全字符: {value!r}")


def _map_arch(arch: str) -> str:
    """将 config 架构名转换为 deb 架构名。

    参数：
        arch: 配置架构名，如 aarch64、armhf
    返回：
        deb 包架构名，如 arm64、armhf
    """
    return _ARCH_MAP.get(arch, arch)


# ---------------------------------------------------------------------------
# 控制文件生成
# ---------------------------------------------------------------------------

def _generate_control_text(
    name: str,
    version: str,
    arch: str,
    maintainer: str,
    description: str,
    depends: List[str],
    extra_fields: Optional[Dict[str, str]] = None,
) -> str:
    """生成 control 文件文本。

    参数：
        name:        包名
        version:     版本号
        arch:        deb 目标架构
        maintainer:  维护者字符串（格式：Name <email>）
        description: 包描述
        depends:     运行期依赖列表
        extra_fields: 附加控制字段（可选）
    返回：
        control 文件内容字符串
    """
    lines: List[str] = [
        f"Package: {name}",
        f"Version: {version}",
        f"Architecture: {arch}",
        f"Maintainer: {maintainer}",
    ]

    if depends:
        lines.append(f"Depends: {', '.join(depends)}")

    # 附加可选字段
    if extra_fields:
        for key, value in extra_fields.items():
            lines.append(f"{key}: {value}")

    # Description 必须是最后一个字段，多行描述以空格缩进
    desc_lines = description.splitlines()
    if desc_lines:
        lines.append(f"Description: {desc_lines[0]}")
        for line in desc_lines[1:]:
            # 空行用 " ." 表示
            lines.append(f" {line}" if line.strip() else " .")
    else:
        lines.append("Description: (no description)")

    return "\n".join(lines) + "\n"


def _generate_conffiles_text(conffiles: List[str]) -> str:
    """生成 conffiles 文件文本。

    注意：dpkg 将空行视为无效路径，必须过滤。

    参数：
        conffiles: 配置文件路径列表（绝对路径）
    返回：
        conffiles 文件内容（无尾随空行）
    """
    # 过滤空行和空白行
    valid = [p.strip() for p in conffiles if p.strip()]
    if not valid:
        return ""
    return "\n".join(valid) + "\n"


def _generate_postinst(service_name: str, data_dirs: List[str]) -> str:
    """生成 postinst 脚本，兼容 chroot 环境。

    chroot 中没有 /run/systemd/system，无法直接调用 systemctl。
    兼容策略：检测 /run/systemd/system 存在性，若不存在则手动创建软链接。

    参数：
        service_name: systemd service unit 文件名（如 my-daemon.service）
        data_dirs:    需要在安装时创建的数据目录列表
    返回：
        postinst 脚本内容字符串
    """
    _validate_shell_safe(service_name, "service_name")

    mkdir_lines: List[str] = []
    for d in data_dirs:
        d = d.strip()
        if d:
            _validate_shell_safe(d, "data_dirs 条目")
            mkdir_lines.append(f"    mkdir -p {d}")
    mkdir_block = "\n".join(mkdir_lines) if mkdir_lines else "    # 无需创建数据目录"

    script = f"""\
#!/bin/bash
set -e

# 启用 systemd 服务（兼容 chroot 环境）
if [ -d /run/systemd/system ]; then
    # 运行中的系统：通过 systemctl 启用
    systemctl daemon-reload
    systemctl enable {service_name}
else
    # chroot 环境：手动创建 .wants 软链接
    WANTED_BY=$(grep "^WantedBy=" /lib/systemd/system/{service_name} 2>/dev/null | cut -d= -f2)
    for target in $WANTED_BY; do
        mkdir -p /etc/systemd/system/$target.wants
        ln -sf /lib/systemd/system/{service_name} /etc/systemd/system/$target.wants/
    done
fi

# 创建运行时数据目录
{mkdir_block}
"""
    return script


def _generate_prerm(service_name: str) -> str:
    """生成 prerm 脚本。

    在软件包移除前停止并禁用 systemd 服务。
    在 chroot 中 /run/systemd/system 不存在，跳过 systemctl 操作。

    参数：
        service_name: systemd service unit 文件名
    返回：
        prerm 脚本内容字符串
    """
    _validate_shell_safe(service_name, "service_name")

    return f"""\
#!/bin/bash
set -e

# 停止并禁用 systemd 服务（仅在运行中的系统执行）
if [ -d /run/systemd/system ]; then
    systemctl stop {service_name} 2>/dev/null || true
    systemctl disable {service_name} 2>/dev/null || true
fi
"""


def generate_control(spec: AppSpec, arch: str) -> Dict[str, str]:
    """从 AppSpec 生成 control 目录下的所有文件内容。

    参数：
        spec: 已解析的 AppSpec 对象
        arch: 目标架构（config 格式，如 aarch64）
    返回：
        文件名 → 文件内容的字典，键包括：
        - "control":    必须存在
        - "conffiles":  仅当 spec.conffiles 非空时存在
        - "postinst":   仅当 app.type == "service" 且有 systemd 配置时存在
        - "prerm":      同上
        - vendor 在 maintainer_scripts 中显式映射的维护脚本与 triggers
    """
    deb_arch = _map_arch(arch)
    maintainer_str = f"{spec.maintainer.name} <{spec.maintainer.email}>"

    control_text = _generate_control_text(
        name=spec.app.name,
        version=spec.app.version,
        arch=deb_arch,
        maintainer=maintainer_str,
        description=spec.app.description,
        depends=spec.depends,
    )

    result: Dict[str, str] = {"control": control_text}

    # conffiles（过滤空行）
    if spec.conffiles:
        conffiles_text = _generate_conffiles_text(spec.conffiles)
        if conffiles_text:
            result["conffiles"] = conffiles_text

    # postinst / prerm（仅 service 类型且有 systemd 配置）
    if spec.app.type == "service" and spec.systemd and spec.systemd.unit:
        # 从 unit 路径提取文件名（如 systemd/my.service → my.service）
        service_name = Path(spec.systemd.unit).name
        result["postinst"] = _generate_postinst(service_name, spec.data_dirs)
        result["prerm"] = _generate_prerm(service_name)

    # vendor 参考包的脚本必须先完成平台适配，再由 app.yaml 显式映射。
    result.update(spec.maintainer_scripts)

    return result


# ---------------------------------------------------------------------------
# tar.gz 构建辅助
# ---------------------------------------------------------------------------

def _build_control_tar(control_files: Dict[str, str]) -> bytes:
    """将控制文件字典打包为 control.tar.gz bytes。

    参数：
        control_files: 文件名 → 文件内容的字典
    返回：
        control.tar.gz 的字节内容
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # 添加根目录 "./"
        dir_info = tarfile.TarInfo(name="./")
        dir_info.type = tarfile.DIRTYPE
        dir_info.mode = 0o755
        tf.addfile(dir_info)

        for filename, content in control_files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"./{filename}")
            info.size = len(data)
            # postinst / prerm 需要可执行权限
            if filename in ("postinst", "prerm", "postrm", "preinst"):
                info.mode = 0o755
            else:
                info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))

    return buf.getvalue()


def _build_data_tar(
    files: List[Tuple[Path, str, int]],
) -> bytes:
    """将文件列表打包为 data.tar.gz bytes。

    参数：
        files: (src_path, install_path, mode) 三元组列表
               - src_path:    宿主机上的源文件路径
               - install_path: 目标系统的安装绝对路径（如 /usr/bin/foo）
               - mode:        文件权限（如 0o755）
    返回：
        data.tar.gz 的字节内容
    """
    buf = io.BytesIO()
    # 记录已添加的目录，避免重复
    added_dirs: set = set()

    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # 添加根目录 "./"
        root_info = tarfile.TarInfo(name="./")
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        tf.addfile(root_info)
        added_dirs.add("./")

        for src_path, install_path, mode in files:
            # 将绝对路径转换为相对于根的 tar 路径（"./" 前缀）
            # 例如 /usr/bin/foo → ./usr/bin/foo
            install_path = install_path.lstrip("/")
            tar_path = f"./{install_path}"

            # 确保父目录已添加（按层级递归）
            _ensure_parent_dirs(tf, tar_path, added_dirs)

            # 添加文件
            info = tarfile.TarInfo(name=tar_path)
            info.mode = mode

            src = Path(src_path)
            if src.is_symlink():
                # 符号链接
                info.type = tarfile.SYMTYPE
                info.linkname = str(src.readlink())
                info.size = 0
                tf.addfile(info)
            elif src.is_file():
                raw = src.read_bytes()
                info.size = len(raw)
                tf.addfile(info, io.BytesIO(raw))
            else:
                raise DebBuildError(f"源路径不存在或不是普通文件：{src_path}")

    return buf.getvalue()


def _ensure_parent_dirs(
    tf: tarfile.TarFile,
    tar_path: str,
    added_dirs: set,
) -> None:
    """递归确保 tar_path 的所有父目录已被添加到 tf 中。

    参数：
        tf:         正在写入的 TarFile 对象
        tar_path:   目标文件的 tar 路径（如 ./usr/bin/foo）
        added_dirs: 已添加目录集合（会被修改）
    """
    parts = tar_path.split("/")
    # 从 "./" 开始逐级构建目录路径
    for i in range(2, len(parts)):  # parts[0]=".", parts[1]="usr", ...
        dir_path = "/".join(parts[:i]) + "/"
        if dir_path not in added_dirs:
            dir_info = tarfile.TarInfo(name=dir_path)
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            tf.addfile(dir_info)
            added_dirs.add(dir_path)


# ---------------------------------------------------------------------------
# DebBuilder 主类
# ---------------------------------------------------------------------------

def _write_ar(output_path: Path, members: List[tuple[str, bytes]]) -> None:
    """以纯 Python 实现的 ar 归档写入器，生成符合 POSIX ar 格式的归档文件。

    .deb 包使用标准 ar 格式（非 System V / GNU ar 扩展），无需符号表。
    格式规范：
      - 全局 magic：b"!<arch>\\n"（8 字节）
      - 每个成员头：60 字节定长，字段均为 ASCII 文本，右填充空格
      - 成员数据：字节内容；若长度为奇数，尾部追加 \\n 填充至偶数边界

    参数：
        output_path: 输出 ar 文件路径
        members:     (filename, data) 元组列表，按顺序写入
    """
    with output_path.open("wb") as f:
        # ar 全局 magic
        f.write(b"!<arch>\n")

        for filename, data in members:
            # ar 成员头（60 字节）：
            #   文件名（16 字节）、修改时间（12 字节）、uid（6 字节）、
            #   gid（6 字节）、权限（8 字节）、文件大小（10 字节）、结束 magic（2 字节）
            name_field = filename.encode("ascii")[:16].ljust(16)
            mtime_field = b"0           "          # 12 字节，固定 0
            uid_field   = b"0     "                # 6 字节
            gid_field   = b"0     "                # 6 字节
            mode_field  = b"100644  "              # 8 字节
            size_field  = str(len(data)).encode("ascii").ljust(10)
            end_magic   = b"\x60\x0a"              # 2 字节

            header = (
                name_field
                + mtime_field
                + uid_field
                + gid_field
                + mode_field
                + size_field
                + end_magic
            )
            assert len(header) == 60, f"ar 头长度错误：{len(header)}"

            f.write(header)
            f.write(data)
            # ar 要求成员数据按 2 字节对齐，奇数长度补 \n
            if len(data) % 2 != 0:
                f.write(b"\n")


class DebBuilder:
    """deb 包构建器。

    将文件树与控制元数据组合为标准 .deb 归档包。
    使用 Python tarfile 构建内部 tar.gz，使用纯 Python ar 写入器生成最终 .deb，
    无需依赖系统 ar 命令。

    典型用法：
        builder = DebBuilder()
        deb_path = builder.build_deb(
            name="my-daemon",
            version="1.0.0",
            arch="aarch64",
            control_fields={"control": ..., "conffiles": ..., "postinst": ...},
            files=[(Path("bin/my-daemon"), "/usr/bin/my-daemon", 0o755)],
            output_dir=Path("dist"),
        )
    """

    def build_deb(
        self,
        name: str,
        version: str,
        arch: str,
        control_fields: Dict[str, str],
        files: List[Tuple[Path, str, int]],
        output_dir: Path,
    ) -> Path:
        """构建 .deb 包。

        参数：
            name:           包名（如 my-daemon）
            version:        版本号（如 1.0.0）
            arch:           目标架构（config 格式，如 aarch64；或已是 deb 格式，如 arm64）
            control_fields: 控制文件内容字典，键为文件名（control/conffiles/postinst/prerm）
            files:          安装文件列表，每项为 (src_path, install_path, mode)
            output_dir:     .deb 输出目录
        返回：
            生成的 .deb 文件路径
        抛出：
            DebBuildError: 构建过程出错
        """
        # arch 可能已是 deb 格式（arm64），也可能是 config 格式（aarch64），统一映射一次
        deb_arch = _map_arch(arch)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        deb_filename = f"{name}_{version}_{deb_arch}.deb"
        deb_path = output_dir / deb_filename

        # 1. 构建 debian-binary 内容
        debian_binary_data = b"2.0\n"

        # 2. 构建 control.tar.gz
        control_tar_data = _build_control_tar(control_fields)

        # 3. 构建 data.tar.gz
        data_tar_data = _build_data_tar(files)

        # 4. 使用纯 Python ar 写入器组合为 .deb
        _write_ar(deb_path, [
            ("debian-binary",  debian_binary_data),
            ("control.tar.gz", control_tar_data),
            ("data.tar.gz",    data_tar_data),
        ])

        return deb_path

    def build_from_spec(
        self,
        spec: AppSpec,
        arch: str,
        files: List[Tuple[Path, str, int]],
        output_dir: Path,
    ) -> Path:
        """从 AppSpec 直接构建 .deb 包（便捷方法）。

        参数：
            spec:       已解析的 AppSpec 对象
            arch:       目标架构（config 格式，如 aarch64）
            files:      安装文件列表，每项为 (src_path, install_path, mode)
            output_dir: .deb 输出目录
        返回：
            生成的 .deb 文件路径
        """
        control_fields = generate_control(spec, arch)
        return self.build_deb(
            name=spec.app.name,
            version=spec.app.version,
            arch=arch,
            control_fields=control_fields,
            files=files,
            output_dir=output_dir,
        )
