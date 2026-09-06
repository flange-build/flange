"""Jsonnet canonical 配置注册表。"""

from pathlib import Path

from builder.config.jsonnet import JsonnetConfigLoader, JsonnetEvaluator
from builder.paths import PROJECT_ROOT, components_dir


def _root(project_root: Path | None) -> Path:
    return Path(project_root) if project_root else PROJECT_ROOT


def _discover_platform_configs(
    project_root: Path | None = None,
) -> dict[str, str]:
    root = _root(project_root)
    platform_dir = components_dir(root) / "platform"
    return (
        {
            child.name: str((child / "config.jsonnet").relative_to(root))
            for child in sorted(platform_dir.iterdir())
            if child.is_dir() and (child / "config.jsonnet").is_file()
        }
        if platform_dir.is_dir()
        else {}
    )


def _discover_soc_configs(
    project_root: Path | None = None,
) -> dict[str, str]:
    root = _root(project_root)
    result: dict[str, str] = {}
    for platform in _discover_platform_configs(root):
        directory = components_dir(root) / "platform" / platform
        for child in sorted(directory.iterdir()):
            path = child / "config.jsonnet"
            if child.is_dir() and path.is_file():
                result[child.name] = str(path.relative_to(root))
    return result


def _evaluate_overlay(path: Path, project_root: Path) -> dict:
    result = (
        JsonnetEvaluator(project_root)
        .evaluate_file(path, ext_vars={"product": "default", "variant": "release"})
        .config
    )
    JsonnetConfigLoader._validate_authored_shape(result)
    return result


def _load_platform_config(
    platform: str,
    project_root: Path | None = None,
) -> dict:
    root = _root(project_root)
    configs = _discover_platform_configs(root)
    if platform not in configs:
        raise ValueError(f"未发现平台：{platform}（可用: {', '.join(sorted(configs)) or '无'}）")
    return _evaluate_overlay(root / configs[platform], root)


def _load_soc_config(soc: str, project_root: Path | None = None) -> dict:
    root = _root(project_root)
    configs = _discover_soc_configs(root)
    if soc not in configs:
        raise ValueError(f"未发现 SoC：{soc}（可用: {', '.join(sorted(configs)) or '无'}）")
    return _evaluate_overlay(root / configs[soc], root)


def discover_boards(project_root: Path | None = None) -> dict[str, dict]:
    """扫描 board/*/config.jsonnet 并返回身份元数据。"""
    root = _root(project_root)
    board_dir = components_dir(root) / "board"
    if not board_dir.is_dir():
        return {}
    loader = JsonnetConfigLoader(root)
    boards: dict[str, dict] = {}
    for child in sorted(board_dir.iterdir()):
        if child.is_dir() and (child / "config.jsonnet").is_file():
            boards[child.name] = loader.board_identity(child.name)
    return boards


def _require_board(
    board_name: str,
    boards: dict[str, dict] | None,
    root: Path,
) -> dict:
    available = boards if boards is not None else discover_boards(root)
    if board_name not in available:
        raise KeyError(f"未找到板子 {board_name!r}；可用: {', '.join(sorted(available)) or '无'}")
    return available[board_name]


def get_board_config(
    board_name: str,
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> dict:
    """求值指定 board 的首个 product/variant canonical 配置。"""
    root = _root(project_root)
    identity = _require_board(board_name, boards, root)
    return JsonnetConfigLoader(root).evaluate_board(
        board_name,
        identity.get("products", ["default"])[0],
        identity.get("variants", ["release"])[0],
    )


def resolve_config(
    board_name: str,
    product: str,
    variant: str,
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> dict:
    """按显式 product/variant 求值并返回最终 canonical 配置。"""
    root = _root(project_root)
    _require_board(board_name, boards, root)
    return JsonnetConfigLoader(root).evaluate_board(board_name, product, variant)
