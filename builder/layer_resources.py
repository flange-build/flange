"""共享有序内容解析；构建执行、指纹及来源诊断使用同一规则。"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from builder.layers import LayerStack, ResourceRef
from builder.patches import normalize_excluded_patches


def patch_resources(stack: LayerStack, config: dict, component: str, *, excluded=True):
    omitted = (
        set(
            normalize_excluded_patches(
                (config.get(component) or {}).get("exclude_patches"),
                f"{component}.exclude_patches",
            )
        )
        if excluded
        else set()
    )
    result = []
    for scope, name in (("platform", config["platform"]), ("board", config["board"])):
        directory = f"components/{scope}/{name}/patches/{component}"
        for ref in stack.files(directory, "*.patch"):
            if not omitted.intersection(
                (ref.path.name, ref.relative_path, ref.identity)
            ):
                result.append(ref)
    return tuple(result)


def overlay_resources(stack: LayerStack, config: dict, component: str):
    subdir = "overlay" if component == "rootfs" else "recovery-overlay"
    distro = config.get("distro", "ubuntu")
    baseline = (
        f"components/{component}/overlay"
        if distro == "ubuntu"
        else f"components/distro/{distro}/{subdir}"
    )
    directories = (
        baseline,
        f"components/platform/{config['platform']}/{subdir}",
        f"components/board/{config['board']}/{subdir}",
    )
    return tuple(ref for directory in directories for ref in stack.all(directory))


def content_path(stack: LayerStack, relative: str) -> Path:
    """普通内容文件自动选择上层；缺失时返回基础层路径以保留原错误位置。"""
    ref = stack.selected(f"components/{relative}")
    return ref.path if ref else stack.layers[0].components / relative


def copy_overlay(source: Path, destination: Path) -> None:
    """逐节点覆盖且不跟随目标符号链接；允许文件/目录/链接类型替换。"""
    if destination.is_symlink():
        raise ValueError(f"overlay 根不能是符号链接：{destination}")
    destination.mkdir(parents=True, exist_ok=True)

    def remove(path):
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)

    def copy(src, dst):
        mode = src.lstat().st_mode
        directory = stat.S_ISDIR(mode)
        if dst.exists() or dst.is_symlink():
            if not directory or dst.is_symlink() or not dst.is_dir():
                remove(dst)
        if directory:
            dst.mkdir(exist_ok=True)
            for child in sorted(src.iterdir()):
                copy(child, dst / child.name)
            shutil.copystat(src, dst)
        elif stat.S_ISLNK(mode):
            dst.symlink_to(os.readlink(src))
        elif stat.S_ISREG(mode):
            shutil.copy2(src, dst)
        else:
            raise ValueError(f"overlay 不支持此节点类型：{src}")

    for child in sorted(source.iterdir()):
        copy(child, destination / child.name)


def overlay_entries(stack: LayerStack, config: dict, component: str):
    """最终可见文件树；被上层覆盖的文件不进入构建指纹。"""
    entries = {}
    for root in overlay_resources(stack, config, component):
        for path in sorted(root.path.rglob("*")):
            relative = path.relative_to(root.path).as_posix()
            if path.is_symlink() or not path.is_dir():
                for old in list(entries):
                    if old.startswith(relative + "/"):
                        del entries[old]
            entries[relative] = ResourceRef(
                root.layer, f"{root.relative_path}/{relative}", symlink_node=True
            )
    return entries


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("用法：python -m builder.layer_resources <overlay> <rootfs>")
    copy_overlay(Path(sys.argv[1]), Path(sys.argv[2]))
