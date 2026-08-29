#!/usr/bin/env python3
"""在 flange 构建容器内交叉编译并重打 Rockchip 多媒体 runtime DEB。"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from builder.deb import DebBuilder


GST_VERSION = "1.24.2"
MIRRORS_GIT = "https://github.com/JeffyCN/mirrors.git"
JOBS = str(os.cpu_count() or 1)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PATCH_ROOT = PACKAGE_ROOT / "patches"
BUILD_ROOT = Path(os.environ["FLANGE_BUILD_ROOT"]).resolve()
WORK_ROOT = Path(os.environ["FLANGE_APP_WORK_DIR"]).resolve()
OUTPUT_ROOT = Path(os.environ["FLANGE_APP_OUTPUT_DIR"]).resolve()
TARGET_ARCH = os.environ["FLANGE_TARGET_ARCH"]
SOURCE_ROOT = BUILD_ROOT / "sources" / "rockchip-multimedia"
DOWNLOAD_ROOT = SOURCE_ROOT / "downloads"
GIT_ROOT = SOURCE_ROOT / "git"
SOURCE_WORK_ROOT = WORK_ROOT / "sources"
BUILD_WORK_ROOT = WORK_ROOT / "build"
STAGE_ROOT = WORK_ROOT / "stage"
SYSROOT = WORK_ROOT / "sysroot"
TEMPLATE_ROOT = WORK_ROOT / "templates"


@dataclass(frozen=True)
class TarSource:
    name: str
    sha256: str

    @property
    def filename(self) -> str:
        return f"{self.name}-{GST_VERSION}.tar.xz"

    @property
    def url(self) -> str:
        return (
            f"https://gstreamer.freedesktop.org/src/{self.name}/"
            f"{self.filename}"
        )


@dataclass(frozen=True)
class GitSource:
    name: str
    branch: str
    commit: str


@dataclass(frozen=True)
class TemplatePackage:
    name: str
    version: str

    @property
    def flange_version(self) -> str:
        return f"{self.version}+flange1"

    def filename(self, version: str | None = None) -> str:
        return f"{self.name}_{version or self.version}_arm64.deb"


GST_SOURCES = (
    TarSource(
        "gstreamer",
        "9cafdd23bd180f1681c56cd3a6879a8497ccf24da6f422a6b6f356fa074a8481",
    ),
    TarSource(
        "gst-plugins-base",
        "282f1cc8065c9b62eb6a0a20fb9e8328f8e5296df2458b7236daa729c41ae769",
    ),
    TarSource(
        "gst-plugins-good",
        "6e347c72d4b8b2886d890ffe9f6767a9edb02f201588e8c3a572dcd08d9852bd",
    ),
    TarSource(
        "gst-plugins-bad",
        "448e32787bc82b586c6cb2f81c9a8ef404fea4f77f25566fe06e597a3f59136b",
    ),
)

GIT_SOURCES = (
    GitSource(
        "rockchip-mpp",
        "mpp-dev-2024_06_27",
        "b29e4b798d28a5d0709bff87479d17f247645bc8",
    ),
    GitSource(
        "rockchip-librga",
        "linux-rga-multi",
        "c6105b06ade0e5dc7f16924c7f0f5e9dcdb198bc",
    ),
    GitSource(
        "gstreamer1.0-rockchip",
        "gstreamer-rockchip",
        "c37e7cf10283521c262f9e71fd9be0422a457989",
    ),
)

TEMPLATE_PACKAGES = (
    TemplatePackage("libgstreamer1.0-0", "1.24.2-1ubuntu0.1"),
    TemplatePackage("gstreamer1.0-tools", "1.24.2-1ubuntu0.1"),
    TemplatePackage("gstreamer1.0-plugins-base-apps", "1.24.2-1ubuntu0.4"),
    TemplatePackage("libgstreamer-plugins-base1.0-0", "1.24.2-1ubuntu0.4"),
    TemplatePackage("libgstreamer-gl1.0-0", "1.24.2-1ubuntu0.4"),
    TemplatePackage("gstreamer1.0-alsa", "1.24.2-1ubuntu0.4"),
    TemplatePackage("gstreamer1.0-plugins-base", "1.24.2-1ubuntu0.4"),
    TemplatePackage("gstreamer1.0-x", "1.24.2-1ubuntu0.4"),
    TemplatePackage("gstreamer1.0-gl", "1.24.2-1ubuntu0.4"),
    TemplatePackage("gstreamer1.0-plugins-good", "1.24.2-1ubuntu1.5"),
    TemplatePackage("libgstreamer-plugins-good1.0-0", "1.24.2-1ubuntu1.5"),
    TemplatePackage("gstreamer1.0-plugins-bad-apps", "1.24.2-1ubuntu4"),
    TemplatePackage("gstreamer1.0-plugins-bad", "1.24.2-1ubuntu4"),
    TemplatePackage("libgstreamer-plugins-bad1.0-0", "1.24.2-1ubuntu4"),
)


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """执行单个 argv 命令，失败即终止。"""
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def clean_work_path(path: Path) -> None:
    """只允许清理当前 App 工作目录内的派生物。"""
    resolved = path.resolve()
    if resolved == WORK_ROOT or not resolved.is_relative_to(WORK_ROOT):
        raise RuntimeError(f"拒绝清理 App 工作目录外路径: {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_tarball(source: TarSource) -> Path:
    """下载并校验固定 GStreamer release tarball。"""
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_ROOT / source.filename
    if target.is_file() and sha256_file(target) == source.sha256:
        return target
    target.unlink(missing_ok=True)
    partial = target.with_suffix(target.suffix + ".download")
    partial.unlink(missing_ok=True)
    run(["wget", "-q", "--show-progress", "-O", str(partial), source.url])
    actual = sha256_file(partial)
    if actual != source.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"{source.filename} SHA256 不匹配: {actual} != {source.sha256}"
        )
    partial.replace(target)
    return target


def prepare_gstreamer_source(source: TarSource) -> Path:
    """解压干净源码并按文件名顺序应用 package 内补丁。"""
    tarball = ensure_tarball(source)
    source_dir = SOURCE_WORK_ROOT / f"{source.name}-{GST_VERSION}"
    clean_work_path(source_dir)
    SOURCE_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:xz") as archive:
        archive.extractall(SOURCE_WORK_ROOT, filter="data")
    patches = sorted((PATCH_ROOT / source.name).glob("*.patch"))
    if not patches:
        raise RuntimeError(f"{source.name} 没有迁移任何 Rockchip 补丁")
    for patch in patches:
        run(
            ["patch", "-p1", "--forward", "--batch", "-i", str(patch)],
            cwd=source_dir,
        )
    return source_dir


def ensure_git_source(source: GitSource) -> Path:
    """确保 Rockchip 固定 branch/commit 的干净 checkout。"""
    GIT_ROOT.mkdir(parents=True, exist_ok=True)
    source_dir = GIT_ROOT / source.name
    if not (source_dir / ".git").is_dir():
        if source_dir.exists():
            shutil.rmtree(source_dir)
        run(
            [
                "git", "clone", "--branch", source.branch, "--single-branch",
                MIRRORS_GIT, str(source_dir),
            ]
        )
    run(["git", "fetch", "origin", source.branch], cwd=source_dir)
    run(["git", "checkout", "--detach", source.commit], cwd=source_dir)
    run(["git", "reset", "--hard", source.commit], cwd=source_dir)
    run(["git", "clean", "-ffdqx"], cwd=source_dir)
    return source_dir


def prepare_cross_file() -> tuple[Path, dict[str, str]]:
    """准备 Meson cross-file 与目标架构 pkg-config 搜索路径。"""
    cross_file = Path("/etc/meson/cross-aarch64.ini")
    pkgconfig_dirs = [
        SYSROOT / "usr/lib/aarch64-linux-gnu/pkgconfig",
        SYSROOT / "usr/lib/pkgconfig",
        SYSROOT / "usr/share/pkgconfig",
        Path("/usr/lib/aarch64-linux-gnu/pkgconfig"),
        Path("/usr/share/pkgconfig"),
    ]
    env = os.environ.copy()
    env.pop("PKG_CONFIG_PATH", None)
    env["PKG_CONFIG_LIBDIR"] = ":".join(str(path) for path in pkgconfig_dirs)
    env["CFLAGS"] = (
        f"-D_LARGEFILE64_SOURCE -D_FILE_OFFSET_BITS=64 "
        f"-I{SYSROOT}/usr/include"
    )
    env["CXXFLAGS"] = env["CFLAGS"]
    env["LDFLAGS"] = (
        f"-L{SYSROOT}/usr/lib/aarch64-linux-gnu "
        f"-L{SYSROOT}/usr/lib -Wl,-rpath-link,{SYSROOT}/usr/lib/aarch64-linux-gnu"
    )
    return cross_file, env


def merge_stage(stage: Path) -> None:
    """把当前组件的安装树合入后续组件共用的交叉编译 sysroot。"""
    entries = sorted(
        stage.rglob("*"),
        key=lambda path: (path.is_symlink(), path.as_posix()),
    )
    for source in entries:
        target = SYSROOT / source.relative_to(stage)
        if source.is_dir() and not source.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file() or source.is_symlink():
            copy_entry(source, target)
    for source in stage.rglob("*.pc"):
        target = SYSROOT / source.relative_to(stage)
        content = target.read_text(encoding="utf-8")
        target.write_text(
            content.replace("prefix=/usr\n", f"prefix={SYSROOT}/usr\n", 1),
            encoding="utf-8",
        )


def build_mpp(source_dir: Path, env: dict[str, str]) -> Path:
    build_dir = BUILD_WORK_ROOT / "rockchip-mpp"
    stage = STAGE_ROOT / "rockchip-mpp"
    run(
        [
            "cmake", "-S", str(source_dir), "-B", str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=/usr",
            "-DCMAKE_INSTALL_LIBDIR=lib/aarch64-linux-gnu",
            "-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
            "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc",
            "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++",
            "-DBUILD_TEST=OFF",
        ],
        env=env,
    )
    run(["cmake", "--build", str(build_dir), f"-j{JOBS}"], env=env)
    install_env = {**env, "DESTDIR": str(stage)}
    run(["cmake", "--install", str(build_dir)], env=install_env)
    merge_stage(stage)
    return stage


def build_meson(
    label: str,
    source_dir: Path,
    cross_file: Path,
    env: dict[str, str],
    options: list[str],
) -> Path:
    build_dir = BUILD_WORK_ROOT / label
    stage = STAGE_ROOT / label
    run(
        [
            "meson", "setup", str(build_dir), str(source_dir),
            "--cross-file", str(cross_file), "--prefix=/usr",
            "--libdir=lib/aarch64-linux-gnu", "--buildtype=release",
            "--wrap-mode=nodownload", *options,
        ],
        env=env,
    )
    compile_command = [
        "meson", "compile", "-C", str(build_dir), "-j", JOBS,
    ]
    try:
        run(compile_command, env=env)
    except subprocess.CalledProcessError:
        # Docker Desktop 的 Rosetta 并发执行偶发失败；Ninja 增量重试可恢复。
        print("Meson 编译失败，增量重试一次", flush=True)
        run(compile_command, env=env)
    run(
        ["meson", "install", "-C", str(build_dir), "--destdir", str(stage)],
        env=env,
    )
    merge_stage(stage)
    return stage


def runtime_files(stage: Path) -> list[tuple[Path, str, int]]:
    """收集 runtime 文件，排除 headers、pkg-config、CMake 与 static library。"""
    files: list[tuple[Path, str, int]] = []
    for source in sorted(stage.rglob("*")):
        if not (source.is_file() or source.is_symlink()):
            continue
        relative = source.relative_to(stage)
        if (
            "include" in relative.parts
            or "pkgconfig" in relative.parts
            or "cmake" in relative.parts
            or source.name.endswith((".a", ".la"))
        ):
            continue
        if source.is_symlink() and source.name.endswith(".so"):
            parent = relative.parent.as_posix()
            if parent in {"usr/lib", "usr/lib/aarch64-linux-gnu"}:
                continue
        mode = stat.S_IMODE(source.lstat().st_mode)
        files.append((source, f"/{relative.as_posix()}", mode))
    if not files:
        raise RuntimeError(f"runtime staging 为空: {stage}")
    return files


def build_vendor_deb(
    name: str,
    version: str,
    description: str,
    depends: list[str],
    stage: Path,
) -> Path:
    """使用 flange DebBuilder 生成没有开发文件的厂商 runtime 包。"""
    control = "\n".join(
        [
            f"Package: {name}",
            f"Version: {version}",
            "Architecture: arm64",
            "Maintainer: flange <flange@localhost>",
            f"Depends: {', '.join(depends)}",
            f"Description: {description}",
            "",
        ]
    )
    return DebBuilder().build_deb(
        name=name,
        version=version,
        arch="aarch64",
        control_fields={"control": control},
        files=runtime_files(stage),
        output_dir=OUTPUT_ROOT,
    )


def download_template(package: TemplatePackage) -> Path:
    """通过已签名 Noble APT 索引下载固定 ARM64 binary package。"""
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_ROOT / package.filename()
    if target.is_file():
        return target
    run(
        ["apt-get", "download", f"{package.name}:arm64={package.version}"],
        cwd=DOWNLOAD_ROOT,
    )
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


def copy_entry(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_file():
        target.unlink()
    if source.is_symlink():
        target.symlink_to(source.readlink())
    else:
        shutil.copy2(source, target)


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
    if (
        "include" in relative.parts
        or "pkgconfig" in relative.parts
        or "cmake" in relative.parts
        or relative.name.endswith((".a", ".la"))
    ):
        return True
    return (
        relative.name.endswith(".so")
        and relative.parent.as_posix()
        in {"usr/lib", "usr/lib/aarch64-linux-gnu"}
    )


def validate_stage_mapping(stages: list[Path], mapped: set[Path]) -> None:
    """拒绝悄悄丢弃新增的 runtime library、plugin 或 executable。"""
    missing: list[str] = []
    for stage in stages:
        for source in stage.rglob("*"):
            if not (source.is_file() or source.is_symlink()):
                continue
            relative = source.relative_to(stage)
            if relative not in mapped and not is_development_path(relative):
                missing.append(f"{stage.name}:{relative.as_posix()}")
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
            digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
            lines.append(f"{digest}  {relative.as_posix()}")
    (package_root / "DEBIAN/md5sums").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def repack_templates(gstreamer_stages: list[Path]) -> list[Path]:
    """覆盖 Noble 分包模板并重打为较高的 flange 修订版本。"""
    extracted: dict[TemplatePackage, Path] = {}
    mapped: set[Path] = set()
    for package in TEMPLATE_PACKAGES:
        package_root = TEMPLATE_ROOT / package.name
        run(
            ["dpkg-deb", "--raw-extract", str(download_template(package)),
             str(package_root)]
        )
        extracted[package] = package_root
        mapped.update(template_data_paths(package_root))

    validate_stage_mapping(gstreamer_stages, mapped)

    outputs: list[Path] = []
    for package, package_root in extracted.items():
        for relative in template_data_paths(package_root):
            source = SYSROOT / relative
            if source.is_file() or source.is_symlink():
                copy_entry(source, package_root / relative)

        control_path = package_root / "DEBIAN/control"
        control = control_path.read_text(encoding="utf-8")
        control = control.replace(package.version, package.flange_version)
        control_lines = [
            "Maintainer: flange <flange@localhost>"
            if line.startswith("Maintainer:") else line
            for line in control.splitlines()
        ]
        control_path.write_text("\n".join(control_lines) + "\n", encoding="utf-8")
        write_md5sums(package_root)

        output = OUTPUT_ROOT / package.filename(package.flange_version)
        run(
            ["dpkg-deb", "--root-owner-group", "--build", str(package_root),
             str(output)]
        )
        run(["dpkg", "--compare-versions", package.flange_version, "gt", package.version])
        outputs.append(output)
    return outputs


def validate_webrtc() -> None:
    """保证引用任务要求的 WebRTC/DTLS/SRTP runtime 全部生成。"""
    plugin_dir = SYSROOT / "usr/lib/aarch64-linux-gnu/gstreamer-1.0"
    required = [
        plugin_dir / "libgstwebrtc.so",
        plugin_dir / "libgstdtls.so",
        plugin_dir / "libgstsrtp.so",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if not list((plugin_dir.parent).glob("libgstwebrtcnice-1.0.so.0*")):
        missing.append(str(plugin_dir.parent / "libgstwebrtcnice-1.0.so.0*"))
    if missing:
        raise RuntimeError("WebRTC runtime 缺失: " + ", ".join(missing))


def validate_debs(paths: list[Path]) -> None:
    """检查最终 DEB identity、架构和 root 所有权。"""
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"DEB 输出不存在: {path}")
        architecture = run(
            ["dpkg-deb", "-f", str(path), "Architecture"], capture=True,
        ).stdout.strip()
        if architecture != "arm64":
            raise RuntimeError(f"{path.name} 架构错误: {architecture}")
        listing = run(["dpkg-deb", "-c", str(path)], capture=True).stdout
        bad_owners = [
            line for line in listing.splitlines()
            if len(line.split()) >= 2
            and line.split()[1] not in {"root/root", "0/0"}
        ]
        if bad_owners:
            raise RuntimeError(f"{path.name} 含非 root 所有者: {bad_owners[0]}")


def main() -> None:
    if TARGET_ARCH != "aarch64":
        raise RuntimeError("rockchip-multimedia 当前仅支持 aarch64 userspace")
    if not WORK_ROOT.is_relative_to(BUILD_ROOT):
        raise RuntimeError("FLANGE_APP_WORK_DIR 必须位于 FLANGE_BUILD_ROOT 内")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for path in (SOURCE_WORK_ROOT, BUILD_WORK_ROOT, STAGE_ROOT, SYSROOT, TEMPLATE_ROOT):
        clean_work_path(path)
        path.mkdir(parents=True, exist_ok=True)

    cross_file, env = prepare_cross_file()
    git_sources = {source.name: ensure_git_source(source) for source in GIT_SOURCES}
    gst_sources = {
        source.name: prepare_gstreamer_source(source) for source in GST_SOURCES
    }

    mpp_stage = build_mpp(git_sources["rockchip-mpp"], env)
    rga_stage = build_meson(
        "rockchip-librga",
        git_sources["rockchip-librga"],
        cross_file,
        env,
        ["-Dlibdrm=true"],
    )
    gst_stages = [
        build_meson(
            "gstreamer",
            gst_sources["gstreamer"],
            cross_file,
            env,
            [
                "-Dtests=disabled", "-Dexamples=disabled", "-Ddoc=disabled",
                "-Dintrospection=disabled",
                "--libexecdir=lib/aarch64-linux-gnu/gstreamer1.0",
            ],
        ),
        build_meson(
            "gst-plugins-base",
            gst_sources["gst-plugins-base"],
            cross_file,
            env,
            [
                "-Dtests=disabled", "-Dexamples=disabled", "-Ddoc=disabled",
                "-Dintrospection=disabled",
            ],
        ),
        build_meson(
            "gst-plugins-good",
            gst_sources["gst-plugins-good"],
            cross_file,
            env,
            ["-Dtests=disabled", "-Dexamples=disabled", "-Ddoc=disabled"],
        ),
        build_meson(
            "gst-plugins-bad",
            gst_sources["gst-plugins-bad"],
            cross_file,
            env,
            [
                "-Dtests=disabled", "-Dexamples=disabled", "-Ddoc=disabled",
                "-Dintrospection=disabled", "-Dwebrtc=enabled", "-Ddtls=enabled",
                "-Dsrtp=enabled", "-Dkms=enabled", "-Dwayland=enabled",
            ],
        ),
    ]
    validate_webrtc()
    rockchip_stage = build_meson(
        "gstreamer1.0-rockchip",
        git_sources["gstreamer1.0-rockchip"],
        cross_file,
        env,
        ["-Drockchipmpp=enabled", "-Drga=enabled", "-Dkmssrc=enabled"],
    )

    outputs = repack_templates(gst_stages)
    outputs.extend(
        [
            build_vendor_deb(
                "rockchip-mpp", "1.3.9-1flange1",
                "Rockchip Media Process Platform runtime",
                ["libc6 (>= 2.38)", "libdrm2", "libgcc-s1"],
                mpp_stage,
            ),
            build_vendor_deb(
                "librga2", "2.1.0-1flange1",
                "Rockchip RGA 2D acceleration runtime",
                ["libc6 (>= 2.38)", "libdrm2", "libgcc-s1"],
                rga_stage,
            ),
            build_vendor_deb(
                "gstreamer1.0-rockchip", "1.0-1flange1",
                "GStreamer Rockchip MPP, RGA and KMS plugins",
                [
                    "rockchip-mpp (>= 1.3.9-1flange1)",
                    "librga2 (>= 2.1.0-1flange1)",
                    "libgstreamer1.0-0 (>= 1.24.2)",
                    "gstreamer1.0-plugins-base (>= 1.24.2)",
                ],
                rockchip_stage,
            ),
        ]
    )
    validate_debs(outputs)
    print(f"已生成 {len(outputs)} 个 Rockchip 多媒体 runtime DEB")


if __name__ == "__main__":
    main()
