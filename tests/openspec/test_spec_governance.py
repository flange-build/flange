"""OpenSpec 治理闸门。

**为什么需要它**：spec 与实现的漂移不会自己暴露 —— 没有人会在改代码时顺手
去读一份没提到的 spec。这次清理发现的两类问题都是长期无人察觉：

  1. **12 份 live spec 规定 `flange build` 执行 `bazel build`**，而仓库里
     一个 Bazel 文件都没有。任何按 spec 实现的人（或 agent）都会做错事。
  2. **6 个变更任务全部勾选但从未归档**，其中一个的 spec delta 已经挂在被
     后续变更重写过的标题上，归档时直接失败 —— 变更越拖越难收口。

两条闸门都只检查"能机械判定"的部分，判断留给人。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "openspec" / "specs"
CHANGES = ROOT / "openspec" / "changes"


def _live_specs() -> list[Path]:
    return sorted(SPECS.glob("*/spec.md"))


def _active_changes() -> list[Path]:
    return sorted(
        d for d in CHANGES.iterdir()
        if d.is_dir() and d.name != "archive"
    )


def test_发现到了spec与变更():
    """守住发现逻辑：扫空时下面的检查会全部静默通过。"""
    assert len(_live_specs()) > 20
    assert _active_changes()


# ---------------------------------------------------------------------------
# 闸门一：任务全部完成的变更必须归档
# ---------------------------------------------------------------------------

def test_任务全部完成的变更必须归档():
    """全勾选却不归档，spec 的事实源就停在旧状态。

    更糟的是拖得越久越难收口：后续变更会重写同一片 spec，早先那份 delta
    挂着的标题随之消失，归档时报"header not found"，只能回头逐条核对。
    """
    stale = []
    for change in _active_changes():
        tasks = change / "tasks.md"
        if not tasks.is_file():
            continue
        text = tasks.read_text(encoding="utf-8")
        done = len(re.findall(r"^- \[x\]", text, re.M))
        todo = len(re.findall(r"^- \[ \]", text, re.M))
        if done and not todo:
            stale.append(change.name)

    assert not stale, (
        f"这些变更任务已全部完成但未归档: {stale}；"
        f"执行 openspec archive <name> —— 拖得越久，spec delta 越可能挂在"
        f"已被后续变更重写的标题上")


# ---------------------------------------------------------------------------
# 闸门二：live spec 不得规定仓库里不存在的构建系统
# ---------------------------------------------------------------------------

#: 仓库已经不使用、但历史 spec 里大量出现的构建系统标记。
#: 键是标记，值是"判断仓库是否真的在用它"的证据文件。
ABANDONED_TOOLING = {
    "bazel": ("MODULE.bazel", "WORKSPACE", ".bazelversion"),
}

#: 否定式引用是**允许**的：spec 明确要求"不得依赖 Bazel"是有效契约。
_NEGATIVE = re.compile(r"(SHALL NOT|MUST NOT|不得|不依赖|不包含|无需)")


def test_仓库确实没有这些构建系统():
    """闸门的前提：这些标记确实已经废弃。前提不成立时闸门必须先被更新。"""
    for tool, evidence in ABANDONED_TOOLING.items():
        present = [name for name in evidence if (ROOT / name).exists()]
        assert not present, (
            f"{tool} 又被引入了（{present}）—— 先更新 ABANDONED_TOOLING，"
            f"再决定 spec 该怎么写")


@pytest.mark.parametrize("spec", _live_specs(), ids=lambda p: p.parent.name)
def test_live_spec不规定已废弃的构建系统(spec: Path):
    """规定一个不存在的构建系统，比没有 spec 更糟 —— 它会主动误导实现者。"""
    offending = []
    for line in spec.read_text(encoding="utf-8").splitlines():
        lowered = line.lower()
        for tool in ABANDONED_TOOLING:
            if tool in lowered and not _NEGATIVE.search(line):
                offending.append(line.strip()[:100])

    assert not offending, (
        f"{spec.parent.name} 规定了仓库中不存在的构建系统:\n  "
        + "\n  ".join(offending)
        + "\n（明确要求'不得依赖'的否定式引用是允许的）")


# ---------------------------------------------------------------------------
# 闸门三：spec 必须写明 Purpose
# ---------------------------------------------------------------------------

def test_live_spec不留归档模板占位():
    """`TBD - created by archiving change ...` 是归档工具留下的占位。

    留着它等于宣告"这份 spec 没人认领过"，而这次清理里每一份内容失效的
    spec 都恰好带着这个占位。
    """
    placeholder = []
    for spec in _live_specs():
        # 只看 Purpose 段：正文里引用这个占位串是合法的（描述本闸门本身）
        purpose = re.search(
            r"^## Purpose\n(.*?)^## ", spec.read_text(encoding="utf-8"),
            re.S | re.M)
        if purpose and "TBD - created by archiving change" in purpose.group(1):
            placeholder.append(spec.parent.name)

    assert not placeholder, (
        f"这些 spec 的 Purpose 仍是归档占位: {placeholder}；"
        f"写清它到底约束什么，否则没人会在改代码时想起它")
