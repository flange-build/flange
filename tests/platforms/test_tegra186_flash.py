"""Tegra186 tegraflash 刷写包：布局渲染、manifest 校验、flash-config 与宿主刷写策略。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.flash.model import FlashConfig, FlashError
from builder.flash.plan import get_flash_plan
from builder.flash.tegra import (
    BUNDLE_PATH, flash_args, layout_partitions, posix_cksum, render_layout,
    validate_bundle,
)
from builder.platforms.nvidiategra186.image import Tegra186ImageBuilder
from tests.builder.context import component_context
from tests.platforms.tegra186_fixtures import (
    TEMPLATE, TOKENS, fake_mksparse, image_config, tegraflash_config, upstream,
)

GENERATED = {"APPSIZE": "1073741824", "APPFILE": "system.img", "KERNELDTB-FILE": "kernel_x.dtb",
             "LNXFILE": "boot.img", "BOOTCTRL-FILE": "kernel_bootctrl.bin",
             "VERFILE": "emmc_bootblob_ver.txt"}


def _render() -> str:
    return render_layout(TEMPLATE, {**TOKENS, **GENERATED})


# ---- 构建期：布局与参数 --------------------------------------------------------


def test_suffixed_tokens_are_replaced():
    layout = _render()
    assert 'name="cpu-bootloader_b"' in layout
    assert "TBCNAME" not in layout


def test_empty_file_token_drops_only_filename_line():
    layout = _render()
    assert 'name="recovery"' in layout
    assert "RECFILE" not in layout
    assert "<unique_guid>  </unique_guid>" in layout


def test_unknown_token_is_rejected():
    with pytest.raises(FlashError, match="MB1NAMEX"):
        render_layout(TEMPLATE, {**TOKENS, **GENERATED, "MB1NAMEX": "mb1"})


def test_layout_partitions_reports_signing_and_sizes():
    parts = {entry["name"]: entry for entry in layout_partitions(_render())}
    assert set(parts) == {"cpu-bootloader", "cpu-bootloader_b", "APP", "kernel", "kernel-dtb",
                          "kernel-bootctrl", "VER"}
    assert parts["kernel"]["sign"] is True and parts["APP"]["sign"] is False
    assert parts["APP"]["bytes"] == 1073741824


@pytest.mark.parametrize("filename", ["../evil.bin", "sub/evil.bin"])
def test_layout_rejects_paths(filename):
    layout = _render().replace("<filename> cboot.bin </filename>", f"<filename> {filename} </filename>", 1)
    with pytest.raises(FlashError, match="不是刷写目录中的文件"):
        layout_partitions(layout)


def test_flash_args_follow_flashcmd_order():
    args = flash_args(tegraflash_config())
    flags = [item for item in args if item.startswith("--")]
    assert flags == ["--bl", "--sdram_config", "--odmdata", "--applet", "--cfg", "--chip",
                     "--misc_config", "--dev_params", "--bins"]


def test_posix_cksum_matches_reference_vector():
    # `printf 123456789 | cksum` → 930766865
    assert posix_cksum(b"123456789") == 930766865
    assert posix_cksum(b"") == 4294967295


# ---- 刷写包 manifest 与 flash-config -------------------------------------------


def _bundle(tmp_path) -> tuple[Path, dict]:
    config = image_config()
    docker = MagicMock()
    docker.run.side_effect = fake_mksparse
    builder = Tegra186ImageBuilder(docker, MagicMock())
    builder.context = component_context(tmp_path, config)
    upstream(builder.context.target_dir)
    return builder.build(config)["bundle"], config


@pytest.mark.parametrize(
    "tamper, message",
    [
        (lambda b: (b / "cboot.bin").write_bytes(b"patched"), "摘要"),
        (lambda b: (b / "extra.bin").write_bytes(b"x"), "多出"),
        (lambda b: (b / "boot.img").unlink(), "缺少"),
        (lambda b: ((b / "tos.img").unlink(), (b / "tos.img").symlink_to("/etc/passwd")), "摘要"),
    ],
)
def test_validate_bundle_rejects_tampering(tmp_path, tamper, message):
    bundle, _ = _bundle(tmp_path)
    tamper(bundle)
    with pytest.raises(FlashError, match=message):
        validate_bundle(bundle)


def _flash_config(tmp_path):
    bundle, config = _bundle(tmp_path)
    target = tmp_path / "target"
    (target / BUNDLE_PATH).parent.mkdir(parents=True)
    os.rename(bundle, target / BUNDLE_PATH)
    return get_flash_plan("nvidiategra186").generate_flash_config(config, target), target


def test_flash_config_uses_existing_fields_only(tmp_path):
    cfg, target = _flash_config(tmp_path)

    assert (cfg.platform, cfg.flash_tool, cfg.storage_type) == ("nvidiategra186", "tegraflash", "emmc")
    assert (cfg.pre_flash.usb_vid, cfg.pre_flash.usb_pid) == ("0955", "7c18")
    assert cfg.bundle_manifest == f"{BUNDLE_PATH}/manifest.json"
    names = {part.name: part for part in cfg.partitions}
    assert names["APP"].image == f"{BUNDLE_PATH}/system.img" and not names["APP"].protected
    assert names["cpu-bootloader"].protected and names["cpu-bootloader"].type == "raw"
    assert all((target / part.image).exists() for part in cfg.partitions)
    cfg.to_json(target / "flash-config.json")
    assert FlashConfig.from_json(target / "flash-config.json") == cfg


# ---- 宿主机刷写策略 ------------------------------------------------------------

from builder.flash import tegra as tegra_flash  # noqa: E402
from builder.flash.model import DeviceInfo  # noqa: E402
from builder.flash.tegra import TegraFlashStrategy  # noqa: E402


@pytest.fixture
def host(monkeypatch):
    """x86_64 Linux root 宿主，USB 设备树与子进程全部替换为记录桩。"""
    monkeypatch.setattr(tegra_flash.sys, "platform", "linux")
    monkeypatch.setattr(tegra_flash.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(tegra_flash.os, "geteuid", lambda: 0)
    calls = []

    def stream(command, directory, log, timeout):
        calls.append(command)
        if "dump eeprom boardinfo cvm.bin" in command:
            (Path(directory) / "cvm.bin").write_bytes(b"eeprom")
        return 0

    monkeypatch.setattr(tegra_flash, "stream_qdl", stream)
    return calls


def _usb(tmp_path, monkeypatch, count=1):
    root = tmp_path / "usb"
    for index in range(count):
        node = root / f"1-{index + 1}"
        node.mkdir(parents=True)
        (node / "idVendor").write_text("0955\n")
        (node / "idProduct").write_text("7c18\n")
    other = root / "2-1"
    other.mkdir(parents=True)
    (other / "idVendor").write_text("0955\n")
    (other / "idProduct").write_text("7020\n")
    monkeypatch.setattr(tegra_flash, "USB_DEVICES", root)


def _strategy(tmp_path, cfg, target, partitions=None, *, allow=False):
    strategy = TegraFlashStrategy()
    strategy.allow_protected = allow
    strategy.preflight(target, cfg, cfg.partitions if partitions is None else partitions)
    return strategy


def _board_info(monkeypatch, strategy, fab="B02", board_id="3310"):
    monkeypatch.setattr(strategy, "_board_info", lambda: {
        "board_id": board_id, "board_sku": "1000", "fab": fab, "revision": "E.0"})


def test_non_x86_host_fails_before_touching_device(tmp_path, monkeypatch):
    cfg, target = _flash_config(tmp_path)
    monkeypatch.setattr(tegra_flash.sys, "platform", "linux")
    monkeypatch.setattr(tegra_flash.platform, "machine", lambda: "aarch64")

    with pytest.raises(FlashError, match="x86_64 Linux"):
        TegraFlashStrategy().preflight(target, cfg, cfg.partitions)


def test_manifest_digest_must_match_flash_config(tmp_path, host):
    cfg, target = _flash_config(tmp_path)
    cfg.bundle_manifest_sha256 = "0" * 64

    with pytest.raises(FlashError, match="摘要不符"):
        TegraFlashStrategy().preflight(target, cfg, cfg.partitions)


def test_protected_single_partition_requires_yes(tmp_path, host):
    cfg, target = _flash_config(tmp_path)
    kernel = next(part for part in cfg.partitions if part.name == "kernel")

    with pytest.raises(FlashError, match="--yes"):
        _strategy(tmp_path, cfg, target, [kernel])
    _strategy(tmp_path, cfg, target, [kernel], allow=True)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_detect_requires_single_recovery_device(tmp_path, monkeypatch, count):
    _usb(tmp_path, monkeypatch, count)
    strategy = TegraFlashStrategy()

    if count == 2:
        with pytest.raises(FlashError, match="只连接目标 TX2"):
            strategy.detect_device(Path("python3"))
    elif count == 1:
        assert strategy.detect_device(Path("python3")) == DeviceInfo(
            "nvidiategra186", "recovery", "Tegra186 USB Recovery", serial="1-1")
    else:
        assert strategy.detect_device(Path("python3")) is None


def test_identity_is_read_like_flash_sh_before_any_write(tmp_path, monkeypatch, host):
    _usb(tmp_path, monkeypatch)
    cfg, target = _flash_config(tmp_path)
    strategy = _strategy(tmp_path, cfg, target)
    _board_info(monkeypatch, strategy)

    strategy.pre_flash(Path("/usr/bin/python3"), target, cfg)

    assert host[0] == ["./tegrarcm_v2", "--uid"]
    assert host[1] == ["/usr/bin/python3", "tegraflash.py", "--chip", "0x18",
                       "--applet", "mb1_recovery_prod.bin", "--skipuid",
                       "--cmd", "dump eeprom boardinfo cvm.bin"]
    assert (strategy.workdir / "system.img").is_symlink()
    assert not (strategy.workdir / "cboot.bin").is_symlink()


@pytest.mark.parametrize("board_id, fab", [("3489", "B02"), ("3310", "C04")])
def test_identity_mismatch_stops_before_write(tmp_path, monkeypatch, host, board_id, fab):
    _usb(tmp_path, monkeypatch)
    cfg, target = _flash_config(tmp_path)
    strategy = _strategy(tmp_path, cfg, target)
    _board_info(monkeypatch, strategy, fab=fab, board_id=board_id)

    with pytest.raises(FlashError, match="未写入任何分区"):
        strategy.pre_flash(Path("python3"), target, cfg)
    assert not any("flash; reboot" in " ".join(command) for command in host)


def test_full_flash_requires_confirmation_when_non_interactive(tmp_path, monkeypatch, host):
    _usb(tmp_path, monkeypatch)
    monkeypatch.setenv("FLANGE_NO_INTERACTION", "1")
    cfg, target = _flash_config(tmp_path)
    strategy = _strategy(tmp_path, cfg, target)
    _board_info(monkeypatch, strategy)

    with pytest.raises(FlashError, match="--yes"):
        strategy.pre_flash_all(Path("python3"), target, cfg)


def test_full_flash_runs_flashcmd(tmp_path, monkeypatch, host):
    _usb(tmp_path, monkeypatch)
    cfg, target = _flash_config(tmp_path)
    strategy = _strategy(tmp_path, cfg, target, allow=True)
    _board_info(monkeypatch, strategy)
    strategy.pre_flash_all(Path("python3"), target, cfg)

    assert strategy.flash_whole_disk(Path("python3"), target, cfg) is True

    command = host[-1]
    assert command[:3] == ["python3", "tegraflash.py", "--bl"]
    assert command[-2:] == ["--cmd", "flash; reboot"]
    assert "--skipuid" not in command


@pytest.mark.parametrize("name, cmd", [
    ("APP", "write APP system.img; reboot"),
    ("kernel-dtb", "signwrite kernel-dtb kernel_tegra186-quill-p3310-1000-c03-00-base.dtb; reboot"),
])
def test_named_partition_write(tmp_path, monkeypatch, host, name, cmd):
    _usb(tmp_path, monkeypatch)
    cfg, target = _flash_config(tmp_path)
    part = next(item for item in cfg.partitions if item.name == name)
    strategy = _strategy(tmp_path, cfg, target, [part])
    _board_info(monkeypatch, strategy)
    strategy.pre_flash(Path("python3"), target, cfg)

    strategy.write_named_partition(Path("python3"), part, target / part.image, cfg)

    assert host[-1][-2:] == ["--cmd", cmd]


def test_offset_write_is_rejected():
    with pytest.raises(FlashError, match="按分区名"):
        TegraFlashStrategy().write_partition(Path("python3"), 0, Path("system.img"))


def test_raw_mode_points_to_named_flash(tmp_path):
    from builder.flash.execute import FlashExecutor

    cfg, target = _flash_config(tmp_path)
    cfg.to_json(target / "flash-config.json")

    with pytest.raises(FlashError, match="flange flash"):
        FlashExecutor(target).flash_raw("/dev/sdX", yes=True)
