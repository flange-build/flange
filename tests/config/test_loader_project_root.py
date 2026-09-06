"""目标状态按工作区隔离，显式上下文不受调用目录干扰。"""

import json

import pytest

from builder.config.loader import load_current_config, save_state
from builder.paths import PROJECT_ROOT
from builder.workspace import init_workspace, load_workspace


def test_two_workspaces_do_not_share_target_state(tmp_path, monkeypatch):
    first, second, outside = (tmp_path / name for name in ("first", "second", "outside"))
    for root in (first, second):
        init_workspace(root, tool_root=PROJECT_ROOT)
    outside.mkdir()
    monkeypatch.chdir(outside)
    save_state("radxa-zero3w", "default", "debug", workspace_root=first)
    save_state("radxa-zero3w", "default", "release", workspace_root=second)
    first_context, second_context = load_workspace(first), load_workspace(second)
    assert load_current_config(first_context)["variant"] == "debug"
    assert load_current_config(second_context)["variant"] == "release"
    assert not (outside / ".flange/current_config").exists()
    save_state("radxa-zero3w", "default", "release", context=first_context)
    assert json.loads(first_context.state_file.read_text())["variant"] == "release"
    assert json.loads(second_context.state_file.read_text())["variant"] == "release"


def test_implicit_load_discovers_workspace_from_subdirectory(tmp_path, monkeypatch):
    init_workspace(tmp_path, tool_root=PROJECT_ROOT)
    save_state("radxa-zero3w", "default", "debug", workspace_root=tmp_path)
    nested = tmp_path / "apps/demo"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert load_current_config()["variant"] == "debug"


def test_save_requires_explicit_workspace():
    with pytest.raises(ValueError, match="context 或 workspace_root"):
        save_state("radxa-zero3w", "default", "debug")
