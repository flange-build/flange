"""Rockchip AMP out-of-tree App 解析与缓存测试。"""

from pathlib import Path

import pytest

from builder.component_plan import create_component_plan
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext
from builder.config.registry import resolve_config
from builder.platforms.rockchip.amp import RockchipAmpBuilder


class FakeSource:
    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.calls = []

    def ensure_app(self, app_name: str, config: dict) -> Path:
        self.calls.append((app_name, config))
        return self.app_dir


def make_amp_app(tmp_path: Path, *, app_type: str = "amp") -> Path:
    app_dir = tmp_path / "rk3506_amp_fluxion_foc"
    (app_dir / "applications").mkdir(parents=True)
    (app_dir / "app.yaml").write_text(
        "app:\n"
        "  name: rk3506_amp_fluxion_foc\n"
        "  version: 0.1.0\n"
        "  description: Fluxion RK3506 AMP 测试应用\n"
        f"  type: {app_type}\n"
        "  arch: [armhf]\n"
        "maintainer:\n"
        "  name: flange\n"
        "  email: flange@localhost\n"
        "build:\n"
        + ("  system: scons\n" if app_type == "amp" else "  system: none\n")
    )
    return app_dir


def amp_config(app_dir: Path) -> dict:
    return {
        "amp": {
            "app": "rk3506_amp_fluxion_foc",
            "mode": "rt-thread",
        },
        "external_apps": {
            "rk3506_amp_fluxion_foc": {
                "local_path": str(app_dir),
            },
        },
    }


def test_amp_builder_resolves_app_through_source_manager(tmp_path):
    """amp.app 应复用 app registry，而非硬编码 components/app。"""
    app_dir = make_amp_app(tmp_path)
    source = FakeSource(app_dir)
    config = amp_config(app_dir)
    builder = RockchipAmpBuilder(docker=None, source=source)
    builder.context = WorkspaceContext(tmp_path / "tool", tmp_path / "workspace", tmp_path / ".build", Target("board", "default", "release"))

    assert builder._amp_app_dir(config) == app_dir
    assert source.calls == [("rk3506_amp_fluxion_foc", config)]


def test_amp_builder_rejects_non_amp_external_app(tmp_path):
    """OOT 目录存在也不能绕过 app.type 安全校验。"""
    app_dir = make_amp_app(tmp_path, app_type="exec")
    builder = RockchipAmpBuilder(docker=None, source=FakeSource(app_dir))
    builder.context = WorkspaceContext(tmp_path / "tool", tmp_path / "workspace", tmp_path / ".build", Target("board", "default", "release"))

    with pytest.raises(ValueError, match="app.type 必须是 amp"):
        builder._amp_app_dir(amp_config(app_dir))


def test_local_oot_amp内容变化使计划失效(tmp_path):
    app = make_amp_app(tmp_path)
    context = WorkspaceContext(tmp_path / 'tool', tmp_path / 'workspace', tmp_path / '.build',
                               Target('board', 'default', 'release'), apps={'rk3506_amp_fluxion_foc': app})
    config = {**amp_config(app), 'board': 'board', 'platform': 'rockchip'}
    config['amp']['enabled'] = True
    source = SourceManager(context=context)
    first = create_component_plan('amp', config, context, source)
    before = first.fingerprint({'kernel': 'same'}).digest
    (app / 'applications/main.c').write_text('new')
    second = create_component_plan('amp', config, context, source)
    assert second.fingerprint({'kernel': 'same'}).digest != before
    before = second.fingerprint({'kernel': 'same'}).digest
    (app / 'applications/main.c').write_text('changed')
    assert first.fingerprint({'kernel': 'same'}).digest != before
    assert second.path('amp:application') == app


def test_atk_rk3506b_fluxion_product_selects_runtime_only():
    default = resolve_config("atk-rk3506b", "default", "debug")
    fluxion = resolve_config("atk-rk3506b", "fluxion", "debug")

    assert default["amp"]["app"] == "rk3506_amp_uart4_rtt_demo"
    assert default["external_apps"] == {}
    assert fluxion["amp"]["app"] == "fluxion_runtime"
    assert set(fluxion["external_apps"]) == {"fluxion_runtime"}
    assert "fluxion-rpmsg-bridge" not in fluxion["rootfs"]["custom_packages"]
