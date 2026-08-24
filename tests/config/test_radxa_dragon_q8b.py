"""Radxa Dragon Q8B / SC8280XP 配置与复用路径。"""

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import Mock, call, patch

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
from builder.flash import (
    FlashConfig, FlashError, QualcommFlashStrategy, get_flash_strategy,
)
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


def test_kernel_tracks_radxa_branch_and_boot_inputs_are_pinned():
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")
    kernel_repo = cfg["repos"]["kernel"]
    assert kernel_repo == {
        "repo": "https://github.com/radxa/kernel.git",
        "branch": "linux-7.0.11",
        "recurse_submodules": False,
        "product": "default",
        "variant": "release",
    }
    assert cfg["kernel"]["defconfig"] == [
        "radxa_qcom_7_0_defconfig", "CONFIG_DRM_MSM=m"]
    assert {
        "SCSI_UFSHCD", "SCSI_UFSHCD_PLATFORM", "SCSI_UFS_QCOM",
        "PHY_QCOM_QMP", "INTERCONNECT_QCOM_SC8280XP",
        "DEBUG_INFO_NONE",
    }.issubset(cfg["kernel"]["enable_configs"])
    disabled = set(cfg["kernel"]["disable_configs"])
    assert {
        "DEBUG_INFO_DWARF5", "DRM_AMDGPU", "DRM_NOUVEAU",
        "NET_VENDOR_CHELSIO", "NET_VENDOR_I825XX", "NET_VENDOR_INTEL",
        "NET_VENDOR_MELLANOX", "NET_VENDOR_MUCSE",
    } == disabled
    assert {
        "DRM_MSM", "NET_VENDOR_STMICRO", "STMMAC_ETH", "DWMAC_TC956X",
        "TOSHIBA_TC956X_PCI", "QCA808X_PHY", "WLAN_VENDOR_ATH",
        "USB_USBNET",
    }.isdisjoint(disabled)
    assert cfg["bootloader"]["edk2_firmware_url"].endswith(
        "dragon-q8b_flat_build_wp_260731.zip")
    assert cfg["bootloader"]["edk2_firmware_sha256"] == (
        "f9bd55ac342bad53f056f620bdbf6e090ab1ef80c99cbf90ed685a64d7980fb8")
    assert cfg["bootloader"]["ufs_firehose"]["sha256"] == (
        "2922271fb6d0792d737fb757e7783513b2e7ca54eacb219e80e58ba233dcbaf2")
    provisions = cfg["bootloader"]["ufs_provisions"]
    assert provisions["lun0-only"]["sha256"] == (
        "54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8")
    assert provisions["qcom"]["sha256"] == (
        "2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e")
    assert cfg["partitions"]["sector_size"] == 4096
    assert [entry["name"] for entry in cfg["partitions"]["entries"]] == [
        "esp", "rootfs"]


def test_board_kernel_patch_sets_usb0_peripheral():
    patch_path = (
        PROJECT_ROOT / "components/board/radxa-dragon-q8b/patches/kernel/"
        "0001-dts-q8b-set-usb-roles.patch"
    )
    patch_text = patch_path.read_text()

    assert '&usb_0_dwc3 {' in patch_text
    assert '&usb_1_dwc3 {' not in patch_text
    assert patch_text.count('-\tdr_mode = "host";') == 1
    assert patch_text.count('+\tdr_mode = "peripheral";') == 1
    assert 'dr_mode = "otg"' not in patch_text
    assert "usb-role-switch" not in patch_text
    assert "toshiba,axi-bus-frequency-half" not in patch_text

    builder = Qcs6490KernelBuilder(Mock(), Mock())
    q8b_patches = builder._patch_paths(
        resolve_config("radxa-dragon-q8b", "default", "release"))
    q6a_patches = builder._patch_paths(
        resolve_config("radxa-dragon-q6a", "default", "release"))
    assert patch_path in q8b_patches
    assert patch_path not in q6a_patches

    q8b_dwc3_patch = (
        PROJECT_ROOT / "components/platform/qualcommsc8280xp/patches/kernel/"
        "0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch"
    )
    q6a_dwc3_patch = (
        PROJECT_ROOT / "components/platform/qualcommqcs6490/patches/kernel/"
        "0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch"
    )
    assert q8b_dwc3_patch in q8b_patches
    assert q8b_dwc3_patch.read_bytes() == q6a_dwc3_patch.read_bytes()

    tc956x_patch = (
        PROJECT_ROOT / "components/platform/qualcommsc8280xp/patches/kernel/"
        "0002-net-tc956x-zero-init-irq-domain-info.patch"
    )
    tc956x_text = tc956x_patch.read_text()
    assert tc956x_patch in q8b_patches
    assert "+\tstruct irq_domain_chip_generic_info dgc_info = { };" in tc956x_text
    assert "+\tstruct irq_domain_info info = { };" in tc956x_text
    assert "toshiba,axi-bus-frequency-half" not in tc956x_text


