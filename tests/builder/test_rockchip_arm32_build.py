"""Rockchip ARM32、vendor FIT 与组件级工具链配置测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.base import ComponentBuilder
from builder.platforms.rockchip.boot import RockchipBootBuilder
from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder
from builder.platforms.rockchip.kernel import RockchipKernelBuilder


ARM32_DTS = "rk3506b-test-amp-linux"
ARM32_GCC10 = "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"


VENDOR_BOOT_ITS = """\
/dts-v1/;
/ {
    images {
        fdt {
            data = /incbin/("fdt");
            type = "flat_dt";
            arch = "";
        };
        kernel {
            data = /incbin/("kernel");
            type = "kernel";
            arch = "";
            os = "linux";
            compression = "";
        };
        resource {
            data = /incbin/("resource");
            type = "multi";
            arch = "";
        };
    };
    configurations {
        conf {
            fdt = "fdt";
            kernel = "kernel";
            multi = "resource";
        };
    };
};
"""


class RecordingKernelBuilder(RockchipKernelBuilder):
    """记录 make 参数，避免执行实际 kernel 编译。"""

    def __init__(self):
        super().__init__(docker=None, source=None)
        self.make_calls: list[tuple[list[str], dict]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append((list(targets), dict(kwargs)))


class RecordingBootloaderBuilder(RockchipBootloaderBuilder):
    """记录 U-Boot defconfig/fragment 的顺序与工具链。"""

    def __init__(self):
        super().__init__(docker=None, source=None)
        self.make_calls: list[tuple[list[str], dict]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append((list(targets), dict(kwargs)))


class FakeCache:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir


class ForbiddenDocker:
    """FIT pass-through 路径若调用 Docker 就立即失败。"""

    def run(self, cmd: list[str], **kwargs):
        raise AssertionError(f"FIT boot 不应调用 Docker: {cmd}")


class BootloaderPatchCounter(ComponentBuilder):
    component = "bootloader"

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        pass

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {}


def _arm32_config() -> dict:
    return {
        "platform": "rockchip",
        "soc": "rk3506b",
        "board": "atk-rk3506b",
        "kernel": {
            "arch": "arm",
            "cross_compile": ARM32_GCC10,
            "image": "zImage",
            "dts": ARM32_DTS,
            "dts_dir": "",
            "defconfig": [
                "rk3506_defconfig",
                "CONFIG_RPMSG_CHAR=y",
            ],
            "boot_format": "fit",
            "boot_its": "boot.its",
        },
        "boot": {
            "dtb_overlays": [],
            "vendor_overlays": [],
            "board_overlays": [],
            "package_overlays": [],
            "default_overlays": [],
        },
    }


def _arm64_config() -> dict:
    return {
        "platform": "rockchip",
        "soc": "rk3566",
        "board": "tspi-rk3566",
        "kernel": {
            "dts": "rk3566-test",
            "dts_dir": "rockchip",
            "defconfig": "rockchip_linux_defconfig",
        },
        "boot": {
            "dtb_overlays": [],
            "vendor_overlays": [],
            "board_overlays": [],
            "package_overlays": [],
            "default_overlays": [],
        },
    }


def test_kernel_arm32_context_and_inline_fragment_use_arm_path(tmp_path):
    src = tmp_path / "linux"
    (src / "arch" / "arm" / "configs").mkdir(parents=True)
    builder = RecordingKernelBuilder()

    builder.configure(src, _arm32_config())

    assert builder.ARCH == "arm"
    assert builder.CROSS == ARM32_GCC10
    inline = src / "arch" / "arm" / "configs" / "flange_inline.config"
    assert "CONFIG_RPMSG_CHAR=y" in inline.read_text()
    assert builder.make_calls[-1][0] == ["flange_inline.config"]
    assert all(call[1]["arch"] == "arm" for call in builder.make_calls)
    assert all(
        call[1]["cross"] == ARM32_GCC10
        for call in builder.make_calls
    )


def test_kernel_context_resets_to_arm64_defaults_between_targets():
    builder = RecordingKernelBuilder()

    builder._configure_build_context(_arm32_config())
    builder._configure_build_context(_arm64_config())

    assert builder.ARCH == "arm64"
    assert builder.CROSS == ComponentBuilder.CROSS
    assert RockchipKernelBuilder.ARCH == "arm64"
    assert RockchipKernelBuilder.CROSS == ComponentBuilder.CROSS


def test_kernel_arm32_fit_targets_and_collect_paths(tmp_path):
    builder = RecordingKernelBuilder()
    config = _arm32_config()

    builder.compile(tmp_path, config)
    targets, kwargs = builder.make_calls[0]

    # BSP %.img 规则内部已经构建 modules；并列传 modules 会让两个 make
    # 实例争用同一批 .o/.d 文件。
    assert targets == [f"{ARM32_DTS}.img"]
    assert kwargs["arch"] == "arm"
    assert kwargs["cross"] == ARM32_GCC10
    assert "BOOT_ITS=boot.its" in kwargs["extra"]
    outputs = builder.collect(tmp_path, config)
    assert outputs["image"] == tmp_path / "arch/arm/boot/zImage"
    assert outputs["dtb"] == tmp_path / f"arch/arm/boot/dts/{ARM32_DTS}.dtb"
    assert outputs["fit_boot"] == tmp_path / "boot.img"


def test_arm32_vendor_fit_structure_target_fdt_resource_and_ubi_bootargs():
    """锁定 vendor scripts/mkimg 的 ARM32 FIT 输入与目标 DTS 启动契约。"""
    config = _arm32_config()
    rendered = VENDOR_BOOT_ITS.replace('arch = ""', 'arch = "arm"')
    rendered = rendered.replace('compression = ""', 'compression = "none"')
    dts = (
        "/dts-v1/;\n/ { chosen { bootargs = \"console=ttyFIQ0 "
        "ubi.mtd=5 root=ubi0:rootfs rw rootfstype=ubifs rootwait\"; }; };\n"
    )

    assert config["kernel"]["arch"] == "arm"
    assert config["kernel"]["image"] == "zImage"
    assert config["kernel"]["dts"] == ARM32_DTS
    assert f"{ARM32_DTS}.img" == RockchipKernelBuilder._dts_target(
        config["kernel"]["dts_dir"], config["kernel"]["dts"], "img"
    )
    assert 'data = /incbin/("kernel")' in rendered
    assert 'type = "kernel"' in rendered
    assert 'arch = "arm"' in rendered
    assert 'compression = "none"' in rendered
    assert 'data = /incbin/("fdt")' in rendered
    assert 'fdt = "fdt"' in rendered
    assert 'data = /incbin/("resource")' in rendered
    assert 'multi = "resource"' in rendered
    assert "ubi.mtd=5" in dts
    assert "root=ubi0:rootfs" in dts
    assert "rootfstype=ubifs" in dts


def test_kernel_arm64_extlinux_defaults_remain_unchanged(tmp_path):
    builder = RecordingKernelBuilder()
    config = _arm64_config()

    builder.compile(tmp_path, config)
    targets, kwargs = builder.make_calls[0]

    assert targets == ["Image", "rockchip/rk3566-test.dtb", "modules"]
    assert kwargs["arch"] == "arm64"
    assert kwargs["cross"] == ComponentBuilder.CROSS
    assert all(not item.startswith("BOOT_ITS=") for item in kwargs["extra"])
    outputs = builder.collect(tmp_path, config)
    assert outputs["image"] == tmp_path / "arch/arm64/boot/Image"
    assert outputs["dtb"] == (
        tmp_path / "arch/arm64/boot/dts/rockchip/rk3566-test.dtb"
    )
    assert "fit_boot" not in outputs


def test_fit_boot_builder_reuses_kernel_fit_without_ext4(tmp_path):
    target_dir = tmp_path / "target"
    kernel_fit = target_dir / "kernel" / "boot.img"
    kernel_fit.parent.mkdir(parents=True)
    kernel_fit.write_bytes(b"FIT")
    builder = RockchipBootBuilder(docker=ForbiddenDocker(), source=None)
    builder.cache = FakeCache(target_dir)

    builder.compile(None, _arm32_config())

    assert builder.collect(None, _arm32_config()) == {"boot": kernel_fit}
    assert not hasattr(builder, "_work_dir")


def test_fit_boot_builder_requires_kernel_fit(tmp_path):
    builder = RockchipBootBuilder(docker=ForbiddenDocker(), source=None)
    builder.cache = FakeCache(tmp_path / "target")

    with pytest.raises(FileNotFoundError, match="FIT boot.img"):
        builder.compile(None, _arm32_config())


def test_bootloader_fragments_are_merged_sequentially_with_arm32_toolchain(
    tmp_path,
):
    builder = RecordingBootloaderBuilder()
    config = {
        "bootloader": {
            "arch": "arm",
            "cross_compile": ARM32_GCC10,
            "defconfig": [
                "alientek_rk3506_defconfig",
                "rk-amp.config",
            ],
        },
    }

    builder.configure(tmp_path, config)

    assert [call[0] for call in builder.make_calls] == [
        ["alientek_rk3506_defconfig"],
        ["rk-amp.config"],
    ]
    assert all(call[1]["arch"] == "arm" for call in builder.make_calls)
    assert all(
        call[1]["cross"] == ARM32_GCC10
        for call in builder.make_calls
    )


def test_atk_bootloader_patch_carries_official_board_config():
    counter = BootloaderPatchCounter(docker=None, source=None)
    config = {
        "platform": "rockchip",
        "board": "atk-rk3506b",
        "bootloader": {},
    }

    paths = counter._patch_paths(config)
    board_patch = next(
        path for path in paths
        if path.name == "0001-add-alientek-rk3506-board.patch"
    )
    text = board_patch.read_text()

    assert "configs/alientek_rk3506_defconfig" in text
    assert 'CONFIG_DEFAULT_DEVICE_TREE="alientek-rk3506"' in text
    assert "# CONFIG_SPL_AB is not set" in text
    assert "CONFIG_ROCKCHIP_HWID_DTB=y" in text
    assert "arch/arm/dts/alientek-rk3506.dts" in text


def test_atk_bootloader_patch_uses_rockchip_bootdev_for_vendor_fit():
    counter = BootloaderPatchCounter(docker=None, source=None)
    config = {
        "platform": "rockchip",
        "board": "atk-rk3506b",
        "bootloader": {},
    }

    paths = counter._patch_paths(config)
    bootdev_patch = next(
        path for path in paths
        if path.name == "0002-fix-vendor-fit-bootdev.patch"
    )
    text = bootdev_patch.read_text()

    assert "fit_image_load_bootables" in text
    assert "resource_scan" in text
    assert "vendor_storage_init" in text
    assert text.count("android_get_bootdev();") == 8
    assert text.count("rockchip_get_bootdev();") == 8


def test_vendor_fit_pack_uses_fixed_offset_and_redundant_slots(tmp_path):
    class MkimageDocker:
        def __init__(self):
            self.calls = []

        def run(self, cmd, **kwargs):
            self.calls.append((cmd, kwargs))
            Path(cmd[-1]).write_bytes(b"FIT")

    src = tmp_path / "u-boot"
    (src / "tools").mkdir(parents=True)
    (src / ".config").write_text(
        "CONFIG_SPL_FIT_IMAGE_KB=2\n"
        "CONFIG_SPL_FIT_IMAGE_MULTIPLE=2\n"
    )
    its = src / "u-boot.its"
    its.write_text("/dts-v1/;\n")
    docker = MkimageDocker()
    builder = RockchipBootloaderBuilder(docker=docker, source=None)

    builder._pack_vendor_fit(
        src,
        its,
        {
            "external_data_offset": "0x1200",
            "slot_size_kb": 2,
            "copies": 2,
        },
    )

    cmd = docker.calls[0][0]
    assert cmd[cmd.index("-p") + 1] == "0x1200"
    packed = (src / "u-boot.itb").read_bytes()
    assert len(packed) == 4 * 1024
    assert packed[:3] == b"FIT"
    assert packed[2 * 1024:2 * 1024 + 3] == b"FIT"


def test_vendor_fit_pack_rejects_kconfig_slot_drift(tmp_path):
    (tmp_path / ".config").write_text(
        "CONFIG_SPL_FIT_IMAGE_KB=2048\n"
    )

    with pytest.raises(ValueError, match="不一致"):
        RockchipBootloaderBuilder._fit_pack_value(
            tmp_path,
            {"slot_size_kb": 1024},
            "slot_size_kb",
            "CONFIG_SPL_FIT_IMAGE_KB",
        )


def test_extlinux_only_patch_can_be_excluded_by_config():
    counter = BootloaderPatchCounter(docker=None, source=None)
    config = {
        "platform": "rockchip",
        "board": "tspi-rk3566",
        "bootloader": {
            "exclude_patches": ["0004-skip-dtb-bootargs-merge.patch"],
        },
    }

    paths = counter._patch_paths(config)

    assert all(path.name != "0004-skip-dtb-bootargs-merge.patch" for path in paths)
    assert any(
        path.name == "0002-select-flange-recovery-extlinux-conf.patch"
        for path in paths
    )
    assert counter._count_patches(config) == len(paths)


def test_patch_exclusion_must_be_a_string_list():
    counter = BootloaderPatchCounter(docker=None, source=None)
    config = {
        "platform": "rockchip",
        "board": "tspi-rk3566",
        "bootloader": {"exclude_patches": "one.patch"},
    }

    with pytest.raises(TypeError, match="exclude_patches"):
        counter._patch_paths(config)


def test_patch_created_files_are_removed_without_cleaning_other_cache(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "u-boot"
    added = source / "arch/arm/dts/alientek-rk3506.dts"
    added.parent.mkdir(parents=True)
    added.write_text("old patch output")
    cached = source / "arch/arm/dts/rk3506.o"
    cached.write_bytes(b"incremental-cache")
    patch_file = tmp_path / "board.patch"
    patch_file.write_text(
        "diff --git a/arch/arm/dts/alientek-rk3506.dts "
        "b/arch/arm/dts/alientek-rk3506.dts\n"
        "--- /dev/null\n"
        "+++ b/arch/arm/dts/alientek-rk3506.dts\n"
    )
    counter = BootloaderPatchCounter(docker=None, source=None)
    monkeypatch.setattr(
        counter,
        "_all_patch_paths",
        lambda config: [patch_file],
    )

    counter._remove_patch_created_files(source, {})

    assert not added.exists()
    assert cached.read_bytes() == b"incremental-cache"


def test_excluded_patch_created_file_is_removed_on_route_switch(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "u-boot"
    added = source / "arch/arm/dts/route-only.dts"
    added.parent.mkdir(parents=True)
    added.write_text("previous route")
    patch_file = tmp_path / "route.patch"
    patch_file.write_text(
        "diff --git a/arch/arm/dts/route-only.dts "
        "b/arch/arm/dts/route-only.dts\n"
        "--- /dev/null\n"
        "+++ b/arch/arm/dts/route-only.dts\n"
    )
    counter = BootloaderPatchCounter(docker=None, source=None)
    monkeypatch.setattr(
        counter,
        "_all_patch_paths",
        lambda config: [patch_file],
    )
    monkeypatch.setattr(counter, "_patch_paths", lambda config: [])

    counter._remove_patch_created_files(source, {})

    assert not added.exists()
