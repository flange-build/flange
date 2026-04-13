"""配置查询接口。

提供目标枚举（get_valid_targets）和目标解析（parse_target），
供 CLI 和构建系统使用。
"""

from pathlib import Path

from config.registry import discover_boards, get_board_config


def _merged_configs(
    boards: dict[str, dict],
    project_root: Path | None = None,
) -> dict[str, dict]:
    """返回 {board_name: merged_config} 映射（三层合并后）。

    products/variants 等字段可能来自 platform 层，必须用合并结果才能正确读取。
    """
    return {
        name: get_board_config(name, boards=boards, project_root=project_root)
        for name in boards
    }


def get_valid_targets(
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> list[str]:
    """返回所有合法的 <board>-<product>-<variant> 目标列表。

    按字母序排列，便于用户浏览。
    """
    if boards is None:
        boards = discover_boards(project_root)

    merged = _merged_configs(boards, project_root)
    targets: list[str] = []
    for board_name, cfg in sorted(merged.items()):
        products = cfg.get("products", ["default"])
        variants = cfg.get("variants", ["release"])
        for product in products:
            for variant in variants:
                targets.append(f"{board_name}-{product}-{variant}")

    return targets


def parse_target(
    target: str,
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> dict[str, str]:
    """解析 <board>-<product>-<variant> 目标字符串。

    板名可含连字符（如 radxa-zero3w），使用最长匹配策略：
    按板名长度降序尝试匹配，取最长匹配的板名。

    返回 {"board": ..., "product": ..., "variant": ...} 字典。
    若无法匹配则抛出 ValueError。
    """
    if boards is None:
        boards = discover_boards(project_root)

    merged = _merged_configs(boards, project_root)

    # 按板名长度降序排列，优先匹配最长的板名
    sorted_names = sorted(merged.keys(), key=len, reverse=True)

    for board_name in sorted_names:
        prefix = board_name + "-"
        if target.startswith(prefix):
            remainder = target[len(prefix):]
            # remainder 应为 <product>-<variant>
            parts = remainder.rsplit("-", 1)
            if len(parts) == 2:
                product, variant = parts
                cfg = merged[board_name]
                valid_products = cfg.get("products", ["default"])
                valid_variants = cfg.get("variants", ["release"])
                if product in valid_products and variant in valid_variants:
                    return {
                        "board": board_name,
                        "product": product,
                        "variant": variant,
                    }

    raise ValueError(f"无法解析目标：{target}")
