"""lunch 层级界面的纯逻辑。

界面本身要终端才跑得起来，但**最容易写错的部分不在绘制上** —— 而在展开/
折叠后光标落在哪、过滤命中了却看不见叶子、配置还没加载完时右栏显示什么。
所以 `TreeView` 与 `SummaryLoader` 都不碰 curses，能在这里直接测。
"""

from __future__ import annotations

import threading
import time

import pytest

from builder.config.query import build_target_tree
from builder.lunch_tui import (
    SummaryLoader,
    leaf_parts,
    TreeView,
    display_width,
    pad,
    truncate,
)

BOARDS = {
    "board-a": {"board": "board-a", "platform": "rockchip", "soc": "rk3588",
                "products": ["default", "desktop"], "variants": ["debug", "release"]},
    "board-b": {"board": "board-b", "platform": "amlogic", "soc": "s905y2",
                "products": ["default"], "variants": ["release"]},
}


@pytest.fixture()
def view() -> TreeView:
    return TreeView(build_target_tree(BOARDS))


# ---------------------------------------------------------------------------
# 显示宽度：中文是双宽
# ---------------------------------------------------------------------------

def test_中文按两列计算():
    """按 len() 算会让右栏表格错位、截断切出半个字符。"""
    assert display_width("abc") == 3
    assert display_width("内核") == 4
    assert display_width("rk3588 内核") == 11


def test_截断不留半个字符():
    assert truncate("abcdef", 10) == "abcdef"
    assert display_width(truncate("内核配置表", 6)) <= 6
    assert truncate("abcdef", 0) == ""


def test_补齐按显示宽度():
    assert display_width(pad("内核", 10)) == 10
    assert display_width(pad("kernel", 10)) == 10


# ---------------------------------------------------------------------------
# 初始状态
# ---------------------------------------------------------------------------

def test_初始只显示顶层平台(view: TreeView):
    assert [node.name for node, _d in view.rows] == ["amlogic", "rockchip"]


def test_初始光标在第一行(view: TreeView):
    assert view.cursor == 0
    assert view.current.name == "amlogic"


# ---------------------------------------------------------------------------
# 展开与折叠
# ---------------------------------------------------------------------------

def test_展开显示下一层(view: TreeView):
    view.move(1)              # rockchip
    view.expand()

    assert [node.name for node, _d in view.rows] == ["amlogic", "rockchip", "rk3588"]


def test_对已展开的节点再按展开则进入子树(view: TreeView):
    """否则"展开"键在展开后就没有任何作用，用户得改按方向键。"""
    view.move(1)
    view.expand()
    view.expand()

    assert view.current.name == "rk3588"


def test_折叠收起子树(view: TreeView):
    view.move(1)
    view.expand()
    view.collapse()

    assert [node.name for node, _d in view.rows] == ["amlogic", "rockchip"]


def test_在未展开节点上折叠会跳到父节点(view: TreeView):
    """深处往回走时不必一路按上箭头。"""
    view.move(1)
    view.expand()
    view.move(1)              # rk3588
    view.collapse()           # rk3588 无展开状态 → 回到 rockchip

    assert view.current.name == "rockchip"


def test_叶子节点没有子项(view: TreeView):
    view.reveal_target("board-b-default-release")
    assert view.current.is_leaf
    assert not view.current.children


# ---------------------------------------------------------------------------
# 定位到当前目标
# ---------------------------------------------------------------------------

def test_定位会展开沿途各层并把光标放到目标上(view: TreeView):
    assert view.reveal_target("board-a-desktop-release")

    assert view.current.target == "board-a-desktop-release"
    names = [node.name for node, _d in view.rows]
    for expected in ("rockchip", "rk3588", "board-a", "desktop", "release"):
        assert expected in names


def test_定位到不存在的目标返回False(view: TreeView):
    assert not view.reveal_target("nope-default-release")


# ---------------------------------------------------------------------------
# 过滤
# ---------------------------------------------------------------------------

