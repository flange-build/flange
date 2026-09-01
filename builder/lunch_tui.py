"""`lunch` 的层级选择界面。

**为什么要有它**：`lunch` 无参数时原先把 90 个目标打成一张编号平表让用户输
数字。一屏放不下，而且它把配置本来就有的层级结构抹平了 —— 用户其实是先想清
楚"哪个平台、哪颗 SoC、哪块板"，再决定 product 与 variant。

**两条设计约束**决定了实现形态：

1. **导航不能碰配置求值**。单个目标求值约 1.3 秒，挂在方向键上每按一次都卡
   住。所以左侧树只由板级身份投影构造（`build_target_tree`），配置表在停到
   末级目标时由后台线程加载并缓存，加载中显示占位。
2. **不引入 TUI 依赖**。用标准库 curses。这个界面的复杂度（一棵树 + 一张只读
   表）配不上再往构建环境里加一个第三方包。

界面本身不导出环境变量 —— 子进程改不了父 shell。选中的目标写到 ``--out``
指定的文件，由 `envsetup.sh` 读回后走既有的导出与持久化路径。取消则不写，
当前目标保持不变。
"""

from __future__ import annotations

import argparse
import curses
import sys
import threading
from pathlib import Path

from builder.config.query import TargetNode, build_target_tree
from builder.term import display_width, pad, truncate

# 各层级在树上的标记，让用户一眼看出自己在哪一层。
LEVEL_MARK = {
    "platform": "▣",
    "soc": "▸",
    "board": "▪",
    "product": "·",
    "variant": " ",
}

_HELP = "↑↓ 移动   ←→ 折叠/展开   PgUp/PgDn 翻配置表   Enter 选中   / 过滤   q 取消"


# ---------------------------------------------------------------------------
# 树的可见行：展开状态 + 过滤共同决定
# ---------------------------------------------------------------------------

class TreeView:
    """把树摊平成"当前可见的行"，并维护展开状态、光标与过滤。

    这一层是纯逻辑，不碰 curses —— 树的行为（展开、折叠、过滤后光标落在哪）
    正是最容易写错的部分，把它和绘制分开才测得动。
    """

    def __init__(self, root: TargetNode):
        self.root = root
        self.expanded: set[int] = set()
        self.cursor = 0
        self.filter = ""
        self._rows: list[tuple[TargetNode, int]] = []
        self.refresh()

    # -- 过滤 ---------------------------------------------------------------

    def _matches(self, node: TargetNode) -> bool:
        """节点自身或任一后代命中过滤串。"""
        if not self.filter:
            return True
        needle = self.filter.lower()
        if node.target and needle in node.target.lower():
            return True
        if needle in node.name.lower():
            return True
        return any(self._matches(child) for child in node.children)

    # -- 可见行 -------------------------------------------------------------

    def refresh(self) -> None:
        """按展开状态与过滤重算可见行，并把光标夹回合法范围。"""
        rows: list[tuple[TargetNode, int]] = []

        def walk(node: TargetNode, depth: int) -> None:
            for child in node.children:
                if not self._matches(child):
                    continue
                rows.append((child, depth))
                # 过滤生效时自动展开，否则用户看不到命中的叶子
                if child.children and (self.filter or id(child) in self.expanded):
                    walk(child, depth + 1)

        walk(self.root, 0)
        self._rows = rows
        self.cursor = max(0, min(self.cursor, len(rows) - 1)) if rows else 0

    @property
    def rows(self) -> list[tuple[TargetNode, int]]:
        return self._rows

    @property
    def current(self) -> TargetNode | None:
        if not self._rows:
            return None
        return self._rows[self.cursor][0]

    # -- 操作 ---------------------------------------------------------------

    def move(self, delta: int) -> None:
        if not self._rows:
            return
        self.cursor = max(0, min(self.cursor + delta, len(self._rows) - 1))

    def expand(self) -> None:
        """展开当前节点；已展开或无子节点时下移一行（进入子树）。"""
        node = self.current
        if node is None:
            return
        if node.children and id(node) not in self.expanded:
            self.expanded.add(id(node))
            self.refresh()
        elif node.children:
            self.move(1)

    def collapse(self) -> None:
        """折叠当前节点；本就未展开时跳到父节点。"""
        node = self.current
        if node is None:
            return
        if node.children and id(node) in self.expanded:
            self.expanded.discard(id(node))
            self.refresh()
            return
        parent = node.parent
        if parent is not None and parent.level:
            self.expanded.discard(id(parent))
            self.refresh()
            self.focus(parent)

    def focus(self, node: TargetNode) -> bool:
        """把光标移到指定节点；不可见时返回 False。"""
        for index, (candidate, _depth) in enumerate(self._rows):
            if candidate is node:
                self.cursor = index
                return True
        return False

    def reveal_target(self, target: str) -> bool:
        """展开到指定目标并把光标置于其上。"""
        for leaf in self.root.leaves():
            if leaf.target != target:
                continue
            node = leaf.parent
            while node is not None and node.level:
                self.expanded.add(id(node))
                node = node.parent
            self.refresh()
            return self.focus(leaf)
        return False

    def set_filter(self, text: str) -> None:
        self.filter = text
        self.cursor = 0
        self.refresh()


