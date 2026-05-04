"""Panel firmware 编码器单元测试。

字节布局以 mainline ``panel-mipi-dbi.c`` 实际期望逐字节核对——同源代码
位于 ``.build/sources/kernel/tspi-rk3566/drivers/gpu/drm/tiny/panel-mipi-dbi.c``
（v5.18 上游的 Rockchip 6.1 backport，header / 命令编码与上游一致）。
"""

from __future__ import annotations

import pytest

from builder.firmware_panel import (
    HEADER,
    MAGIC,
    NOP_CMD,
    PanelFirmwareError,
    encode_panel_firmware,
)


def test_header_constants_match_driver_layout():
    """header = 8B 'MIPI DBI' + 7B 0x00 + 1B 0x01."""
    assert MAGIC == b"MIPI DBI\x00\x00\x00\x00\x00\x00\x00"
    assert len(MAGIC) == 15
    assert HEADER == MAGIC + b"\x01"
    assert len(HEADER) == 16
    assert NOP_CMD == 0x00


def test_empty_text_yields_only_header():
    """空文本（含注释与空行）只产出 header，不含命令字节。"""
    text = """
    # 全是注释
    # 与空行

    """
    assert encode_panel_firmware(text) == HEADER


def test_command_no_params():
    """SLPOUT 这类无参命令编码为 cmd=0x11 num_params=0x00。"""
    text = "command 0x11"
    out = encode_panel_firmware(text)
    assert out == HEADER + bytes([0x11, 0x00])


def test_command_with_multiple_params():
    """多参命令逐字节排列在 num_params 之后。"""
    text = "command 0xB1 0x01 0x2C 0x2D"
    out = encode_panel_firmware(text)
    assert out == HEADER + bytes([0xB1, 0x03, 0x01, 0x2C, 0x2D])


def test_delay_encodes_as_nop_with_one_byte_ms():
    """delay 120ms → 0x00 0x01 0x78（NOP cmd + num_params=1 + ms_u8）。"""
    text = "delay 120"
    out = encode_panel_firmware(text)
    assert out == HEADER + bytes([0x00, 0x01, 0x78])


def test_full_minimal_init_sequence():
    """对照 driver 注释里的示例字节序列：SLPOUT / sleep 120 /
    PORCTRL+3 / DISPON。"""
    text = """\
command 0x11
delay 120
command 0xB1 0x01 0x2C 0x2D
command 0x29
"""
    expected = HEADER + bytes([
        0x11, 0x00,
        0x00, 0x01, 0x78,
        0xB1, 0x03, 0x01, 0x2C, 0x2D,
        0x29, 0x00,
    ])
    assert encode_panel_firmware(text) == expected


def test_inline_comment_is_stripped():
    """`#` 起始的行末注释应当被剥除，不影响解析。"""
    text = "command 0x36 0x00  # MADCTL portrait"
    out = encode_panel_firmware(text)
    assert out == HEADER + bytes([0x36, 0x01, 0x00])


def test_invalid_byte_literal_reports_line():
    """缺少 0x 前缀的字节字面量报告行号。"""
    text = "\n# pad\ncommand FF\n"
    with pytest.raises(PanelFirmwareError) as exc:
        encode_panel_firmware(text)
    assert "line 3" in str(exc.value)
    assert "0xNN" in str(exc.value)


def test_delay_out_of_range_reports_line():
    """255 ms 上限是 driver 编码限制，越界要明示。"""
    text = "delay 256"
    with pytest.raises(PanelFirmwareError) as exc:
        encode_panel_firmware(text)
    assert "line 1" in str(exc.value)
    assert "1..255" in str(exc.value)


def test_unknown_op_reports_line():
    """除 command/delay 外的指令一律报错。"""
    text = "command 0x11\nfoo 0x22\n"
    with pytest.raises(PanelFirmwareError) as exc:
        encode_panel_firmware(text)
    assert "line 2" in str(exc.value)
    assert "foo" in str(exc.value)


def test_command_missing_cmd_byte():
    """`command` 后必须跟 CMD。"""
    with pytest.raises(PanelFirmwareError) as exc:
        encode_panel_firmware("command")
    assert "line 1" in str(exc.value)
    assert "command 缺少 CMD" in str(exc.value)


def test_delay_must_be_decimal():
    """delay 参数 0xFF 形式要被拒绝（语法约束：十进制）。"""
    with pytest.raises(PanelFirmwareError):
        encode_panel_firmware("delay 0xFF")
