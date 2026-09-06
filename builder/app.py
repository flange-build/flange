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

from pathlib import Path
from typing import List, Tuple

from builder.app_spec import AppSpec


# ---------------------------------------------------------------------------
# 架构后缀映射表：目标架构 → 允许的文件名后缀列表
# ---------------------------------------------------------------------------

_ARCH_SUFFIXES: dict[str, list[str]] = {
    "aarch64": ["-arm64", "-aarch64"],
    "armhf": ["-armhf", "-arm32"],
    "x86_64": ["-x86_64", "-amd64"],
    "i386": ["-i386", "-x86"],
    "riscv64": ["-riscv64"],
}

# ---------------------------------------------------------------------------
# 约定映射：子目录名 → (安装路径模板, 文件权限)
# 模板中 {name} 会被替换为 app 名称
# ---------------------------------------------------------------------------

_CONVENTION_MAP: dict[str, tuple[str, int]] = {
    "bin": ("/usr/bin/", 0o755),
    "lib": ("/usr/lib/", 0o644),
    "include": ("/usr/include/{name}/", 0o644),
    "conf": ("/etc/{name}/", 0o644),
    "scripts": ("/usr/lib/{name}/", 0o755),
    "systemd": ("/lib/systemd/system/", 0o644),
    "udev": ("/lib/udev/rules.d/", 0o644),
    "res": ("/usr/share/{name}/", 0o644),
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
                results.append(
                    (
                        src_file,
                        f"/{relative}",
                        mode,
                        f"rootfs/{relative}",
                    )
                )

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

# 构建服务与纯文件收集分开，外部调用统一从此导入。
from builder.app_build import AppBuilder  # noqa: E402,F401
