"""配置注册表。

扫描 board/*/config.py 发现所有板子，按 rootfs 基线 + platform -> SoC -> board
继承合并配置，并支持 product/variant 条件解析。
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from builder.config.apps import normalize_app_sources
from builder.config.merge import deep_merge, resolve_conditions
from builder.paths import PROJECT_ROOT, components_dir


def _unique_preserve_order(items: list[str]) -> list[str]:
    """按首次出现顺序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _expand_rootfs_package_sets(config: dict) -> dict:
    """将 rootfs.package_set 展开到 rootfs.packages。

    ``components/rootfs/config.py`` 提供平台无关的包集合。platform / SoC /
    board 仍可通过 ``rootfs.+packages`` 或条件标记追加硬件相关包。
    """
    rootfs_cfg = config.get("rootfs")
    if not isinstance(rootfs_cfg, dict):
        return config

    package_sets = rootfs_cfg.get("package_sets") or {}
    package_set = rootfs_cfg.get("package_set") or []
    if isinstance(package_set, str):
        package_set = [package_set]

    expanded: list[str] = []
    for set_name in package_set:
        if set_name not in package_sets:
            raise ValueError(f"rootfs.package_set 引用了未知集合: {set_name}")
        expanded.extend(package_sets[set_name])

    explicit_packages = rootfs_cfg.get("packages") or []
    rootfs_cfg["packages"] = _unique_preserve_order(
        expanded + explicit_packages
    )
    return config


def _discover_platform_configs(project_root: Path) -> dict[str, str]:
    """自动扫描 components/platform/*/config.py，返回 {平台名: 配置文件相对路径} 映射。"""
    platform_dir = components_dir(project_root) / "platform"
    result: dict[str, str] = {}
    if not platform_dir.is_dir():
        return result
    for child in sorted(platform_dir.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        config_file = child / "config.py"
        if config_file.is_file():
            result[child.name] = str(config_file.relative_to(project_root))
    return result


def _discover_soc_configs(project_root: Path) -> dict[str, str]:
    """自动扫描 components/platform/*/*/config.py，返回 {SoC名: 配置文件相对路径} 映射。

    SoC 目录是平台目录的直接子目录（排除 __pycache__ 等）。
    """
    platform_dir = components_dir(project_root) / "platform"
    result: dict[str, str] = {}
    if not platform_dir.is_dir():
        return result
    for plat_child in sorted(platform_dir.iterdir()):
        if not plat_child.is_dir() or plat_child.name.startswith((".", "_")):
            continue
        for soc_child in sorted(plat_child.iterdir()):
            if not soc_child.is_dir() or soc_child.name.startswith((".", "_")):
                continue
            config_file = soc_child / "config.py"
            if config_file.is_file():
                result[soc_child.name] = str(config_file.relative_to(project_root))
    return result


def _load_rootfs_config(project_root: Path | None = None) -> dict:
    """加载平台无关的 rootfs 基线配置。

    该配置位于 ``components/rootfs/config.py``，用于声明与具体 platform、
    SoC、board 无关的 rootfs 输入。文件缺失时返回空 dict，保持旧项目布局
    兼容。
    """
    root = Path(project_root) if project_root else _project_root()
    config_file = components_dir(root) / "rootfs" / "config.py"
    if not config_file.is_file():
        return {}
    return _load_module_var(config_file, "ROOTFS")


def _load_overlay_config(project_root: Path | None = None) -> dict:
    """加载 device-tree-overlay 组件的基线配置。

    该配置位于 ``components/device-tree-overlay/config.py``，声明 vendor
    overlay 仓库的 git source（repo + ref）以及 ``boot.vendor_overlays``
    默认空列表。多 vendor 共用同一仓库，source 声明放在这里以保持单一来源。
    文件缺失时返回空 dict（保持旧项目布局兼容）。
    """
    root = Path(project_root) if project_root else _project_root()
    config_file = components_dir(root) / "device-tree-overlay" / "config.py"
    if not config_file.is_file():
        return {}
    return _load_module_var(config_file, "DEVICE_TREE_OVERLAY")


def _project_root() -> Path:
    """返回项目根目录。"""
    return PROJECT_ROOT


def _load_module_var(file_path: Path, var_name: str) -> Any:
    """使用 importlib.util 从文件加载指定变量。

    避免使用 import 语句，因为板级目录名含连字符（如 radxa-zero3w），
    不是合法的 Python 包名。
    """
    module_name = f"_flange_dynamic_{file_path.stem}_{id(file_path)}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载配置文件：{file_path}")
    module = importlib.util.module_from_spec(spec)
    # 不注册到 sys.modules，避免污染全局命名空间
    spec.loader.exec_module(module)
    if not hasattr(module, var_name):
        raise ValueError(f"配置文件 {file_path} 缺少变量 {var_name}")
    return getattr(module, var_name)


