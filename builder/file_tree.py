"""App 与 Package 文件树复制：保留链接对象，不依赖链接目标所在环境。"""

from __future__ import annotations

from collections.abc import Callable, Collection
import os
from pathlib import Path
import shutil


def copy_entry(source: Path, destination: Path) -> None:
    """复制普通文件或链接；替换目标节点时不跟随旧链接。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir() and not destination.is_symlink():
        raise IsADirectoryError(f"不能用文件或链接替换目录：{destination}")
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    if source.is_symlink():
        # 共享卷可能在 setxattr(..., follow_symlinks=False) 时仍要求链接
        # 目标存在。链接只保留目标文本，不复制其宿主扩展属性或时间戳。
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


def copy_tree(
    source: Path,
    destination: Path,
    *,
    ignore: Callable[[str, list[str]], Collection[str]] | None = None,
) -> None:
    """合并文件树，保留空目录及普通节点元数据，原样传播复制错误。"""
    if source.is_symlink() or not source.is_dir():
        raise NotADirectoryError(f"复制源必须是普通目录：{source}")
    if destination.is_symlink():
        raise FileExistsError(f"不能通过目标符号链接写入目录：{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    entries = list(source.iterdir())
    excluded = set(ignore(str(source), [entry.name for entry in entries])) if ignore else set()
    for entry in entries:
        if entry.name in excluded:
            continue
        target = destination / entry.name
        if entry.is_symlink() or not entry.is_dir():
            copy_entry(entry, target)
        else:
            copy_tree(entry, target, ignore=ignore)
    # 子项写入后再设置目录权限，确保只读目录也可以完整复制。
    shutil.copystat(source, destination)
