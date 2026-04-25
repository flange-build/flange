"""builder.config.validate 测试套件。"""

import pytest

from builder.config.validate import (
    ConfigError,
    validate_config,
    validate_recovery_partition,
)


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