def test_rootfs_firmware_and_ucm_inputs_are_complete():
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")
    packages = set(cfg["rootfs"]["packages"])
    assert {
        "bluez", "protection-domain-mapper", "qrtr-tools",
        "libgl1-mesa-dri", "mesa-vulkan-drivers", "linux-firmware",
        "acl", "libbsd0", "libyaml-0-2", "udev",
    }.issubset(packages)
    assert "fastrpc" in cfg["rootfs"]["groups"]

    firmware_by_name = {
        item["name"]: item for item in cfg["rootfs"]["extra_firmware"]
    }
    firmware = firmware_by_name["radxa-firmware-sc8280xp"]
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
    assert "firmware-qcom-audioreach" in cfg["rootfs"]["custom_packages"]
    topology_package = (
        PROJECT_ROOT / "components/packages/firmware-qcom-audioreach"
    )
    assert cfg["external_apps"]["firmware-qcom-audioreach"] == {
        "local_path": str(topology_package)
    }
    topology_path = (
        topology_package / "firmware/qcom/sc8280xp/"
        "SC8280XP-Radxa-Dragon-Q8B-tplg.bin"
    )
    assert topology_path.stat().st_size == 28660
    assert hashlib.sha256(topology_path.read_bytes()).hexdigest() == (
        "737787a3b6a52ff9b66e1f5208e98c6491180130ffbff4a770"
        "c40cca34f63ee6")
    debs = {
        deb["name"]: deb for deb in cfg["rootfs"]["extra_debs"]
    }
    assert len(debs["alsa-ucm-conf-radxa-q8b"]["sha256"]) == 64

    fastrpc_package = (
        PROJECT_ROOT / "components/packages/radxa-q8b-fastrpc"
    )
    runtime_packages = {
        "libadsprpc1",
        "libadsp-default-listener1",
        "libcdsprpc1",
        "libcdsp-default-listener1",
        "fastrpc",
    }
    assert runtime_packages.issubset(cfg["rootfs"]["custom_packages"])
    assert "fastrpc-test" not in cfg["rootfs"]["custom_packages"]
    for name in runtime_packages:
        assert cfg["external_apps"][name] == {
            "local_path": str(fastrpc_package / name)
        }
    firmware_package = (
        PROJECT_ROOT / "components/packages/radxa-firmware-sc8280xp"
    )
    assert "radxa-firmware-sc8280xp" in cfg["rootfs"]["custom_packages"]
    assert cfg["external_apps"]["radxa-firmware-sc8280xp"] == {
        "local_path": str(firmware_package)
    }
    libcdsprpc = fastrpc_package / "libcdsprpc1/rootfs"
    assert hashlib.sha256(
        (libcdsprpc / "usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0")
        .read_bytes()
    ).hexdigest() == (
        "4a2eb1b30f90cbb8abc5d7c09d2e9131dec46538a63017619524596fe873960d"
    )
    dsp_runtime = firmware_package / "rootfs"
    assert hashlib.sha256(
        (dsp_runtime / "usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp/"
         "cdsp/fastrpc_shell_3").read_bytes()
    ).hexdigest() == (
        "5f8844f7d13d72e07a9d224366c834b2bfa9e2283dfe922ce2b83fd945e60ee6"
    )
    assert (dsp_runtime / "usr/lib/dsp").readlink() == Path(
        "/usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp")


def test_q8b_debug_includes_fastrpc_v68_test_only():
    debug = resolve_config("radxa-dragon-q8b", "default", "debug")
    release = resolve_config("radxa-dragon-q8b", "default", "release")

    assert "fastrpc-test" in debug["rootfs"]["custom_packages"]
    assert "fastrpc-test" not in release["rootfs"]["custom_packages"]
    test_package = (
        PROJECT_ROOT / "components/packages/radxa-q8b-fastrpc/fastrpc-test"
    )
    assert debug["external_apps"]["fastrpc-test"] == {
        "local_path": str(test_package)
    }
    test_binary = test_package / "rootfs/usr/bin/fastrpc_test"
    assert hashlib.sha256(test_binary.read_bytes()).hexdigest() == (
        "aa083f32accbed1962264a04ffd9b80cca14e1efee689843de8a05fd71e7ecd3"
    )


def test_q6a_ufs_provision_inputs_are_pinned():
    cfg = resolve_config("radxa-dragon-q6a", "default", "release")
    bootloader = cfg["bootloader"]
    assert "/Kodiak/" in bootloader["ufs_firehose"]["url"]
    assert bootloader["ufs_firehose"]["sha256"] == (
        "bd726ad721639767260a39bfbdce0323a0ea4976f24601c30f3c4f547d26719b")
    assert bootloader["ufs_provisions"]["lun0-only"]["sha256"] == (
        "54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8")
    assert bootloader["ufs_provisions"]["qcom"]["sha256"] == (
        "2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e")


@pytest.mark.parametrize(
    "component",
    ["kernel", "bootloader", "rootfs", "boot", "recovery", "image"],
)
def test_platform_reuses_existing_qualcomm_builders(component):
    builder = create_builder(component, Mock(), Mock())
    assert builder.__class__.__module__.startswith(
        "builder.platforms.qualcommqcs6490.")


