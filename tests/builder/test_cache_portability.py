"""缓存哈希的机器无关性。

**为什么需要它**：同一个仓库在宿主机是 `/Volumes/bsp/flange`，在构建容器里
是 `/workspace`，在 CI 上又是别的路径。任何把绝对路径混进哈希的地方，都会让
同一份源码在这三处算出三个不同的值 —— 缓存永远不命中，而现象是"明明什么都
没改却全量重建"，没有任何东西会告诉你原因是路径。

这组测试把同一棵树复制到两个不同目录，断言所有组件哈希逐一相同。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from builder.cache import DEPENDENCY_GRAPH, BuildCache

ROOT = Path(__file__).resolve().parents[2]


def _config(local_kernel: str | None = None) -> dict:
    sources = {
        "linux": {"url": "https://example.com/linux.git", "branch": "main"},
    }
    if local_kernel:
        sources["linux"] = {"local_path": local_kernel}
    return {
        "board": "b", "product": "default", "variant": "release",
        "platform": "rockchip", "soc": "rk3566",
        "architecture": {"userspace": "aarch64", "kernel": "arm64",
                         "bootloader": "arm"},
        "kernel": {"device_tree": {"directory": "rockchip", "name": "x"},
                   "source": {"name": "linux"}},
        "rootfs": {"url": "https://example.com/base.tar.gz", "sha256": "a" * 64},
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": [
            {"name": "rootfs", "type": "ext4", "offset": "0x8000",
             "size": "remaining", "image_size": "2G"},
        ]},
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
        "sources": sources,
    }


def _plant(root: Path, local_kernel: Path | None = None) -> BuildCache:
    """把真实的 builder/ 复制到 root 下，返回锚定在那里的 cache。"""
    shutil.copytree(ROOT / "builder", root / "builder",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "docker").mkdir()
    (root / "docker/Dockerfile").write_text("FROM x\n")
    (root / "docker-compose.yml").write_text("services: {}\n")
    (root / "components").mkdir()

    cache = BuildCache.__new__(BuildCache)
    cache.project_root = root
    cache.config = _config(str(local_kernel) if local_kernel else None)
    cache.target_dir = root / ".build/target/b/default/release"
    return cache


COMPONENTS = sorted(DEPENDENCY_GRAPH)


@pytest.mark.parametrize("component", COMPONENTS)
def test_同一棵树在不同目录算出相同哈希(component: str, tmp_path: Path):
    """核心不变量：哈希只取决于内容，不取决于树在哪儿。"""
    left = _plant(tmp_path / "somewhere/deep/checkout")
    right = _plant(tmp_path / "elsewhere")

    assert left.compute_hash(component) == right.compute_hash(component), (
        f"{component} 的哈希依赖了项目根的绝对路径")


def test_项目根内的本地源码路径归一化(tmp_path: Path):
    """local_path 指向项目内时，两处检出必须算出相同的值。"""
    results = []
    for name in ("first", "second"):
        root = tmp_path / name
        kernel = root / "vendor/linux"
        kernel.mkdir(parents=True)
        (kernel / "Makefile").write_text("all:\n")
        cache = _plant(root, local_kernel=kernel)
        results.append(cache.compute_hash("kernel"))

    assert results[0] == results[1]


def test_项目根外的本地源码不泄漏机器布局(tmp_path: Path):
    """指向项目外时无法做到路径相同，但哈希不该带上机器相关的前缀。

    两台机器各自 hack 自己的 checkout，内容相同就该算出相同的哈希 ——
    身份用末级目录名，内容另行哈希。
    """
    results = []
    for name in ("machine-a/deep/path", "machine-b"):
        outside = tmp_path / name / "linux"
        outside.mkdir(parents=True)
        (outside / "Makefile").write_text("all:\n")
        cache = _plant(tmp_path / f"proj-{name.replace('/', '-')}",
                       local_kernel=outside)
        results.append(cache.compute_hash("kernel"))

    assert results[0] == results[1], "外部源码路径的机器相关前缀泄漏进了哈希"


def test_本地源码模式下框架放弃缓存决策(tmp_path: Path):
    """归一化路径不能顺手把 local_path 的语义也改掉。

    local_path 目录的内容变化不走 git，没有可靠的廉价指纹 —— 框架的选择
    是**不哈希内容、直接强制重建**（见 `local-source` spec）。所以这里的
    正确断言不是"内容变了哈希就变"，而是"根本不看哈希"。
    """
    outside = tmp_path / "outside/linux"
    outside.mkdir(parents=True)
    (outside / "Makefile").write_text("all:\n")

    cache = _plant(tmp_path / "p1", local_kernel=outside)
    target = cache.target_dir / "kernel"
    target.mkdir(parents=True)
    (target / ".build_hash").write_text(cache.compute_hash("kernel"))

    assert not cache.is_up_to_date("kernel"), (
        "local_path 组件必须强制重建，而不是按哈希命中")


def test_不同末级名的外部源码算出不同哈希(tmp_path: Path):
    """身份完全丢掉也不对：两个不同的外部源不该被当成同一个。"""
    hashes = []
    for stem in ("linux", "linux-next"):
        outside = tmp_path / "src" / stem
        outside.mkdir(parents=True)
        (outside / "Makefile").write_text("all:\n")
        hashes.append(
            _plant(tmp_path / f"p-{stem}", local_kernel=outside)
            .compute_hash("kernel"))

    assert hashes[0] != hashes[1]


def test_可移植化对组件与App共用一份():
    """各写一份的后果是其中一侧仍把绝对路径混进哈希，且不会报错。"""
    import inspect

    source = inspect.getsource(BuildCache._portable_app_source)
    assert "_portable_source" in source, (
        "App 侧应委托给共用的 _portable_source，而不是自己再实现一遍")
