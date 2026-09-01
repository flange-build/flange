"""配置查询接口。

提供目标枚举（get_valid_targets）和目标解析（parse_target），
供 CLI 和构建系统使用。
"""

from pathlib import Path

from builder.config.registry import discover_boards


def _merged_configs(
    boards: dict[str, dict],
    project_root: Path | None = None,
) -> dict[str, dict]:
    """返回 board 身份映射；身份投影已包含 products/variants。"""
    return boards


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

    # 兑现"按字母序排列"契约：board 已排序，但单板内 products 按声明序
    # （default 须为 products[0] 供 lunch 缺省选用），二者未必字母序——
    # 故对最终列表整体排序（仅影响展示/校验枚举顺序，不影响默认 product 选择）。
    return sorted(targets)


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


# ---------------------------------------------------------------------------
# 层级目标树
# ---------------------------------------------------------------------------

#: 树的层级顺序。末级即一个完整的 <board>-<product>-<variant> 目标。
TREE_LEVELS = ("platform", "soc", "board", "product", "variant")


class TargetNode:
    """目标树上的一个节点。

    树只由板级身份投影构造（`discover_boards()`），**不触发**完整配置求值 ——
    求值单个目标约 1.3 秒，挂在导航上会让每次按键都卡住。配置表另行按需加载。
    """

    __slots__ = ("name", "level", "children", "target", "parent")

    def __init__(self, name: str, level: str, parent: "TargetNode | None" = None):
        self.name = name
        #: 该节点所处的层级名，取自 TREE_LEVELS；根节点为 ""。
        self.level = level
        self.children: list["TargetNode"] = []
        #: 仅末级节点非空：完整的 <board>-<product>-<variant>。
        self.target: str | None = None
        self.parent = parent

    @property
    def is_leaf(self) -> bool:
        return self.target is not None

    def child(self, name: str) -> "TargetNode | None":
        for node in self.children:
            if node.name == name:
                return node
        return None

    def leaves(self) -> list["TargetNode"]:
        if self.is_leaf:
            return [self]
        found: list["TargetNode"] = []
        for node in self.children:
            found.extend(node.leaves())
        return found

    def path(self) -> list[str]:
        """从根到本节点的名字序列（不含根）。"""
        names: list[str] = []
        node: "TargetNode | None" = self
        while node is not None and node.level:
            names.append(node.name)
            node = node.parent
        return list(reversed(names))

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<TargetNode {self.level}:{self.name} children={len(self.children)}>"


def build_target_tree(
    boards: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> TargetNode:
    """构造 平台 → SoC → 板 → product → variant 的目标树。

    每一层按名字排序，使界面顺序稳定、可预期。
    """
    if boards is None:
        boards = discover_boards(project_root)

    root = TargetNode("", "", None)
    for board_name in sorted(boards):
        identity = boards[board_name]
        platform = identity.get("platform") or "未知平台"
        soc = identity.get("soc") or "未知 SoC"
        products = identity.get("products") or ["default"]
        variants = identity.get("variants") or ["release"]

        node = root
        for level, name in (("platform", platform), ("soc", soc),
                            ("board", board_name)):
            existing = node.child(name)
            if existing is None:
                existing = TargetNode(name, level, node)
                node.children.append(existing)
            node = existing

        for product in products:
            product_node = node.child(product)
            if product_node is None:
                product_node = TargetNode(product, "product", node)
                node.children.append(product_node)
            for variant in variants:
                if product_node.child(variant) is not None:
                    continue
                leaf = TargetNode(variant, "variant", product_node)
                leaf.target = f"{board_name}-{product}-{variant}"
                product_node.children.append(leaf)

    _sort_tree(root)
    return root


def _sort_tree(node: TargetNode) -> None:
    node.children.sort(key=lambda item: item.name)
    for child in node.children:
        _sort_tree(child)
