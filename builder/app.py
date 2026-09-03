"""App 构建器 — 文件收集与路径映射，以及 AppBuilder 构建协调器。

约定式路径映射规则：
  bin/       → /usr/bin/          (mode 0o755)
  lib/       → /usr/lib/          (mode 0o644)
  include/   → /usr/include/<name>/  (mode 0o644，仅 lib 类型)
  conf/      → /etc/<name>/       (mode 0o644)
  scripts/   → /usr/lib/<name>/   (mode 0o755)
  systemd/   → /lib/systemd/system/  (mode 0o644)
  udev/      → /lib/udev/rules.d/ (mode 0o644)
  res/       → /usr/share/<name>/ (mode 0o644)
  rootfs/    → /                    (仅 vendor，递归保留目录结构与执行位)

预编译二进制架构后缀选择规则：
  aarch64 目标：匹配 -arm64、-aarch64 后缀
  armhf   目标：匹配 -armhf、-arm32 后缀
  匹配后去掉后缀作为安装文件名；不匹配目标架构的文件排除。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from builder.app_spec import AppSpec
from builder.config.canonical import userspace_arch
from builder.paths import build_dir


# ---------------------------------------------------------------------------
# 交叉编译工具链前缀映射：目标架构 → 工具链前缀
# ---------------------------------------------------------------------------

_CROSS_COMPILE_PREFIX: dict[str, str] = {
    "aarch64": "aarch64-linux-gnu-",
    "armhf":   "arm-linux-gnueabihf-",
    "x86_64":  "",      # 原生，无需前缀
    "i386":    "",
    "riscv64": "riscv64-linux-gnu-",
}

# ---------------------------------------------------------------------------
# 构建系统命令模板：构建系统名 → 命令步骤列表
# 每个步骤是一个字符串列表（argv 格式），选项展开后追加到对应位置
# ---------------------------------------------------------------------------

_BUILD_SYSTEMS: dict[str, list[list[str]]] = {
    # 预编译包，无需编译步骤
    "none": [],
    # CMake 两阶段：configure + build
    "cmake": [
        [
            "cmake", "-B", "build",
            "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc",
            "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++",
        ],
        ["cmake", "--build", "build", "-j$(nproc)"],
    ],
    # Meson + Ninja 两阶段：setup + build
    "meson": [
        ["meson", "setup", "build", "--cross-file", "/etc/meson/cross-aarch64.ini"],
        ["ninja", "-C", "build"],
    ],
    # Make 单阶段
    "make": [
        ["make", "ARCH=arm64", "CROSS_COMPILE=aarch64-linux-gnu-", "-j$(nproc)"],
    ],
    # Swift 交叉编译
    "swift": [
        ["swift", "build", "-c", "release", "--triple", "aarch64-unknown-linux-gnu"],
    ],
    # custom：命令由 spec.build.commands 提供，不使用此模板
    "custom": [],
}

_NATIVE_INSTALL_SYSTEMS = {"cmake", "meson", "make", "swift"}

# ---------------------------------------------------------------------------
# 架构后缀映射表：目标架构 → 允许的文件名后缀列表
# ---------------------------------------------------------------------------

_ARCH_SUFFIXES: dict[str, list[str]] = {
    "aarch64": ["-arm64", "-aarch64"],
    "armhf":   ["-armhf", "-arm32"],
    "x86_64":  ["-x86_64", "-amd64"],
    "i386":    ["-i386", "-x86"],
    "riscv64": ["-riscv64"],
}

# ---------------------------------------------------------------------------
# 约定映射：子目录名 → (安装路径模板, 文件权限)
# 模板中 {name} 会被替换为 app 名称
# ---------------------------------------------------------------------------

_CONVENTION_MAP: dict[str, tuple[str, int]] = {
    "bin":     ("/usr/bin/",           0o755),
    "lib":     ("/usr/lib/",           0o644),
    "include": ("/usr/include/{name}/", 0o644),
    "conf":    ("/etc/{name}/",        0o644),
    "scripts": ("/usr/lib/{name}/",    0o755),
    "systemd": ("/lib/systemd/system/", 0o644),
    "udev":    ("/lib/udev/rules.d/",  0o644),
    "res":     ("/usr/share/{name}/",  0o644),
}


def _strip_arch_suffix(filename: str, arch: str) -> str | None:
    """尝试从文件名中剥离架构后缀。

    参数：
        filename: 文件名（不含目录），如 adbd-arm64
        arch:     目标架构名称，如 aarch64

    返回：
        剥离后缀后的文件名（如 adbd），若文件名不含该架构的任何后缀则返回 None
    """
    suffixes = _ARCH_SUFFIXES.get(arch, [])
    for suffix in suffixes:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return None


def _has_any_arch_suffix(filename: str) -> bool:
    """判断文件名是否带有任意已知架构后缀。

    用于区分"普通文件"与"带架构标签的预编译文件"：
    若文件名不带任何已知架构后缀，则视为普通文件，不经过架构过滤。

    参数：
        filename: 文件名（不含目录）

    返回：
        True 表示含有已知架构后缀，False 表示普通文件
    """
    all_suffixes = [s for sl in _ARCH_SUFFIXES.values() for s in sl]
    return any(filename.endswith(s) for s in all_suffixes)


def _resolve_convention_path(subdir: str, filename: str, app_name: str) -> str:
    """根据约定映射规则计算文件的安装路径。

    参数：
        subdir:   子目录名称（如 bin、conf）
        filename: 文件名（安装后的名称，已完成架构后缀剥离）
        app_name: App 名称，用于替换路径模板中的 {name}

    返回：
        安装路径字符串（如 /usr/bin/adbd）
    """
    template, _ = _CONVENTION_MAP[subdir]
    dir_path = template.format(name=app_name)
    return dir_path + filename


def _collect_convention(
    app_dir: Path,
    app_name: str,
    arch: str,
    app_type: str = "exec",
) -> list[tuple[Path, str, int, str]]:
    """遍历约定子目录，收集文件并映射路径。

    返回 (src_path, install_path, mode, rel_key) 四元组列表，
    其中 rel_key 为 "subdir/filename" 格式，用于后续与 install 段合并时去重。

    参数：
        app_dir:  App 工程目录
        app_name: App 名称
        arch:     目标架构名称
        app_type: App 类型（默认 exec），用于限制某些约定（如 include/ 仅限 lib 类型）

    返回：
        [(src_path, install_path, mode, rel_key), ...]
    """
    results: list[tuple[Path, str, int, str]] = []

    # vendor 是从上游发行包审计、筛选后重组的文件树。允许直接按目标
    # rootfs 布局存放，避免为大量 DSP library 逐文件重复声明 install 映射。
    if app_type == "vendor":
        rootfs_dir = app_dir / "rootfs"
        if rootfs_dir.is_dir():
            for src_file in sorted(rootfs_dir.rglob("*")):
                if not (src_file.is_file() or src_file.is_symlink()):
                    continue
                if src_file.name == ".DS_Store":
                    continue
                relative = src_file.relative_to(rootfs_dir).as_posix()
                mode = src_file.lstat().st_mode & 0o777
                results.append((
                    src_file,
                    f"/{relative}",
                    mode,
                    f"rootfs/{relative}",
                ))

    for subdir_name, (template, mode) in _CONVENTION_MAP.items():
        # include/ 约定仅适用于 lib 类型
        if subdir_name == "include" and app_type != "lib":
            continue

        subdir_path = app_dir / subdir_name
        if not subdir_path.is_dir():
            continue

        for src_file in sorted(subdir_path.iterdir()):
            # 仅处理普通文件和符号链接，跳过子目录
            if src_file.is_dir():
                continue

            filename = src_file.name

            # 架构过滤：若文件名带有已知架构后缀，只保留匹配目标架构的
            if _has_any_arch_suffix(filename):
                stripped = _strip_arch_suffix(filename, arch)
                if stripped is None:
                    # 不匹配目标架构，排除
                    continue
                install_name = stripped
            else:
                # 普通文件，直接使用原文件名
                install_name = filename

            install_path = _resolve_convention_path(subdir_name, install_name, app_name)
            rel_key = f"{subdir_name}/{filename}"
            results.append((src_file, install_path, mode, rel_key))

    return results


def collect_files(
    app_dir: Path,
    spec: AppSpec,
    arch: str,
) -> List[Tuple[Path, str, int]]:
    """收集 App 文件并映射安装路径。

    策略（按优先级）：
    1. 先通过约定映射枚举所有子目录，生成 (src, install_path, mode) 基础列表
    2. 若 spec.install 非空，对 install 段中声明的文件进行显式覆盖：
       - 已在约定列表中的条目替换其安装路径（mode 按目标目录重新推断）
       - 未在约定目录中的条目直接追加（如指向任意路径的额外文件）
    3. 仅返回实际存在于磁盘的文件，不包含 app.yaml 等非安装文件

    参数：
        app_dir: App 工程目录（必须包含 app.yaml）
        spec:    已解析的 AppSpec 对象
        arch:    目标架构名称（如 aarch64、armhf）

    返回：
        [(src_path, install_path, mode), ...] 列表，
        src_path 为绝对路径，install_path 为目标系统绝对路径，
        mode 为文件权限（bin/ 和 scripts/ 为 0o755，其余为 0o644）
    """
    app_name = spec.app.name
    app_type = spec.app.type

    # -----------------------------------------------------------------------
    # 第一步：约定映射
    # -----------------------------------------------------------------------
    convention_entries = _collect_convention(app_dir, app_name, arch, app_type)

    # 构建 rel_key → (src, install_path, mode) 映射，用于 install 段覆盖
    # rel_key 格式："subdir/filename"（原始文件名，含架构后缀）
    convention_by_key: dict[str, tuple[Path, str, int]] = {
        rel_key: (src, install_path, mode)
        for src, install_path, mode, rel_key in convention_entries
    }

    if not spec.install:
        # 无显式 install 段，直接使用约定映射结果
        return [(src, install_path, mode) for src, install_path, mode, _ in convention_entries]

    # -----------------------------------------------------------------------
    # 第二步：合并 install 显式覆盖
    # -----------------------------------------------------------------------
    # 已处理的 rel_key 集合，避免约定路径与 install 覆盖路径重复出现
    overridden_keys: set[str] = set()

    # 最终结果列表
    final: list[tuple[Path, str, int]] = []

    for src_rel, dest_path in spec.install.items():
        # src_rel 形如 "conf/usbdevice.conf"
        src_path = app_dir / src_rel
        if not src_path.exists():
            # 源文件不存在，记录警告并跳过
            import warnings
            warnings.warn(f"install 映射的源文件不存在，跳过: {src_path}")
            continue

        # 推断文件权限：安装到 /usr/bin/ 或 /usr/sbin/ 或 /usr/lib/<name>/ 时赋予执行权限
        mode = _infer_mode(dest_path, src_rel)

        final.append((src_path, dest_path, mode))
        # 标记该 rel_key 已被 install 覆盖，约定列表中的条目不再输出
        overridden_keys.add(src_rel)

    # 将约定列表中未被 install 段覆盖的条目追加到最终结果
    for src, install_path, mode, rel_key in convention_entries:
        if rel_key not in overridden_keys:
            final.append((src, install_path, mode))

    return final


def _infer_mode(install_path: str, src_rel: str) -> int:
    """根据安装路径推断文件权限。

    可执行目录（/usr/bin/、/usr/sbin/、/bin/、/sbin/）或来源于 scripts/ 子目录
    的文件赋予 0o755，其余赋予 0o644。

    参数：
        install_path: 目标系统安装路径（如 /usr/sbin/usbdevice）
        src_rel:      相对于 app_dir 的源路径（如 scripts/usbdevice）

    返回：
        0o755 或 0o644
    """
    # 按来源子目录判断
    src_subdir = src_rel.split("/")[0] if "/" in src_rel else ""
    if src_subdir in ("bin", "scripts"):
        return 0o755

    # 按安装目录判断
    exec_prefixes = ("/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/")
    for prefix in exec_prefixes:
        if install_path.startswith(prefix):
            return 0o755

    return 0o644


# ---------------------------------------------------------------------------
# 共享库文件名判断辅助
# ---------------------------------------------------------------------------

def _is_shared_lib(filename: str) -> bool:
    """判断文件名是否为共享库（.so 或带版本号的 .so.*）。

    匹配规则：
    - 精确以 .so 结尾，如 libfoo.so
    - 含有 .so. 子串，如 libfoo.so.1、libfoo.so.1.2.3

    参数：
        filename: 文件名（不含目录）

    返回：
        True 表示共享库，False 表示其他文件
    """
    return filename.endswith(".so") or ".so." in filename


def _is_pkg_config(install_path: str) -> bool:
    """判断安装路径是否为 pkg-config 开发元数据。"""
    return (
        install_path.startswith("/usr/lib/")
        and "/pkgconfig/" in install_path
        and install_path.endswith(".pc")
    )


# ---------------------------------------------------------------------------
# App 间拓扑排序
# ---------------------------------------------------------------------------

class CircularDependencyError(ValueError):
    """检测到循环依赖时抛出。"""


def _topo_sort_apps(graph: dict[str, list[str]]) -> list[str]:
    """对 App 依赖图进行拓扑排序，返回合法的构建顺序。

    使用深度优先搜索（DFS）实现拓扑排序，同时检测循环依赖。

    参数：
        graph: {app_name: [依赖 app_name, ...]} 字典，
               键必须包含所有待构建 App；依赖列表中的 App 也必须出现在键中。

    返回：
        拓扑排序后的 App 名称列表（依赖先于被依赖方）

    抛出：
        CircularDependencyError: 若依赖图中存在循环依赖
    """
    # 0 = 未访问，1 = 访问中（检测循环），2 = 已完成
    state: dict[str, int] = {name: 0 for name in graph}
    order: list[str] = []

    def _visit(name: str, path: list[str]) -> None:
        """深度优先遍历，path 记录当前访问路径（用于循环检测报错）。"""
        if state[name] == 2:
            # 已处理完毕，跳过
            return
        if state[name] == 1:
            # 发现回边，报告循环路径
            cycle_start = path.index(name)
            cycle = " → ".join(path[cycle_start:] + [name])
            raise CircularDependencyError(f"检测到循环依赖：{cycle}")

        state[name] = 1  # 标记为"访问中"
        path.append(name)

        for dep in graph.get(name, []):
            _visit(dep, path)

        path.pop()
        state[name] = 2  # 标记为"已完成"
        order.append(name)

    for name in graph:
        if state[name] == 0:
            _visit(name, [])

    return order


# ---------------------------------------------------------------------------
# AppBuilder：协调单个或全量 App 的构建与打包
# ---------------------------------------------------------------------------

class AppBuilder:
    """App 构建协调器 — 负责查找 App 目录、加载规格、编译（预留）和打包。

    参数：
        docker:     DockerRunner 实例（用于后续编译步骤，Task 5 实现）
        source:     SourceManager 实例（用于外部仓库 App 查找，Task 7 实现）
        config:     FINAL_CONFIG 字典，需包含 board/product/variant/rootfs 等字段
        project_dir: 项目根目录，默认为当前工作目录
    """

    output = None  # BuildOutput，由 engine 注入
    cache = None   # BuildCache，由 engine（或 CLI 单 App 入口）注入

    def __init__(
        self,
        docker,
        source,
        config: dict,
        project_dir: Optional[Path] = None,
    ) -> None:
        self._docker = docker
        self._source = source
        self._config = config
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()

        # 推导输出目录：.build/target/<board>/<product>/<variant>/app/
        board   = config.get("board", "unknown")
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self._output_dir = self._project_dir / ".build/target" / board / product / variant / "app"

        # 目标架构
        self._arch: str = userspace_arch(config)

        # 同一次 flange build 共用一个容器，只需刷新一次 APT 索引；已安装的
        # 编译依赖也不重复请求。下载包复用 docker-compose 挂载的 /cache/apt。
        self._apt_index_updated = False
        self._installed_build_packages: set[str] = set()

    def _status(self, msg: str):
        if self.output:
            self.output.status(msg)

    # -----------------------------------------------------------------------
    # 公开接口
    # -----------------------------------------------------------------------

    def build_all(self, force: bool = False) -> Dict[str, Path]:
        """构建所有 custom_packages，返回 {app_name: deb_path}。

        待构建集合为 ``rootfs.custom_packages`` 与 ``recovery.custom_packages``
        的并集（启用 recovery 时合并）；rootfs 的 phase2 与 recovery 的
        phase2 各自挑选所需的 deb 安装。

        **per-App 增量**：注入了 cache 时，逐个比对 App 内容哈希与产物清单，
        未变的 App 直接复用既有 deb —— 改一个 App 不再牵连其余（多媒体包一次
        全量编译约 10 分钟）。构建完成后清理"不属于任何在册 App"的 deb，替代
        旧的"先删光再全建"，既保证 rootfs 按 glob 全装不会吃到残留，也让某个
        App 构建失败时不破坏其他 App 已有的产物。

        参数：
            force: 跳过 per-App 缓存判定，强制重建全部 App

        返回：
            {app_name: .deb 路径} 字典
        """
        from builder.config.apps import gather_custom_packages
        custom_packages: list[str] = gather_custom_packages(self._config)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if not custom_packages:
            self._prune_stale_debs(custom_packages, set())
            self._status("custom_packages 为空，无需构建 App")
            return {}

        self._status(f"待构建 App: {custom_packages}")
        ordered = self._resolve_build_order(custom_packages)
        self._status(f"构建顺序: {ordered}")

        results: Dict[str, Path] = {}
        reused: List[str] = []
        produced: set = set()
        for name in ordered:
            if not force and self._reuse_app(name):
                reused.append(name)
                names = (self.cache.read_app_manifest(name) or {}).get(
                    "debs") or []
                produced.update(names)
                results[name] = (
                    self._output_dir / names[0] if names else None)
                continue
            debs = self._build_one_debs(name)
            produced.update(path.name for path in debs)
            results[name] = debs[0] if debs else None

        if reused:
            self._status(
                f"未变更，复用既有 deb ({len(reused)}/{len(ordered)}): "
                f"{', '.join(reused)}"
            )
        self._prune_stale_debs(custom_packages, produced)
        return results

    def _reuse_app(self, name: str) -> bool:
        """判断 App 是否可跳过构建；命中时补齐 lib App 的 sysroot。

        sysroot 是 App 之间的编译期契约（下游 App 用 ``build.deps`` 引用上游
        的头文件与 .so），它不在产物清单里、也可能被 ``flange clean`` 清掉。
        命中路径重新安装一次（纯文件复制，廉价），避免下游 App 因上游被跳过
        而找不到 sysroot。
        """
        if self.cache is None or not self.cache.is_app_up_to_date(name):
            return False
        from builder.app_spec import load_spec

        # 用 cache 的只读解析，不走 SourceManager.ensure_app —— 命中路径不该
        # 触发 clone/fetch 之类的网络操作。
        app_dir = self.cache._registered_app_source_dir(name)
        if not (app_dir / "app.yaml").is_file():
            return False
        spec = load_spec(app_dir)
        if spec.app.type == "lib":
            install_dir = self._native_install_dir(spec)
            if (
                install_dir is not None
                and spec.build.system != "make"
                and not install_dir.is_dir()
            ):
                return False
            self._install_sysroot(app_dir, spec)
        return True

    def _staging_dir(self, spec: AppSpec) -> Optional[Path]:
        """返回该 App 声明的 staging 树绝对路径；未声明返回 None。

        位置与编译期注入的 ``FLANGE_APP_WORK_DIR`` 一致，使包内单元脚本
        能按同一约定写入、下游 App 能按同一约定读取。
        """
        if not spec.build.staging:
            return None
        work_dir = (
            build_dir(self._project_dir)
            / "work" / "apps" / spec.app.name / self._arch
        )
        return work_dir / spec.build.staging

    def _native_install_dir(self, spec: AppSpec) -> Optional[Path]:
        """返回标准构建系统的 per-App install staging 目录。"""
        if spec.build.system not in _NATIVE_INSTALL_SYSTEMS:
            return None
        board = self._config.get("board", "unknown")
        product = self._config.get("product", "default")
        variant = self._config.get("variant", "release")
        return (
            build_dir(self._project_dir)
            / "work" / "apps" / spec.app.name / self._arch
            / board / product / variant / "install"
        )

    def _record_app_manifest(
        self, name_or_path: str, app_dir: Path, debs: List[Path]
    ) -> None:
        """构建成功后写入该 App 的内容哈希与产物清单。

        两道判据缺一不可：
          - 不在 custom_packages 里的 App（ad-hoc 路径构建）不由 build_all
            管理，写清单只会与同名在册 App 打架；
          - 即使名字在册，若这次实际构建的目录不是缓存用来算哈希的那个目录
            （``flange build app ./some/dir`` 恰好撞名），写进去的哈希与产物
            对不上，下次会命中错误对象。

        standalone ``flange build app <name>`` 满足两道判据，因此单独构建过
        一个 App 之后，随后的 ``flange build`` 只会重建其余真正变化的 App，
        而不是把整组再编一遍。

        声明了 ``build.staging`` 的 App，以及使用原生 install staging 的
        lib App，会把该产物树一并记进清单：下游 App 靠它拿头文件与库，
        被误删时必须让上游重建，而不是命中缓存后让下游编译失败。
        """
        if self.cache is None:
            return
        from builder.config.apps import gather_custom_packages

        if name_or_path not in gather_custom_packages(self._config):
            return
        registered = self.cache._registered_app_source_dir(name_or_path)
        if registered.resolve() != app_dir.resolve():
            return
        from builder.app_spec import load_spec

        spec = load_spec(app_dir)
        staging = self._staging_dir(spec)
        if staging is None and spec.app.type == "lib":
            native_install = self._native_install_dir(spec)
            if native_install is not None and native_install.is_dir():
                staging = native_install
        self.cache.store_app(
            name_or_path, debs,
            staging=str(staging) if staging else None,
        )

    def _prune_stale_debs(self, custom_packages: List[str], keep: set) -> None:
        """删除不属于本次在册 App 的 deb 与已出集合的 App 清单。

        rootfs 按 ``glob("*.deb")`` 全装（builder/platforms/*/rootfs.py），
        所以 App 改名 / 换版本号 / 移出 custom_packages（如 UBI 路由过滤掉
        flange-rootfs-grow）留下的旧 deb 必须清掉，否则会被静默装进镜像。

        参数：
            custom_packages: 本次在册的 App 名单
            keep: 本次构建产出或命中复用的全部 deb 文件名
        """
        wanted = set(custom_packages)
        if self.cache is not None:
            manifest_dir = self._output_dir / self.cache.APP_MANIFEST_DIR
            if manifest_dir.is_dir():
                for path in manifest_dir.glob("*.json"):
                    if path.stem not in wanted:
                        path.unlink()
        removed = []
        for deb in sorted(self._output_dir.glob("*.deb")):
            if deb.name not in keep:
                deb.unlink()
                removed.append(deb.name)
        if removed:
            self._status(f"清理无主 deb ({len(removed)}): {', '.join(removed)}")

    def build_one(self, name_or_path: str) -> Optional[Path]:
        """构建单个 App，返回运行时或多 DEB 声明中的首个 .deb 路径。

        入参既可以是 App 名称（沿用 SourceManager 三层查找），也可以是宿主机上的
        路径（ad-hoc 模式，跳过 registry 直接编译）。路径判定见 _resolve_app_dir。

        流程：
        1. 解析参数为 App 目录（name → SourceManager，path → 直接定位）
        2. 加载 app.yaml 规格（以其中 app.name 为权威身份）
        3. 编译（build.system != "none" 时）
        4. 收集安装文件
        5a. 若为 lib 类型：调用 _build_lib() 生成双包（运行时包 + 开发包）
        5b. 其余类型：打包为单个 .deb

        参数：
            name_or_path: App 名称或路径

        返回：
            代表性 .deb 路径（lib 返回 runtime，多 DEB 返回声明中的首项）

        抛出：
            FileNotFoundError: 路径不存在或缺失 app.yaml
            ValueError:        名称在三层查找中未命中（来自 SourceManager）
        """
        debs = self._build_one_debs(name_or_path)
        return debs[0] if debs else None

    def _build_one_debs(self, name_or_path: str) -> List[Path]:
        """构建单个 App，返回它产出的**全部** deb 路径（amp 类型为空列表）。

        build_all 需要完整清单才能做 per-App 缓存与无主 deb 清理；build_one
        只取首项作为代表，保持既有对外语义。
        """
        from builder.app_spec import load_spec
        from builder.deb import DebBuilder

        # 步骤 1：解析参数为 App 目录
        app_dir = self._resolve_app_dir(name_or_path)

        # 步骤 2：加载规格（app.name 为权威身份）
        spec = load_spec(app_dir)
        app_name = spec.app.name

        self._status(f"开始构建 App '{app_name}' (来源: {app_dir})")

        # amp 类型：协处理器固件，独立分叉——不打 deb、不进 rootfs，也不走
        # host 交叉编译模板（_compile/_BUILD_SYSTEMS）与约定路径收集
        # （collect_files/_CONVENTION_MAP）。固件由 amp 组件在 `flange build`
        # 时把本 app 的 src stage 进 SDK 应用槽位后打进 amp.img。
        if spec.app.type == "amp":
            self._build_amp(app_dir, spec)
            return []

        # 步骤 3：编译并把标准构建系统的 install 产物收集到 staging
        install_dir = self._compile(app_dir, spec, self._config)

        # staging 类型：只产出供下游消费的交叉编译产物树，不打 deb、不进
        # rootfs。它仍进 custom_packages 集合（否则 _resolve_build_order 会
        # 忽略它、根本不构建），但产物清单为空，rootfs 的 glob 自然拿不到它。
        if spec.app.type == "staging":
            self._status(
                f"staging App '{app_name}' 完成 → "
                f"{self._staging_dir(spec)}"
            )
            self._record_app_manifest(name_or_path, app_dir, [])
            return []

        # custom vendor App 可直接交付多个已完成的 deb，避免再套空 wrapper。
        if spec.build.deb_outputs:
            deb_paths = [
                self._output_dir / filename
                for filename in spec.build.deb_outputs
            ]
            missing = [path.name for path in deb_paths if not path.is_file()]
            if missing:
                from builder.docker import BuildError
                raise BuildError(
                    f"App '{app_name}' 缺少声明的 deb 输出: "
                    f"{', '.join(missing)}"
                )
            self._status(
                f"App '{app_name}' 多 deb 交付完成 → "
                f"{', '.join(path.name for path in deb_paths)}"
            )
            self._record_app_manifest(name_or_path, app_dir, deb_paths)
            return deb_paths

        # 步骤 4：lib 类型走双包流程，其余类型走单包流程
        if spec.app.type == "lib":
            outputs = self._build_lib(app_dir, spec, install_dir)
            runtime_path = outputs["runtime"]
            self._status(
                f"lib App '{app_name}' 双包完成 → "
                f"{runtime_path.name}, {outputs['dev'].name}"
            )
            deb_paths = [runtime_path, outputs["dev"]]
            self._record_app_manifest(name_or_path, app_dir, deb_paths)
            return deb_paths

        # 收集文件（非 lib 类型）
        files = self._collect_package_files(app_dir, spec, install_dir)

        # 步骤 5：打包 .deb
        deb_builder = DebBuilder()
        deb_path = deb_builder.build_from_spec(spec, self._arch, files, self._output_dir)
        self._status(f"App '{app_name}' 打包完成 → {deb_path.name}")

        self._record_app_manifest(name_or_path, app_dir, [deb_path])
        return [deb_path]

    def _build_amp(self, app_dir: Path, spec) -> Optional[Path]:
        """amp 类型 app 的独立构建路径：不打 deb、不进 rootfs。

        amp app 是协处理器固件源（裸机 HAL / RT-Thread 之上的用户应用）。其固件
        由 amp 组件（`flange build` → RockchipAmpBuilder）把本 app 的 src stage
        进 SDK 应用槽位、连同 SDK 一起编进 amp.img——故 standalone
        `flange build app <amp>` 不产出 deb（返回 None）。要把它打进固件：在 board
        配置把 amp.app 指向该 app（如 tspi-rk3566 的 amp product），再
        `lunch <board>-amp` + `flange build`。
        """
        self._status(
            f"amp app '{spec.app.name}'：协处理器固件，不打 deb。由 amp 组件经 "
            f"amp.app 打进 amp.img（用 `lunch <board>-amp` + `flange build`）。")
        return None

    # -----------------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------------

    def _build_lib(
        self,
        app_dir: Path,
        spec: AppSpec,
        install_dir: Optional[Path] = None,
    ) -> Dict[str, Path]:
        """为 lib 类型 App 构建双包：运行时包和开发包。

        运行时包（lib<name>）：
          - 收集 lib/ 下的 .so 文件（含 .so.* 版本化符号链接）
          - 安装路径：/usr/lib/

        开发包（lib<name>-dev）：
          - 收集 include/ 下头文件
          - 收集 lib/ 下的 .a 静态库文件
          - Depends 中包含运行时包版本约束

        构建完成后调用 _install_sysroot() 将头文件与 .so 安装到 sysroot。

        参数：
            app_dir: App 工程目录
            spec:    已解析的 AppSpec 对象
            install_dir: 原生 install staging 目录

        返回：
            {"runtime": runtime_deb_path, "dev": dev_deb_path}
        """
        from builder.app_spec import AppInfo, AppSpec, LibConfig
        from builder.deb import DebBuilder, generate_control

        app_name = spec.app.name
        version  = spec.app.version

        # 获取 lib 配置（使用默认值兜底）
        lib_cfg: LibConfig = spec.lib if spec.lib is not None else LibConfig()

        # -----------------------------------------------------------------------
        # 从 collect_files 结果中分拣运行时文件和开发文件
        # -----------------------------------------------------------------------
        all_files = self._collect_package_files(app_dir, spec, install_dir)

        runtime_files: List[Tuple[Path, str, int]] = []  # .so 文件
        dev_files: List[Tuple[Path, str, int]] = []      # 头文件 + .a 文件

        for src_path, install_path, mode in all_files:
            fname = Path(install_path).name
            # lib/ 下的文件：按扩展名分拣到运行时包或开发包
            if install_path.startswith("/usr/lib/"):
                if _is_shared_lib(fname):
                    # 共享库（.so 或 .so.* 版本化文件）→ 运行时包
                    runtime_files.append((src_path, install_path, mode))
                elif fname.endswith(".a"):
                    # 静态库 → 开发包
                    dev_files.append((src_path, install_path, mode))
                elif _is_pkg_config(install_path):
                    # pkg-config 元数据 → 开发包
                    dev_files.append((src_path, install_path, mode))
            elif install_path.startswith("/usr/include/"):
                # 头文件 → 开发包
                dev_files.append((src_path, install_path, mode))

        # debug: 文件分拣结果（仅写日志）

        deb_builder = DebBuilder()

        # -----------------------------------------------------------------------
        # 构建运行时包：lib<name>
        # -----------------------------------------------------------------------
        runtime_name = f"lib{app_name}"

        # 构造运行时包用的 spec 副本（改名，保留原 depends）
        runtime_spec = AppSpec(
            app=AppInfo(
                name=runtime_name,
                version=version,
                description=spec.app.description,
                type="lib",
                arch=spec.app.arch,
            ),
            maintainer=spec.maintainer,
            depends=list(spec.depends),
            build=spec.build,
        )
        runtime_control = generate_control(runtime_spec, self._arch)
        runtime_deb = deb_builder.build_deb(
            name=runtime_name,
            version=version,
            arch=self._arch,
            control_fields=runtime_control,
            files=runtime_files,
            output_dir=self._output_dir,
        )
        # 运行时包生成完毕

        # -----------------------------------------------------------------------
        # 构建开发包：lib<name>-dev
        # -----------------------------------------------------------------------
        dev_suffix = lib_cfg.dev_suffix
        dev_name = f"{runtime_name}{dev_suffix}"

        # 开发包 Depends：包含运行时包的精确版本约束 + 原 spec.depends
        dev_depends = [f"{runtime_name} (= {version})"] + list(spec.depends)

        dev_spec = AppSpec(
            app=AppInfo(
                name=dev_name,
                version=version,
                description=f"{spec.app.description} (开发头文件与静态库)",
                type="lib",
                arch=spec.app.arch,
            ),
            maintainer=spec.maintainer,
            depends=dev_depends,
            build=spec.build,
        )
        dev_control = generate_control(dev_spec, self._arch)
        dev_deb = deb_builder.build_deb(
            name=dev_name,
            version=version,
            arch=self._arch,
            control_fields=dev_control,
            files=dev_files,
            output_dir=self._output_dir,
        )
        # 开发包生成完毕

        # -----------------------------------------------------------------------
        # sysroot 安装：供后续依赖此库的 App 编译使用
        # -----------------------------------------------------------------------
        self._install_sysroot(app_dir, spec, all_files)

        return {"runtime": runtime_deb, "dev": dev_deb}

    def _collect_package_files(
        self,
        app_dir: Path,
        spec: AppSpec,
        install_dir: Optional[Path],
    ) -> List[Tuple[Path, str, int]]:
        """合并 App 目录约定、显式 install 映射与原生 install staging。

        原生 install 产物覆盖同路径的约定文件，但 app.yaml 显式声明的
        install 映射始终优先，保持既有配置语义。
        """
        files = collect_files(app_dir, spec, self._arch)
        if install_dir is None or not install_dir.is_dir():
            return files

        explicit_destinations = {
            destination
            for source, destination in spec.install.items()
            if (app_dir / source).exists() or (app_dir / source).is_symlink()
        }
        destination_indexes = {
            install_path: index
            for index, (_, install_path, _) in enumerate(files)
        }
        for src_path in sorted(install_dir.rglob("*")):
            if not (src_path.is_file() or src_path.is_symlink()):
                continue
            relative = src_path.relative_to(install_dir).as_posix()
            install_path = f"/{relative}"
            if install_path in explicit_destinations:
                continue

            entry = (
                src_path,
                install_path,
                src_path.lstat().st_mode & 0o777,
            )
            index = destination_indexes.get(install_path)
            if index is None:
                destination_indexes[install_path] = len(files)
                files.append(entry)
            else:
                files[index] = entry

        return files

    def _install_sysroot(
        self,
        app_dir: Path,
        spec: AppSpec,
        files: Optional[List[Tuple[Path, str, int]]] = None,
    ) -> None:
        """将 lib App 的头文件和共享库安装到 sysroot 目录。

        安装约定：
          /usr/include/** → sysroot/usr/include/**
          /usr/lib/*.so* 与 pkgconfig/*.pc → sysroot/usr/lib/

        sysroot 路径：target/<board>/<product>/<variant>/sysroot/

        参数：
            app_dir: App 工程目录
            spec:    已解析的 AppSpec 对象
            files: 已合并的打包文件；省略时从 App 与 install staging 重建
        """
        board   = self._config.get("board",   "unknown")
        product = self._config.get("product", "default")
        variant = self._config.get("variant", "release")

        sysroot_base = (
            self._project_dir / ".build/target" / board / product / variant / "sysroot"
        )

        if files is None:
            install_dir = self._native_install_dir(spec)
            files = self._collect_package_files(app_dir, spec, install_dir)

        for src_path, install_path, _mode in files:
            is_header = install_path.startswith("/usr/include/")
            is_library = (
                install_path.startswith("/usr/lib/")
                and _is_shared_lib(Path(install_path).name)
            )
            if not (is_header or is_library or _is_pkg_config(install_path)):
                continue

            relative = Path(install_path.lstrip("/"))
            if ".." in relative.parts:
                raise ValueError(
                    f"sysroot 安装路径不得包含 '..': {install_path}"
                )
            destination = sysroot_base / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            if src_path.is_symlink():
                destination.symlink_to(os.readlink(src_path))
            else:
                shutil.copy2(src_path, destination)

        self._status(f"lib '{spec.app.name}' sysroot 安装完成")

    def _resolve_app_dir(self, name_or_path: str) -> Path:
        """解析入参为 App 目录的绝对路径。

        判定为路径分支的条件（满足任一即可）：
          - 字符串含有 ``/``
          - 字符串以 ``.`` 开头
          - 字符串解析后是一个存在的目录，且其下含 ``app.yaml``

        路径分支：``Path(arg).expanduser().resolve()`` 后校验 ``app.yaml`` 存在，
        失败抛 ``FileNotFoundError``（错误信息含原始字符串）。
        名称分支：委托 ``_find_app_dir`` 走 SourceManager 三层查找。

        参数：
            name_or_path: App 名称或路径字符串

        返回：
            App 目录的绝对路径

        抛出：
            FileNotFoundError: 路径分支下路径不存在或缺失 app.yaml
            ValueError:        名称分支下三层查找均未命中（由 SourceManager 抛出）
        """
        candidate = Path(name_or_path).expanduser()
        is_path = (
            "/" in name_or_path
            or name_or_path.startswith(".")
            or (candidate.is_dir() and (candidate / "app.yaml").is_file())
        )
        if is_path:
            resolved = candidate.resolve()
            if not (resolved.is_dir() and (resolved / "app.yaml").is_file()):
                raise FileNotFoundError(
                    f"App 路径 '{name_or_path}' 不存在或缺失 app.yaml"
                )
            return resolved
        return self._find_app_dir(name_or_path)

    def _find_app_dir(self, app_name: str) -> Path:
        """查找 App 目录——完全委托给 SourceManager.ensure_app()。

        ensure_app 已负责三层查找：本地 → external_apps → external_app_dirs，
        并在未命中时给出详尽的错误信息。此处仅做"source 缺失"的防御性报错。

        参数：
            app_name: App 名称

        返回：
            App 目录 Path

        抛出：
            FileNotFoundError: SourceManager 未配置
            ValueError: App 在三层查找中均未命中
        """
        if self._source is None:
            # 无 SourceManager 时退化为仅查本地，用于早期测试 / 简化场景
            local_dir = self._project_dir / "components" / "app" / app_name
            if (local_dir / "app.yaml").is_file():
                return local_dir
            raise FileNotFoundError(
                f"App '{app_name}' 目录不存在，已查找：{local_dir}"
            )
        return self._source.ensure_app(app_name, self._config)

    def _spec_dir(self, app_name: str) -> Path:
        """解析仅用于读取 app.yaml 的 App 目录。

        优先用 cache 的只读解析：排序阶段只需要 ``build.deps``，不该为此对
        每个 App 走一遍 ``SourceManager.ensure_app``（git 来源会真的 fetch）。
        只有在只读解析拿不到 app.yaml 时才回退到 ensure，让首次构建照常
        clone。
        """
        if self.cache is not None:
            candidate = self.cache._registered_app_source_dir(app_name)
            if (candidate / "app.yaml").is_file():
                return candidate
        return self._find_app_dir(app_name)

    def _resolve_build_order(self, app_names: list[str]) -> list[str]:
        """解析各 App 的 build.deps，拓扑排序返回构建顺序。

        仅将 app_names 集合内的依赖纳入排序；集合外的依赖被忽略
        （认为已在系统中安装，不需要本次构建）。

        参数：
            app_names: 待构建的 App 名称列表

        返回：
            拓扑排序后的名称列表

        抛出：
            CircularDependencyError: 存在循环依赖
        """
        from builder.app_spec import load_spec

        app_set = set(app_names)
        graph: dict[str, list[str]] = {}

        for name in app_names:
            app_dir = self._spec_dir(name)
            spec = load_spec(app_dir)
            # 仅保留同属本次构建集合的依赖
            graph[name] = [d for d in spec.build.deps if d in app_set]

        return _topo_sort_apps(graph)

    def _build_commands(self, spec: AppSpec, config: dict) -> list[list[str]]:
        """根据构建规格生成实际执行的命令列表。

        处理流程：
        1. 从 _BUILD_SYSTEMS 模板中克隆基础命令
        2. 注入与目标架构匹配的交叉编译参数（CROSS_COMPILE、CMAKE 编译器等）
        3. 将 build.options 展开为对应构建系统的参数格式
        4. 若存在 sysroot（build.deps 非空），注入 sysroot 路径

        参数：
            spec:   已加载的 AppSpec
            config: FINAL_CONFIG 字典，需包含 board/product/variant/arch 字段

        返回：
            命令步骤列表，每个步骤是 argv 字符串列表
        """
        system = spec.build.system
        arch = userspace_arch(config)
        variant = config.get("variant", "release")
        is_debug = variant == "debug"

        # custom 构建系统：直接使用 spec.build.commands，不做任何模板展开
        if system == "custom":
            # 深拷贝，避免意外修改 spec 内部状态
            return [list(cmd) for cmd in spec.build.commands]

        # 从模板深拷贝基础命令，避免污染全局常量
        template = _BUILD_SYSTEMS.get(system, [])
        if not template:
            # none 或未知系统，返回空列表
            return []
        commands = [list(step) for step in template]

        # ------------------------------------------------------------------
        # 注入目标架构的交叉编译参数
        # ------------------------------------------------------------------
        cross_prefix = _CROSS_COMPILE_PREFIX.get(arch, "aarch64-linux-gnu-")
        cross_gcc = f"{cross_prefix}gcc"
        cross_gxx = f"{cross_prefix}g++"

        if system == "cmake":
            # 替换 configure 步骤中的编译器标志
            for i, arg in enumerate(commands[0]):
                if arg.startswith("-DCMAKE_C_COMPILER="):
                    commands[0][i] = f"-DCMAKE_C_COMPILER={cross_gcc}"
                elif arg.startswith("-DCMAKE_CXX_COMPILER="):
                    commands[0][i] = f"-DCMAKE_CXX_COMPILER={cross_gxx}"
            if "CMAKE_BUILD_TYPE" not in spec.build.options:
                build_type = "Debug" if is_debug else "Release"
                commands[0].append(f"-DCMAKE_BUILD_TYPE={build_type}")
            if "CMAKE_INSTALL_PREFIX" not in spec.build.options:
                commands[0].append("-DCMAKE_INSTALL_PREFIX=/usr")

        elif system == "make":
            # 替换 CROSS_COMPILE= 参数
            for i, arg in enumerate(commands[0]):
                if arg.startswith("CROSS_COMPILE="):
                    commands[0][i] = f"CROSS_COMPILE={cross_prefix}"
            if "CFLAGS" not in spec.build.options:
                flags = "-Wall -O0 -g" if is_debug else "-Wall -O2"
                commands[0].append(f"CFLAGS={flags}")

        elif system == "meson":
            # Meson 使用 cross-file，不直接替换命令参数；
            # 架构信息在 /etc/meson/cross-*.ini 中由 Docker 镜像管理
            if "buildtype" not in spec.build.options:
                build_type = "debug" if is_debug else "release"
                commands[0].append(f"--buildtype={build_type}")
            if "prefix" not in spec.build.options:
                commands[0].append("--prefix=/usr")

        elif system == "swift":
            configuration = spec.build.options.get("configuration")
            if not configuration:
                configuration = "debug" if is_debug else "release"
            # 替换 --triple 后面的目标三元组
            for i, arg in enumerate(commands[0]):
                if arg == "-c" and i + 1 < len(commands[0]):
                    commands[0][i + 1] = configuration
                elif arg == "--triple" and i + 1 < len(commands[0]):
                    # 根据架构构造 LLVM 三元组
                    triple_map = {
                        "aarch64": "aarch64-unknown-linux-gnu",
                        "armhf":   "armv7-unknown-linux-gnueabihf",
                        "x86_64":  "x86_64-unknown-linux-gnu",
                    }
                    commands[0][i + 1] = triple_map.get(arch, f"{arch}-unknown-linux-gnu")

        # ------------------------------------------------------------------
        # 展开 build.options
        # ------------------------------------------------------------------
        options = spec.build.options  # dict[str, str]
        if options:
            if system == "cmake":
                # CMake 选项格式：-DKEY=VALUE，追加到 configure 步骤
                for key, value in options.items():
                    commands[0].append(f"-D{key}={value}")

            elif system == "meson":
                # Meson 选项格式：-Dkey=value，追加到 setup 步骤
                for key, value in options.items():
                    commands[0].append(f"-D{key}={value}")

            elif system == "make":
                # Make 选项格式：KEY=VALUE，追加到 make 步骤
                for key, value in options.items():
                    commands[0].append(f"{key}={value}")

            elif system == "swift":
                # Swift 选项格式：--key value 或仅 --key（value 为空时）
                for key, value in options.items():
                    commands[0].append(f"--{key}")
                    if value:
                        commands[0].append(value)

        # ------------------------------------------------------------------
        # Sysroot 注入（当 build.deps 非空时启用）
        # ------------------------------------------------------------------
        if spec.build.deps:
            board   = config.get("board",   "unknown")
            product = config.get("product", "default")
            variant = config.get("variant", "release")
            # sysroot 目录约定：.build/target/<board>/<product>/<variant>/sysroot/
            sysroot = (
                self._project_dir
                / ".build/target" / board / product / variant / "sysroot"
            )
            sysroot_str = str(sysroot)

            if system == "cmake":
                commands[0].append(f"-DCMAKE_SYSROOT={sysroot_str}")

            elif system == "make":
                cflags_index = next(
                    (
                        index
                        for index in range(len(commands[0]) - 1, -1, -1)
                        if commands[0][index].startswith("CFLAGS=")
                    ),
                    None,
                )
                include_flag = f"-I{sysroot_str}/usr/include"
                if cflags_index is None:
                    commands[0].append(f"CFLAGS={include_flag}")
                else:
                    commands[0][cflags_index] += f" {include_flag}"
                ldflags_index = next(
                    (
                        index
                        for index in range(len(commands[0]) - 1, -1, -1)
                        if commands[0][index].startswith("LDFLAGS=")
                    ),
                    None,
                )
                library_flag = f"-L{sysroot_str}/usr/lib"
                if ldflags_index is None:
                    commands[0].append(f"LDFLAGS={library_flag}")
                else:
                    commands[0][ldflags_index] += f" {library_flag}"

            elif system == "meson":
                # Meson 的 sysroot 通过 cross-file 管理，此处不做额外注入
                pass

        # ------------------------------------------------------------------
        # $(nproc) 占位符替换为实际 CPU 数
        #
        # _BUILD_SYSTEMS 模板里写的是 "-j$(nproc)" 字面量，沿 shell 习惯保留；
        # 但 DockerRunner.run 用 argv 直跑、不经 shell，cmake/make 会把
        # "$(nproc)" 当成字面字符串而报 "invalid number"。这里在生成命令时
        # 把所有 token 内的 "$(nproc)" 替换成 os.cpu_count() 的字符串值。
        # ------------------------------------------------------------------
        nproc = str(os.cpu_count() or 1)
        commands = [[tok.replace("$(nproc)", nproc) for tok in cmd] for cmd in commands]

        return commands

    def _compile(
        self,
        app_dir: Path,
        spec: AppSpec,
        config: dict,
    ) -> Optional[Path]:
        """编译 App。

        根据 build.system 选择执行策略：
        - none：预编译包，直接跳过
        - custom：执行 spec.build.commands 中的命令列表
        - 其余（cmake/meson/make/swift）：通过 _build_commands 生成命令后逐步执行

        所有命令均通过 DockerRunner 在容器内执行，工作目录设为 app_dir。
        当 app_dir 不在项目根目录子树内（out-of-tree 模式）时，把 app_dir 作为
        extra_mounts 注入，让 DockerRunner 在 docker compose run 时动态挂入容器。

        参数：
            app_dir: App 目录（容器内的工作目录）
            spec:    已加载的 AppSpec
            config:  FINAL_CONFIG 字典

        返回：
            标准构建系统的 install staging 目录；其他构建系统返回 None
        """
        system = spec.build.system

        if system == "none":
            # 预编译 App，无需编译步骤
            return None

        self._status(f"App '{spec.app.name}' 编译 ({system})")

        # 生成命令列表
        commands = self._build_commands(spec, config)

        # out-of-tree 检测：app_dir 不在 project_dir 子树时需动态挂入容器
        extra_mounts = None
        try:
            app_dir.resolve().relative_to(self._project_dir.resolve())
        except ValueError:
            extra_mounts = [app_dir]

        self._install_build_packages(
            spec,
            cwd=str(app_dir),
            extra_mounts=extra_mounts,
        )

        # 逐步执行编译命令
        cwd = str(app_dir)
        work_dir = (
            build_dir(self._project_dir)
            / "work" / "apps" / spec.app.name / self._arch
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        build_env = {
            "FLANGE_BUILD_ROOT": str(build_dir(self._project_dir).resolve()),
            "FLANGE_APP_WORK_DIR": str(work_dir.resolve()),
            "FLANGE_APP_OUTPUT_DIR": str(self._output_dir.resolve()),
            "FLANGE_TARGET_ARCH": self._arch,
        }
        for cmd in commands:
            self._docker.run(
                cmd,
                cwd=cwd,
                env=build_env,
                extra_mounts=extra_mounts,
            )

        if system not in _NATIVE_INSTALL_SYSTEMS:
            return None

        install_dir = self._native_install_dir(spec)
        assert install_dir is not None
        if install_dir.exists():
            shutil.rmtree(install_dir)
        install_env = {**build_env, "DESTDIR": str(install_dir.resolve())}

        if system == "cmake":
            install_cmd = ["cmake", "--install", "build"]
        elif system == "meson":
            install_cmd = ["meson", "install", "-C", "build"]
        elif system == "make":
            make_variables = [arg for arg in commands[0][1:] if "=" in arg]
            destdir_arg = f"DESTDIR={install_dir.resolve()}"
            probe_cmd = [
                "make", "-n", "install", *make_variables, destdir_arg,
            ]
            probe = self._docker.run(
                probe_cmd,
                cwd=cwd,
                env=install_env,
                check=False,
                capture=True,
                extra_mounts=extra_mounts,
            )
            if probe.returncode != 0:
                output = "\n".join(
                    str(value) for value in (probe.stdout, probe.stderr)
                    if value
                )
                no_rule_prefixes = (
                    "make: *** No rule to make target 'install'",
                    "make: *** No rule to make target `install'",
                )
                missing_install_target = any(
                    line.strip().startswith(no_rule_prefixes)
                    for line in output.splitlines()
                )
                if missing_install_target:
                    self._status(
                        f"App '{spec.app.name}' 未定义 Make install target，"
                        "回退约定文件收集"
                    )
                    return None
                from builder.docker import BuildError
                detail = f"\n{output.strip()}" if output.strip() else ""
                raise BuildError(
                    f"Make install target 检查失败 "
                    f"(exit {probe.returncode}){detail}"
                )
            install_cmd = [
                "make",
                "install",
                *make_variables,
                destdir_arg,
            ]
        else:
            swift_cmd = commands[0]
            configuration = swift_cmd[swift_cmd.index("-c") + 1]
            triple = swift_cmd[swift_cmd.index("--triple") + 1]
            executable = Path(".build") / triple / configuration / spec.app.name
            destination = install_dir / "usr" / "bin" / spec.app.name
            install_cmd = [
                "install", "-Dm755", str(executable), str(destination),
            ]

        install_dir.mkdir(parents=True)
        self._docker.run(
            install_cmd,
            cwd=cwd,
            env=install_env,
            extra_mounts=extra_mounts,
        )
        return install_dir

    def _install_build_packages(
        self,
        spec: AppSpec,
        *,
        cwd: str,
        extra_mounts: Optional[List[Path]],
    ) -> None:
        """在当前构建容器中安装 App 声明的 APT 编译依赖。"""
        from builder.deb import _map_arch

        apt_arch = _map_arch(self._arch)
        requested = list(dict.fromkeys(
            package.replace("{arch}", apt_arch)
            for package in spec.build.apt_packages
        ))
        pending = [
            package
            for package in requested
            if package not in self._installed_build_packages
        ]
        if not pending:
            return

        if not self._apt_index_updated:
            self._status("更新 App 构建依赖 APT 索引")
            self._docker.run(
                ["apt-get", "update"],
                cwd=cwd,
                extra_mounts=extra_mounts,
            )
            self._apt_index_updated = True

        self._status(
            f"安装 App 构建依赖 ({self._arch}): {', '.join(pending)}"
        )
        self._docker.run(
            [
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                "-o",
                "Dir::Cache::archives=/cache/apt",
                *pending,
            ],
            cwd=cwd,
            extra_mounts=extra_mounts,
        )
        self._installed_build_packages.update(pending)
