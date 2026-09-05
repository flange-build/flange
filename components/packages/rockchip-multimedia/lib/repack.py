"""把四个 GStreamer 编译单元的产物按 Ubuntu Noble 的分包边界重打成 deb。

为什么不直接把 DESTDIR 塞进四个粗粒度包：Noble 的模板携带 Source /
Installed-Size / Breaks / Replaces / Provides / Multi-Arch / Gstreamer-Elements
等十余个字段，以及 md5sums / shlibs / symbols / triggers / postinst，还隐含
14 个包之间的精确文件归属拆分。用模板覆盖重打，等于把这份维护成本外包给
Ubuntu，目标 rootfs 因而不需要 --force-overwrite 或 APT hold。

为什么它是独立的一个单元而不是某个编译单元的尾巴：分包边界与编译单元边界
并不重合 —— 已验证 ``gstreamer1.0-plugins-good`` 与
``libgstreamer-plugins-good1.0-0`` 两个 deb 里实际含有来自 gst-plugins-bad
staging 的文件。所以重打必须在四个单元**全部就绪之后**做一次。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from builder.apt import AptCache

from toolkit import (
    OUTPUT_ROOT,
    REPACK_DEPS,
    SYSROOT,
    TEMPLATE_PACKAGES,
    TEMPLATE_WORK,
    TemplatePackage,
    clean_work_path,
    compose_sysroot,
    copy_entry,
    run,
    upstream_stage,
    validate_debs,
)


def download_template(package: TemplatePackage) -> Path:
    """通过已签名 Noble APT 索引下载固定 ARM64 binary package。"""
    from toolkit import DOWNLOAD_ROOT

    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_ROOT / package.filename()
    if target.is_file():
        return target
    cache = AptCache.for_tool(Path(os.environ["FLANGE_PROJECT_ROOT"]))
    with cache.locked():
        # 模板解析会读取共享索引，必须与其他工作区的 update 协调。
        run(["apt-get", "download", *cache.options, f"{package.name}:arm64={package.version}"],
            cwd=DOWNLOAD_ROOT)
    if not target.is_file():
        raise RuntimeError(f"APT 未生成模板 DEB: {target.name}")
    return target


def template_data_paths(package_root: Path) -> set[Path]:
    """返回模板 data archive 的全部普通文件和符号链接路径。"""
    result: set[Path] = set()
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        if relative.parts and relative.parts[0] == "DEBIAN":
            continue
        if path.is_file() or path.is_symlink():
            result.add(relative)
    return result


def is_development_path(relative: Path) -> bool:
    """判断 staging 中允许不发布到 runtime template 的开发文件。"""
    if any(
        relative.is_relative_to(Path(path))
        for path in (
            "usr/share/aclocal",
            "usr/share/gdb",
            "usr/share/gstreamer-1.0/gdb",
            "usr/share/man",
        )
    ):
        return True
    if ("include" in relative.parts or "pkgconfig" in relative.parts
            or "cmake" in relative.parts
            or relative.name.endswith((".a", ".la"))):
        return True
    return (
        relative.name.endswith(".so")
        and relative.parent.as_posix()
        in {"usr/lib", "usr/lib/aarch64-linux-gnu"}
    )


def validate_stage_mapping(stages: list[Path], mapped: set[Path]) -> None:
    """拒绝悄悄丢弃新增的 runtime library、plugin 或 executable。

    模板一旦过期（上游新增了插件而 Noble 的分包里还没有），这里会在构建期
    硬失败，而不是让文件静默消失、到运行期才发现缺插件。
    """
    missing: list[str] = []
    for stage in stages:
        for source in stage.rglob("*"):
            if not (source.is_file() or source.is_symlink()):
                continue
            relative = source.relative_to(stage)
            if relative not in mapped and not is_development_path(relative):
                missing.append(f"{stage.parent.parent.name}:{relative.as_posix()}")
    if missing:
        raise RuntimeError(
            "GStreamer runtime 文件没有 Noble 分包归属:\n  "
            + "\n  ".join(sorted(missing))
        )


def write_md5sums(package_root: Path) -> None:
    lines: list[str] = []
    for path in sorted(package_root.rglob("*")):
        relative = path.relative_to(package_root)
        if relative.parts and relative.parts[0] == "DEBIAN":
            continue
        if path.is_file() and not path.is_symlink():
            digest = hashlib.md5(
                path.read_bytes(), usedforsecurity=False).hexdigest()
            lines.append(f"{digest}  {relative.as_posix()}")
    (package_root / "DEBIAN/md5sums").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def validate_webrtc() -> None:
    """保证 WebRTC / DTLS / SRTP runtime 全部生成（gst-plugins-bad 的产物）。"""
    plugin_dir = SYSROOT / "usr/lib/aarch64-linux-gnu/gstreamer-1.0"
    required = [
        plugin_dir / "libgstwebrtc.so",
        plugin_dir / "libgstdtls.so",
        plugin_dir / "libgstsrtp.so",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if not list(plugin_dir.parent.glob("libgstwebrtcnice-1.0.so.0*")):
        missing.append(str(plugin_dir.parent / "libgstwebrtcnice-1.0.so.0*"))
    if missing:
        raise RuntimeError("WebRTC runtime 缺失: " + ", ".join(missing))


def repack() -> list[Path]:
    """覆盖 Noble 分包模板并重打为较高的 flange 修订版本。"""
    extracted: dict[TemplatePackage, Path] = {}
    mapped: set[Path] = set()
    for package in TEMPLATE_PACKAGES:
        package_root = TEMPLATE_WORK / package.name
        run(["dpkg-deb", "--raw-extract",
             str(download_template(package)), str(package_root)])
        extracted[package] = package_root
        mapped.update(template_data_paths(package_root))

    validate_stage_mapping([upstream_stage(app) for app in REPACK_DEPS], mapped)

    outputs: list[Path] = []
    for package, package_root in extracted.items():
        for relative in template_data_paths(package_root):
            source = SYSROOT / relative
            if source.is_file() or source.is_symlink():
                copy_entry(source, package_root / relative)

        control_path = package_root / "DEBIAN/control"
        control = control_path.read_text(encoding="utf-8")
        # 全量替换是必需的：三个模板的 Depends 里含 "(= 同版本)" 的同族包
        # 引用，只改 Version 字段会让它们指向不存在的版本。
        control = control.replace(package.version, package.flange_version)
        control_lines = [
            "Maintainer: flange <flange@localhost>"
            if line.startswith("Maintainer:") else line
            for line in control.splitlines()
        ]
        control_path.write_text("\n".join(control_lines) + "\n",
                                encoding="utf-8")
        write_md5sums(package_root)

        output = OUTPUT_ROOT / package.filename(package.flange_version)
        run(["dpkg-deb", "--root-owner-group", "--build",
             str(package_root), str(output)])
        run(["dpkg", "--compare-versions",
             package.flange_version, "gt", package.version])
        outputs.append(output)
    return outputs


def build() -> None:
    """重打单元入口：合成四个 gst 单元的产物 → 校验 → 重打 14 个 deb。"""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    compose_sysroot(REPACK_DEPS)
    validate_webrtc()
    clean_work_path(TEMPLATE_WORK)
    TEMPLATE_WORK.mkdir(parents=True, exist_ok=True)
    outputs = repack()
    validate_debs(outputs)
    print(f"重打 {len(outputs)} 个 Noble 模板 DEB", flush=True)