def test_kernel_reset_does_not_clean_entire_source_tree(tmp_path):
    docker = Mock()
    Qcs6490KernelBuilder(docker, Mock()).reset_source(tmp_path)

    docker.run.assert_called_once_with(
        ["git", "checkout", "-f", "."], cwd=str(tmp_path), check=False)


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


def test_kernel_build_uses_persistent_ccache(tmp_path):
    builder = Qcs6490KernelBuilder(Mock(), Mock())
    builder.make = Mock()
    builder._compile_oot_modules = Mock()
    builder._clean_modules_staging = Mock()
    builder._install_oot_modules = Mock()

    builder.compile(tmp_path, {
        "jobs": 2,
        "kernel": {"dts_dir": "qcom", "dtb": "q8b"},
    })

    compile_extra = builder.make.call_args_list[0].kwargs["extra"]
    assert f"CC=ccache {builder.CROSS}gcc" in compile_extra
    assert "HOSTCC=ccache gcc" in compile_extra
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "CCACHE_DIR: /workspace/.build/cache/ccache" in compose


def test_bootloader_download_is_sha256_verified(tmp_path, monkeypatch):
    work_dir = tmp_path / "edk2"
    archive = tmp_path / "q8b.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("flat_build/spinor/dragon-q8b/prog_firehose_ddr.elf", b"")
    ufs_loader = tmp_path / "prog_firehose_ufs.elf"
    ufs_loader.write_bytes(b"ufs-loader")
    ufs_provision = tmp_path / "provision_ufs31_lun0_only.xml"
    ufs_provision.write_text("<data />")
    qcom_provision = tmp_path / "provision_ufs31.xml"
    qcom_provision.write_text("<data />")
    source = Mock()
    source.ensure_prebuilt_image.side_effect = [
        archive, ufs_loader, ufs_provision, qcom_provision]
    monkeypatch.setattr(
        qcom_bootloader.tempfile, "mkdtemp", lambda prefix: str(work_dir))
    cfg = resolve_config("radxa-dragon-q8b", "default", "release")

    builder = Qcs6490BootloaderBuilder(FakeDocker(), source)
    builder.compile(None, cfg)
    output = builder.collect(None, cfg)["edk2"]

    assert source.ensure_prebuilt_image.call_args_list == [
        call("radxa-dragon-q8b-edk2", {
            "url": cfg["bootloader"]["edk2_firmware_url"],
            "sha256": cfg["bootloader"]["edk2_firmware_sha256"],
        }),
        call("radxa-dragon-q8b-ufs-firehose",
             cfg["bootloader"]["ufs_firehose"]),
        call("radxa-dragon-q8b-ufs-provision-lun0-only",
             cfg["bootloader"]["ufs_provisions"]["lun0-only"]),
        call("radxa-dragon-q8b-ufs-provision-qcom",
             cfg["bootloader"]["ufs_provisions"]["qcom"]),
    ]
    assert (output / "prog_firehose_ufs.elf").read_bytes() == b"ufs-loader"
    assert (output / "provision_ufs31_lun0_only.xml").is_file()
    assert (output / "provision_ufs31.xml").is_file()


@pytest.mark.parametrize(("profile", "filename"), [
    ("lun0-only", "provision_ufs31_lun0_only.xml"),
    ("qcom", "provision_ufs31.xml"),
])
def test_ufs_provision_uses_selected_profile(tmp_path, profile, filename):
    firmware = tmp_path / "bootloader" / "edk2-spi-firmware"
    firmware.mkdir(parents=True)
    loader = firmware / "prog_firehose_ufs.elf"
    provision = firmware / filename
    loader.write_bytes(b"loader")
    provision.write_text("<data />")

    with patch("builder.flash.subprocess.run",
               return_value=Mock(returncode=0)) as run:
        QualcommFlashStrategy().provision_ufs(
            Path("edl-ng"), tmp_path, profile=profile)

    run.assert_called_once_with([
        "edl-ng", "--loader", str(loader), "--memory", "UFS",
        "provision", str(provision),
    ])


@pytest.mark.parametrize(("platform", "board"), [
    ("qualcommqcs6490", "radxa-dragon-q6a"),
    ("qualcommsc8280xp", "radxa-dragon-q8b"),
])
def test_qualcomm_system_flash_requires_dedicated_ufs_loader(
        tmp_path, platform, board):
    raw = tmp_path / "image" / "raw.img"
    raw.parent.mkdir()
    raw.write_bytes(b"image")
    firmware = tmp_path / "bootloader" / "edk2-spi-firmware"
    firmware.mkdir(parents=True)
    (firmware / "prog_firehose_ddr.elf").write_bytes(b"spi-loader")
    config = FlashConfig(
        platform=platform, flash_tool="edl-ng", board=board,
        product="default", variant="debug")

    with pytest.raises(FlashError, match="UFS firehose loader"):
        QualcommFlashStrategy().flash_whole_disk(
            Path("edl-ng"), tmp_path, config)


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