def discover_boards(project_root: Path | None = None) -> dict[str, dict]:
    """扫描 board/*/config.py，返回 {板名: BOARD字典} 映射。

    仅发现含 config.py 的板级目录，跳过无配置的目录。
    """
    root = Path(project_root) if project_root else _project_root()
    board_dir = components_dir(root) / "board"
    boards: dict[str, dict] = {}

    if not board_dir.is_dir():
        return boards

    for child in sorted(board_dir.iterdir()):
        config_file = child / "config.py"
        if child.is_dir() and config_file.is_file():
            board_cfg = _load_module_var(config_file, "BOARD")
            board_name = board_cfg.get("board", child.name)
            boards[board_name] = board_cfg

    return boards


def _load_platform_config(platform: str, project_root: Path | None = None) -> dict:
    """加载平台配置（第一层）。"""
    root = Path(project_root) if project_root else _project_root()
    configs = _discover_platform_configs(root)
    rel_path = configs.get(platform)
    if rel_path is None:
        available = ", ".join(sorted(configs)) or "无"
        raise ValueError(f"未发现平台：{platform}（可用: {available}）")
    return _load_module_var(root / rel_path, "PLATFORM")


def _load_soc_config(soc: str, project_root: Path | None = None) -> dict:
    """加载 SoC 配置（第二层）。"""
    root = Path(project_root) if project_root else _project_root()
    configs = _discover_soc_configs(root)
    rel_path = configs.get(soc)
    if rel_path is None:
        available = ", ".join(sorted(configs)) or "无"
        raise ValueError(f"未发现 SoC：{soc}（可用: {available}）")
    return _load_module_var(root / rel_path, "SOC")


def get_board_config(
    board_name: str,
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> dict:
    """rootfs 基线 + 三层合并，返回合并后的配置。

    不做条件解析（不处理 product/variant），仅做深度合并。rootfs 基线只
    承载平台无关的 rootfs 字段；platform -> SoC -> board 仍是硬件配置
    的三层继承主体。
    """
    root = Path(project_root) if project_root else _project_root()

    if boards is None:
        boards = discover_boards(root)

    if board_name not in boards:
        raise KeyError(f"未找到板子：{board_name}")

    board_cfg = boards[board_name]
    platform_name = board_cfg["platform"]
    soc_name = board_cfg["soc"]

    # 平台无关的基线配置：rootfs（包集合）+ device-tree-overlay（vendor overlay
    # 仓库 source pin）。两者都是跨 platform 共享的"组件级默认"，先合并到一起
    # 再被 platform / SoC / board 覆盖。
    rootfs_cfg = _load_rootfs_config(root)
    overlay_cfg = _load_overlay_config(root)
    baseline = deep_merge(rootfs_cfg, overlay_cfg)
    # 第一层：平台配置
    platform_cfg = _load_platform_config(platform_name, root)
    merged = deep_merge(baseline, platform_cfg)
    # 第二层：SoC 配置合并到平台上
    soc_cfg = _load_soc_config(soc_name, root)
    merged = deep_merge(merged, soc_cfg)
    # 第三层：板级配置合并到 SoC 上
    merged = deep_merge(merged, board_cfg)

    return merged


def resolve_config(
    board_name: str,
    product: str,
    variant: str,
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> dict:
    """完整配置解析：三层合并 + 条件解析。

    先执行 get_board_config 三层合并，再调用 resolve_conditions
    展开 product/variant 条件标记。
    """
    root = Path(project_root) if project_root else _project_root()
    merged = get_board_config(
        board_name, boards=boards, project_root=root
    )
    resolved = resolve_conditions(merged, product=product, variant=variant)
    resolved = _expand_rootfs_package_sets(resolved)
    # App 来源字段归一化：校验 external_apps 互斥 + 解析 local_path / external_app_dirs
    # 到绝对路径，确保下游模块（SourceManager、app_list）拿到一致的形态。
    return normalize_app_sources(resolved, project_root=root)
