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

预编译二进制架构后缀选择规则：
  aarch64 目标：匹配 -arm64、-aarch64 后缀
  armhf   目标：匹配 -armhf、-arm32 后缀
  匹配后去掉后缀作为安装文件名；不匹配目标架构的文件排除。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from builder.app_spec import AppSpec

log = logging.getLogger("flange")


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
            log.warning(f"install 映射的源文件不存在，跳过: {src_path}")
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

        # 推导输出目录：target/<board>/<product>/<variant>/app/
        board   = config.get("board", "unknown")
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self._output_dir = self._project_dir / "target" / board / product / variant / "app"

        # 目标架构
        self._arch: str = config.get("arch", "aarch64")

    # -----------------------------------------------------------------------
    # 公开接口
    # -----------------------------------------------------------------------

    def build_all(self) -> Dict[str, Path]:
        """构建所有 custom_packages，返回 {app_name: deb_path}。

        从 config["rootfs"]["custom_packages"] 获取待构建 App 列表，
        按拓扑排序顺序逐个调用 build_one()。

        返回：
            {app_name: .deb 路径} 字典
        """
        custom_packages: list[str] = (
            self._config.get("rootfs", {}).get("custom_packages", [])
        )
        if not custom_packages:
            log.info("AppBuilder: custom_packages 为空，无需构建任何 App")
            return {}

        log.info(f"AppBuilder: 待构建 App 列表：{custom_packages}")
        ordered = self._resolve_build_order(custom_packages)
        log.info(f"AppBuilder: 构建顺序（拓扑排序）：{ordered}")

        results: Dict[str, Path] = {}
        for name in ordered:
            deb_path = self.build_one(name)
            results[name] = deb_path

        return results

    def build_one(self, app_name: str) -> Path:
        """构建单个 App，返回生成的 .deb 路径。

        流程：
        1. 查找 App 目录
        2. 加载 app.yaml 规格
        3. 编译（build.system != "none" 时，当前为占位实现，Task 5 完成）
        4. 收集安装文件
        5. 打包为 .deb

        参数：
            app_name: App 名称（与目录名一致）

        返回：
            .deb 文件路径

        抛出：
            FileNotFoundError: App 目录或 app.yaml 不存在
        """
        from builder.app_spec import load_spec
        from builder.deb import DebBuilder

        log.info(f"AppBuilder: 开始构建 App '{app_name}'")

        # 步骤 1：查找 App 目录
        app_dir = self._find_app_dir(app_name)
        log.debug(f"AppBuilder: App 目录 = {app_dir}")

        # 步骤 2：加载规格
        spec = load_spec(app_dir)
        log.debug(f"AppBuilder: 已加载规格，版本 = {spec.app.version}")

        # 步骤 3：编译
        self._compile(app_dir, spec, self._config)

        # 步骤 4：收集文件
        files = collect_files(app_dir, spec, self._arch)
        log.debug(f"AppBuilder: 收集到 {len(files)} 个文件")

        # 步骤 5：打包 .deb
        deb_builder = DebBuilder()
        deb_path = deb_builder.build_from_spec(spec, self._arch, files, self._output_dir)
        log.info(f"AppBuilder: App '{app_name}' 打包完成 → {deb_path}")

        return deb_path

    # -----------------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------------

    def _find_app_dir(self, app_name: str) -> Path:
        """查找 App 目录。

        当前仅支持在 <project_dir>/app/<name>/ 中查找。
        Task 7 将扩展为支持 SourceManager 外部仓库查找。

        参数：
            app_name: App 名称

        返回：
            App 目录 Path

        抛出：
            FileNotFoundError: App 目录不存在
        """
        # 优先在本地 app/ 目录查找
        local_dir = self._project_dir / "app" / app_name
        if local_dir.is_dir():
            return local_dir

        raise FileNotFoundError(
            f"App '{app_name}' 目录不存在，已查找：{local_dir}"
        )

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
            app_dir = self._find_app_dir(name)
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
        arch   = config.get("arch", "aarch64")

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

        elif system == "make":
            # 替换 CROSS_COMPILE= 参数
            for i, arg in enumerate(commands[0]):
                if arg.startswith("CROSS_COMPILE="):
                    commands[0][i] = f"CROSS_COMPILE={cross_prefix}"

        elif system == "meson":
            # Meson 使用 cross-file，不直接替换命令参数；
            # 架构信息在 /etc/meson/cross-*.ini 中由 Docker 镜像管理
            pass

        elif system == "swift":
            # 替换 --triple 后面的目标三元组
            for i, arg in enumerate(commands[0]):
                if arg == "--triple" and i + 1 < len(commands[0]):
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
            # sysroot 目录约定：target/<board>/<product>/<variant>/sysroot/
            sysroot = (
                self._project_dir
                / "target" / board / product / variant / "sysroot"
            )
            sysroot_str = str(sysroot)

            if system == "cmake":
                commands[0].append(f"-DCMAKE_SYSROOT={sysroot_str}")

            elif system == "make":
                commands[0].append(f"CFLAGS=-I{sysroot_str}/usr/include")
                commands[0].append(f"LDFLAGS=-L{sysroot_str}/usr/lib")

            elif system == "meson":
                # Meson 的 sysroot 通过 cross-file 管理，此处不做额外注入
                pass

        return commands

    def _compile(self, app_dir: Path, spec: AppSpec, config: dict) -> None:
        """编译 App。

        根据 build.system 选择执行策略：
        - none：预编译包，直接跳过
        - custom：执行 spec.build.commands 中的命令列表
        - 其余（cmake/meson/make/swift）：通过 _build_commands 生成命令后逐步执行

        所有命令均通过 DockerRunner 在容器内执行，工作目录设为 app_dir。

        参数：
            app_dir: App 目录（容器内的工作目录）
            spec:    已加载的 AppSpec
            config:  FINAL_CONFIG 字典
        """
        system = spec.build.system

        if system == "none":
            # 预编译 App，无需编译步骤
            log.debug(f"AppBuilder: App '{spec.app.name}' 为预编译包，跳过编译")
            return

        log.info(
            f"AppBuilder: App '{spec.app.name}' 使用构建系统 '{system}'，开始编译"
        )

        # 生成命令列表
        commands = self._build_commands(spec, config)

        # 逐步执行编译命令
        cwd = str(app_dir)
        for cmd in commands:
            log.debug(f"AppBuilder: 执行命令 {cmd}")
            self._docker.run(cmd, cwd=cwd)
