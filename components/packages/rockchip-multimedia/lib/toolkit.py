"""Rockchip 多媒体单元的共享构建工具。

这个 package 把 MPP、RGA、GStreamer 1.24.2 四件套与 Rockchip 插件拆成 8 个
App（7 个编译单元 + 1 个模板重打单元），每个 App 由 flange 的 per-App 缓存
独立判定是否重建 —— 包内不再自建增量机制。

单元之间的编译期依赖靠 **staging 树** 传递：每个单元把 DESTDIR 安装树留在
自己的 ``FLANGE_APP_WORK_DIR/stage``，并在 ``app.yaml`` 里用
``build.staging: stage`` 声明它，使它进入该 App 的产物门禁（被删就重建上游，
而不是让下游在 configure 阶段莫名失败）。下游单元在编译前从各上游的 staging
树重新合成自己的 sysroot —— 每次重新合成，所以上游命中缓存被跳过也不影响，
且不会残留上一轮的头文件。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass, field
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

# 源码下载与 git 检出跨单元共享（在 BUILD_ROOT 下，不在任何 App 的 work 里），
# 8 个单元只下载一次。
SOURCE_ROOT = BUILD_ROOT / "sources" / "rockchip-multimedia"
DOWNLOAD_ROOT = SOURCE_ROOT / "downloads"
GIT_ROOT = SOURCE_ROOT / "git"

# 本单元自己的工作区。
SOURCE_WORK = WORK_ROOT / "src"
BUILD_WORK = WORK_ROOT / "build"
STAGE = WORK_ROOT / "stage"
SYSROOT = WORK_ROOT / "sysroot"
TEMPLATE_WORK = WORK_ROOT / "templates"



# ---------------------------------------------------------------------------
# 源码声明
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TarSource:
    """GStreamer 上游 release tarball，按固定 sha256 校验。"""

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
    """Rockchip 上游仓库，按固定 commit 检出。"""

    name: str
    branch: str
    commit: str


@dataclass(frozen=True)
class DebSpec:
    """本单元直接交付的 vendor runtime deb。"""

    name: str
    version: str
    description: str
    depends: tuple[str, ...]


@dataclass(frozen=True)
class Unit:
    """一个编译单元。

    ``deps`` 是**编译期**依赖的上游 App 名：它们的 staging 树会在本单元编译前
    合成进 sysroot。同一组名字也写在 ``app.yaml`` 的 ``build.deps`` 里，由
    flange 用于构建排序与缓存的 Merkle 级联 —— 两处必须一致，
    ``tests/builder/test_rockchip_multimedia_units.py`` 会对账。
    """

    app: str
    source: TarSource | GitSource
    system: str                      # "cmake" | "meson"
    deps: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    deb: DebSpec | None = None


GST_SOURCES = {
    "gstreamer": TarSource(
        "gstreamer",
        "9cafdd23bd180f1681c56cd3a6879a8497ccf24da6f422a6b6f356fa074a8481",
    ),
    "gst-plugins-base": TarSource(
        "gst-plugins-base",
        "282f1cc8065c9b62eb6a0a20fb9e8328f8e5296df2458b7236daa729c41ae769",
    ),
    "gst-plugins-good": TarSource(
        "gst-plugins-good",
        "6e347c72d4b8b2886d890ffe9f6767a9edb02f201588e8c3a572dcd08d9852bd",
    ),
    "gst-plugins-bad": TarSource(
        "gst-plugins-bad",
        "448e32787bc82b586c6cb2f81c9a8ef404fea4f77f25566fe06e597a3f59136b",
    ),
}

GIT_SOURCES = {
    "rockchip-mpp": GitSource(
        "rockchip-mpp",
        "mpp-dev-2024_06_27",
        "b29e4b798d28a5d0709bff87479d17f247645bc8",
    ),
    "rockchip-librga": GitSource(
        "rockchip-librga",
        "linux-rga-multi",
        "c6105b06ade0e5dc7f16924c7f0f5e9dcdb198bc",
    ),
    "gstreamer1.0-rockchip": GitSource(
        "gstreamer1.0-rockchip",
        "gstreamer-rockchip",
        "c37e7cf10283521c262f9e71fd9be0422a457989",
    ),
}

_GST_COMMON = ("-Dtests=disabled", "-Dexamples=disabled", "-Ddoc=disabled")

UNITS: dict[str, Unit] = {
    "rkmm-mpp": Unit(
        app="rkmm-mpp",
        source=GIT_SOURCES["rockchip-mpp"],
        system="cmake",
        deb=DebSpec(
            "rockchip-mpp", "1.3.9-1flange1",
            "Rockchip Media Process Platform runtime",
            ("libc6 (>= 2.38)", "libdrm2", "libgcc-s1"),
        ),
    ),
    "rkmm-rga": Unit(
        app="rkmm-rga",
        source=GIT_SOURCES["rockchip-librga"],
        system="meson",
        options=("-Dlibdrm=true",),
        deb=DebSpec(
            "librga2", "2.1.0-1flange1",
            "Rockchip RGA 2D acceleration runtime",
            ("libc6 (>= 2.38)", "libdrm2", "libgcc-s1"),
        ),
    ),
    "rkmm-gstreamer": Unit(
        app="rkmm-gstreamer",
        source=GST_SOURCES["gstreamer"],
        system="meson",
        options=(
            *_GST_COMMON, "-Dintrospection=disabled",
            "--libexecdir=lib/aarch64-linux-gnu/gstreamer1.0",
        ),
    ),
    "rkmm-gst-base": Unit(
        app="rkmm-gst-base",
        source=GST_SOURCES["gst-plugins-base"],
        system="meson",
        deps=("rkmm-gstreamer",),
        options=(*_GST_COMMON, "-Dintrospection=disabled"),
    ),
    "rkmm-gst-good": Unit(
        app="rkmm-gst-good",
        source=GST_SOURCES["gst-plugins-good"],
        system="meson",
        deps=("rkmm-gstreamer", "rkmm-gst-base"),
        options=_GST_COMMON,
    ),
    "rkmm-gst-bad": Unit(
        app="rkmm-gst-bad",
        source=GST_SOURCES["gst-plugins-bad"],
        system="meson",
        deps=("rkmm-gstreamer", "rkmm-gst-base"),
        options=(
            *_GST_COMMON, "-Dintrospection=disabled", "-Dwebrtc=enabled",
            "-Ddtls=enabled", "-Dsrtp=enabled", "-Dkms=enabled",
            "-Dwayland=enabled",
        ),
    ),
    "rkmm-gst-rockchip": Unit(
        app="rkmm-gst-rockchip",
        source=GIT_SOURCES["gstreamer1.0-rockchip"],
        system="meson",
        deps=("rkmm-mpp", "rkmm-rga", "rkmm-gstreamer", "rkmm-gst-base"),
        options=("-Drockchipmpp=enabled", "-Drga=enabled", "-Dkmssrc=enabled"),
        deb=DebSpec(
            "gstreamer1.0-rockchip", "1.0-1flange1",
            "GStreamer Rockchip MPP, RGA and KMS plugins",
            (
                "rockchip-mpp (>= 1.3.9-1flange1)",
                "librga2 (>= 2.1.0-1flange1)",
                "libgstreamer1.0-0 (>= 1.24.2)",
                "gstreamer1.0-plugins-base (>= 1.24.2)",
            ),
        ),
    ),
}

# 四个 GStreamer 编译单元的产物汇合后，才能按 Noble 的分包边界重打模板 deb
# （已验证 *-good 的两个 deb 实际含 gst-plugins-bad 的文件）——所以重打是一个
# 独立单元，而不是某个编译单元的尾巴。
REPACK_APP = "rkmm-gst-repack"
REPACK_DEPS = (
    "rkmm-gstreamer", "rkmm-gst-base", "rkmm-gst-good", "rkmm-gst-bad",
)


@dataclass(frozen=True)
class TemplatePackage:
    """Ubuntu Noble 的 runtime deb，用作分包模板。"""

    name: str
    version: str

    @property
    def flange_version(self) -> str:
        return f"{self.version}+flange1"

    def filename(self, version: str | None = None) -> str:
        return f"{self.name}_{version or self.version}_arm64.deb"


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


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def run(command: list[str], *, cwd: Path | None = None,
        env: dict[str, str] | None = None, capture: bool = False):
    """执行单个 argv 命令，失败即终止。"""
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command, cwd=cwd, env=env, check=True, text=True,
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


def copy_entry(source: Path, target: Path) -> None:
    """复制单个文件或符号链接，覆盖已存在的目标。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.is_file():
        target.unlink()
    if source.is_symlink():
        target.symlink_to(source.readlink())
    else:
        shutil.copy2(source, target)