# ---------------------------------------------------------------------------
# 配置表的后台加载
# ---------------------------------------------------------------------------

class SummaryLoader:
    """按目标名后台求值配置并缓存。

    求值约 1.3 秒。放在主循环里会让导航卡死，所以交给后台线程；主循环带超时
    轮询按键，加载完成后自然重绘。同一目标只算一次。
    """

    def __init__(self, resolve=None, summarize=None):
        # 延迟导入：求值链较重，界面启动时不该为它付时间
        if resolve is None or summarize is None:
            from builder.config.loader import resolve_config
            from builder.config.summary import summarize_config

            resolve = resolve or resolve_config
            summarize = summarize or summarize_config
        self._resolve = resolve
        self._summarize = summarize
        self._cache: dict[str, list | str] = {}
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def get(self, target: str, parts: tuple[str, str, str]):
        """返回已缓存的摘要；未就绪时触发加载并返回 None。

        `parts` 是 (board, product, variant)，由叶子节点直接给出 —— 不再把
        自己拼出来的目标名解析回去。多一次解析既无意义，也会把界面绑死在
        "目标必须能被全局校验通过"上。
        """
        with self._lock:
            if target in self._cache:
                return self._cache[target]
            if target in self._pending:
                return None
            self._pending.add(target)
        threading.Thread(target=self._load, args=(target, parts),
                         daemon=True).start()
        return None

    def _load(self, target: str, parts: tuple[str, str, str]) -> None:
        try:
            value = self._summarize(self._resolve(*parts))
        except Exception as error:  # 配置有问题不该让界面崩掉
            value = f"配置求值失败: {type(error).__name__}: {error}"
        with self._lock:
            self._cache[target] = value
            self._pending.discard(target)


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------

def _row_label(node: TargetNode, depth: int, expanded: bool) -> str:
    mark = LEVEL_MARK.get(node.level, " ")
    if node.children:
        arrow = "▾" if expanded else "▸"
    else:
        arrow = " "
    return f"{'  ' * depth}{arrow} {mark} {node.name}"


def leaf_parts(node: TargetNode) -> tuple[str, str, str]:
    """从末级节点直接取出 (board, product, variant)。

    树是按这三层构造的，沿父链取回来比把 `<board>-<product>-<variant>`
    再解析一次可靠 —— board 名本身含连字符，解析要靠试探。
    """
    variant = node.name
    product = node.parent.name if node.parent else ""
    board = node.parent.parent.name if node.parent and node.parent.parent else ""
    return board, product, variant


def _summary_lines(node: TargetNode | None, loader: SummaryLoader) -> list[tuple[str, int]]:
    """右栏内容：(文本, curses 属性)。"""
    if node is None:
        return [("没有匹配的目标", curses.A_DIM)]

    if not node.is_leaf:
        leaves = node.leaves()
        lines = [(f"{node.level or '根'}: {node.name}", curses.A_BOLD), ("", 0)]
        lines.append((f"子项      {len(node.children)} 个", 0))
        lines.append((f"可选目标   {len(leaves)} 个", 0))
        lines.append(("", 0))
        lines.append(("展开继续下钻到具体 variant，", curses.A_DIM))
        lines.append(("停在 variant 上会显示它的完整配置。", curses.A_DIM))
        return lines

    summary = loader.get(node.target, leaf_parts(node))
    header = [(node.target or "", curses.A_BOLD), ("", 0)]
    if summary is None:
        return header + [("配置求值中…", curses.A_DIM)]
    if isinstance(summary, str):
        return header + [(summary, curses.A_BOLD)]

    lines: list[tuple[str, int]] = header
    for title, rows in summary:
        lines.append((f"── {title}", curses.A_BOLD))
        for key, value in rows:
            lines.append((f"  {pad(key, 14)}{value}", 0))
        lines.append(("", 0))
    return lines


