"""Rockchip 宿主工具的入库完整性与可执行格式验证，不访问 USB。"""

import hashlib
import json
import struct
from pathlib import Path

import pytest


@pytest.mark.parametrize("host", ["linux", "macos"])
def test_bundled_upgrade_tool_integrity(host: str) -> None:
    directory = Path(__file__).resolve().parents[2] / "tools" / host / "upgrade_tool"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {
        "upgrade_tool", "config.ini", "revision.txt", "命令行开发工具使用文档.pdf",
    }
    for filename, expected in manifest["files"].items():
        data = (directory / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, filename

    revision = (directory / "revision.txt").read_text(encoding="utf-8")
    assert revision.startswith(f"{manifest['version']} revision(")
    tool = directory / "upgrade_tool"
    assert tool.stat().st_mode & 0o111
    binary = tool.read_bytes()
    if host == "linux":
        assert binary[:6] == b"\x7fELF\x02\x01"
        assert struct.unpack_from("<H", binary, 18)[0] == 62  # ELF x86_64。
    else:
        magic, count = struct.unpack_from(">II", binary)
        assert magic == 0xCAFEBABE
        assert count == 2
        architectures = set()
        for index in range(count):
            cpu, _, offset, size, _ = struct.unpack_from(">IIIII", binary, 8 + index * 20)
            architectures.add(cpu)
            assert offset + size <= len(binary)
            assert binary[offset:offset + 4] == b"\xcf\xfa\xed\xfe"
            assert struct.unpack_from("<I", binary, offset + 4)[0] == cpu
        assert architectures == {0x01000007, 0x0100000C}  # x86_64 与 arm64。