# ---------------------------------------------------------------------------
# 源码准备
# ---------------------------------------------------------------------------

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
            f"{source.filename} SHA256 不匹配: {actual} != {source.sha256}")
    partial.replace(target)
    return target


def prepare_tar_source(source: TarSource) -> Path:
    """解压干净源码并按文件名顺序应用 package 内补丁。"""
    tarball = ensure_tarball(source)
    source_dir = SOURCE_WORK / f"{source.name}-{GST_VERSION}"
    clean_work_path(source_dir)
    SOURCE_WORK.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:xz") as archive:
        archive.extractall(SOURCE_WORK, filter="data")
    patches = sorted((PATCH_ROOT / source.name).glob("*.patch"))
    if not patches:
        raise RuntimeError(f"{source.name} 没有迁移任何 Rockchip 补丁")
    for patch in patches:
        run(["patch", "-p1", "--forward", "--batch", "-i", str(patch)],
            cwd=source_dir)
    return source_dir


def _git_head(source_dir: Path) -> str:
    try:
        return run(["git", "rev-parse", "HEAD"], cwd=source_dir,
                   capture=True).stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def prepare_git_source(source: GitSource) -> Path:
    """确保 Rockchip 固定 branch/commit 的干净 checkout。

    commit 已 pin，本地已有该对象时跳过 fetch —— 省掉网络往返，也让离线重建
    成为可能。HEAD 已经就位则连 reset/clean 都跳过。
    """
    GIT_ROOT.mkdir(parents=True, exist_ok=True)
    source_dir = GIT_ROOT / source.name
    if not (source_dir / ".git").is_dir():
        if source_dir.exists():
            shutil.rmtree(source_dir)
        run(["git", "clone", "--branch", source.branch, "--single-branch",
             MIRRORS_GIT, str(source_dir)])
    elif _git_head(source_dir) == source.commit:
        return source_dir

    have_commit = subprocess.run(
        ["git", "cat-file", "-e", f"{source.commit}^{{commit}}"],
        cwd=source_dir, capture_output=True,
    ).returncode == 0
    if not have_commit:
        run(["git", "fetch", "origin", source.branch], cwd=source_dir)
    run(["git", "checkout", "--detach", source.commit], cwd=source_dir)
    run(["git", "reset", "--hard", source.commit], cwd=source_dir)
    run(["git", "clean", "-ffdqx"], cwd=source_dir)
    return source_dir


