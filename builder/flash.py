"""统一刷写系统 — 配置生成 + 刷写执行 + 平台策略。

双职责设计：
- 构建时（Docker 内）：FlashConfigGenerator 从 FINAL_CONFIG 生成 flash-config.json
- 刷写时（宿主机）：FlashExecutor 读取 flash-config.json，通过平台策略执行刷写
"""

import argparse
import json
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 宿主机 CLI 输出辅助（与 BuildOutput 风格统一）
# ---------------------------------------------------------------------------

def _tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(color: str, text: str) -> str:
    if not _tty():
        return text
    return f"{color}{text}\033[0m"

_BLUE_BOLD = "\033[1;34m"
_GREEN     = "\033[0;32m"
_YELLOW    = "\033[1;33m"
_RED_BOLD  = "\033[1;31m"
_GRAY      = "\033[0;90m"
_WHITE     = "\033[0;37m"

def _header(text: str):
    sep = "═" * 58
    print()
    print(_c(_WHITE, sep))
    print(_c(_WHITE, f" {text}"))
    print(_c(_WHITE, sep))
    print()

def _step(text: str):
    print(_c(_BLUE_BOLD, f"▸ {text}"))

def _ok(text: str):
    print(_c(_GREEN, f"  ✓ {text}"))

def _warn(text: str):
    print(_c(_YELLOW, f"  ⚠ {text}"))

def _err(text: str):
    print(_c(_RED_BOLD, f"  ✗ {text}"))

def _info(text: str):
    print(_c(_GRAY, f"  · {text}"))


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class FlashPartition:
    """单个分区的刷写信息。"""
    name: str
    offset: str       # "0x40" 等 hex 字符串
    type: str         # "raw", "ext4" 等
    image: str        # 相对于 target_dir 的路径


@dataclass
class PreFlashConfig:
    """刷写前准备操作配置。"""
    download_boot: str = ""  # miniloader 路径（相对于 target_dir）


@dataclass
class FlashConfig:
    """flash-config.json 的完整数据模型。"""
    platform: str
    flash_tool: str
    board: str
    product: str
    variant: str
    partitions: list[FlashPartition] = field(default_factory=list)
    pre_flash: PreFlashConfig = field(default_factory=PreFlashConfig)

    def to_json(self, path: Path):
        """序列化为 JSON 文件。"""
        data = asdict(self)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def from_json(cls, path: Path) -> "FlashConfig":
        """从 JSON 文件反序列化。"""
        data = json.loads(path.read_text())
        partitions = [FlashPartition(**p) for p in data.get("partitions", [])]
        pre_flash = PreFlashConfig(**data.get("pre_flash", {}))
        return cls(
            platform=data["platform"],
            flash_tool=data["flash_tool"],
            board=data["board"],
            product=data["product"],
            variant=data["variant"],
            partitions=partitions,
            pre_flash=pre_flash,
        )


class FlashError(Exception):
    """刷写过程中的错误。"""
    pass


@dataclass
class DeviceInfo:
    """检测到的设备信息。"""
    platform: str
    mode: str         # "maskrom", "loader" 等
    description: str


# ---------------------------------------------------------------------------
# 平台刷写策略
# ---------------------------------------------------------------------------

