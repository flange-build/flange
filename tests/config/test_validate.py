"""builder.config.validate 测试套件。"""

import pytest

from builder.config.validate import (
    ConfigError,
    validate_amp,
    validate_build_routes,
    validate_config,
    validate_flash_identity,
    validate_mtd_ubi,
    validate_recovery_partition,
    validate_rootfs_auto_grow,
)
from builder.config.registry import resolve_config


# ── recovery 分区存在性 ─────────────────────────────────────────────


class TestValidateRecoveryPartition:
    """recovery.enabled=True 时强制 partitions.entries 中存在合规 recovery 分区。"""

    def _cfg_with_partitions(self, partitions: list, *, enabled: bool = True) -> dict:
        return {
            "recovery": {"enabled": enabled},
            "partitions": {"format": "gpt", "entries": partitions},
        }

    def test_disabled_skips_partition_check(self):
        # enabled=False 不强制分区表；调用应静默通过
        cfg = self._cfg_with_partitions([], enabled=False)
        validate_recovery_partition(cfg)  # no raise

    def test_enabled_with_recovery_partition_passes(self):
        cfg = self._cfg_with_partitions([
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "recovery", "offset": "0x240000", "size": "0x100000", "type": "ext4"},
        ])
        validate_recovery_partition(cfg)  # no raise

    def test_enabled_without_recovery_partition_raises(self):
        cfg = self._cfg_with_partitions([
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
        ])
        with pytest.raises(ConfigError, match="recovery 分区"):
            validate_recovery_partition(cfg)

    def test_enabled_recovery_wrong_type_raises(self):
        cfg = self._cfg_with_partitions([
            {"name": "recovery", "offset": "0x240000", "size": "0x100000", "type": "raw"},
        ])
        with pytest.raises(ConfigError, match="ext4"):
            validate_recovery_partition(cfg)

    def test_enabled_recovery_missing_offset_raises(self):
        cfg = self._cfg_with_partitions([
            {"name": "recovery", "offset": "", "size": "0x100000", "type": "ext4"},
        ])
        with pytest.raises(ConfigError, match="offset"):
            validate_recovery_partition(cfg)

    def test_enabled_recovery_missing_size_raises(self):
        cfg = self._cfg_with_partitions([
            {"name": "recovery", "offset": "0x240000", "size": "", "type": "ext4"},
        ])
        with pytest.raises(ConfigError, match="size"):
            validate_recovery_partition(cfg)


# ── validate_config 总入口 ─────────────────────────────────────────


class TestValidateConfig:
    def test_recovery_enabled_without_partition_blocks_loading(self):
        cfg = {
            "recovery": {"enabled": True},
            "partitions": {"format": "gpt", "entries": [
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            ]},
        }
        with pytest.raises(ConfigError):
            validate_config(cfg)

    def test_minimal_disabled_config_passes(self):
        validate_config({"recovery": {"enabled": False}})  # no raise
        validate_config({})  # no raise (recovery 缺省即关闭)

    @pytest.mark.parametrize("product", ["default", "amp", "amp-rtt"])
    def test_orangepi_cm4_products_pass_validation(self, product):
        cfg = resolve_config("orangepi-cm4", product=product, variant="release")
        validate_config(cfg)  # no raise

    @pytest.mark.parametrize("product", ["amp", "amp-rtt"])
    def test_orangepi_cm4_amp_partition_before_remaining_rootfs(self, product):
        cfg = resolve_config("orangepi-cm4", product=product, variant="release")
        names = [entry["name"] for entry in cfg["partitions"]["entries"]]

        assert names.index("amp") < names.index("rootfs")
        assert cfg["partitions"]["entries"][names.index("amp")]["type"] != "raw"


# ── rootfs 首次启动扩容布局校验 ───────────────────────────────────


