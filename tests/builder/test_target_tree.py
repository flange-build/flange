"""目标树与配置摘要。

`lunch` 的层级界面靠这两个纯数据函数驱动：树决定能看到什么，摘要决定选中
末级目标时显示什么。两者都不碰终端，所以能独立测。

树有一条硬约束：**构造过程不得触发配置求值**。求值单个目标约 1.3 秒，挂在
导航上会让每次按键都卡住 —— 这正是把层级与配置表分成两条路径的原因。
"""

from __future__ import annotations

import pytest

from builder.config.query import (
    TREE_LEVELS,
    build_target_tree,
    get_valid_targets,
)
from builder.config.summary import summarize_config

BOARDS = {
    "board-a": {"board": "board-a", "platform": "rockchip", "soc": "rk3588",
                "products": ["default", "desktop"], "variants": ["debug", "release"]},
    "board-b": {"board": "board-b", "platform": "rockchip", "soc": "rk3566",
                "products": ["default"], "variants": ["release"]},
    "board-c": {"board": "board-c", "platform": "amlogic", "soc": "s905y2",
                "products": ["default"], "variants": ["debug", "release"]},
}


# ---------------------------------------------------------------------------
# 树的形状
# ---------------------------------------------------------------------------

def test_层级顺序():
    assert TREE_LEVELS == ("platform", "soc", "board", "product", "variant")


def test_按平台_soc_板_product_variant分层():
    root = build_target_tree(BOARDS)

    assert [n.name for n in root.children] == ["amlogic", "rockchip"]
    rockchip = root.child("rockchip")
    assert [n.name for n in rockchip.children] == ["rk3566", "rk3588"]
    board = rockchip.child("rk3588").child("board-a")
    assert [n.name for n in board.children] == ["default", "desktop"]
    assert [n.name for n in board.child("desktop").children] == ["debug", "release"]


def test_末级节点携带完整目标名():
    root = build_target_tree(BOARDS)
    leaf = root.child("rockchip").child("rk3588").child("board-a") \
               .child("desktop").child("debug")

    assert leaf.is_leaf
    assert leaf.target == "board-a-desktop-debug"
    assert leaf.level == "variant"


def test_非末级节点不是叶子():
    root = build_target_tree(BOARDS)
    for name in ("rockchip",):
        assert not root.child(name).is_leaf


def test_叶子集合与get_valid_targets一致():
    """两者都是"有哪些目标"的答案，不一致说明界面会漏或多出目标。"""
    root = build_target_tree(BOARDS)
    leaves = sorted(node.target for node in root.leaves())

    assert leaves == sorted(get_valid_targets(BOARDS))


def test_真实仓库的叶子与目标枚举一致():
    root = build_target_tree()
    assert sorted(n.target for n in root.leaves()) == sorted(get_valid_targets())


def test_path给出从根到该节点的层级路径():
    root = build_target_tree(BOARDS)
    leaf = root.child("amlogic").child("s905y2").child("board-c") \
               .child("default").child("debug")

    assert leaf.path() == ["amlogic", "s905y2", "board-c", "default", "debug"]


def test_每层按名字排序():
    """顺序必须稳定可预期，否则用户每次打开看到的位置都不一样。"""
    shuffled = {k: BOARDS[k] for k in ("board-c", "board-a", "board-b")}
    root = build_target_tree(shuffled)

    assert [n.name for n in root.children] == sorted(n.name for n in root.children)
    for platform in root.children:
        assert [n.name for n in platform.children] == \
               sorted(n.name for n in platform.children)


def test_缺失身份字段不会让树构造失败():
    """板级配置写漏 platform/soc 时，界面应能显示而不是崩掉。"""
    root = build_target_tree({"x": {"board": "x"}})
    leaf = root.leaves()[0]

    assert leaf.target == "x-default-release"
    assert leaf.path()[:2] == ["未知平台", "未知 SoC"]


def test_构造树不触发配置求值(monkeypatch):
    """这是整个设计的前提：求值 1.3s，挂在导航上每按一次键都卡住。"""
    import builder.config.loader as loader

    def explode(*args, **kwargs):
        raise AssertionError("build_target_tree 触发了配置求值")

    monkeypatch.setattr(loader, "resolve_config", explode)
    assert build_target_tree(BOARDS).leaves()


# ---------------------------------------------------------------------------
# 配置摘要
# ---------------------------------------------------------------------------

def test_摘要分节且每节都有行():
    config = {
        "board": "b", "platform": "rockchip", "soc": "rk3588", "vendor": "rockchip",
        "product": "desktop", "variant": "debug",
        "architecture": {"userspace": "aarch64", "kernel": "arm64",
                         "bootloader": "arm"},
        "kernel": {"source": {"name": "k"}, "device_tree": {
            "directory": "rockchip", "name": "rk3588-x"}},
        "sources": {"k": {"url": "https://example/k.git", "branch": "main"}},
        "partitions": {"format": "gpt", "entries": [
            {"name": "rootfs", "type": "ext4", "offset": "0x1000",
             "size": "remaining", "image_size": "4G"}]},
        "rootfs": {"url": "https://e/base.tar.gz", "packages": ["a", "b"]},
        "recovery": {"enabled": True}, "amp": {"enabled": False},
    }
    sections = summarize_config(config)
    titles = [title for title, _rows in sections]

    assert titles == ["身份", "架构", "内核", "Bootloader",
                      "存储与分区", "Rootfs", "功能开关"]
    for _title, rows in sections:
        assert rows, "空节等于占着行不给信息"


def test_摘要渲染source为可读的仓库与ref():
    config = {"kernel": {"source": {"name": "k"}},
              "sources": {"k": {"url": "https://example/k.git",
                                "commit": "0123456789abcdef"}}}
    rows = dict(summarize_config(config)[2][1])

    assert rows["source"] == "k → https://example/k.git @0123456789ab"


def test_摘要渲染本地源为路径():
    config = {"kernel": {"source": {"name": "k"}},
              "sources": {"k": {"local_path": "/work/linux"}}}
    rows = dict(summarize_config(config)[2][1])

    assert "本地 /work/linux" in rows["source"]


def test_摘要列出分区几何():
    config = {"partitions": {"entries": [
        {"name": "boot", "type": "ext4", "offset": "0x8000", "size": "0x20000"}]}}
    rows = dict(summarize_config(config)[4][1])

    assert "off=0x8000" in rows["  boot"]


def test_分区优先显示image_size():
    """image_size 才是实际做出来的镜像大小，size 是分区上限。"""
    config = {"partitions": {"entries": [
        {"name": "rootfs", "type": "ext4", "size": "remaining",
         "image_size": "4G"}]}}
    rows = dict(summarize_config(config)[4][1])

    assert "size=4G" in rows["  rootfs"]


@pytest.mark.parametrize("config", [{}, {"kernel": {}}, {"rootfs": None}])
def test_字段缺失时用占位符而不是报错(config: dict):
    """摘要用于浏览，不该因为某块板没声明某个可选字段就打断。"""
    sections = summarize_config(config)
    assert any("—" in value for _t, rows in sections for _k, value in rows)


def test_布尔渲染成中文():
    rows = dict(summarize_config({"recovery": {"enabled": True},
                                  "amp": {"enabled": False}})[6][1])
    assert rows["recovery"] == "是" and rows["amp"] == "否"


def test_真实目标的摘要可渲染():
    from builder.config.loader import resolve_config

    sections = summarize_config(
        resolve_config("radxa-rock5b", "desktop", "debug"))
    identity = dict(sections[0][1])

    assert identity["board"] == "radxa-rock5b"
    assert identity["soc"] == "rk3588"
