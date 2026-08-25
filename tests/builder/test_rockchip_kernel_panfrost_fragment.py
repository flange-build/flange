"""测试 RockchipKernelBuilder._write_panfrost_fragment 行为。

rk3566 / rk3568 / rk3576（GPU 均 Mali-G52 Bifrost）走 mainline panfrost：
关闭闭源 mali_kbase + 启用 CONFIG_DRM_PANFROST；其他 SoC 写空 fragment
（不污染 panthor 路线）。
覆盖 rockchip-platform spec "Rockchip GPU 开源驱动 fragment 按 SoC GPU 架构选型"。
"""

from pathlib import Path

import pytest

from builder.platforms.rockchip.kernel import RockchipKernelBuilder


@pytest.fixture
def builder(monkeypatch):
    """构造 RockchipKernelBuilder 实例并屏蔽 _status（绕过基类 __init__）。"""
    b = RockchipKernelBuilder.__new__(RockchipKernelBuilder)
    monkeypatch.setattr(b, "_status", lambda *a, **kw: None, raising=False)
    return b


def _src_with_configs(tmp_path: Path) -> Path:
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)
    return src


def _fragment(src: Path) -> Path:
    return src / "arch" / "arm64" / "configs" / "panfrost.config"


@pytest.mark.parametrize("soc", ["rk3566", "rk3568", "rk3576"])
def test_g52_soc_enables_panfrost_disables_kbase(builder, tmp_path, soc):
    src = _src_with_configs(tmp_path)
    builder._write_panfrost_fragment(src, {"soc": soc})
    text = _fragment(src).read_text()
    assert "CONFIG_DRM_PANFROST=m" in text
    assert "# CONFIG_MALI_BIFROST is not set" in text
    assert "# CONFIG_MALI_MIDGARD is not set" in text
    # 不得保留闭源 kbase 的 =y
    assert "CONFIG_MALI_BIFROST=y" not in text


def test_non_g52_writes_empty_fragment(builder, tmp_path):
    """rk3588 上 panfrost fragment 为空，panthor 路线不受影响。"""
    src = _src_with_configs(tmp_path)
    builder._write_panfrost_fragment(src, {"soc": "rk3588"})
    text = _fragment(src).read_text()
    assert "CONFIG_DRM_PANFROST" not in text
    assert "PANTHOR" not in text


def test_missing_soc_writes_empty_fragment(builder, tmp_path):
    src = _src_with_configs(tmp_path)
    builder._write_panfrost_fragment(src, {})
    assert "CONFIG_DRM_PANFROST" not in _fragment(src).read_text()


def test_fragment_is_idempotent(builder, tmp_path):
    src = _src_with_configs(tmp_path)
    builder._write_panfrost_fragment(src, {"soc": "rk3576"})
    first = _fragment(src).read_text()
    builder._write_panfrost_fragment(src, {"soc": "rk3576"})
    assert first == _fragment(src).read_text()


def test_configure_invokes_panfrost_fragment(builder, tmp_path, monkeypatch):
    """configure() 应调用 _write_panfrost_fragment 一次。"""
    src = _src_with_configs(tmp_path)
    calls = []
    monkeypatch.setattr(RockchipKernelBuilder, "_write_panfrost_fragment",
                        lambda self, s, c: calls.append(s))
    monkeypatch.setattr(RockchipKernelBuilder, "_write_case_insensitive_fix",
                        lambda self, s: None)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_panthor_fragment",
                        lambda self, s, c: None)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_panel_mipi_dbi_fragment",
                        lambda self, s: None)
    monkeypatch.setattr(RockchipKernelBuilder, "make",
                        lambda self, s, t, **kw: None)
    builder.configure(
        src, {
            "soc": "rk3576",
            "architecture": {
                "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
            },
            "kernel": {"defconfig": ["rockchip_linux_defconfig"]},
        })
    assert calls == [src]