def prepare_source(unit: Unit) -> Path:
    if isinstance(unit.source, TarSource):
        return prepare_tar_source(unit.source)
    return prepare_git_source(unit.source)


# ---------------------------------------------------------------------------
# sysroot 合成
# ---------------------------------------------------------------------------

def upstream_stage(app: str) -> Path:
    """从构建报告注入的准确依赖映射读取 staging，不推测工作目录。"""
    import json
    dependencies = json.loads(os.environ.get("FLANGE_DEPENDENCY_DIRS", "{}"))
    if app not in dependencies:
        raise ValueError(f"缺少依赖 {app} 的已发布安装树，请在 build.deps 声明依赖")
    return Path(dependencies[app])


def merge_into_sysroot(stage: Path) -> None:
    """把一棵 staging 树合入 sysroot，并把 .pc 的 prefix 指向 sysroot。"""
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


def compose_sysroot(deps: tuple[str, ...]) -> None:
    """从各上游单元的 staging 树重新合成本单元的 sysroot。

    每次都重新合成，因此上游命中缓存被整体跳过也不影响，且不会残留上一轮的
    头文件。上游 staging 缺失时直接报错并指出补救命令 —— 它已在上游 App 的
    产物门禁里，正常情况下不会缺。
    """
    clean_work_path(SYSROOT)
    SYSROOT.mkdir(parents=True, exist_ok=True)
    for app in deps:
        stage = upstream_stage(app)
        if not stage.is_dir():
            raise RuntimeError(
                f"上游单元 {app} 的 staging 树不存在: {stage}\n"
                f"  执行 `flange build app {app} -f` 重建后再试"
            )
        print(f"[sysroot] 合入 {app}", flush=True)
        merge_into_sysroot(stage)


def cross_build_env() -> tuple[Path, dict[str, str]]:
    """准备 Meson cross-file 与目标架构的 pkg-config / 编译搜索路径。"""
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
        f"-L{SYSROOT}/usr/lib "
        f"-Wl,-rpath-link,{SYSROOT}/usr/lib/aarch64-linux-gnu"
    )
    return cross_file, env


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------

