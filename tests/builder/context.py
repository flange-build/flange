"""组件单测的显式上下文替身；工作区发现和路径不变量另用真实模型验证。"""

from pathlib import Path
from types import SimpleNamespace

from builder.workspace import Target


def component_context(root: Path, config: dict | None = None, *, target_dir: Path | None = None):
    config = config or {}
    root = Path(root).resolve()
    target = Target(
        config.get("board", "test"),
        config.get("product", "default"),
        config.get("variant", "release"),
    )
    build_root = root / ".build"
    return SimpleNamespace(
        tool_root=root,
        workspace_root=root,
        build_root=build_root,
        invocation_dir=root,
        components_root=root / "components",
        target=target,
        target_dir=target_dir
        or build_root / "target" / target.board / target.product / target.variant,
        sources_dir=build_root / "sources",
        apps={},
        app_dirs=(),
    )
