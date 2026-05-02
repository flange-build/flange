"""Device Tree Overlay（设备树覆盖）构建辅助函数。

flange 支持两类 overlay 来源并存：

- ``boot.dtb_overlays``：来自内核源码树的 in-tree overlay，由 kernel make 编译
- ``boot.vendor_overlays``：来自外部 vendor overlay 仓库（如 radxa-overlays），
  由 device-tree-overlay 组件用 cpp + dtc 单独编译

二者打包到 boot.img 同一目录 ``/dtbs/<vendor>/overlay/`` 下平铺，basename 必须
全局唯一；撞名时构建立即失败。``boot.default_overlays`` 是 extlinux 默认应用
的子集，必须出现在两源的并集中，不需要带前缀。
"""

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
    """返回 in-tree overlay 文件名列表（从内核源码树编译）。"""
    return _overlay_names(config, "dtb_overlays")


def vendor_overlays(config: dict) -> list[str]:
    """返回 vendor overlay 文件名列表（从外部 vendor 仓库编译）。"""
    return _overlay_names(config, "vendor_overlays")


def all_declared_overlays(config: dict) -> list[str]:
    """返回 in-tree 与 vendor 两源的并集（保持声明顺序，先 in-tree 后 vendor）。

    两源 basename 撞名 → raise ValueError，错误信息列出冲突项。
    """
    intree = dtb_overlays(config)
    vendor = vendor_overlays(config)
    intree_set = set(intree)
    collisions = [name for name in vendor if name in intree_set]
    if collisions:
        raise ValueError(
            "boot.dtb_overlays 与 boot.vendor_overlays 中存在重名: "
            f"{', '.join(collisions)}；"
            "boot.img 内 overlay 平铺到同一目录，basename 必须全局唯一，"
            "请重命名 in-tree 的同名 overlay"
        )
    return intree + vendor


def default_overlays(config: dict) -> list[str]:
    """返回默认启动应用的 overlay 文件名列表，并校验其属于两源的并集。"""
    declared = all_declared_overlays(config)
    defaults = _overlay_names(config, "default_overlays")
    missing = [name for name in defaults if name not in declared]
    if missing:
        intree = dtb_overlays(config)
        vendor = vendor_overlays(config)
        raise ValueError(
            "boot.default_overlays 引用了未声明在 boot.dtb_overlays 或 "
            f"boot.vendor_overlays 中的 DT overlay: {', '.join(missing)}；"
            f"候选 dtb_overlays={intree}，候选 vendor_overlays={vendor}"
        )
    return defaults


def overlay_make_targets(config: dict, dts_dir: str) -> list[str]:
    """生成 Linux kernel make 使用的 in-tree overlay 目标列表。

    仅覆盖 ``boot.dtb_overlays``；vendor overlay 由 device-tree-overlay 组件
    单独构建，不走 kernel make。
    """
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
    """复制声明的 overlay 文件到 boot staging 目录。

    若 ``dst_dir`` 中已存在同名 ``.dtbo`` 文件 → raise ValueError；这是 in-tree
    与 vendor 两源平铺到同一目录时的撞名兜底，把冲突点抓在写入瞬间，错误信息
    同时列出 dst 已有路径与本次源路径，便于定位。
    """
    if not names:
        return
    require_overlay_files(src_dir, names)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        dst_path = dst_dir / name
        if dst_path.exists():
            raise ValueError(
                f"DT overlay 撞名: {name}；目标已存在 {dst_path}，"
                f"本次源路径 {src_dir / name}；boot.img 内 overlay 平铺到同一"
                "目录，basename 必须全局唯一"
            )
        shutil.copy2(src_dir / name, dst_path)