class _App:
    """curses 主循环。"""

    def __init__(self, root: TargetNode, current: str | None, loader: SummaryLoader):
        self.view = TreeView(root)
        self.loader = loader
        self.selected: str | None = None
        self.filtering = False
        self.summary_scroll = 0
        if current:
            self.view.reveal_target(current)

    def run(self, stdscr) -> str | None:
        curses.curs_set(0)
        stdscr.timeout(150)  # 让后台加载完成后能自动重绘
        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if key == -1:
                continue  # 超时：仅用于刷新
            if self._handle(key):
                return self.selected

    # -- 输入 ---------------------------------------------------------------

    def _handle(self, key: int) -> bool:
        """返回 True 表示结束。"""
        if self.filtering:
            return self._handle_filter(key)

        if key in (ord("q"), 27):  # q / Esc
            self.selected = None
            return True
        if key in (curses.KEY_UP, ord("k")):
            self.view.move(-1)
            self.summary_scroll = 0
        elif key in (curses.KEY_DOWN, ord("j")):
            self.view.move(1)
            self.summary_scroll = 0
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.view.expand()
        elif key in (curses.KEY_LEFT, ord("h")):
            self.view.collapse()
        elif key == curses.KEY_NPAGE:
            # 翻的是右栏配置表：完整配置约 40 行，比任何常见终端高度都长，
            # 而左树有方向键、右表原本一个键都没有，够不着的行只能干看着。
            self.summary_scroll += 10
        elif key == curses.KEY_PPAGE:
            self.summary_scroll = max(0, self.summary_scroll - 10)
        elif key == ord("/"):
            self.filtering = True
        elif key in (curses.KEY_ENTER, 10, 13):
            node = self.view.current
            if node is None:
                return False
            if node.is_leaf:
                self.selected = node.target
                return True
            self.view.expand()
        return False

    def _handle_filter(self, key: int) -> bool:
        if key in (curses.KEY_ENTER, 10, 13):
            self.filtering = False
        elif key == 27:  # Esc 清空过滤
            self.filtering = False
            self.view.set_filter("")
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.view.set_filter(self.view.filter[:-1])
        elif 32 <= key < 127:
            self.view.set_filter(self.view.filter + chr(key))
        return False

    # -- 绘制 ---------------------------------------------------------------

    def _draw(self, stdscr) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 6 or width < 40:
            self._safe(stdscr, 0, 0, "终端太小，请放大窗口", width, 0)
            stdscr.refresh()
            return

        left = max(28, min(46, width // 3))
        body = height - 2

        self._draw_tree(stdscr, body, left)
        self._draw_summary(stdscr, body, left, width - left - 1)

        for row in range(body):
            self._safe(stdscr, row, left - 1, "│", 1, curses.A_DIM)

        status = (f"过滤: {self.view.filter}_" if self.filtering
                  else (f"过滤: {self.view.filter}" if self.view.filter else _HELP))
        self._safe(stdscr, height - 2, 0, "─" * width, width, curses.A_DIM)
        self._safe(stdscr, height - 1, 0, status, width - 1,
                   curses.A_BOLD if self.filtering else 0)
        stdscr.refresh()

    def _draw_tree(self, stdscr, body: int, left: int) -> None:
        rows = self.view.rows
        top = max(0, min(self.view.cursor - body // 2, max(0, len(rows) - body)))
        for offset in range(body):
            index = top + offset
            if index >= len(rows):
                break
            node, depth = rows[index]
            label = _row_label(node, depth, id(node) in self.view.expanded
                               or bool(self.view.filter))
            attr = curses.A_REVERSE if index == self.view.cursor else 0
            if node.is_leaf and index != self.view.cursor:
                attr |= curses.A_DIM
            self._safe(stdscr, offset, 0, pad(truncate(label, left - 2), left - 2),
                       left - 2, attr)

    def _draw_summary(self, stdscr, body: int, left: int, width: int) -> None:
        lines = _summary_lines(self.view.current, self.loader)
        self.summary_scroll = max(0, min(self.summary_scroll,
                                         max(0, len(lines) - body)))
        for offset in range(body):
            index = self.summary_scroll + offset
            if index >= len(lines):
                break
            text, attr = lines[index]
            self._safe(stdscr, offset, left, truncate(text, width), width, attr)

    @staticmethod
    def _safe(stdscr, row: int, col: int, text: str, width: int, attr: int) -> None:
        """越界写入会抛 curses.error；界面缩小时不该因此崩掉。"""
        try:
            stdscr.addnstr(row, col, text, max(0, width), attr)
        except curses.error:
            pass


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def select_target(current: str | None = None) -> str | None:
    """打开界面并返回选中的目标；取消时返回 None。"""
    root = build_target_tree()
    if not root.children:
        raise RuntimeError("未发现任何目标配置")
    app = _App(root, current, SummaryLoader())
    return curses.wrapper(app.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m builder.lunch_tui",
        description="lunch 的层级目标选择界面")
    parser.add_argument("--current", default="", help="当前已选目标，用于定位光标")
    parser.add_argument("--out", required=True,
                        help="选中结果写入的文件；取消时不写")
    args = parser.parse_args(argv)

    if not sys.stdout.isatty():
        print("需要终端环境", file=sys.stderr)
        return 2

    target = select_target(args.current or None)
    if target is None:
        return 1
    Path(args.out).write_text(target + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
