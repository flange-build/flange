"""AmlogicFlashStrategy 单元测试。

覆盖场景：
- ``get_flash_strategy("amlogic")`` 返回 ``AmlogicFlashStrategy`` 实例
- ``_FLASH_STRATEGIES`` 注册表仍含 rockchip / allwinnera733（无回归）
- ``pre_flash`` 调 pyamlboot 命令行参数构造正确（mock subprocess）
- ``generate_pre_flash_config`` 返回的 PreFlashConfig 含正确 download_boot
  与 USB vid/pid（``1b8e:c003``）
- ``write_partition`` 通过 fastboot flash <name> <image> 写入分区
- ``reboot`` 调 fastboot reboot
- ``partition_image_map`` 含 bootloader/boot/rootfs，启用 recovery 时含 recovery
- ``find_tool`` 找不到 fastboot 时抛 FlashError
- ``pre_flash`` 找不到 boot-g12.py 时抛 FlashError
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.flash import (
    AllwinnerA733FlashStrategy,
    AmlogicFlashStrategy,
    DeviceInfo,
    FlashConfig,
    FlashError,
    FlashPartition,
    PreFlashConfig,
    RockchipFlashStrategy,
    _FLASH_STRATEGIES,
    get_flash_strategy,
)


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_get_flash_strategy_amlogic(self):
        s = get_flash_strategy("amlogic")
        assert isinstance(s, AmlogicFlashStrategy)

    def test_registry_contains_amlogic(self):
        assert "amlogic" in _FLASH_STRATEGIES
        assert _FLASH_STRATEGIES["amlogic"] is AmlogicFlashStrategy

    def test_registry_still_contains_rockchip(self):
        assert "rockchip" in _FLASH_STRATEGIES
        assert _FLASH_STRATEGIES["rockchip"] is RockchipFlashStrategy

    def test_registry_still_contains_allwinnera733(self):
        assert "allwinnera733" in _FLASH_STRATEGIES
        assert _FLASH_STRATEGIES["allwinnera733"] is AllwinnerA733FlashStrategy


# ---------------------------------------------------------------------------
# generate_pre_flash_config
# ---------------------------------------------------------------------------

class TestGeneratePreFlashConfig:
    def test_returns_pre_flash_config(self):
        s = AmlogicFlashStrategy()
        cfg = s.generate_pre_flash_config({})
        assert isinstance(cfg, PreFlashConfig)

    def test_download_boot_points_to_bare_fip_image(self):
        """boot-g12.py 通过 AMLC chunk 协议从单一 binary 拉数据，需要 BL2
        位于 binary offset 0；SD 格式的 .sd.bin 前置了 block-1 header，BL2
        被推到错位置，BL2 起来后 AMLC 握手超时。所以 download_boot 必须
        指向 build-fip.sh 直接产出的裸 FIP ``u-boot.bin``（非 .sd.bin）。"""
        s = AmlogicFlashStrategy()
        cfg = s.generate_pre_flash_config({})
        assert cfg.download_boot == "bootloader/u-boot.bin"
        assert not cfg.download_boot.endswith(".sd.bin")

    def test_usb_vid_pid_is_amlogic_maskrom(self):
        s = AmlogicFlashStrategy()
        cfg = s.generate_pre_flash_config({})
        assert cfg.usb_vid == "1b8e"
        assert cfg.usb_pid == "c003"


# ---------------------------------------------------------------------------
# find_tool
# ---------------------------------------------------------------------------

class TestFindTool:
    def test_returns_fastboot_path(self):
        s = AmlogicFlashStrategy()
        # find_tool 内部 ``from shutil import which``，按需 import；
        # patch 路径走 shutil.which 即可拦截。
        with patch("shutil.which", return_value="/usr/bin/fastboot"):
            tool = s.find_tool(Path("/proj"))
            assert tool == Path("/usr/bin/fastboot")

    def test_missing_fastboot_raises(self):
        s = AmlogicFlashStrategy()
        with patch("shutil.which", return_value=None):
            with pytest.raises(FlashError, match="fastboot"):
                s.find_tool(Path("/proj"))


# ---------------------------------------------------------------------------
# pre_flash
# ---------------------------------------------------------------------------

class TestPreFlash:
    def _make_config(self, download_boot="bootloader/u-boot.bin.sd.bin"):
        return FlashConfig(
            platform="amlogic", flash_tool="fastboot",
            board="khadas-vim3l", product="default", variant="debug",
            pre_flash=PreFlashConfig(
                download_boot=download_boot,
                usb_vid="1b8e", usb_pid="c003",
            ),
        )

    def test_pre_flash_invokes_pyamlboot(self):
        s = AmlogicFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            boot_img = target_dir / "bootloader" / "u-boot.bin.sd.bin"
            boot_img.parent.mkdir(parents=True)
            boot_img.write_bytes(b"fakeboot")

            cfg = self._make_config()
            with patch("shutil.which", return_value="/usr/local/bin/boot-g12.py"), \
                 patch("builder.flash.strategy.subprocess.run") as mock_run, \
                 patch.object(s, "_wait_maskrom_device"), \
                 patch("builder.flash.strategy.time.sleep"):
                s.pre_flash(Path("/usr/bin/fastboot"), target_dir, cfg)

            # 至少有一次调用是 boot-g12.py 推 u-boot
            calls = mock_run.call_args_list
            pyamlboot_calls = [
                c for c in calls
                if any("boot-g12.py" in str(a) for a in (c[0][0] if c[0] else []))
            ]
            assert len(pyamlboot_calls) >= 1
            cmd = pyamlboot_calls[0][0][0]
            # 命令形如 ["sudo", "/usr/local/bin/boot-g12.py", "<boot_img>"]
            assert "sudo" in cmd
            assert "/usr/local/bin/boot-g12.py" in cmd
            assert str(boot_img) in cmd

    def test_macos_resolves_shim_before_launch(self, tmp_path):
        s = AmlogicFlashStrategy()
        boot = tmp_path / "bootloader/u-boot.bin.sd.bin"
        boot.parent.mkdir()
        boot.write_bytes(b"boot")
        with patch("builder.flash.strategy.sys.platform", "darwin"), \
             patch("shutil.which", return_value="/pyenv/shims/boot-g12.py"), \
             patch.object(s, "_resolve_pyamlboot_entry", return_value="/python/bin/boot-g12.py") as resolve, \
             patch.object(s, "_darwin_dyld_lib_path", return_value="/opt/homebrew/lib"), \
             patch.object(s, "_wait_maskrom_device"), \
             patch("builder.flash.strategy.time.sleep"), \
             patch("builder.flash.strategy.subprocess.run") as run:
            s.pre_flash(Path("/bin/fastboot"), tmp_path, self._make_config())
        resolve.assert_called_once_with("/pyenv/shims/boot-g12.py")
        run.assert_called_once_with([
            "sudo", "env", "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib",
            "/python/bin/boot-g12.py", str(boot),
        ], check=True)

    def test_pre_flash_missing_boot_image_raises(self):
        s = AmlogicFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            cfg = self._make_config()
            with patch("shutil.which", return_value="/usr/local/bin/boot-g12.py"):
                with pytest.raises(FlashError, match="未找到引导镜像"):
                    s.pre_flash(Path("/usr/bin/fastboot"), target_dir, cfg)

    def test_pre_flash_missing_pyamlboot_raises(self):
        s = AmlogicFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            boot_img = target_dir / "bootloader" / "u-boot.bin.sd.bin"
            boot_img.parent.mkdir(parents=True)
            boot_img.write_bytes(b"fakeboot")
            cfg = self._make_config()
            with patch("shutil.which", return_value=None):
                with pytest.raises(FlashError, match="boot-g12.py"):
                    s.pre_flash(Path("/usr/bin/fastboot"), target_dir, cfg)

    def test_pre_flash_skips_pyamlboot_when_already_fastboot(self):
        """如果 detect_device 已识别为 fastboot 模式（u-boot 在 DDR 跑着），
        pre_flash 应直接返回，跳过 pyamlboot 推送 ——避免要求用户接串口
        手动 ``fastboot usb 0``，也省一次 sudo 提示与 3s 推送等待。"""
        s = AmlogicFlashStrategy()
        cfg = self._make_config()
        fb_device = DeviceInfo(
            platform="amlogic", mode="fastboot",
            description="Amlogic fastboot 设备",
        )
        # 关键断言：subprocess.run 与 which 都不应被调用（没下载、没 sudo）
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            s.pre_flash(Path("/fastboot"), Path("/target"), cfg, device=fb_device)
            mock_run.assert_not_called()

    def test_pre_flash_missing_download_boot_field_raises(self):
        s = AmlogicFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            cfg = self._make_config(download_boot="")
            with pytest.raises(FlashError, match="download_boot"):
                s.pre_flash(Path("/usr/bin/fastboot"), target_dir, cfg)


# ---------------------------------------------------------------------------
# write_partition
# ---------------------------------------------------------------------------

class TestWritePartition:
    def test_bootloader_writes_via_fastboot_flash(self):
        s = AmlogicFlashStrategy()
        img = Path("/target/bootloader/u-boot.bin.sd.bin")
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            # bypass image.stat() OSError handling
            with patch.object(Path, "stat", side_effect=OSError):
                s.write_partition(Path("/usr/bin/fastboot"), 0x200, img)
            mock_run.assert_called_once_with(
                ["/usr/bin/fastboot", "flash", "bootloader",
                 "/target/bootloader/u-boot.bin.sd.bin"],
                check=True,
            )

    def test_boot_writes_via_fastboot_flash(self):
        s = AmlogicFlashStrategy()
        img = Path("/target/boot/boot.img")
        with patch("builder.flash.strategy.subprocess.run") as mock_run, \
             patch.object(Path, "stat", side_effect=OSError):
            s.write_partition(Path("/usr/bin/fastboot"), 0x40, img)
            mock_run.assert_called_once_with(
                ["/usr/bin/fastboot", "flash", "boot",
                 "/target/boot/boot.img"],
                check=True,
            )

    def test_rootfs_writes_via_fastboot_flash(self):
        s = AmlogicFlashStrategy()
        img = Path("/target/rootfs/rootfs.img")
        with patch("builder.flash.strategy.subprocess.run") as mock_run, \
             patch.object(Path, "stat", side_effect=OSError):
            s.write_partition(Path("/fastboot"), 0x120040, img)
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/fastboot", "flash", "rootfs",
                           "/target/rootfs/rootfs.img"]

    def test_recovery_writes_via_fastboot_flash(self):
        s = AmlogicFlashStrategy()
        img = Path("/target/recovery/recovery.img")
        with patch("builder.flash.strategy.subprocess.run") as mock_run, \
             patch.object(Path, "stat", side_effect=OSError):
            s.write_partition(Path("/fastboot"), 0x20040, img)
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/fastboot", "flash", "recovery",
                           "/target/recovery/recovery.img"]


# ---------------------------------------------------------------------------
# reboot
# ---------------------------------------------------------------------------

class TestReboot:
    def test_reboot_calls_fastboot_reboot(self):
        s = AmlogicFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            s.reboot(Path("/usr/bin/fastboot"))
            mock_run.assert_called_once_with(
                ["/usr/bin/fastboot", "reboot"],
                check=True,
            )


# ---------------------------------------------------------------------------
# partition_image_map
# ---------------------------------------------------------------------------

class TestPartitionImageMap:
    def test_minimal_map(self):
        s = AmlogicFlashStrategy()
        m = s.partition_image_map({})
        assert m["bootloader"] == "bootloader/u-boot.bin.sd.bin"
        assert m["boot"] == "boot/boot.img"
        assert m["rootfs"] == "rootfs/rootfs.img"
        # recovery 默认不开启
        assert "recovery" not in m

    def test_recovery_enabled_includes_recovery(self):
        s = AmlogicFlashStrategy()
        m = s.partition_image_map({"recovery": {"enabled": True}})
        assert m["recovery"] == "recovery/recovery.img"

    def test_recovery_disabled_excludes_recovery(self):
        s = AmlogicFlashStrategy()
        m = s.partition_image_map({"recovery": {"enabled": False}})
        assert "recovery" not in m


# ---------------------------------------------------------------------------
# detect_device
# ---------------------------------------------------------------------------

class TestDetectDevice:
    def test_no_device_returns_none(self):
        s = AmlogicFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="")
            info = s.detect_device(Path("/fastboot"))
            assert info is None

    def test_fastboot_device_detected(self):
        s = AmlogicFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1234567890\tfastboot\n",
                stderr="",
            )
            info = s.detect_device(Path("/fastboot"))
            assert info is not None
            assert info.platform == "amlogic"
            assert info.mode == "fastboot"

    def test_timeout_returns_none(self):
        s = AmlogicFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="", timeout=5)
            info = s.detect_device(Path("/fastboot"))
            assert info is None

    def test_maskrom_device_detected_via_lsusb(self):
        """pre_flash 之前板在 MaskROM 阶段，fastboot 看不到但 USB 总线上
        有 1b8e:c003 ——必须把这种状态识别为"设备就绪"，否则首刷会卡
        在 wait_for_device 死循环。
        """
        s = AmlogicFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Bus 003 Device 042: ID 1b8e:c003 Amlogic, Inc.\n",
                stderr="",
            )
            info = s.detect_device(Path("/fastboot"))
            assert info is not None
            assert info.mode == "maskrom", (
                f"应识别 MaskROM 阶段，实际 mode={info.mode}"
            )
            assert "1b8e:c003" in info.description

    def test_maskrom_device_detected_via_ioreg_macos(self):
        """macOS 用 ioreg 而非 lsusb；同样要被识别为 maskrom。"""
        s = AmlogicFlashStrategy()
        ioreg_output = '''
        +-o GX-CHIP@01120000  <class IOUSBHostDevice, id 0x10006044e>
            "idProduct" = 49155
            "idVendor" = 7054
            "kUSBProductString" = "GX-CHIP"
        '''
        def fake_run(cmd, **kwargs):
            if cmd[0] == "lsusb":
                # macOS 上 lsusb 不存在
                raise FileNotFoundError("lsusb")
            if cmd[0] == "ioreg":
                return MagicMock(returncode=0, stdout=ioreg_output, stderr="")
            # fastboot devices 兜底
            return MagicMock(returncode=0, stdout="", stderr="")
        with patch("builder.flash.strategy.subprocess.run", side_effect=fake_run):
            info = s.detect_device(Path("/fastboot"))
            assert info is not None
            assert info.mode == "maskrom"


class TestPyenvEntry:
    def test_direct_entry_does_not_invoke_pyenv(self, tmp_path):
        entry = tmp_path / "boot-g12.py"
        with patch("builder.flash.strategy.subprocess.check_output") as command:
            assert AmlogicFlashStrategy._resolve_pyamlboot_entry(str(entry)) == str(entry)
        command.assert_not_called()

    @pytest.mark.parametrize("invalid", [False, True])
    def test_shim_resolves_selected_environment_or_fails(self, tmp_path, invalid):
        root = tmp_path / "pyenv"
        shim = root / "shims/boot-g12.py"
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/bin/sh\n")
        real = root / "versions/custom/bin/boot-g12.py"
        real.parent.mkdir(parents=True)
        real.write_text("#!/python\n")
        real.chmod(0o755)
        with patch("shutil.which", return_value="/bin/pyenv"), \
             patch("builder.flash.strategy.subprocess.check_output",
                   side_effect=[str(root), str(shim if invalid else real)]) as command:
            if invalid:
                with pytest.raises(FlashError, match="真实"):
                    AmlogicFlashStrategy._resolve_pyamlboot_entry(str(shim))
            else:
                assert AmlogicFlashStrategy._resolve_pyamlboot_entry(str(shim)) == str(real)
                assert command.call_args[0][0] == ["/bin/pyenv", "which", "boot-g12.py"]

    def test_resolution_failure_is_actionable(self, tmp_path):
        shim = tmp_path / "shims/boot-g12.py"
        with patch("shutil.which", return_value="/bin/pyenv"), \
             patch("builder.flash.strategy.subprocess.check_output",
                   side_effect=subprocess.TimeoutExpired("pyenv", 5)), \
             pytest.raises(FlashError, match="无法解析 pyenv"):
            AmlogicFlashStrategy._resolve_pyamlboot_entry(str(shim))
