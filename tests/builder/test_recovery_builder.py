"""recovery 镜像构建器测试。

不实际跑 Docker / mke2fs。覆盖：
- recovery-config.json 渲染逻辑
- 自定义包并集 helper
- 平台 builder 工厂注册
- 关键路径与文件系统 label 常量
"""

from __future__ import annotations

import json

import pytest

from builder.config.apps import gather_custom_packages
from builder.platforms.rockchip import (
    ARTIFACT_NAMES as ROCKCHIP_ARTIFACT_NAMES,
    create_builder as rockchip_create,
)
from builder.platforms.allwinnera733 import (
    ARTIFACT_NAMES as A733_ARTIFACT_NAMES,
    create_builder as a733_create,
)
from builder.platforms.rockchip.recovery import RockchipRecoveryBuilder
from builder.platforms.allwinnera733.recovery import AllwinnerA733RecoveryBuilder
from builder.recovery import (
    FS_LABEL,
    RECOVERY_CONFIG_PATH,
    RecoveryBuilder,
    build_recovery_config,
)


# ── 自定义包并集 ─────────────────────────────────────────────────


class TestGatherCustomPackages:
    def test_recovery_disabled_returns_only_rootfs(self):
        cfg = {
            "rootfs": {"custom_packages": ["adbd"]},
            "recovery": {"enabled": False, "custom_packages": ["recoveryctl"]},
        }
        assert gather_custom_packages(cfg) == ["adbd"]

    def test_recovery_disabled_default(self):
        cfg = {"rootfs": {"custom_packages": ["adbd"]}}
        assert gather_custom_packages(cfg) == ["adbd"]

    def test_union_when_recovery_enabled(self):
        cfg = {
            "rootfs": {"custom_packages": ["adbd"]},
            "recovery": {"enabled": True, "custom_packages": ["adbd", "recoveryctl"]},
        }
        # adbd 不重复，结果有序
        assert gather_custom_packages(cfg) == ["adbd", "recoveryctl"]

    def test_recovery_only_packages(self):
        cfg = {
            "rootfs": {"custom_packages": []},
            "recovery": {"enabled": True, "custom_packages": ["recoveryctl"]},
        }
        assert gather_custom_packages(cfg) == ["recoveryctl"]

    def test_empty_config(self):
        assert gather_custom_packages({}) == []


# ── recovery-config.json 渲染 ───────────────────────────────────


class TestBuildRecoveryConfig:
    def _base_cfg(self) -> dict:
        return {
            "board": "tspi-rk3566",
            "product": "default",
            "variant": "release",
            "recovery": {
                "enabled": True,
                "transport": "adb",
                "protected_partitions": ["recovery"],
            },
            "partitions": {
                "format": "gpt",
                "entries": [
                    {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
                    {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
                    {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                    {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
                    {"name": "recovery", "offset": "0x240000", "size": "0x100000", "type": "ext4"},
                    {"name": "userdata", "offset": "0x340000", "size": "remaining", "type": "ext4"},
                ],
            },
        }

    def test_top_level_fields(self):
        data = build_recovery_config(self._base_cfg())
        assert data["version"] == 1
        assert data["board"] == "tspi-rk3566"
        assert data["product"] == "default"
        assert data["variant"] == "release"
        assert data["transport"] == "adb"
        assert isinstance(data["partitions"], list)

    def test_partitions_preserve_offset_size_type(self):
        data = build_recovery_config(self._base_cfg())
        rootfs = next(p for p in data["partitions"] if p["name"] == "rootfs")
        assert rootfs["offset"] == "0x40000"
        assert rootfs["size"] == "0x200000"
        assert rootfs["type"] == "ext4"

    def test_raw_partitions_marked_protected(self):
        data = build_recovery_config(self._base_cfg())
        idb = next(p for p in data["partitions"] if p["name"] == "idbloader")
        uboot = next(p for p in data["partitions"] if p["name"] == "uboot")
        assert idb["protected"] is True
        assert uboot["protected"] is True

    def test_recovery_self_protected(self):
        data = build_recovery_config(self._base_cfg())
        rec = next(p for p in data["partitions"] if p["name"] == "recovery")
        assert rec["protected"] is True

    def test_rootfs_default_not_protected(self):
        data = build_recovery_config(self._base_cfg())
        rootfs = next(p for p in data["partitions"] if p["name"] == "rootfs")
        assert rootfs["protected"] is False

    def test_protected_partitions_list_extends(self):
        cfg = self._base_cfg()
        cfg["recovery"]["protected_partitions"] = ["recovery", "boot"]
        data = build_recovery_config(cfg)
        boot = next(p for p in data["partitions"] if p["name"] == "boot")
        assert boot["protected"] is True

    def test_default_transport_adb(self):
        cfg = self._base_cfg()
        del cfg["recovery"]["transport"]
        data = build_recovery_config(cfg)
        assert data["transport"] == "adb"

    def test_json_round_trip(self):
        """渲染结果必须可序列化为 JSON 并往返成功。"""
        data = build_recovery_config(self._base_cfg())
        text = json.dumps(data, ensure_ascii=False)
        assert json.loads(text) == data


# ── 平台工厂与 ARTIFACT_NAMES 注册 ──────────────────────────────


class TestPlatformIntegration:
    def test_rockchip_factory_returns_recovery_builder(self):
        builder = rockchip_create("recovery", docker=None, source=None)
        assert isinstance(builder, RockchipRecoveryBuilder)
        assert isinstance(builder, RecoveryBuilder)

    def test_a733_factory_returns_recovery_builder(self):
        builder = a733_create("recovery", docker=None, source=None)
        assert isinstance(builder, AllwinnerA733RecoveryBuilder)
        assert isinstance(builder, RecoveryBuilder)

    def test_rockchip_artifact_name(self):
        assert ROCKCHIP_ARTIFACT_NAMES[("recovery", "recovery")] == "recovery.img"

    def test_a733_artifact_name(self):
        assert A733_ARTIFACT_NAMES[("recovery", "recovery")] == "recovery.img"


# ── recovery 镜像约定常量 ────────────────────────────────────────


class TestRecoveryConstants:
    def test_fs_label_is_recovery(self):
        assert FS_LABEL == "recovery"
        assert RecoveryBuilder.fs_label == "recovery"

    def test_recovery_config_path(self):
        assert RECOVERY_CONFIG_PATH == "etc/flange/recovery-config.json"
        assert RecoveryBuilder.config_rel_path == "etc/flange/recovery-config.json"

    def test_component_name(self):
        assert RecoveryBuilder.component == "recovery"


# ── 分区大小读取 ──────────────────────────────────────────────


class TestPartitionSize:
    def test_recovery_size_512mb(self):
        builder = RockchipRecoveryBuilder(docker=None, source=None)
        cfg = {
            "partitions": {"entries": [
                {"name": "recovery", "offset": "0x240000", "size": "0x100000", "type": "ext4"},
            ]},
        }
        assert builder._partition_size_mb(cfg, "recovery") == 512

    def test_unknown_partition_raises(self):
        builder = RockchipRecoveryBuilder(docker=None, source=None)
        with pytest.raises(KeyError, match="recovery"):
            builder._partition_size_mb({"partitions": {"entries": []}}, "recovery")
