"""recoveryctl 设备端 CLI 单元测试（§6.10）。

通过 importlib 把脚本作为模块加载，独立验证各纯函数。文件 IO 与
subprocess 调用通过依赖注入参数替换，无需真实块设备。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


# ── 模块加载 ─────────────────────────────────────────────────────


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "components" / "app" / "recoveryctl" / "bin" / "recoveryctl"
)


def _load_recoveryctl() -> types.ModuleType:
    # 文件无 .py 后缀，需显式提供 SourceFileLoader
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("recoveryctl_script", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("recoveryctl_script", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("recoveryctl_script", mod)
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rc():
    return _load_recoveryctl()


# ── mode 检测（§6.2） ───────────────────────────────────────────


class TestParseMode:
    def test_normal_when_no_marker(self, rc):
        assert rc.parse_mode_from_cmdline("root=LABEL=rootfs ro quiet") == rc.MODE_NORMAL

    def test_recovery_when_marker_present(self, rc):
        assert rc.parse_mode_from_cmdline(
            "root=LABEL=recovery flange.mode=recovery ro"
        ) == rc.MODE_RECOVERY

    def test_unknown_value_falls_back_to_normal(self, rc):
        assert rc.parse_mode_from_cmdline("flange.mode=garbage") == rc.MODE_NORMAL

    def test_detect_mode_missing_proc_returns_normal(self, rc, tmp_path):
        missing = tmp_path / "nope"
        assert rc.detect_mode(missing) == rc.MODE_NORMAL

    def test_detect_mode_recovery(self, rc, tmp_path):
        f = tmp_path / "cmdline"
        f.write_text("flange.mode=recovery root=LABEL=recovery\n")
        assert rc.detect_mode(f) == rc.MODE_RECOVERY


# ── 配置加载与分区查询（§6.3 / 错误信息） ──────────────────────


def _sample_config() -> dict:
    return {
        "version": 1,
        "board": "tspi-rk3566",
        "product": "default",
        "variant": "release",
        "transport": "adb",
        "partitions": [
            {"name": "idbloader", "offset": "0x40", "size": "0x2000",
             "type": "raw", "protected": True},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000",
             "type": "ext4", "protected": False},
            {"name": "recovery", "offset": "0x240000", "size": "0x100000",
             "type": "ext4", "protected": True},
        ],
    }


class TestConfig:
    def test_load_missing(self, rc, tmp_path):
        with pytest.raises(rc.RecoveryError, match="未找到 recovery"):
            rc.load_recovery_config(tmp_path / "missing.json")

    def test_load_corrupt(self, rc, tmp_path):
        f = tmp_path / "rc.json"
        f.write_text("not json")
        with pytest.raises(rc.RecoveryError, match="解析"):
            rc.load_recovery_config(f)

    def test_load_round_trip(self, rc, tmp_path):
        f = tmp_path / "rc.json"
        f.write_text(json.dumps(_sample_config()))
        cfg = rc.load_recovery_config(f)
        assert cfg["board"] == "tspi-rk3566"

    def test_find_partition(self, rc):
        entry = rc.find_partition_entry(_sample_config(), "rootfs")
        assert entry["type"] == "ext4"

    def test_find_unknown_partition(self, rc):
        with pytest.raises(rc.RecoveryError, match="未知分区"):
            rc.find_partition_entry(_sample_config(), "boot42")


# ── mountinfo 解析（§6.5） ────────────────────────────────────


class TestMountinfo:
    SAMPLE = (
        "26 21 0:23 / /sys rw,nosuid,nodev,noexec,relatime shared:7 - sysfs sysfs rw\n"
        "27 21 0:5 / /proc rw,nosuid,nodev,noexec,relatime shared:11 - proc proc rw\n"
        "30 21 8:1 / /mnt/data rw,relatime shared:21 - ext4 /dev/sda1 rw,errors=remount-ro\n"
        "31 21 8:17 / /mnt/recovery rw,relatime shared:25 - ext4 /dev/mmcblk0p5 rw\n"
    )

    def test_parse_extracts_block_devices(self, rc):
        m = rc.parse_mountinfo(self.SAMPLE)
        assert m["/dev/sda1"] == "/mnt/data"
        assert m["/dev/mmcblk0p5"] == "/mnt/recovery"

    def test_skips_non_block_sources(self, rc):
        m = rc.parse_mountinfo(self.SAMPLE)
        assert "sysfs" not in m
        assert "proc" not in m

    def test_find_mountpoint_hit(self, rc, tmp_path):
        f = tmp_path / "mountinfo"
        f.write_text(self.SAMPLE)
        # 直接传非符号链接路径以避免 resolve()
        result = rc.find_mountpoint(Path("/dev/sda1"), mountinfo_path=f)
        assert result == "/mnt/data"

    def test_find_mountpoint_miss(self, rc, tmp_path):
        f = tmp_path / "mountinfo"
        f.write_text(self.SAMPLE)
        assert rc.find_mountpoint(Path("/dev/zzz"), mountinfo_path=f) is None


# ── set_extlinux_default（§6.9） ──────────────────────────────


class TestExtlinuxSwitch:
    SAMPLE = (
        "DEFAULT flange\n"
        "\n"
        "label flange\n  kernel /Image\n  append root=LABEL=rootfs\n"
        "\n"
        "label flange-recovery\n  kernel /Image\n  append root=LABEL=recovery\n"
    )

    def test_switch_to_recovery(self, rc):
        out = rc.set_extlinux_default(self.SAMPLE, "flange-recovery")
        assert "DEFAULT flange-recovery" in out
        assert out.count("DEFAULT") == 1

    def test_switch_back(self, rc):
        switched = rc.set_extlinux_default(self.SAMPLE, "flange-recovery")
        back = rc.set_extlinux_default(switched, "flange")
        assert back == self.SAMPLE

    def test_unknown_target_label(self, rc):
        with pytest.raises(rc.RecoveryError, match="不在 extlinux"):
            rc.set_extlinux_default(self.SAMPLE, "nope")

    def test_multiple_default_rejected(self, rc):
        bad = "DEFAULT a\nDEFAULT b\nlabel a\nlabel b\n"
        with pytest.raises(rc.RecoveryError, match="DEFAULT"):
            rc.set_extlinux_default(bad, "a")

    def test_read_extlinux_default(self, rc, tmp_path):
        path = tmp_path / "extlinux.conf"
        path.write_text(self.SAMPLE)
        assert rc.read_extlinux_default(path) == rc.NORMAL_LABEL

    def test_read_extlinux_default_missing(self, rc, tmp_path):
        assert rc.read_extlinux_default(tmp_path / "missing.conf") is None


# ── validate_flash 校验（§6.6） ───────────────────────────────


def _flash_request(rc, tmp_path, *, name="rootfs", sha=None, force=False):
    img = tmp_path / "in.img"
    img.write_bytes(b"\x00" * 1024)
    return rc.FlashRequest(
        partition=name, image_path=img,
        sha256_expected=sha, force=force,
    )


class TestValidateFlash:
    def test_protected_blocks_without_force(self, rc, tmp_path):
        req = _flash_request(rc, tmp_path, name="recovery")
        with pytest.raises(rc.ProtectedPartitionError):
            rc.validate_flash(
                req, _sample_config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/disk/by-partlabel/{n}"),
            )

    def test_protected_passes_with_force_and_sha(self, rc, tmp_path):
        # protected 分区强制写入要求 --sha256（设备端二次校验，§8.2）
        req = _flash_request(rc, tmp_path, name="recovery", force=True)
        req.sha256_expected = rc.sha256_of_file(req.image_path)
        dev = rc.validate_flash(
            req, _sample_config(),
            block_size_lookup=lambda d: 1 << 30,
            mounted_lookup=lambda d: None,
            partition_resolver=lambda n: Path(f"/dev/disk/by-partlabel/{n}"),
        )
        assert dev == Path("/dev/disk/by-partlabel/recovery")

    def test_unknown_partition(self, rc, tmp_path):
        req = _flash_request(rc, tmp_path, name="garbage")
        with pytest.raises(rc.RecoveryError, match="未知分区"):
            rc.validate_flash(req, _sample_config())

    def test_image_not_found(self, rc, tmp_path):
        req = rc.FlashRequest(partition="rootfs",
                              image_path=tmp_path / "missing.img",
                              sha256_expected=None)
        with pytest.raises(rc.RecoveryError, match="镜像文件不存在"):
            rc.validate_flash(req, _sample_config())

    def test_sha256_mismatch(self, rc, tmp_path):
        img = tmp_path / "in.img"
        img.write_bytes(b"hello")
        req = rc.FlashRequest(
            partition="rootfs", image_path=img,
            sha256_expected="00" * 32,
        )
        with pytest.raises(rc.RecoveryError, match="sha256"):
            rc.validate_flash(
                req, _sample_config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )

    def test_image_too_large(self, rc, tmp_path):
        img = tmp_path / "in.img"
        img.write_bytes(b"\xff" * 100)
        req = rc.FlashRequest(partition="rootfs", image_path=img,
                              sha256_expected=None)
        with pytest.raises(rc.RecoveryError, match="超过分区"):
            rc.validate_flash(
                req, _sample_config(),
                block_size_lookup=lambda d: 50,  # smaller than image
                mounted_lookup=lambda d: None,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )

    def test_already_mounted(self, rc, tmp_path):
        req = _flash_request(rc, tmp_path)
        with pytest.raises(rc.RecoveryError, match="已挂载"):
            rc.validate_flash(
                req, _sample_config(),
                block_size_lookup=lambda d: 1 << 30,
                mounted_lookup=lambda d: "/mnt/x",
                partition_resolver=lambda n: Path(f"/dev/{n}"),
            )


# ── do_backup 错误（§6.8） ────────────────────────────────────


class TestBackup:
    def test_unknown_partition(self, rc, tmp_path):
        req = rc.BackupRequest(partition="garbage",
                               output=tmp_path / "out.img.zst")
        with pytest.raises(rc.RecoveryError, match="未知分区"):
            rc.do_backup(req, _sample_config())

    def test_unknown_compress(self, rc, tmp_path):
        # 走 partition_resolver 替身，避免触达真实块设备
        called = {"runner": False}
        def fake_runner(*a, **k):
            called["runner"] = True
            class R: returncode = 0
            return R()
        req = rc.BackupRequest(partition="rootfs",
                               output=tmp_path / "out",
                               compress="lzma")
        with pytest.raises(rc.RecoveryError, match="未知压缩"):
            rc.do_backup(
                req, _sample_config(),
                runner=fake_runner,
                partition_resolver=lambda n: Path(f"/dev/{n}"),
                block_size_lookup=lambda d: 1 << 30,
            )
        assert called["runner"] is False


# ── do_reboot ────────────────────────────────────────────────


class TestReboot:
    def test_invalid_target(self, rc):
        with pytest.raises(rc.RecoveryError, match="normal、recovery 或 loader"):
            rc.do_reboot("garbage")

    def test_request_boot_once_recovery_requires_tool_and_config(self, rc, tmp_path):
        cfg = tmp_path / "fw_env.config"
        assert rc.request_boot_once_recovery(
            which=lambda name: None,
            fw_env_config=cfg,
        ) is False
        assert rc.request_boot_once_recovery(
            which=lambda name: "/usr/sbin/fw_setenv",
            fw_env_config=cfg,
        ) is False

    def test_request_boot_once_recovery_sets_env(self, rc, tmp_path):
        cfg = tmp_path / "fw_env.config"
        cfg.write_text("/dev/mmcblk0 0x0 0x2000\n")
        runs = []

        def runner(cmd, **kw):
            runs.append((cmd, kw))
            return types.SimpleNamespace(returncode=0)

        assert rc.request_boot_once_recovery(
            runner=runner,
            which=lambda name: "/usr/sbin/fw_setenv",
            fw_env_config=cfg,
        ) is True
        assert runs == [(
            ["/usr/sbin/fw_setenv", rc.BOOT_ONCE_ENV, rc.BOOT_ONCE_RECOVERY],
            {"check": False},
        )]

    def test_clear_boot_once_recovery_deletes_env(self, rc, tmp_path):
        cfg = tmp_path / "fw_env.config"
        cfg.write_text("/dev/mmcblk0 0x0 0x2000\n")
        runs = []

        def runner(cmd, **kw):
            runs.append((cmd, kw))
            return types.SimpleNamespace(returncode=0)

        assert rc.clear_boot_once_recovery(
            runner=runner,
            which=lambda name: "/usr/sbin/fw_setenv",
            fw_env_config=cfg,
        ) is True
        assert runs == [(
            ["/usr/sbin/fw_setenv", rc.BOOT_ONCE_ENV],
            {"check": False},
        )]

    def test_normal_target_clears_boot_once_without_extlinux_write(self, rc):
        cleared = {"called": False}
        runs = []
        reboots = []

        def clearer(**kwargs):
            cleared["called"] = True
            return True

        def runner(cmd, **kw):
            runs.append(cmd)
            return types.SimpleNamespace(returncode=0)

        rc.do_reboot(
            "normal",
            runner=runner,
            boot_once_clearer=clearer,
            reboot_command=lambda target: reboots.append(target),
        )
        assert cleared["called"] is True
        assert ["sync"] in runs
        assert reboots == [rc.MODE_NORMAL]

    def test_recovery_target_uses_reboot_reason_by_default(self, rc):
        runs = []
        reboots = []

        def runner(cmd, **kw):
            runs.append(cmd)
            return types.SimpleNamespace(returncode=0)

        rc.do_reboot(
            "recovery",
            runner=runner,
            boot_once_requester=lambda **kwargs: pytest.fail(
                "默认 recovery 入口不应写 U-Boot env"
            ),
            reboot_command=lambda target: reboots.append(target),
        )
        assert ["sync"] in runs
        assert reboots == [rc.MODE_RECOVERY]

    def test_loader_target_uses_reboot_reason(self, rc):
        runs = []
        reboots = []

        def runner(cmd, **kw):
            runs.append(cmd)
            return types.SimpleNamespace(returncode=0)

        rc.do_reboot(
            "loader",
            runner=runner,
            reboot_command=lambda target: reboots.append(target),
        )
        assert ["sync"] in runs
        assert reboots == [rc.MODE_LOADER]

    def test_recovery_persistent_uses_boot_once_then_normal_reboot(self, rc):
        runs = []
        reboots = []
        requested = {"called": False}

        def requester(**kwargs):
            requested["called"] = True
            return True

        def runner(cmd, **kw):
            runs.append(cmd)
            return types.SimpleNamespace(returncode=0)

        rc.do_reboot(
            "recovery",
            runner=runner,
            boot_once_requester=requester,
            reboot_command=lambda target: reboots.append(target),
            persistent=True,
        )
        assert requested["called"] is True
        assert ["sync"] in runs
        assert reboots == [rc.MODE_NORMAL]

    def test_recovery_persistent_requires_boot_once_env(self, rc):
        with pytest.raises(rc.RecoveryError, match="flange_boot_once"):
            rc.do_reboot(
                "recovery",
                boot_once_requester=lambda **kwargs: False,
                reboot_command=lambda target: pytest.fail("不应重启"),
                persistent=True,
            )

    def test_reboot_with_command_uses_restart2_syscall(self, rc):
        seen = []

        rc.reboot_with_command(
            "recovery",
            syscall_func=lambda command: seen.append(command) or 0,
        )
        assert seen == ["recovery"]

    def test_reboot_with_command_unknown_arch(self, rc):
        with pytest.raises(rc.RecoveryError, match="未声明 reboot syscall"):
            rc.reboot_with_command(
                "recovery",
                machine=lambda: "mystery-cpu",
            )


# ── build_partition_listing（§6.3） ───────────────────────────


class TestPartitionListing:
    def test_listing_includes_all_partitions(self, rc):
        listing = rc.build_partition_listing(
            _sample_config(),
            partition_resolver=lambda n: Path(f"/dev/by-partlabel/{n}"),
            mounted_lookup=lambda d: None,
            block_size_lookup=lambda d: 1024 * 1024 * 1024,
        )
        names = [p["name"] for p in listing["partitions"]]
        assert names == ["idbloader", "rootfs", "recovery"]

    def test_listing_marks_mounts(self, rc):
        listing = rc.build_partition_listing(
            _sample_config(),
            partition_resolver=lambda n: Path(f"/dev/by-partlabel/{n}"),
            mounted_lookup=lambda d: "/mnt" if "rootfs" in str(d) else None,
            block_size_lookup=lambda d: 1024 * 1024 * 1024,
        )
        rootfs = next(p for p in listing["partitions"] if p["name"] == "rootfs")
        recovery = next(p for p in listing["partitions"] if p["name"] == "recovery")
        assert rootfs["mounted"] is True
        assert rootfs["mountpoint"] == "/mnt"
        assert recovery["mounted"] is False

    def test_listing_passes_through_protected_flag(self, rc):
        listing = rc.build_partition_listing(
            _sample_config(),
            partition_resolver=lambda n: Path(f"/dev/by-partlabel/{n}"),
            mounted_lookup=lambda d: None,
            block_size_lookup=lambda d: 1024 * 1024 * 1024,
        )
        idb = next(p for p in listing["partitions"] if p["name"] == "idbloader")
        rootfs = next(p for p in listing["partitions"] if p["name"] == "rootfs")
        assert idb["protected"] is True
        assert rootfs["protected"] is False
