"""配置注册表。

扫描 board/*/config.py 发现所有板子，按 platform -> SoC -> board
三层继承合并配置，并支持 product/variant 条件解析。
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from config.merge import deep_merge, resolve_conditions

def _discover_platform_configs(project_root: Path) -> dict[str, str]:
    """自动扫描 platform/*/config.py，返回 {平台名: 配置文件相对路径} 映射。"""
    platform_dir = project_root / "platform"
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
    """自动扫描 platform/*/*/config.py，返回 {SoC名: 配置文件相对路径} 映射。

    SoC 目录是平台目录的直接子目录（排除 __pycache__ 等）。
    """
    platform_dir = project_root / "platform"
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


def _project_root() -> Path:
    """返回项目根目录（config/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


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
    board_dir = root / "board"
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
    """三层合并：platform -> SoC -> board，返回合并后的配置。

    不做条件解析（不处理 product/variant），仅做深度合并。
    """
    root = Path(project_root) if project_root else _project_root()

    if boards is None:
        boards = discover_boards(root)

    if board_name not in boards:
        raise KeyError(f"未找到板子：{board_name}")

    board_cfg = boards[board_name]
    platform_name = board_cfg["platform"]
    soc_name = board_cfg["soc"]

    # 第一层：平台配置
    platform_cfg = _load_platform_config(platform_name, root)
    # 第二层：SoC 配置合并到平台上
    soc_cfg = _load_soc_config(soc_name, root)
    merged = deep_merge(platform_cfg, soc_cfg)
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
    merged = get_board_config(
        board_name, boards=boards, project_root=project_root
    )
    return resolve_conditions(merged, product=product, variant=variant)
