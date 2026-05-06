"""测试 RockchipKernelBuilder._write_panel_mipi_dbi_fragment 行为。

与 _write_panthor_fragment 不同：panel-mipi-dbi-spi driver 在 mainline v5.18
已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport patch、无需条件分支。
fragment 总是写入相同内容，由 SoC kernel.defconfig list 决定是否引入。
"""

from pathlib import Path

import pytest

from builder.platforms.rockchip.kernel import RockchipKernelBuilder


@pytest.fixture
def builder(monkeypatch):
    """构造一个 RockchipKernelBuilder 实例，并屏蔽其 _status 输出。

    KernelBuilder 基类的 __init__ 需要 source/docker 等依赖，但本测试
    只调用纯 Path I/O 的方法，所以走 object.__new__ 绕过构造函数。
    """
    b = RockchipKernelBuilder.__new__(RockchipKernelBuilder)
    monkeypatch.setattr(b, "_status", lambda *a, **kw: None, raising=False)
    return b


def test_writes_fragment_to_arch_configs(builder, tmp_path):
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)

    fragment = src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config"
    assert fragment.is_file()


def test_fragment_enables_panel_mipi_dbi_module(builder, tmp_path):
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)

    text = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()
    assert "CONFIG_DRM_PANEL_MIPI_DBI=m" in text


def test_fragment_is_idempotent(builder, tmp_path):
    """重复调用应得到相同内容（不追加、不报错）。"""
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)
    first = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()

    builder._write_panel_mipi_dbi_fragment(src)
    second = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()

    assert first == second


def test_configure_invokes_panel_mipi_dbi_fragment(builder, tmp_path, monkeypatch):
    """configure() 应在写其他 fragment 后也调用 panel mipi dbi fragment。

    通过监控 _write_panel_mipi_dbi_fragment 是否被调用一次来验证。
    """
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    calls = []

    def fake_panel(self, src_dir):
        calls.append(src_dir)

    def fake_case(self, src_dir):
        pass

    def fake_panthor(self, src_dir, config):
        pass

    def fake_make(self, src_dir, targets, **kw):
        pass

    monkeypatch.setattr(RockchipKernelBuilder, "_write_panel_mipi_dbi_fragment", fake_panel)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_case_insensitive_fix", fake_case)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_panthor_fragment", fake_panthor)
    monkeypatch.setattr(RockchipKernelBuilder, "make", fake_make)

    builder.configure(src, {"kernel": {"defconfig": "rockchip_linux_defconfig"}})

    assert calls == [src], f"expected exactly one call to _write_panel_mipi_dbi_fragment with src={src}, got {calls}"
