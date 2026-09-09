"""UNO Q 宿主 QDL 架构选择与入库完整性验证，不访问 USB。"""

import hashlib
import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from builder.flash import unoq
from builder.flash.model import FlashError


@pytest.mark.parametrize("host,machine,arch", [
    ("darwin", "arm64", "arm64"),
    ("darwin", "x86_64", "x86_64"),
    ("linux", "aarch64", "arm64"),
    ("linux", "x86_64", "x86_64"),
    ("linux", "AMD64", "x86_64"),
])
def test_bundled_qdl_matches_host(monkeypatch, host, machine, arch):
    project = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(unoq.sys, "platform", host)
    monkeypatch.setattr(unoq.platform, "machine", lambda: machine)
    monkeypatch.setattr(unoq.shutil, "which", lambda name: None)
    tool = unoq.UnoQFlashStrategy().find_tool(project)
    directory = project / "tools" / ("macos" if host == "darwin" else "linux") / "qdl"
    assert tool == directory / arch / "qdl"
    assert tool.stat().st_mode & 0o111
    manifest = json.loads((tool.parent / "manifest.json").read_text())
    assert manifest["version"] == "v2.4-26"
    for filename, expected in manifest["files"].items():
        assert hashlib.sha256((tool.parent / filename).read_bytes()).hexdigest() == expected


def test_existing_local_qdl_override_keeps_priority(monkeypatch, tmp_path):
    monkeypatch.setattr(unoq.sys, "platform", "darwin")
    monkeypatch.setattr(unoq.platform, "machine", lambda: "arm64")
    tool = tmp_path / "tools/macos/qdl/qdl"
    tool.parent.mkdir(parents=True)
    tool.touch()
    assert unoq.UnoQFlashStrategy().find_tool(tmp_path) == tool


def test_unsupported_arch_uses_path_or_reports_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(unoq.sys, "platform", "linux")
    monkeypatch.setattr(unoq.platform, "machine", lambda: "riscv64")
    monkeypatch.setattr(unoq.shutil, "which", lambda name: "/custom/qdl")
    assert unoq.UnoQFlashStrategy().find_tool(tmp_path) == Path("/custom/qdl")
    monkeypatch.setattr(unoq.shutil, "which", lambda name: None)
    with pytest.raises(FlashError, match="linux/riscv64"):
        unoq.UnoQFlashStrategy().find_tool(tmp_path)


@pytest.mark.parametrize("list_root", [False, True])
def test_macos_ioreg_tree_requests_properties_and_accepts_root_shapes(monkeypatch, list_root):
    device = {"idVendor": 0x05c6, "idProduct": 0x9008,
              "USB Product Name": "QUSB_BULK_CID:0420_SN:ABCDEF12"}
    tree = {"IORegistryEntryChildren": [
        {"IORegistryEntryChildren": [device]},
        {"idVendor": 0x05c6, "idProduct": 0x900e},
        {"idVendor": 0x1234, "idProduct": 0x9008},
        "非设备节点",
    ]}
    payload = plistlib.dumps([tree] if list_root else tree)
    monkeypatch.setattr(unoq.sys, "platform", "darwin")

    def run(argv, **kwargs):
        assert argv == ["ioreg", "-p", "IOUSB", "-l", "-a"]
        return subprocess.CompletedProcess(argv, 0, payload, b"")

    monkeypatch.setattr(unoq.subprocess, "run", run)
    device = unoq.UnoQFlashStrategy().detect_device(Path("qdl"))
    assert device.serial == "ABCDEF12"