class TestValidateRootfsAutoGrow:
    def _cfg(self, entries: list[dict]) -> dict:
        return {"partitions": {"format": "gpt", "entries": entries}}

    def test_remaining_rootfs_last_non_raw_passes(self):
        cfg = self._cfg([
            {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "remaining", "type": "ext4",
             "image_size": "2G", "grow_on_first_boot": True},
        ])
        validate_rootfs_auto_grow(cfg)  # no raise

    def test_data_partition_after_growing_rootfs_raises(self):
        cfg = self._cfg([
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "remaining", "type": "ext4",
             "image_size": "2G", "grow_on_first_boot": True},
            {"name": "data", "offset": "0x440000", "size": "remaining", "type": "ext4"},
        ])
        with pytest.raises(ConfigError, match="最后一个非 raw 分区"):
            validate_rootfs_auto_grow(cfg)

    def test_fixed_partition_smaller_than_image_size_raises(self):
        cfg = self._cfg([
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4",
             "image_size": "2G", "grow_on_first_boot": True},
        ])
        with pytest.raises(ConfigError, match="不得大于"):
            validate_rootfs_auto_grow(cfg)

    def test_missing_image_size_raises(self):
        cfg = self._cfg([
            {"name": "rootfs", "offset": "0x40000", "size": "remaining", "type": "ext4",
             "grow_on_first_boot": True},
        ])
        with pytest.raises(ConfigError, match="image_size"):
            validate_rootfs_auto_grow(cfg)


# ── ARM32/FIT 与 MTD/UBI 路由 ─────────────────────────────────────


def _write_mtd_parameter(tmp_path, *, rootfs_name="rootfs", amp_after=False):
    parts = [
        "0x1000@0x0000(security)",
        "0x2000@0x1000(uboot)",
        "0x1000@0x3000(misc)",
        "0x10000@0x4000(boot)",
    ]
    if amp_after:
        parts.extend([
            "0x2000@0x14000(rootfs-placeholder)",
            f"-@0x16000({rootfs_name})",
        ])
        # 追加 amp 会违反 remaining 必须最后，改用固定 rootfs 模拟错误顺序。
        parts[-1] = f"0xe0000@0x16000({rootfs_name})"
        parts.append("0x1000@0xf6000(amp)")
    else:
        parts.extend([
            "0x2000@0x14000(amp)",
            f"-@0x16000({rootfs_name})",
        ])
    path = tmp_path / "parameter.txt"
    path.write_text(
        "TYPE: MTD\n"
        "CMDLINE:mtdparts=rk29xxnand:" + ",".join(parts) + "\n"
    )
    return path


def _valid_mtd_config(tmp_path) -> dict:
    return {
        "platform": "rockchip",
        "arch": "armhf",
        "kernel": {
            "arch": "arm",
            "cross_compile": "arm-linux-gnueabihf-",
            "image": "zImage",
            "dts_dir": "",
            "boot_format": "fit",
            "boot_its": "boot.its",
        },
        "bootloader": {"cross_compile": "arm-linux-gnueabihf-"},
        "recovery": {"enabled": False},
        "storage": {"type": "spinand", "size": "512M"},
        "partitions": {
            "format": "mtd",
            "parameter": str(_write_mtd_parameter(tmp_path)),
        },
        "rootfs": {
            "image_format": "ubi",
            "ubi": {
                "min_io_size": 2048,
                "peb_size": 131072,
                "subpage_size": 2048,
                "vid_hdr_offset": 2048,
                "leb_size": 126976,
                "max_leb_count": 3500,
                "volume_size": "400M",
                "reserved_pebs": 20,
                "mtd_index": 5,
            },
        },
        "amp": {
            "enabled": True,
            "mode": "rt-thread",
            "soc_project": "rk3506",
            "max_image_size": "1M",
            "memory": {
                "cpu": 2,
                "cpu_base": 0x03E00000,
                "dram_size": 0x00100000,
                "sram_base": 0xFFF80000,
                "sram_size": 0x0000C000,
                "shmem_base": 0x03B00000,
                "shmem_size": 0x00100000,
                "rpmsg_base": 0x03C00000,
                "rpmsg_size": 0x00200000,
            },
        },
    }