def test_过滤保留命中分支的整条路径(view: TreeView):
    view.set_filter("board-b")
    names = [node.name for node, _d in view.rows]

    assert "amlogic" in names and "s905y2" in names and "board-b" in names
    assert "rockchip" not in names


def test_过滤时自动展开否则看不到命中的叶子(view: TreeView):
    view.set_filter("board-b-default-release")

    assert any(node.is_leaf for node, _d in view.rows)


def test_过滤按目标全名匹配(view: TreeView):
    view.set_filter("desktop-debug")
    leaves = [node.target for node, _d in view.rows if node.is_leaf]

    assert leaves == ["board-a-desktop-debug"]


def test_过滤大小写不敏感(view: TreeView):
    view.set_filter("BOARD-B")
    assert any(node.name == "board-b" for node, _d in view.rows)


def test_清空过滤恢复原有展开状态(view: TreeView):
    view.set_filter("board-b")
    view.set_filter("")

    assert [node.name for node, _d in view.rows] == ["amlogic", "rockchip"]


def test_过滤无命中时光标安全(view: TreeView):
    """空列表上取当前节点不能抛异常 —— 用户一定会打出不匹配的串。"""
    view.set_filter("zzz-no-such-thing")

    assert view.rows == []
    assert view.current is None
    view.move(1)
    view.expand()
    view.collapse()


# ---------------------------------------------------------------------------
# 光标边界
# ---------------------------------------------------------------------------

def test_光标不越界(view: TreeView):
    view.move(-5)
    assert view.cursor == 0
    view.move(999)
    assert view.cursor == len(view.rows) - 1


def test_折叠后光标夹回可见范围(view: TreeView):
    view.reveal_target("board-a-desktop-release")
    last = view.cursor
    view.set_filter("")
    view.expanded.clear()
    view.refresh()

    assert view.cursor < len(view.rows)
    assert last > view.cursor


# ---------------------------------------------------------------------------
# 配置表异步加载
# ---------------------------------------------------------------------------

def test_首次取值返回None并在后台加载():
    """同步加载会让每次移动光标卡 1.3 秒。"""
    started = threading.Event()

    def slow_resolve(board, product, variant):
        started.set()
        time.sleep(0.05)
        return {"board": board}

    loader = SummaryLoader(resolve=slow_resolve,
                           summarize=lambda cfg: [("身份", [("board", cfg["board"])])])

    assert loader.get("board-a-default-debug", ("board-a", "default", "debug")) is None
    assert started.wait(2), "没有触发后台加载"

    for _ in range(100):
        value = loader.get("board-a-default-debug", ("board-a", "default", "debug"))
        if value is not None:
            break
        time.sleep(0.02)
    assert value == [("身份", [("board", "board-a")])]


def test_同一目标只求值一次():
    calls = []

    def counting(board, product, variant):
        calls.append(board)
        return {"board": board}

    loader = SummaryLoader(resolve=counting, summarize=lambda cfg: [])
    for _ in range(20):
        loader.get("board-a-default-debug", ("board-a", "default", "debug"))
        time.sleep(0.01)

    assert len(calls) == 1


def test_求值失败不让界面崩掉():
    """某块板配置写坏时，界面该显示错误而不是整个退出。"""
    def broken(board, product, variant):
        raise ValueError("坏了")

    loader = SummaryLoader(resolve=broken, summarize=lambda cfg: [])
    loader.get("board-a-default-debug", ("board-a", "default", "debug"))

    for _ in range(100):
        value = loader.get("board-a-default-debug", ("board-a", "default", "debug"))
        if value is not None:
            break
        time.sleep(0.02)
    assert isinstance(value, str) and "坏了" in value


def test_叶子的三段直接取自树而不是解析目标名(view: TreeView):
    """board 名本身含连字符，把拼好的目标名再解析回去要靠试探。"""
    view.reveal_target("board-a-desktop-release")

    assert leaf_parts(view.current) == ("board-a", "desktop", "release")
