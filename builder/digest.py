"""具名构建输入和产物共用的结构化摘要；不跟随符号链接。"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import stat
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any


def canonical_value(value: Any) -> Any:
    """转换为可确定序列化的值，拒绝隐式 repr 与不可描述的对象。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: canonical_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("构建输入字典的键必须是字符串")
        return {key: canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((canonical_value(item) for item in value), key=canonical_json)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"构建输入不可序列化: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    """流式读取普通文件；文件节点类型由调用方通过 lstat 确认。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_records(
    path: Path,
    *,
    exclude_names: Collection[str] = (),
    exclude_paths: Collection[Path] = (),
) -> list[dict[str, Any]]:
    """记录所有有效节点，目录和链接也是输入，不包含 mtime 或宿主 uid。"""
    root = Path(path).absolute()
    excluded = {Path(item).absolute() for item in exclude_paths}
    names = set(exclude_names)
    records: list[dict[str, Any]] = []

    def visit(current: Path, relative: str) -> None:
        if relative != "." and (
            current.name in names
            or any(current == item or item in current.parents for item in excluded)
        ):
            return
        info = current.lstat()
        record: dict[str, Any] = {"path": relative, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            record.update(kind="symlink", target=os.readlink(current))
        elif stat.S_ISREG(info.st_mode):
            record.update(kind="file", sha256=file_sha256(current), size=info.st_size)
        elif stat.S_ISDIR(info.st_mode):
            record["kind"] = "tree"
        else:
            # rootfs overlay 可能包含设备节点；保留其类型及设备号。
            record.update(kind=stat.S_IFMT(info.st_mode), device=info.st_rdev)
        records.append(record)
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(current.iterdir(), key=lambda entry: entry.name):
                visit(child, child.relative_to(root).as_posix())

    visit(root, ".")
    return records


def hash_path(
    path: Path,
    *,
    exclude_names: Collection[str] = (),
    exclude_paths: Collection[Path] = (),
) -> str:
    """文件或目录的完整身份；排除规则必须由该输入的声明者明确提供。"""
    return digest_value(
        tree_records(path, exclude_names=exclude_names, exclude_paths=exclude_paths)
    )
