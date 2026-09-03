"""lunch state 始终锚定项目根目录。"""

from __future__ import annotations

import json
from pathlib import Path

from builder.config import loader
from builder.paths import PROJECT_ROOT


def test_state_file_is_anchored_to_project_root() -> None:
    assert loader.STATE_FILE == PROJECT_ROOT / ".flange" / "current_config"
    assert loader.STATE_FILE.is_absolute()


def test_state_round_trip_does_not_depend_on_caller_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_file = tmp_path / "project" / ".flange" / "current_config"
    caller_cwd = tmp_path / "outside"
    caller_cwd.mkdir()
    monkeypatch.chdir(caller_cwd)
    monkeypatch.setattr(loader, "STATE_FILE", state_file)
    monkeypatch.setattr(
        loader,
        "resolve_config",
        lambda board, product, variant: {
            "board": board,
            "product": product,
            "variant": variant,
        },
    )
    monkeypatch.setattr(loader, "validate_config", lambda _: None)

    loader.save_state("demo-board", "demo-product", "debug")

    assert json.loads(state_file.read_text(encoding="utf-8")) == {
        "board": "demo-board",
        "product": "demo-product",
        "variant": "debug",
    }
    assert not (caller_cwd / ".flange" / "current_config").exists()
    assert loader.load_current_config() == {
        "board": "demo-board",
        "product": "demo-product",
        "variant": "debug",
    }
