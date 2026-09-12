"""统一刷写系统测试。

覆盖场景：
- FlashConfig 数据模型：构造、JSON 序列化/反序列化
- FlashConfigGenerator：从 FINAL_CONFIG 生成 flash-config.json
- RockchipFlashStrategy：工具路径、设备检测、命令构造、分区映射
- FlashExecutor：flash_all/flash_partition 执行流程、未知分区报错
"""

import json
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from builder.flash import (
    FlashConfig, FlashConfigGenerator, FlashError, FlashExecutor,
    FlashIdentityConfig, FlashPartition, FlashStrategy, PreFlashConfig,
    RockchipFlashStrategy, DeviceInfo, get_flash_strategy,
)
from builder.flash.console import _header, _info, _ok, _step, _warn
from builder.term import Role


@pytest.mark.parametrize("no_color", [None, "", "1"])
def test_刷写状态颜色区分进行中成功取消与跳过(monkeypatch, no_color):
    class Terminal(StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    if no_color is not None:
        monkeypatch.setenv("NO_COLOR", no_color)
    stream = Terminal()
    monkeypatch.setattr("sys.stdout", stream)
    _header("flange flash")
    _step("等待设备连接")
    _info("写入 boot.img", role=Role.ACTIVE)
    _ok("boot.img 已写入")
    _warn("已取消")
    _info("跳过重启")
    text = stream.getvalue()
    if no_color is None:
        assert "\033[1;34m flange flash" in text
        assert "\033[34m▸ 等待设备连接" in text
        assert "\033[34m  · 写入 boot.img" in text
        assert "\033[32m  ✓ boot.img 已写入" in text
        assert "\033[33m  ⚠ 已取消" in text
        assert "\033[2m  · 跳过重启" in text
        assert "\033[0;37m" not in text
    else:
        assert "\033" not in text


# ---------------------------------------------------------------------------
# FlashConfig 数据模型
# ---------------------------------------------------------------------------

class TestFlashConfig:
    def test_construct(self):
        config = FlashConfig(
            platform="rockchip", flash_tool="upgrade_tool",
            board="test", product="default", variant="release",
        )
        assert config.platform == "rockchip"
        assert config.partitions == []

    def test_json_roundtrip(self):
        config = FlashConfig(
            platform="rockchip", flash_tool="upgrade_tool",
            board="test", product="default", variant="release",
            partitions=[
                FlashPartition("idbloader", "0x40", "raw", "bootloader/idbloader.img"),
                FlashPartition("uboot", "0x4000", "raw", "bootloader/u-boot.itb"),
            ],
            pre_flash=PreFlashConfig(download_boot="bootloader/miniloader.bin"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "flash-config.json"
            config.to_json(path)
            assert path.exists()

            loaded = FlashConfig.from_json(path)
            assert loaded.platform == "rockchip"
            assert loaded.board == "test"
            assert len(loaded.partitions) == 2
            assert loaded.partitions[0].name == "idbloader"
            assert loaded.partitions[0].offset == "0x40"
            assert loaded.partitions[1].image == "bootloader/u-boot.itb"
            assert loaded.pre_flash.download_boot == "bootloader/miniloader.bin"

    def test_json_is_valid_json(self):
        config = FlashConfig(
            platform="rockchip", flash_tool="upgrade_tool",
            board="test", product="default", variant="release",
            partitions=[FlashPartition("boot", "0x8000", "ext4", "boot/boot.img")],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "flash-config.json"
            config.to_json(path)
            data = json.loads(path.read_text())
            assert data["platform"] == "rockchip"
            assert len(data["partitions"]) == 1

    def test_from_json_missing_field_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text('{"platform": "rockchip"}')
            with pytest.raises(KeyError):
                FlashConfig.from_json(path)

    def test_partition_image_is_relative(self):
        part = FlashPartition("boot", "0x8000", "ext4", "boot/boot.img")
        assert not Path(part.image).is_absolute()


# ---------------------------------------------------------------------------
# FlashConfigGenerator
# ---------------------------------------------------------------------------

class TestFlashConfigGenerator:
    def _rockchip_config(self):
        return {
            "platform": "rockchip",
            "flash_tool": "upgrade_tool",
            "board": "radxa-zero3w",
            "product": "default",
            "variant": "release",
            "partitions": {
                "format": "gpt",
                "sector_size": 512,
                "entries": [
                    {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
                    {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
                    {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                    {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
                    {"name": "userdata", "offset": "0x240000", "size": "remaining", "type": "ext4"},
                ],
            },
        }

    def test_generates_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            path = gen.generate(self._rockchip_config(), Path(tmpdir))
            assert path.exists()
            assert path.name == "flash-config.json"

    def test_partitions_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            gen.generate(self._rockchip_config(), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")

            names = [p.name for p in config.partitions]
            assert "idbloader" in names
            assert "uboot" in names
            assert "boot" in names
            assert "rootfs" in names
            # userdata 没有镜像映射，不应出现
            assert "userdata" not in names

    def test_offsets_match_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            gen.generate(self._rockchip_config(), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")

            offsets = {p.name: p.offset for p in config.partitions}
            assert offsets["idbloader"] == "0x40"
            assert offsets["uboot"] == "0x4000"
            assert offsets["boot"] == "0x8000"
            assert offsets["rootfs"] == "0x40000"

    def test_image_paths_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            gen.generate(self._rockchip_config(), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")

            images = {p.name: p.image for p in config.partitions}
            assert images["idbloader"] == "bootloader/idbloader.img"
            assert images["uboot"] == "bootloader/u-boot.itb"
            assert images["boot"] == "boot/boot.img"
            assert images["rootfs"] == "rootfs/rootfs.img"

    def test_pre_flash_includes_miniloader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            gen.generate(self._rockchip_config(), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            assert config.pre_flash.download_boot == "bootloader/miniloader.bin"

    def test_board_info_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashConfigGenerator()
            gen.generate(self._rockchip_config(), Path(tmpdir))
            config = FlashConfig.from_json(Path(tmpdir) / "flash-config.json")
            assert config.board == "radxa-zero3w"
            assert config.product == "default"
            assert config.variant == "release"
            assert config.flash_tool == "upgrade_tool"


# ---------------------------------------------------------------------------
# RockchipFlashStrategy
# ---------------------------------------------------------------------------

class TestRockchipFlashStrategy:
    def test_find_tool_macos(self):
        strategy = RockchipFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_path = Path(tmpdir) / "tools" / "macos" / "upgrade_tool" / "upgrade_tool"
            tool_path.parent.mkdir(parents=True)
            tool_path.touch()

            with patch("builder.flash.strategy.sys") as mock_sys:
                mock_sys.platform = "darwin"
                result = strategy.find_tool(Path(tmpdir))
                assert result == tool_path

    def test_find_tool_linux(self):
        strategy = RockchipFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_path = Path(tmpdir) / "tools" / "linux" / "upgrade_tool" / "upgrade_tool"
            tool_path.parent.mkdir(parents=True)
            tool_path.touch()

            with patch("builder.flash.strategy.sys") as mock_sys:
                mock_sys.platform = "linux"
                result = strategy.find_tool(Path(tmpdir))
                assert result == tool_path

    def test_find_tool_missing_raises(self):
        strategy = RockchipFlashStrategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FlashError, match="未找到"):
                strategy.find_tool(Path(tmpdir))

    def test_detect_device_maskrom(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Found One MASKROM Device",
                stderr="",
            )
            info = strategy.detect_device(Path("/fake/tool"))
            assert info is not None
            assert info.mode == "maskrom"

    def test_detect_device_loader(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Found One LOADER Device",
                stderr="",
            )
            info = strategy.detect_device(Path("/fake/tool"))
            assert info is not None
            assert info.mode == "loader"

    def test_detect_device_none(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="")
            info = strategy.detect_device(Path("/fake/tool"))
            assert info is None

    def test_detect_device_rejects_multiple_rockchip_devices(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=(
                    "List of rockusb connected(2)\n"
                    "DevNo=1 Mode=Loader\nDevNo=2 Mode=Maskrom\n"
                ),
                stderr="",
            )
            with pytest.raises(FlashError, match="2 台.*只连接一台"):
                strategy.detect_device(Path("/fake/tool"))

    def test_device_identity_matches_rk3506_f053_chip_tag(self):
        strategy = RockchipFlashStrategy()
        config = FlashConfig(
            platform="rockchip",
            flash_tool="upgrade_tool",
            board="test",
            product="default",
            variant="release",
            soc="rk3506b",
            storage_type="spinand",
            identity=FlashIdentityConfig(
                chip_patterns=[r"\b(?:46\s+30\s+35\s+33|f053)\b"],
                storage_patterns=[r"\b(?:spi[ -]?nand|snand)\b"],
            ),
        )

        def fake_run(cmd, **kwargs):
            outputs = {
                "RCI": (
                    "Chip Info: 46 30 35 33 AD 8 B1 80 94 CC FE 7F "
                    "AB 8 B1 80\n\nF053\n"
                ),
                "RFI": (
                    "Flash Info:\n"
                    "        Manufacturer: SAMSUNG,value=00\n"
                    "        Flash Size: 511MB\n"
                    "        Block Size: 128KB\n"
                    "        Page Size: 2KB\n"
                ),
                "RID": "Flash ID:53 4E 41 4E 44\n\nSNAND\n",
            }
            return MagicMock(
                returncode=0, stdout=outputs[cmd[1]], stderr="")

        with patch("builder.flash.strategy.subprocess.run", side_effect=fake_run):
            strategy._verify_device_identity(Path("upgrade_tool"), config)

    def test_device_identity_matches_reversed_tag_followed_by_padding(self):
        """反转芯片名后紧跟的填充字节可能是单词字符，不得压制单词边界匹配。"""
        strategy = RockchipFlashStrategy()
        config = FlashConfig(
            platform="rockchip",
            flash_tool="upgrade_tool",
            board="test",
            product="default",
            variant="release",
            soc="rk3566",
            storage_type="emmc",
            identity=FlashIdentityConfig(
                chip_patterns=[r"rk\s*356[68]", r"\b356[68]\b", r"\b8653\b"],
            ),
        )

        def fake_run(cmd, **kwargs):
            outputs = {
                # 实机 maskrom 输出：ASCII "8653"（"3568" 的字节反转）之后
                # 紧跟填充字节 0x5F，即下划线，属于正则的单词字符。
                "RCI": (
                    "Chip Info: 38 36 35 33 5F DF FB FF FF 39 BF FF "
                    "7E EF FF B4\n"
                ),
                "RFI": "Flash Info:\n        Flash Size: 14910MB\n",
                "RID": "Flash ID:15 01 00\n",
            }
            return MagicMock(
                returncode=0, stdout=outputs[cmd[1]], stderr="")

        with patch("builder.flash.strategy.subprocess.run", side_effect=fake_run):
            strategy._verify_device_identity(Path("upgrade_tool"), config)

    def test_device_identity_rejects_wrong_storage_before_write(self):
        strategy = RockchipFlashStrategy()
        config = FlashConfig(
            platform="rockchip",
            flash_tool="upgrade_tool",
            board="test",
            product="default",
            variant="release",
            soc="rk3506b",
            identity=FlashIdentityConfig(
                chip_patterns=["RK3506"],
                storage_patterns=[r"\b(?:spi[ -]?nand|snand)\b"],
            ),
        )

        def fake_run(cmd, **kwargs):
            outputs = {
                "RCI": "Chip Info: RK3506\n",
                "RFI": "Flash Info: EMMC\n",
                "RID": "ReadFlashID: 15 01 00\n",
            }
            return MagicMock(
                returncode=0, stdout=outputs[cmd[1]], stderr="")

        with patch("builder.flash.strategy.subprocess.run", side_effect=fake_run):
            with pytest.raises(FlashError, match="存储身份.*不匹配"):
                strategy._verify_device_identity(Path("upgrade_tool"), config)

    def test_detect_device_timeout(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="", timeout=5)
            info = strategy.detect_device(Path("/fake/tool"))
            assert info is None

    def test_partition_image_map(self):
        strategy = RockchipFlashStrategy()
        m = strategy.partition_image_map({})
        assert "idbloader" in m
        assert "uboot" in m
        assert "boot" in m
        assert "rootfs" in m
        assert m["boot"] == "boot/boot.img"

    def test_write_partition_command(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            strategy.write_partition(
                Path("/tool"), 0x8000, Path("/target/boot/boot.img"))
            mock_run.assert_called_once_with(
                ["/tool", "WL", "32768", "/target/boot/boot.img"],
                check=True,
            )

    def test_reboot_command(self):
        strategy = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as mock_run:
            strategy.reboot(Path("/tool"))
            mock_run.assert_called_once_with(["/tool", "RD"], check=True)

    def test_wait_for_device_timeout(self):
        strategy = RockchipFlashStrategy()
        call_count = [0]

        def fake_time():
            call_count[0] += 1
            # 前几次返回小于 deadline 的值，最后返回超过 deadline 的值
            if call_count[0] <= 4:
                return 0.0
            return 999.0  # 远超 deadline

        with patch.object(strategy, "detect_device", return_value=None), \
             patch("builder.flash.strategy.time.sleep"), \
             patch("builder.flash.strategy.time.time", side_effect=fake_time):
            with pytest.raises(FlashError, match="超时"):
                strategy.wait_for_device(Path("/tool"), timeout=30)


# ---------------------------------------------------------------------------
# get_flash_strategy
# ---------------------------------------------------------------------------

class TestGetFlashStrategy:
    def test_rockchip(self):
        s = get_flash_strategy("rockchip")
        assert isinstance(s, RockchipFlashStrategy)

    def test_unknown_raises(self):
        with pytest.raises(FlashError, match="不支持的平台"):
            get_flash_strategy("qualcomm")


# ---------------------------------------------------------------------------
# FlashExecutor
# ---------------------------------------------------------------------------

class TestFlashExecutor:
    def _setup_executor(self, tmpdir, partitions=None):
        """创建 FlashExecutor 所需的 flash-config.json 和目录结构。"""
        target_dir = Path(tmpdir) / "target"
        target_dir.mkdir()

        parts = partitions or [
            FlashPartition("idbloader", "0x40", "raw", "bootloader/idbloader.img"),
            FlashPartition("uboot", "0x4000", "raw", "bootloader/u-boot.itb"),
            FlashPartition("boot", "0x8000", "ext4", "boot/boot.img"),
            FlashPartition("rootfs", "0x40000", "ext4", "rootfs/rootfs.img"),
        ]
        config = FlashConfig(
            platform="rockchip", flash_tool="upgrade_tool",
            board="test", product="default", variant="release",
            partitions=parts,
            pre_flash=PreFlashConfig(download_boot="bootloader/miniloader.bin"),
        )
        config.to_json(target_dir / "flash-config.json")

        # 创建镜像文件
        for p in parts:
            img = target_dir / p.image
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"fake")

        # 创建 miniloader
        mini = target_dir / "bootloader" / "miniloader.bin"
        mini.parent.mkdir(parents=True, exist_ok=True)
        mini.write_bytes(b"miniloader")

        return target_dir

    def test_flash_all_calls_strategy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            mock_strategy.find_tool.return_value = Path("/fake/tool")
            mock_strategy.wait_for_device.return_value = DeviceInfo("rockchip", "maskrom", "")

            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy):
                executor = FlashExecutor(target_dir, Path(tmpdir))
                executor.flash_all(no_wait=False)

            mock_strategy.find_tool.assert_called_once()
            mock_strategy.wait_for_device.assert_called_once()
            mock_strategy.pre_flash_all.assert_called_once()
            assert mock_strategy.write_partition.call_count == 4
            mock_strategy.reboot.assert_called_once()

    def test_flash_all_no_wait(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            mock_strategy.find_tool.return_value = Path("/fake/tool")

            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy):
                executor = FlashExecutor(target_dir, Path(tmpdir))
                executor.flash_all(no_wait=True)

            mock_strategy.wait_for_device.assert_not_called()

    def test_flash_partition_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            mock_strategy.find_tool.return_value = Path("/fake/tool")
            mock_strategy.wait_for_device.return_value = DeviceInfo("rockchip", "maskrom", "")

            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy):
                executor = FlashExecutor(target_dir, Path(tmpdir))
                executor.flash_partition("rootfs")

            # 只写一个分区
            mock_strategy.write_partition.assert_called_once()
            call_args = mock_strategy.write_partition.call_args
            assert call_args[0][1] == 0x40000  # offset

    def test_flash_unknown_partition_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            mock_strategy.find_tool.return_value = Path("/fake/tool")

            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy):
                executor = FlashExecutor(target_dir, Path(tmpdir))
                with pytest.raises(FlashError, match="未知分区"):
                    executor.flash_partition("nonexistent")

    def test_missing_config_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FlashError, match="未找到 flash-config.json"):
                FlashExecutor(Path(tmpdir))

    def test_list_partitions(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy):
                executor = FlashExecutor(target_dir, Path(tmpdir))
                executor.list_partitions()

            output = capsys.readouterr().out
            assert "idbloader" in output
            assert "rootfs" in output
            assert "0x40000" in output

    def test_flash_raw_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)
            # 创建整盘镜像（image 组件产物，各平台统一命名 raw.img）
            firmware = target_dir / "image" / "raw.img"
            firmware.parent.mkdir(parents=True, exist_ok=True)
            firmware.write_bytes(b"x" * 1024)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy), \
                 patch("builtins.input", return_value="y"), \
                 patch("builder.flash.strategy.subprocess.run") as mock_run:
                executor = FlashExecutor(target_dir, Path(tmpdir))
                executor.flash_raw("/dev/sdX", yes=True)

            # 验证 dd 命令
            dd_call = mock_run.call_args_list[0]
            assert "dd" in dd_call[0][0]
            assert any("/dev/sdX" in str(a) for a in dd_call[0][0])

    def test_flash_raw_cancel(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = self._setup_executor(tmpdir)
            firmware = target_dir / "image" / "raw.img"
            firmware.parent.mkdir(parents=True, exist_ok=True)
            firmware.write_bytes(b"x" * 1024)

            mock_strategy = MagicMock(spec=RockchipFlashStrategy)
            with patch("builder.flash.execute.get_flash_strategy", return_value=mock_strategy), \
                 patch("builtins.input", return_value="n"), \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("builder.flash.strategy.subprocess.run") as mock_run:
                executor = FlashExecutor(target_dir, Path(tmpdir))
                with pytest.raises(KeyboardInterrupt):
                    executor.flash_raw("/dev/sdX")

            # dd 不应被调用
            mock_run.assert_not_called()


class TestFlashRaw:
    """`flange flash --raw` 的整盘镜像定位。

    历史实现 glob `*_firmware_*.img`，而所有平台的 image 产物都叫
    `image/raw.img`（见各平台 ARTIFACT_NAMES）—— 这条命令从未能找到镜像，
    对 write_partition 为 no-op、整盘 dd 是唯一刷写手段的板尤其致命。
    """

    @staticmethod
    def _executor(tmp_path):
        from builder.flash import FlashExecutor

        executor = FlashExecutor.__new__(FlashExecutor)
        executor.target_dir = tmp_path
        return executor

    def test_缺少整盘镜像时报出具体路径(self, tmp_path):
        from builder.flash import FlashError

        with pytest.raises(FlashError, match="image/raw.img"):
            self._executor(tmp_path).flash_raw("/dev/sdX")

    def test_整盘镜像路径与image产物一致(self, tmp_path):
        import importlib

        from builder.flash import FlashExecutor

        for platform in ("rockchip", "allwinnera733", "amlogic",
                         "qualcommqcs6490"):
            names = getattr(
                importlib.import_module(f"builder.platforms.{platform}"),
                "ARTIFACT_NAMES", {})
            assert names.get(("image", "image")) == "raw.img", platform
        assert FlashExecutor.WHOLE_DISK_IMAGE == "image/raw.img"


class TestCLI入口:
    """`flange flash` 经 `python3 -m builder.flash run` 调用。

    flash 从单模块拆成包时，这条路径静默失效过：包必须有 `__main__.py`
    才能被 `python3 -m` 执行，而当时没有任何测试碰过 CLI 入口 —— 单测
    全在直接 import 类，从下面绕过了真正的调用方式。
    """

    def test_可以作为模块执行(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-m", "builder.flash", "--help"],
            cwd=root, capture_output=True, text=True, timeout=60)

        assert result.returncode == 0, (
            f"python3 -m builder.flash 执行失败:\n{result.stderr}")
        assert "run" in result.stdout, "帮助里应列出 run 子命令"

    def test_安装入口与模块入口共用可调用的main(self):
        """Shell 不承载业务路由；安装命令与模块调用指向同一服务。"""
        import importlib.util
        import importlib
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        project = tomllib.loads((root / "pyproject.toml").read_text())
        module, function = project["project"]["scripts"]["flange"].split(":")
        assert callable(getattr(importlib.import_module(module), function))
        assert importlib.util.find_spec("builder.__main__") is not None
