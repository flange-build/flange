"""RootfsBuilder._install_panel_firmware 集成单测。

验证：声明的 panel firmware 文本源被编码为 mainline panel.bin 二进制，
落 rootfs lib/firmware/<dest>，dest 与 DT compatible 派生的 firmware 名一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.firmware_panel import HEADER, encode_panel_firmware
from builder.rootfs import RootfsBuilder


class _StubRootfsBuilder(RootfsBuilder):
    """仅用于测试：跳过 abstract method、不接 docker/source。"""

    component = "rootfs"

    def __init__(self):
        # 不调 super().__init__ —— RootfsBuilder._install_panel_firmware
        # 只读 config + 文件系统，不依赖 docker/source。
        self._statuses: list[str] = []

    def _status(self, msg: str):
        self._statuses.append(msg)

    def configure(self, *a, **kw): ...
    def compile(self, *a, **kw): ...
    def collect(self, *a, **kw): return {}


@pytest.fixture
def builder():
    return _StubRootfsBuilder()


def _make_board(tmp_path: Path, board: str, src_rel: str, text: str) -> Path:
    """在 tmp_path 下搭一个最小 components/board/<board>/<src_rel> 文件。"""
    board_root = tmp_path / "components" / "board" / board
    src_path = board_root / src_rel
    src_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.write_text(text)
    return board_root


def test_install_panel_firmware_writes_encoded_binary(
        builder, tmp_path, monkeypatch):
    """文本源 → 编码 → 落 rootfs/lib/firmware/<dest>。"""
    text = "command 0x11\ndelay 120\ncommand 0x29\n"
    _make_board(tmp_path, "test-board",
                "firmware/panel/test-st7789.txt", text)
    monkeypatch.chdir(tmp_path)

    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir()
    config = {
        "board": "test-board",
        "rootfs": {
            "panel_firmware": [
                {"src": "firmware/panel/test-st7789.txt",
                 "dest": "panel-mipi-dbi-spi.bin"},
            ],
        },
    }

    builder._install_panel_firmware(rootfs_dir, config)

    out = rootfs_dir / "lib/firmware/panel-mipi-dbi-spi.bin"
    assert out.exists()
    expected = encode_panel_firmware(text)
    assert out.read_bytes() == expected
    assert out.read_bytes().startswith(HEADER)


def test_install_panel_firmware_missing_source_raises(
        builder, tmp_path, monkeypatch):
    """声明的 src 不存在时，抛 FileNotFoundError 且消息含 board 名。"""
    monkeypatch.chdir(tmp_path)
    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir()
    config = {
        "board": "ghost-board",
        "rootfs": {
            "panel_firmware": [
                {"src": "firmware/panel/missing.txt",
                 "dest": "panel-mipi-dbi-spi.bin"},
            ],
        },
    }

    with pytest.raises(FileNotFoundError) as exc:
        builder._install_panel_firmware(rootfs_dir, config)
    assert "ghost-board" in str(exc.value)
    assert "missing.txt" in str(exc.value)


def test_install_panel_firmware_no_op_when_unset(builder, tmp_path):
    """未声明 panel_firmware 时 silently no-op。"""
    config = {"board": "x", "rootfs": {}}
    builder._install_panel_firmware(tmp_path, config)
    assert not (tmp_path / "lib").exists()


def test_install_panel_firmware_supports_subdirectory_dest(
        builder, tmp_path, monkeypatch):
    """dest 可含子目录（虽然 panel-mipi-dbi-spi 默认在 /lib/firmware/ 根下，
    但若未来用 firmware-name 子目录路径可扩展）。"""
    text = "command 0x29\n"
    _make_board(tmp_path, "test-board", "firmware/panel/x.txt", text)
    monkeypatch.chdir(tmp_path)
    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir()
    config = {
        "board": "test-board",
        "rootfs": {
            "panel_firmware": [
                {"src": "firmware/panel/x.txt", "dest": "panel/x.bin"},
            ],
        },
    }
    builder._install_panel_firmware(rootfs_dir, config)
    assert (rootfs_dir / "lib/firmware/panel/x.bin").exists()
