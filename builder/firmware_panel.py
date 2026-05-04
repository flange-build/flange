"""Panel firmware 编码器 — 把可读 init 序列文本源编译为 mainline
``panel-mipi-dbi-spi`` driver 兼容的 ``panel.bin`` 二进制。

文本源语法
----------

::

    # 注释
    command 0xNN [0xPP ...]   # CMD 与每个参数都是 0x 起头两位 hex
    delay MS                  # MS 是 1..255 十进制毫秒（driver 的 NOP delay
                              # 参数为单字节 u8，超过 255 ms 必须拆为多条）

二进制格式
----------

与 mainline ``drivers/gpu/drm/tiny/panel-mipi-dbi.c`` 对齐（v5.18 引入，
此处实现以 tspi-rk3566 6.1 BSP 中的同源 backport 为参照逐字节核对）：

- 16 字节 header：``"MIPI DBI"`` magic (8B) + 7B ``0x00`` reserved + 1B
  ``file_format_version = 0x01``
- 命令条目：``cmd:u8  num_params:u8  params:u8[num_params]``
- delay 编码为 NOP 特殊命令：``0x00  0x01  ms_u8``

一份 panel firmware 通过 board 配置 ``rootfs.panel_firmware`` 声明：

::

    {"src": "firmware/panel/<name>.txt", "dest": "<compatible[0]>.bin"}

构建期把 ``src`` 文本编译为 ``dest``，落 rootfs ``lib/firmware/<dest>``。
DT compatible 的最具体字符串（``compatible[0]``）派生 driver 在
``/lib/firmware/`` 下查找的文件名（v5.18 driver 不读 ``firmware-name``）。
"""

from __future__ import annotations

from pathlib import Path


MAGIC = b"MIPI DBI" + b"\x00" * 7  # 15 字节
VERSION = 0x01
HEADER = MAGIC + bytes([VERSION])  # 16 字节
NOP_CMD = 0x00


class PanelFirmwareError(ValueError):
    """文本源解析错误。错误信息包含行号与原因。"""


def _parse_byte(token: str, line_no: int, label: str) -> int:
    if len(token) != 4 or not token.startswith(("0x", "0X")):
        raise PanelFirmwareError(
            f"line {line_no}: {label} 必须是 0xNN 形式十六进制字节字面量，"
            f"得到 {token!r}")
    try:
        value = int(token, 16)
    except ValueError as exc:
        raise PanelFirmwareError(
            f"line {line_no}: {label} 解析失败 {token!r}: {exc}") from exc
    if not 0 <= value <= 0xFF:
        raise PanelFirmwareError(
            f"line {line_no}: {label} 越界 0..255: {token!r}")
    return value


def encode_panel_firmware(text: str) -> bytes:
    """把文本源编码为 ``panel.bin`` 二进制。

    解析失败时 raise :class:`PanelFirmwareError`，错误信息含行号。
    """
    out = bytearray(HEADER)
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        op = parts[0]
        if op == "command":
            if len(parts) < 2:
                raise PanelFirmwareError(
                    f"line {line_no}: command 缺少 CMD 字节")
            cmd = _parse_byte(parts[1], line_no, "CMD")
            params = [_parse_byte(p, line_no, "param") for p in parts[2:]]
            if len(params) > 0xFF:
                raise PanelFirmwareError(
                    f"line {line_no}: command 参数数量 {len(params)} 超过 255")
            out.append(cmd)
            out.append(len(params))
            out.extend(params)
        elif op == "delay":
            if len(parts) != 2:
                raise PanelFirmwareError(
                    f"line {line_no}: delay 需要恰好 1 个毫秒参数")
            try:
                ms = int(parts[1], 10)
            except ValueError as exc:
                raise PanelFirmwareError(
                    f"line {line_no}: delay 毫秒数解析失败 "
                    f"{parts[1]!r}: {exc}") from exc
            if not 1 <= ms <= 255:
                raise PanelFirmwareError(
                    f"line {line_no}: delay 毫秒数越界 1..255: {ms} "
                    f"(driver 把 delay 编码为单字节 u8 参数)")
            out.append(NOP_CMD)
            out.append(0x01)
            out.append(ms)
        else:
            raise PanelFirmwareError(
                f"line {line_no}: 未知指令 {op!r}（仅支持 command / delay）")
    return bytes(out)


def encode_file(src: Path) -> bytes:
    """从文件读文本源，返回编码后的二进制。"""
    return encode_panel_firmware(Path(src).read_text(encoding="utf-8"))
