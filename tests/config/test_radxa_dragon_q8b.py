"""Radxa Dragon Q8B / SC8280XP 配置与复用路径。"""

from unittest.mock import Mock
import zipfile

import pytest

from builder.config.query import get_valid_targets
from builder.config.registry import (
    _discover_platform_configs,
    _discover_soc_configs,
    _load_platform_config,
    _load_soc_config,
    resolve_config,
)
from builder.config.validate import validate_config
from builder.flash import QualcommFlashStrategy, get_flash_strategy
from builder.paths import PROJECT_ROOT
from builder.platforms.qualcommqcs6490 import boot as qcom_boot
from builder.platforms.qualcommqcs6490 import bootloader as qcom_bootloader
from builder.platforms.qualcommqcs6490.boot import Qcs6490BootBuilder
from builder.platforms.qualcommqcs6490.bootloader import Qcs6490BootloaderBuilder
from builder.platforms.qualcommqcs6490.kernel import Qcs6490KernelBuilder
from builder.platforms.qualcommsc8280xp import create_builder


class FakeDocker:
    def run(self, *args, **kwargs):
        return None


def test_platform_soc_and_board_resolve():
    platforms = _discover_platform_configs(PROJECT_ROOT)
    socs = _discover_soc_configs(PROJECT_ROOT)
    assert platforms["qualcommsc8280xp"].endswith(
        "components/platform/qualcommsc8280xp/config.py")
    assert socs["sc8280xp"].endswith(
        "components/platform/qualcommsc8280xp/sc8280xp/config.py")
    assert _load_platform_config("qualcommsc8280xp")["flash_tool"] == "edl-ng"
    assert _load_soc_config("sc8280xp")["platform"] == "qualcommsc8280xp"

    cfg = resolve_config("radxa-dragon-q8b", "default", "debug")
    validate_config(cfg)
    assert (cfg["board"], cfg["soc"], cfg["platform"]) == (
        "radxa-dragon-q8b", "sc8280xp", "qualcommsc8280xp")
    assert cfg["kernel"]["dtb"] == "sc8280xp-radxa-dragon-q8b"
    assert (cfg["product"], cfg["variant"]) == ("default", "debug")


def test_kernel_boot_and_ufs_inputs_are_pinned():
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")
    kernel_repo = cfg["repos"]["kernel"]
    assert kernel_repo == {
        "repo": "https://github.com/radxa/kernel.git",
        "branch": "linux-7.0.11",
        "commit": "4a7a039590c7185ed9c53453b163806311799eed",
        "recurse_submodules": False,
        "product": "default",
        "variant": "release",
    }
    assert cfg["kernel"]["defconfig"] == [
        "radxa_qcom_7_0_defconfig", "CONFIG_DRM_MSM=m"]
    assert {
        "SCSI_UFSHCD", "SCSI_UFSHCD_PLATFORM", "SCSI_UFS_QCOM",
        "PHY_QCOM_QMP", "INTERCONNECT_QCOM_SC8280XP",
    }.issubset(cfg["kernel"]["enable_configs"])
    assert cfg["bootloader"]["edk2_firmware_url"].endswith(
        "dragon-q8b_flat_build_wp_260731.zip")
    assert cfg["bootloader"]["edk2_firmware_sha256"] == (
        "f9bd55ac342bad53f056f620bdbf6e090ab1ef80c99cbf90ed685a64d7980fb8")
    assert cfg["partitions"]["sector_size"] == 4096
    assert [entry["name"] for entry in cfg["partitions"]["entries"]] == [
        "esp", "rootfs"]