class FlashStrategy(ABC):
    """平台刷写策略基类。"""

    @abstractmethod
    def find_tool(self, project_dir: Path) -> Path:
        """查找平台刷写工具路径，未找到抛 FlashError。"""

    @abstractmethod
    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """检测设备，返回 DeviceInfo 或 None。"""

    @abstractmethod
    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        """刷写前准备（如 Rockchip 上传 miniloader）。"""

    @abstractmethod
    def write_partition(self, tool: Path, offset: int, image: Path):
        """写入单个分区。"""

    @abstractmethod
    def reboot(self, tool: Path):
        """重启设备。"""

    @abstractmethod
    def partition_image_map(self, config: dict) -> dict[str, str]:
        """返回 {分区名: 镜像相对路径} 映射。"""

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        """生成平台特定的 pre_flash 配置。默认返回空配置。"""
        return PreFlashConfig()

    def wait_for_device(self, tool: Path, timeout: int = 30) -> DeviceInfo:
        """等待设备就绪，超时抛 FlashError。"""
        _step("等待设备连接...")
        deadline = time.time() + timeout
        # Spinner 字符集
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        idx = 0
        while time.time() < deadline:
            info = self.detect_device(tool)
            if info:
                _ok(f"已检测到 {info.platform} 设备 ({info.mode} 模式)")
                return info
            remaining = int(deadline - time.time())
            if _tty():
                frame = frames[idx % len(frames)]
                sys.stdout.write(
                    f"\r{_c(_GRAY, f'  {frame} 等待设备连接... ({remaining}s)')}")
                sys.stdout.flush()
                idx += 1
            time.sleep(1)
        if _tty():
            sys.stdout.write("\r\033[K")
        _err(f"等待设备超时（{timeout}s）")
        raise FlashError(
            f"等待设备超时（{timeout}s）。\n"
            "请确认设备已通过 USB 连接并进入刷写模式。"
        )