def compile_unit(unit: Unit, source_dir: Path, cross_file: Path,
                 env: dict[str, str]) -> None:
    """configure → compile → install 到本单元的 staging 树。"""
    # staging 必须清空后重装：install 只覆盖同名文件，改名或删除的产物会残留。
    clean_work_path(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)
    BUILD_WORK.mkdir(parents=True, exist_ok=True)

    if unit.system == "cmake":
        run([
            "cmake", "-S", str(source_dir), "-B", str(BUILD_WORK),
            "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=/usr",
            "-DCMAKE_INSTALL_LIBDIR=lib/aarch64-linux-gnu",
            "-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
            "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc",
            "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++",
            "-DBUILD_TEST=OFF", *unit.options,
        ], env=env)
        run(["cmake", "--build", str(BUILD_WORK), f"-j{JOBS}"], env=env)
        run(["cmake", "--install", str(BUILD_WORK)],
            env={**env, "DESTDIR": str(STAGE)})
        return

    setup = [
        "meson", "setup", str(BUILD_WORK), str(source_dir),
        "--cross-file", str(cross_file), "--prefix=/usr",
        "--libdir=lib/aarch64-linux-gnu", "--buildtype=release",
        "--wrap-mode=nodownload", *unit.options,
    ]
    if (BUILD_WORK / "meson-info").is_dir():
        # 复用既有 build 目录让 ninja 走 depfile 增量；meson 不允许对已配置
        # 目录重复 setup，必须显式 --reconfigure。
        setup.append("--reconfigure")
    run(setup, env=env)
    compile_command = ["meson", "compile", "-C", str(BUILD_WORK), "-j", JOBS]
    try:
        run(compile_command, env=env)
    except subprocess.CalledProcessError:
        # Docker Desktop 的 Rosetta 并发执行偶发失败；Ninja 增量重试可恢复。
        print("编译失败，增量重试一次", flush=True)
        run(compile_command, env=env)
    run(["meson", "install", "-C", str(BUILD_WORK), "--destdir", str(STAGE)],
        env=env)


# ---------------------------------------------------------------------------
# deb 交付
# ---------------------------------------------------------------------------

def runtime_files(stage: Path) -> list[tuple[Path, str, int]]:
    """收集 runtime 文件，排除 headers、pkg-config、CMake 与 static library。"""
    files: list[tuple[Path, str, int]] = []
    for source in sorted(stage.rglob("*")):
        if not (source.is_file() or source.is_symlink()):
            continue
        relative = source.relative_to(stage)
        if ("include" in relative.parts or "pkgconfig" in relative.parts
                or "cmake" in relative.parts
                or source.name.endswith((".a", ".la"))):
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


def build_vendor_deb(spec: DebSpec, stage: Path) -> Path:
    """用 flange DebBuilder 生成不含开发文件的厂商 runtime 包。"""
    control = "\n".join([
        f"Package: {spec.name}",
        f"Version: {spec.version}",
        "Architecture: arm64",
        "Maintainer: flange <flange@localhost>",
        f"Depends: {', '.join(spec.depends)}",
        f"Description: {spec.description}",
        "",
    ])
    return DebBuilder().build_deb(
        name=spec.name, version=spec.version, arch="aarch64",
        control_fields={"control": control},
        files=runtime_files(stage), output_dir=OUTPUT_ROOT,
    )


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


# ---------------------------------------------------------------------------
# 单元入口
# ---------------------------------------------------------------------------

def build(app: str) -> None:
    """构建一个编译单元：准备源码 → 合成 sysroot → 编译 → 可选打 deb。"""
    if TARGET_ARCH != "aarch64":
        raise RuntimeError("rockchip-multimedia 当前仅支持 aarch64 userspace")
    if not WORK_ROOT.is_relative_to(BUILD_ROOT):
        raise RuntimeError("FLANGE_APP_WORK_DIR 必须位于 FLANGE_BUILD_ROOT 内")

    unit = UNITS[app]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)

    compose_sysroot(unit.deps)
    cross_file, env = cross_build_env()
    source_dir = prepare_source(unit)
    compile_unit(unit, source_dir, cross_file, env)

    if unit.deb is None:
        print(f"单元 {app} 完成，staging 树留给下游: {STAGE}", flush=True)
        return
    deb = build_vendor_deb(unit.deb, STAGE)
    validate_debs([deb])
    print(f"单元 {app} 完成 → {deb.name}", flush=True)