class TestBuildRouteValidation:
    def test_arm32_fit_ubi_contract_passes(self, tmp_path):
        validate_config(_valid_mtd_config(tmp_path))

    @pytest.mark.parametrize(
        "field,value,match",
        [
            ("arch", "riscv", "kernel.arch"),
            ("boot_format", "android", "boot_format"),
        ],
    )
    def test_invalid_kernel_route_rejected(self, tmp_path, field, value, match):
        cfg = _valid_mtd_config(tmp_path)
        cfg["kernel"][field] = value
        with pytest.raises(ConfigError, match=match):
            validate_build_routes(cfg)

    def test_flash_identity_patterns_must_be_string_lists(self):
        with pytest.raises(ConfigError, match="chip_patterns"):
            validate_flash_identity({
                "flash_identity": {"chip_patterns": "rk3506"},
            })

    def test_fit_requires_boot_its(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        del cfg["kernel"]["boot_its"]
        with pytest.raises(ConfigError, match="boot_its"):
            validate_build_routes(cfg)

    def test_exclude_patches_must_be_string_list(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["kernel"]["exclude_patches"] = "one.patch"

        with pytest.raises(ConfigError, match="exclude_patches"):
            validate_build_routes(cfg)

    def test_rockchip_mtd_requires_ubi_rootfs(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["rootfs"]["image_format"] = "ext4"
        with pytest.raises(ConfigError, match="image_format=ubi"):
            validate_config(cfg)


class TestMtdUbiValidation:
    def test_missing_geometry_lists_field(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        del cfg["rootfs"]["ubi"]["peb_size"]
        with pytest.raises(ConfigError, match="peb_size"):
            validate_mtd_ubi(cfg)

    def test_rootfs_mtd_index_must_match_parameter(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["rootfs"]["ubi"]["mtd_index"] = 4
        with pytest.raises(ConfigError, match="期望 'rootfs'"):
            validate_mtd_ubi(cfg)

    def test_parameter_must_fit_512_mib_storage(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["storage"]["size"] = "32M"
        with pytest.raises(ConfigError, match="超出存储容量"):
            validate_mtd_ubi(cfg)

    def test_ubi_bad_block_margin_must_fit_partition(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["rootfs"]["ubi"]["reserved_pebs"] = 1000
        with pytest.raises(ConfigError, match="坏块余量"):
            validate_mtd_ubi(cfg)

    def test_space_fixup_must_be_boolean(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["rootfs"]["ubi"]["space_fixup"] = "true"
        with pytest.raises(ConfigError, match="space_fixup"):
            validate_mtd_ubi(cfg)

    def test_non_rockchip_ubi_does_not_require_spinand_or_parameter(self):
        cfg = {
            "platform": "allwinnera733",
            "storage": {"type": "spinor"},
            "rootfs": {
                "image_format": "ubi",
                "ubi": {
                    "min_io_size": 2048,
                    "peb_size": 131072,
                    "subpage_size": 2048,
                    "vid_hdr_offset": 2048,
                    "leb_size": 126976,
                    "max_leb_count": 128,
                    "volume_size": "8M",
                    "reserved_pebs": 4,
                },
            },
        }

        validate_config(cfg)


class TestMtdAmpValidation:
    def test_named_raw_amp_partition_is_accepted(self, tmp_path):
        validate_amp(_valid_mtd_config(tmp_path))

    def test_amp_may_follow_fixed_rootfs(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["partitions"]["parameter"] = str(
            _write_mtd_parameter(tmp_path, amp_after=True))
        validate_amp(cfg)

    def test_amp_capacity_gate_rejects_oversized_image(self, tmp_path):
        cfg = _valid_mtd_config(tmp_path)
        cfg["amp"]["max_image_size"] = "8M"
        with pytest.raises(ConfigError, match="超过 MTD amp 分区"):
            validate_amp(cfg)


def test_gpt_amp_must_precede_fixed_rootfs():
    cfg = {
        "platform": "rockchip",
        "partitions": {
            "format": "gpt",
            "entries": [
                {"name": "rootfs", "offset": "0x1000", "size": "64M",
                 "type": "ext4"},
                {"name": "amp", "offset": "0x21000", "size": "16M",
                 "type": "ext4"},
            ],
        },
        "amp": {
            "enabled": True,
            "mode": "rt-thread",
            "soc_project": "rk3506",
            "memory": {
                "cpu": 2,
                "cpu_base": 0x03E00000,
                "dram_size": 0x00100000,
                "sram_base": 0xFFF80000,
                "sram_size": 0x0000C000,
                "shmem_base": 0x03B00000,
                "shmem_size": 0x00100000,
                "rpmsg_base": 0x03C00000,
                "rpmsg_size": 0x00200000,
            },
        },
    }

    with pytest.raises(ConfigError, match="必须排在 rootfs 之前"):
        validate_amp(cfg)
