"""Device Tree Overlay（设备树覆盖）构建辅助函数。"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path


def _overlay_names(config: dict, key: str) -> list[str]:
    """读取 boot.<key> overlay 列表，未声明时返回空列表。"""
    value = (config.get("boot") or {}).get(key, []) or []
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"boot.{key} 必须是字符串列表")

    names = list(value)
    for name in names:
        if not isinstance(name, str) or not name:
            raise TypeError(f"boot.{key} 只能包含非空字符串")
        if "/" in name or name.startswith("."):
            raise ValueError(f"boot.{key} 只能声明 boot overlay 文件名: {name}")
        if not name.endswith(".dtbo"):
            raise ValueError(f"boot.{key} 只能声明 .dtbo 文件: {name}")
    return names


def dtb_overlays(config: dict) -> list[str]:
    """返回需要构建并打包进 boot 分区的 overlay 文件名列表。"""
    return _overlay_names(config, "dtb_overlays")


def default_overlays(config: dict) -> list[str]:
    """返回默认启动应用的 overlay 文件名列表，并校验其属于打包全集。"""
    declared = dtb_overlays(config)
    defaults = _overlay_names(config, "default_overlays")
    missing = [name for name in defaults if name not in declared]
    if missing:
        raise ValueError(
            "boot.default_overlays 引用了未声明在 boot.dtb_overlays 中的 "
            f"DT overlay: {', '.join(missing)}"
        )
    return defaults


def overlay_make_targets(config: dict, dts_dir: str) -> list[str]:
    """生成 Linux kernel make 使用的 overlay 目标列表。"""
    return [f"{dts_dir}/overlay/{name}" for name in dtb_overlays(config)]


def kernel_overlay_dir(src_dir: Path, arch: str, dts_dir: str) -> Path:
    """返回内核源码树中 overlay 产物目录。"""
    return src_dir / f"arch/{arch}/boot/dts/{dts_dir}/overlay"


def require_overlay_files(overlay_dir: Path, names: list[str]) -> None:
    """确认 overlay_dir 中包含 names 指定的全部 .dtbo 文件。"""
    if not names:
        return
    missing = [name for name in names if not (overlay_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"DT overlay 产物未找到: {', '.join(missing)}；目录: {overlay_dir}"
        )


def copy_declared_overlays(src_dir: Path, dst_dir: Path, names: list[str]) -> None:
    """复制声明的 overlay 文件到 boot staging 目录。"""
    if not names:
        return
    require_overlay_files(src_dir, names)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(src_dir / name, dst_dir / name)
