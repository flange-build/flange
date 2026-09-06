"""工作区配置服务的轻量入口；目标状态只有 workspace 模块一个事实源。"""

from pathlib import Path

from builder.workspace import WorkspaceContext, Target, load_workspace, resolve_config, save_target


def load_current_config(context: WorkspaceContext | None = None) -> dict:
    """使用显式上下文，或从调用目录发现工作区，再重新求值当前配置。"""
    return resolve_config(context or load_workspace())


def save_state(
    board: str,
    product: str,
    variant: str,
    *,
    context: WorkspaceContext | None = None,
    workspace_root: Path | None = None,
) -> None:
    """目标写入要求明确工作区，复用原子状态服务，不存在全局状态文件。"""
    if context is None and workspace_root is None:
        raise ValueError("save_state 必须提供 context 或 workspace_root，不能猜测状态位置")
    if context is not None and workspace_root is not None:
        if context.workspace_root != Path(workspace_root).resolve():
            raise ValueError("context 与 workspace_root 指向不同工作区")
    root = context.workspace_root if context is not None else Path(workspace_root).resolve()
    save_target(root, Target(board, product, variant))