class RockchipFlashStrategy(FlashStrategy):
    """Rockchip 刷写策略 — 使用 upgrade_tool。"""

    TOOL_NAME = "upgrade_tool"

    def find_tool(self, project_dir: Path) -> Path:
        platform = "macos" if sys.platform == "darwin" else "linux"
        tool = project_dir / "tools" / platform / "upgrade_tool" / "upgrade_tool"
        if not tool.exists():
            raise FlashError(f"未找到 {self.TOOL_NAME}: {tool}")
        return tool

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        try:
            result = subprocess.run(
                [str(tool), "LD"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.lower() + result.stderr.lower()
            if "maskrom" in output:
                return DeviceInfo("rockchip", "maskrom", "Rockchip Maskrom 设备")
            if "loader" in output:
                return DeviceInfo("rockchip", "loader", "Rockchip Loader 设备")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # DB (Download Boot) 仅在 maskrom 模式下上传 loader；
        # 设备已在 loader 模式时跳过，避免 "did not support this operation"
        if device is None:
            device = self.detect_device(tool)
        if device and device.mode != "maskrom":
            _info(f"设备已在 {device.mode} 模式，跳过 DB")
            return
        if config.pre_flash.download_boot:
            miniloader = target_dir / config.pre_flash.download_boot
            if not miniloader.exists():
                raise FlashError(f"未找到 miniloader: {miniloader}")
            _info("上传 miniloader（DB）...")
            subprocess.run([str(tool), "DB", str(miniloader)], check=True)
            time.sleep(1)

    def write_partition(self, tool: Path, offset: int, image: Path):
        try:
            size_mb = image.stat().st_size / (1024 * 1024)
            size_str = f", {size_mb:.1f}MB"
        except OSError:
            size_str = ""
        _info(f"写入 {image.name} (offset=0x{offset:X}{size_str})...")
        subprocess.run(
            [str(tool), "WL", str(offset), str(image)],
            check=True,
        )
        _ok(f"{image.name}")

    def reboot(self, tool: Path):
        _info("重启设备...")
        subprocess.run([str(tool), "RD"], check=True)

    def partition_image_map(self, config: dict) -> dict[str, str]:
        return {
            "idbloader": "bootloader/idbloader.img",
            "uboot": "bootloader/u-boot.itb",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        return PreFlashConfig(download_boot="bootloader/miniloader.bin")


class AllwinnerFlashStrategy(FlashStrategy):
    """Allwinner 刷写策略 — SD 卡 dd 模式。"""

    def find_tool(self, project_dir: Path) -> Path:
        # SD 卡 dd 模式使用系统 dd，返回占位路径
        return Path("/usr/bin/dd")

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        # SD 卡模式不依赖 USB 设备检测
        return None

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # SD 卡模式无需 pre_flash
        pass

    def write_partition(self, tool: Path, offset: int, image: Path):
        # SD 卡模式通过 raw.img dd，不逐分区写入
        pass

    def reboot(self, tool: Path):
        _info("SD 卡模式：请手动插入 SD 卡并重启设备")

    def partition_image_map(self, config: dict) -> dict[str, str]:
        return {
            "boot0": "bootloader/boot0_sdcard.bin",
            "boot0_ufs": "bootloader/boot0_ufs.bin",
            "boot_package": "bootloader/boot_package.fex",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }


# 策略注册表
_FLASH_STRATEGIES: dict[str, type[FlashStrategy]] = {
    "rockchip": RockchipFlashStrategy,
    "allwinner": AllwinnerFlashStrategy,
}


def get_flash_strategy(platform: str) -> FlashStrategy:
    """根据平台名获取刷写策略实例。"""
    cls = _FLASH_STRATEGIES.get(platform)
    if not cls:
        raise FlashError(f"不支持的平台: {platform}（支持: {', '.join(_FLASH_STRATEGIES)}）")
    return cls()


# ---------------------------------------------------------------------------
# 配置生成器（构建时使用）
# ---------------------------------------------------------------------------

class FlashConfigGenerator:
    """从 FINAL_CONFIG 生成 flash-config.json。"""

    def generate(self, config: dict, target_dir: Path) -> Path:
        """生成 flash-config.json 到 target_dir，返回文件路径。"""
        platform = config.get("platform", "")
        strategy = get_flash_strategy(platform)
        image_map = strategy.partition_image_map(config)

        partitions = []
        for entry in config.get("partitions", {}).get("entries", []):
            name = entry["name"]
            image = image_map.get(name, "")
            if not image:
                continue  # 跳过无镜像映射的分区（如 userdata）
            partitions.append(FlashPartition(
                name=name,
                offset=entry.get("offset", "0x0"),
                type=entry.get("type", "raw"),
                image=image,
            ))

        # 构造 pre_flash（由平台策略声明）
        pre_flash = strategy.generate_pre_flash_config(config)

        flash_config = FlashConfig(
            platform=platform,
            flash_tool=config.get("flash_tool", ""),
            board=config["board"],
            product=config.get("product", "default"),
            variant=config.get("variant", "release"),
            partitions=partitions,
            pre_flash=pre_flash,
        )

        output = target_dir / "flash-config.json"
        flash_config.to_json(output)
        return output


# ---------------------------------------------------------------------------
# 刷写执行器（宿主机使用）
# ---------------------------------------------------------------------------

class FlashExecutor:
    """读取 flash-config.json 并执行刷写。"""

    def __init__(self, target_dir: Path, project_dir: Path = None):
        config_path = target_dir / "flash-config.json"
        if not config_path.exists():
            raise FlashError(f"未找到 flash-config.json: {config_path}\n请先执行 flange build")
        self.config = FlashConfig.from_json(config_path)
        self.target_dir = target_dir
        self.project_dir = project_dir or Path.cwd()
        self.strategy = get_flash_strategy(self.config.platform)

    def flash_all(self, no_wait: bool = False):
        """全量刷写所有分区。"""
        cfg = self.config
        _header(f"flange flash · {cfg.board} · {cfg.product}-{cfg.variant}")
        tool = self.strategy.find_tool(self.project_dir)
        device = None
        if not no_wait:
            device = self.strategy.wait_for_device(tool)
        self.strategy.pre_flash(tool, self.target_dir, cfg, device)

        _step("刷写分区")
        start = time.time()
        for part in cfg.partitions:
            image = self.target_dir / part.image
            if not image.exists():
                _warn(f"跳过 {part.name}: 镜像不存在")
                continue
            offset = int(part.offset, 0)
            self.strategy.write_partition(tool, offset, image)
        self.strategy.reboot(tool)
        elapsed = time.time() - start

        sep = "─" * 58
        print()
        print(_c(_WHITE, sep))
        print(_c(_GREEN, f" ✓ 刷写完成{_c(_GRAY, f'  {elapsed:.1f}s')}"))
        print(_c(_WHITE, sep))
        print()

    def flash_partition(self, name: str, no_wait: bool = False):
        """刷写指定分区。"""
        part = None
        for p in self.config.partitions:
            if p.name == name:
                part = p
                break
        if not part:
            available = [p.name for p in self.config.partitions]
            raise FlashError(
                f"未知分区: {name}\n可用分区: {', '.join(available)}"
            )
        image = self.target_dir / part.image
        if not image.exists():
            raise FlashError(f"镜像不存在: {image}")

        tool = self.strategy.find_tool(self.project_dir)
        if not no_wait:
            self.strategy.wait_for_device(tool)
        self.strategy.pre_flash(tool, self.target_dir, self.config)
        offset = int(part.offset, 0)
        self.strategy.write_partition(tool, offset, image)
        self.strategy.reboot(tool)
        print()
        print(_c(_GREEN, f" ✓ 分区 {name} 刷写完成"))

    def flash_raw(self, device: str):
        """dd 整盘刷写。"""
        firmware = next(self.target_dir.glob("*_firmware_*.img"), None)
        if not firmware:
            raise FlashError(f"未找到固件镜像（*_firmware_*.img）: {self.target_dir}")

        size_mb = firmware.stat().st_size / (1024 * 1024)
        _header("flange flash --raw")
        _info(f"镜像: {firmware.name} ({size_mb:.0f} MB)")
        _info(f"目标: {device}")
        confirm = input(_c(_YELLOW, "  ⚠ 将覆盖目标设备全部数据！确认？[y/N] "))
        if confirm.lower() != "y":
            _info("已取消")
            return

        _step("dd 刷写")
        subprocess.run(
            ["sudo", "dd", f"if={firmware}", f"of={device}",
             "bs=4M", "status=progress", "conv=fsync"],
            check=True,
        )
        subprocess.run(["sync"], check=True)
        print()
        print(_c(_GREEN, " ✓ dd 刷写完成"))

    def list_partitions(self):
        """列出所有可刷写分区。"""
        cfg = self.config
        _header(f"flange flash --list · {cfg.board} · {cfg.product}-{cfg.variant}")
        print(f"  {'分区名':<16} {'偏移':<12} {'类型':<8} {'镜像路径'}")
        print(f"  {'─'*14}   {'─'*10}   {'─'*6}   {'─'*24}")
        for p in cfg.partitions:
            exists = _c(_GREEN, "✓") if (self.target_dir / p.image).exists() else _c(_RED_BOLD, "✗")
            print(f"  {p.name:<16} {p.offset:<12} {p.type:<8} {p.image} [{exists}]")
        print()


# ---------------------------------------------------------------------------
# CLI 入口（python3 -m builder.flash）
# ---------------------------------------------------------------------------

def _cli_main():
    parser = argparse.ArgumentParser(
        prog="python3 -m builder.flash",
        description="flange 刷写工具",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="执行刷写")
    run_parser.add_argument("--target-dir", required=True, help="构建产物目录")
    run_parser.add_argument("--project-dir", default=".", help="项目根目录")
    run_parser.add_argument("--no-wait", action="store_true", help="跳过设备等待")
    run_parser.add_argument("--raw", metavar="DEVICE", help="dd 整盘刷写到指定设备")
    run_parser.add_argument("--list", action="store_true", dest="list_parts", help="列出可刷写分区")
    run_parser.add_argument("partition", nargs="?", help="指定分区名（不指定则全量刷写）")

    # generate 子命令（构建引擎调用）
    gen_parser = subparsers.add_parser("generate", help="生成 flash-config.json")
    gen_parser.add_argument("--config", required=True, help="FINAL_CONFIG JSON 文件路径")
    gen_parser.add_argument("--target-dir", required=True, help="输出目录")

    args = parser.parse_args()

    if args.command == "run":
        target_dir = Path(args.target_dir)
        project_dir = Path(args.project_dir)
        executor = FlashExecutor(target_dir, project_dir)

        if args.list_parts:
            executor.list_partitions()
        elif args.raw:
            executor.flash_raw(args.raw)
        elif args.partition:
            executor.flash_partition(args.partition, no_wait=args.no_wait)
        else:
            executor.flash_all(no_wait=args.no_wait)

    elif args.command == "generate":
        config = json.loads(Path(args.config).read_text())
        gen = FlashConfigGenerator()
        gen.generate(config, Path(args.target_dir))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