def test_rootfs_firmware_and_ucm_inputs_are_complete():
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")
    packages = set(cfg["rootfs"]["packages"])
    assert {
        "bluez", "protection-domain-mapper", "qrtr-tools",
        "libgl1-mesa-dri", "mesa-vulkan-drivers", "linux-firmware",
    }.issubset(packages)

    firmware = cfg["rootfs"]["extra_firmware"][0]
    destinations = {
        entry if isinstance(entry, str) else entry["dest"]
        for entry in firmware["files"]
    }
    assert {
        "qcom/sc8280xp/qupv3fw.elf",
        "qcom/sc8280xp/radxa/dragon-q8b/qcadsp8280.mbn",
        "qcom/sc8280xp/LENOVO/21BX/qcdxkmsuc8280.mbn",
        "qcom/vpu/vpu20_p4_gen2_s6.mbn",
    }.issubset(destinations)
    assert len(firmware["commit"]) == 40
    deb = cfg["rootfs"]["extra_debs"][0]
    assert deb["name"] == "alsa-ucm-conf-radxa-q8b"
    assert len(deb["sha256"]) == 64


@pytest.mark.parametrize(
    "component",
    ["kernel", "bootloader", "rootfs", "boot", "recovery", "image"],
)
def test_platform_reuses_existing_qualcomm_builders(component):
    builder = create_builder(component, Mock(), Mock())
    assert builder.__class__.__module__.startswith(
        "builder.platforms.qualcommqcs6490.")


def test_kernel_builder_applies_inline_module_override(tmp_path):
    configs = tmp_path / "arch" / "arm64" / "configs"
    configs.mkdir(parents=True)
    builder = Qcs6490KernelBuilder(Mock(), Mock())
    calls = []
    builder._write_case_insensitive_fix = Mock()
    builder._apply_config_overrides = Mock()
    builder.make = lambda _src, targets, **_kwargs: calls.append(targets)

    builder.configure(tmp_path, {
        "kernel": {
            "defconfig": ["radxa_qcom_7_0_defconfig", "CONFIG_DRM_MSM=m"],
        },
    })

    assert calls[:2] == [
        ["radxa_qcom_7_0_defconfig"], ["flange_inline.config"]]
    assert "CONFIG_DRM_MSM=m" in (
        configs / "flange_inline.config").read_text()


def test_bootloader_download_is_sha256_verified(tmp_path, monkeypatch):
    work_dir = tmp_path / "edk2"
    archive = tmp_path / "q8b.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("flat_build/spinor/dragon-q8b/prog_firehose_ddr.elf", b"")
    source = Mock()
    source.ensure_prebuilt_image.return_value = archive
    monkeypatch.setattr(
        qcom_bootloader.tempfile, "mkdtemp", lambda prefix: str(work_dir))
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")

    Qcs6490BootloaderBuilder(FakeDocker(), source).compile(None, cfg)

    source.ensure_prebuilt_image.assert_called_once_with(
        "radxa-dragon-q8b-edk2",
        {
            "url": cfg["bootloader"]["edk2_firmware_url"],
            "sha256": cfg["bootloader"]["edk2_firmware_sha256"],
        },
    )


def test_grub_title_is_board_specific_and_q6a_is_unchanged(tmp_path, monkeypatch):
    titles = []
    for board in ("radxa-dragon-q8b", "radxa-dragon-q6a"):
        work_dir = tmp_path / board
        monkeypatch.setattr(
            qcom_boot.tempfile, "mkdtemp", lambda prefix, path=work_dir: str(path))
        cfg = resolve_config(board, "default", "release")
        builder = Qcs6490BootBuilder(FakeDocker(), None)
        builder.compile(None, cfg)
        grub_cfg = work_dir / "esp" / "EFI" / "BOOT" / "grub.cfg"
        titles.append(grub_cfg.read_text())

    assert 'menuentry "Radxa Dragon Q8B (Linux)"' in titles[0]
    assert "devicetree /boot/sc8280xp-radxa-dragon-q8b.dtb" in titles[0]
    assert 'menuentry "Radxa Dragon Q6A (Linux)"' in titles[1]
    assert len(resolve_config(
        "radxa-dragon-q6a", "default", "release")
        ["bootloader"]["edk2_firmware_sha256"]) == 64


def test_flash_route_and_lunch_targets():
    assert isinstance(
        get_flash_strategy("qualcommsc8280xp"), QualcommFlashStrategy)
    targets = set(get_valid_targets())
    assert {
        "radxa-dragon-q8b-default-debug",
        "radxa-dragon-q8b-default-release",
    }.issubset(targets)
