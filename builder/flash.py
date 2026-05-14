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
    # recovery 与宿主机端均消费的保护标记：raw 类型分区一律 True；
    # 此外 recovery.protected_partitions 中显式列出的分区也标记 True。
    # 默认 False，向前兼容现有 flash-config.json 消费者。
    protected: bool = False


@dataclass
class PreFlashConfig:
    """刷写前准备操作配置。

    各平台共享字段：
    - ``download_boot``：第一阶段需推送到 SoC 的引导镜像（rockchip 的
      ``miniloader.bin``、amlogic 的 ``u-boot.bin.sd.bin``）路径，相对于
      ``target_dir``。
    - ``usb_vid`` / ``usb_pid``：MaskROM 阶段 host 端用来识别 SoC 的 USB
      VID/PID（小写 hex 字符串，例如 amlogic = ``"1b8e"`` / ``"c003"``）。
      为兼容现有 flash-config.json，默认为空字符串。
    """
    download_boot: str = ""  # 第一阶段引导镜像路径（相对于 target_dir）
    usb_vid: str = ""        # MaskROM USB Vendor ID，hex 不带 0x
    usb_pid: str = ""        # MaskROM USB Product ID，hex 不带 0x


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

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        """在分区写入前刷新 GPT 表。默认 no-op；需要的平台覆盖。

        Rockchip upgrade_tool 的 WL 命令仅按 offset 写 LBA，不会更新 GPT 表；
        分区表变更（如新增 recovery）必须显式刷一次 GPT，否则 kernel 看不到
        新分区，``Waiting for root device PARTLABEL=...`` 会死等。
        """
        return

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

    # GPT primary 占 LBA 1..33（GPT header + entries），protective MBR 在 LBA 0。
    # rockchip upgrade_tool 拒绝 WL 0（保护 boot region），跳过 protective MBR
    # 直接从 LBA 1 写 33 个 sector 即可让 kernel 看到完整分区表。
    GPT_HEADER_LBA = 1
    GPT_ENTRIES_SECTORS = 33  # 1 header + 32 entries = 33 sectors

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        raw_img = target_dir / "image" / "raw.img"
        if not raw_img.exists():
            _warn(f"未找到 raw.img: {raw_img}，跳过 GPT 刷新（旧 GPT 可能丢失新分区）")
            return
        # 从 raw.img LBA 1 起截取 33 sectors —— 跳过 protective MBR，
        # 保留 GPT header + entries 段。
        import tempfile
        sector = 512
        size = self.GPT_ENTRIES_SECTORS * sector
        with tempfile.NamedTemporaryFile(suffix=".gpt.bin", delete=False) as tmp:
            with raw_img.open("rb") as f:
                f.seek(self.GPT_HEADER_LBA * sector)
                tmp.write(f.read(size))
            tmp_path = Path(tmp.name)
        try:
            _info(f"刷新 GPT 表（LBA {self.GPT_HEADER_LBA}, "
                  f"{self.GPT_ENTRIES_SECTORS} sectors / {size // 1024}KB）...")
            subprocess.run(
                [str(tool), "WL", str(self.GPT_HEADER_LBA), str(tmp_path)],
                check=True,
            )
            _ok("GPT")
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def reboot(self, tool: Path):
        _info("重启设备...")
        subprocess.run([str(tool), "RD"], check=True)

    def partition_image_map(self, config: dict) -> dict[str, str]:
        m = {
            "idbloader": "bootloader/idbloader.img",
            "uboot": "bootloader/u-boot.itb",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        return m

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        return PreFlashConfig(download_boot="bootloader/miniloader.bin")


class AllwinnerA733FlashStrategy(FlashStrategy):
    """Allwinner A733 刷写策略 — SD 卡 dd 模式。"""

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
        # SD 卡模式整体 dd raw.img；列出 recovery 仅为生成 flash-config.json 时
        # 携带 protection 元数据，write_partition 不会被逐分区调用。
        m = {
            "boot0": "bootloader/boot0_sdcard.bin",
            "boot0_ufs": "bootloader/boot0_ufs.bin",
            "boot_package": "bootloader/boot_package.fex",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        return m


class AmlogicFlashStrategy(FlashStrategy):
    """Amlogic 刷写策略 — 两段式 USB Burning。

    流程（详见 design.md Decision 5）：

    pre_flash 阶段：板上按住 KEY1 + USB-C 上电 → 设备以 MaskROM 模式枚举
    （USB ``1b8e:c003``）。host 端调 ``boot-g12.py``（pyamlboot 提供的
    G12A/G12B/SM1 系列入口脚本，VIM3L 的 S905D3 属 SM1，复用 G12 协议）
    把 ``bootloader/u-boot.bin.sd.bin`` 推到 SoC DDR；BL2 在 SRAM 解密执行
    → BL31 → u-boot proper；u-boot 启动后自动进入 fastboot gadget 模式
    （由 mainline ``khadas-vim3l_defconfig`` + ``flange_fastboot.config``
    fragment 启用）。

    flash 主流程：host 端 ``fastboot`` 命令依次写各分区，``bootloader``
    分区由 u-boot 端 ``CONFIG_FASTBOOT_FLASH_MMC_DEV=1`` 指向 eMMC hw
    boot0 分区，offset 0x200；其他分区写 user area GPT。最后
    ``fastboot reboot``。

    host 端依赖：
    - ``pyamlboot``（pip install pyamlboot 或 git clone superna9999/pyamlboot），
      实际入口脚本 ``boot-g12.py``（不是 ``python3 -m pyamlboot.pyamlboot``）
    - ``android-tools-fastboot``（Ubuntu apt 包）
    """

    # MaskROM 模式 USB VID/PID（Amlogic 通用 BootROM 描述符）
    MASKROM_VID = "1b8e"
    MASKROM_PID = "c003"

    # pyamlboot 入口脚本名（由 pip install pyamlboot 暴露到 PATH，或在
    # 本地 git clone 后位于 repo 根）。SM1 family 的 S905D3 复用 G12
    # 协议（同代加密 v3），与 G12A/G12B/S905X3 共用。
    PYAMLBOOT_ENTRY = "boot-g12.py"

    # 进入 fastboot 模式后，host 端等待设备出现的超时（秒）。与
    # RockchipFlashStrategy.wait_for_device 默认 30s 对齐。
    FASTBOOT_WAIT_TIMEOUT = 30

    def find_tool(self, project_dir: Path) -> Path:
        """查找 host 端 fastboot 工具。

        amlogic 主流程靠 host fastboot；pyamlboot 在 pre_flash 单独走
        ``shutil.which("boot-g12.py")``，不进 ``find_tool`` 路径。
        """
        from shutil import which
        fastboot = which("fastboot")
        if not fastboot:
            raise FlashError(
                "未找到 fastboot 命令。请安装：\n"
                "  Ubuntu: sudo apt install android-tools-fastboot\n"
                "  macOS:  brew install android-platform-tools"
            )
        return Path(fastboot)

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """检测 amlogic 设备（MaskROM 或 fastboot 任一即可）。

        amlogic 刷写两段式：刚上电按 KEY1 时设备在 MaskROM 模式
        （``1b8e:c003``），``fastboot devices`` 看不到；pre_flash 推完
        u-boot 后才切到 fastboot gadget。``FlashExecutor.flash_all`` 在
        pre_flash 之前调 wait_for_device，所以这里必须把 MaskROM 也算
        "设备就绪"，否则首刷会卡死直到超时。

        探测顺序：MaskROM USB → fastboot devices（pre_flash 后用）。
        """
        # 1) MaskROM 阶段（pre_flash 前的常态）
        if self._probe_maskrom():
            return DeviceInfo("amlogic", "maskrom",
                              f"Amlogic MaskROM 设备 "
                              f"({self.MASKROM_VID}:{self.MASKROM_PID})")

        # 2) fastboot 阶段（pre_flash 推完 u-boot 之后）
        try:
            result = subprocess.run(
                [str(tool), "devices"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.strip()
            if output:
                # `fastboot devices` 在有设备时仅输出 `<serial>\tfastboot`
                return DeviceInfo("amlogic", "fastboot", "Amlogic fastboot 设备")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _probe_maskrom(self) -> bool:
        """探测 USB 总线上是否有 MaskROM 设备（``1b8e:c003``）。

        Linux 用 ``lsusb``；macOS 用 ``ioreg -p IOUSB -l``（system_profiler
        在某些非交互 shell 下输出为空，ioreg 更可靠）。任一工具不在或
        返回非零都视为"没找到"，由调用方决定是否继续等待。
        """
        vid = int(self.MASKROM_VID, 16)
        pid = int(self.MASKROM_PID, 16)
        # Linux 路径：lsusb 输出 `Bus xxx Device yyy: ID 1b8e:c003 Amlogic, Inc.`
        try:
            res = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0 and (
                f"{self.MASKROM_VID}:{self.MASKROM_PID}".lower()
                in res.stdout.lower()
            ):
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        # macOS 路径：ioreg 把 idVendor / idProduct 暴露为十进制
        try:
            res = subprocess.run(
                ["ioreg", "-p", "IOUSB", "-l"],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0:
                out = res.stdout
                if (f'"idVendor" = {vid}' in out
                        and f'"idProduct" = {pid}' in out):
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return False

    @staticmethod
    def _darwin_dyld_lib_path() -> Optional[str]:
        """在 macOS 上返回应注入子进程 DYLD_FALLBACK_LIBRARY_PATH 的路径。

        pyamlboot 的 pyusb 通过 ctypes 加载 libusb；macOS 上 brew 装的
        libusb 在 /opt/homebrew/lib（Apple Silicon）或 /usr/local/lib
        （Intel）。前者不在 dyld 默认搜索路径，后者虽在但若残留 x86_64
        老 dylib 会与 arm64 Python arch 失配。把 brew 的 lib 路径强行
        加入 fallback 搜索路径即可。

        非 macOS 返回 None（Linux 走 udev rule / sudo 不需要这层）。
        """
        if sys.platform != "darwin":
            return None
        # brew --prefix 是权威；进程不存在时退到 Apple Silicon / Intel 默认路径
        try:
            prefix = subprocess.check_output(
                ["brew", "--prefix"], text=True, timeout=3,
            ).strip()
            return f"{prefix}/lib"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError,
                subprocess.CalledProcessError):
            pass
        for guess in ("/opt/homebrew", "/usr/local"):
            if (Path(guess) / "lib" / "libusb-1.0.dylib").exists():
                return f"{guess}/lib"
        return None

    def _wait_maskrom_device(self, timeout: int = 30) -> None:
        """等待 USB 总线列出 MaskROM 设备。

        探测沿用 ``_probe_maskrom``（Linux lsusb / macOS ioreg）。两者都
        没找到或调用失败时仅打印 warning，不阻塞 —— pyamlboot 本身会在
        没有设备时报错，让其错误冒泡更直观。
        """
        _info(f"等待 MaskROM 设备（USB {self.MASKROM_VID}:{self.MASKROM_PID}）...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._probe_maskrom():
                _ok("MaskROM 设备已就绪")
                return
            time.sleep(1)
        _warn(f"等待 MaskROM 设备超时（{timeout}s），仍尝试 pyamlboot")

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        """调 pyamlboot 把 u-boot 推送到 SoC DDR。"""
        from shutil import which

        if not config.pre_flash.download_boot:
            raise FlashError(
                "amlogic pre_flash 缺少 download_boot 字段；请检查 flash-config.json"
            )
        boot_image = target_dir / config.pre_flash.download_boot
        if not boot_image.exists():
            raise FlashError(f"未找到引导镜像: {boot_image}")

        pyamlboot = which(self.PYAMLBOOT_ENTRY)
        if not pyamlboot:
            raise FlashError(
                f"未找到 {self.PYAMLBOOT_ENTRY}。请安装：\n"
                "  pip install pyamlboot\n"
                "  或 git clone https://github.com/superna9999/pyamlboot.git\n"
                "    并把仓库根目录加入 PATH"
            )

        # MaskROM 设备探测（best-effort）
        self._wait_maskrom_device(timeout=30)

        _info(f"上传 u-boot 到 SoC DDR（{boot_image.name}）...")
        # boot-g12.py 通常需要 root 权限访问 USB raw endpoint；
        # 若用户已配置 udev rule，sudo 可省略。这里默认带 sudo 与
        # Rockchip upgrade_tool 一致心智（rockchip 也需要 udev 或 sudo）。
        #
        # macOS Apple Silicon 特殊处理：brew 装的 libusb 在
        # /opt/homebrew/lib/，不在 dyld 默认搜索路径（/usr/local/lib，
        # /usr/lib）。若系统遗留 /usr/local/lib/libusb-1.0.dylib（Intel
        # x86_64 老 brew 或 Rosetta 工具留下的），ctypes find_library 会
        # 撞到 arch 失配的那一份，pyusb 报 "No backend available"。
        # 通过 ``env DYLD_FALLBACK_LIBRARY_PATH=<brew>/lib`` 透给子进程
        # 解决（DYLD_* 直接传给 sudo 会被 SIP 剥；走 env 作为新命令的
        # 第一参数，env 自身的 args 不在 SIP 剥除范围内）。
        cmd = ["sudo"]
        dyld_extra = self._darwin_dyld_lib_path()
        if dyld_extra:
            cmd += ["env", f"DYLD_FALLBACK_LIBRARY_PATH={dyld_extra}"]
        cmd += [str(pyamlboot), str(boot_image)]
        subprocess.run(cmd, check=True)
        # u-boot 已进 DDR；提示用户松开 KEY1，避免 fastboot reboot 后再次
        # 进 MaskROM（按住 KEY1 状态下 BootROM 优先尝试 USB Burning）。
        _info("u-boot 已推入 DDR — 现在可松开 KEY1，等待 fastboot 设备枚举...")
        # u-boot 主线 USB 枚举需要 ~1.5s，留出余量到 3s。
        time.sleep(3)
        _ok("u-boot 已推送，等待 fastboot 设备")

    def _run_fastboot(self, tool: Path, *args: str) -> None:
        """执行 fastboot 子命令，带 stdout/stderr 透传。"""
        cmd = [str(tool), *args]
        subprocess.run(cmd, check=True)

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        """通过 ``fastboot oem run "gpt write mmc 2 ${partitions}"`` 让
        u-boot 按实际 eMMC 容量重建 GPT。

        u-boot 端约定（详见 components/platform/amlogic/s905d3/patches/
        bootloader/flange_fastboot.config）：
          - PREBOOT 设 ``partitions`` env，含 user area GPT 分区描述
            （boot + rootfs；bootloader 在 hw boot0 不入 user area GPT）
          - ``CONFIG_FASTBOOT_OEM_RUN=y`` 允许 host 端 ``fastboot oem run``
            执行 u-boot 命令脚本
          - ``CONFIG_CMD_GPT=y`` + ``CONFIG_RANDOM_UUID=y`` 提供 gpt write
            子命令与 UUID 生成
        ``gpt write`` 按当前 mmc dev 容量计算 LBA / size，避开"raw.img
        GPT 字段指向 2GB 位置但 eMMC 14.6GB"的尺寸不匹配问题，写完后
        u-boot 自动 rescan 分区表，后续 ``flash boot/rootfs`` 立即可找到
        分区。本步骤必须在 ``fastboot flash boot/rootfs`` 之前。
        """
        _info("用 u-boot gpt write 按实际 eMMC 容量重建 GPT...")
        self._run_fastboot(
            tool, "oem", "run", "gpt write mmc 2 ${partitions}",
        )
        _ok("GPT")

    def write_partition(self, tool: Path, offset: int, image: Path):
        """通过 fastboot flash <name> <image> 写入分区。

        amlogic 的分区路由由 u-boot 端 ``CONFIG_FASTBOOT_GPT_NAME`` +
        ``CONFIG_FASTBOOT_FLASH_MMC_DEV=2`` 决定，不依赖 host 端 offset。
        分区名通过 ``image`` 文件路径反推 —— 在 ``flash_all`` 主流程中
        ``FlashExecutor`` 已按分区名调用，但抽象基类签名只给 offset，故
        这里从镜像路径反推分区名。
        """
        # 从镜像路径反推分区名：bootloader/u-boot.bin.sd.bin → bootloader,
        # boot/boot.img → boot, recovery/recovery.img → recovery,
        # rootfs/rootfs.img → rootfs。
        parent_name = image.parent.name
        partition_name = "bootloader" if parent_name == "bootloader" else parent_name

        try:
            size_mb = image.stat().st_size / (1024 * 1024)
            size_str = f", {size_mb:.1f}MB"
        except OSError:
            size_str = ""
        _info(f"fastboot flash {partition_name} ({image.name}{size_str})...")
        self._run_fastboot(tool, "flash", partition_name, str(image))
        _ok(f"{partition_name}")

    def reboot(self, tool: Path):
        """通过 fastboot reboot 触发 SoC 重启。"""
        _info("fastboot reboot...")
        self._run_fastboot(tool, "reboot")

    def partition_image_map(self, config: dict) -> dict[str, str]:
        """amlogic 平台分区 → 镜像路径映射。

        ``bootloader`` 指向 FIP 封装的 SD/eMMC 启动镜像
        （``u-boot.bin.sd.bin``），由 fastboot 写入 eMMC hw boot0 分区
        （u-boot ``CONFIG_FASTBOOT_FLASH_MMC_DEV=1`` 路由）。
        """
        m = {
            "bootloader": "bootloader/u-boot.bin.sd.bin",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        return m

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        """生成 amlogic 平台的 pre_flash 配置。

        - ``download_boot`` 指向**裸 FIP**（``u-boot.bin``，build-fip.sh 直接
          产出）而非 SD 格式（``u-boot.bin.sd.bin``）。boot-g12.py 在
          SRAM 解第一个 64KB 后会通过 AMLC 控制传输请求剩余 chunks，需要
          binary 的 BL2 位于 offset 0；SD 格式前置了 block-1 header，BL2
          被推到错误偏移，BL2 起来后 AMLC 握手超时。
        - ``usb_vid`` / ``usb_pid``：amlogic MaskROM 通用 USB 描述符
          ``1b8e:c003``。
        """
        return PreFlashConfig(
            download_boot="bootloader/u-boot.bin",
            usb_vid=self.MASKROM_VID,
            usb_pid=self.MASKROM_PID,
        )


# 策略注册表
_FLASH_STRATEGIES: dict[str, type[FlashStrategy]] = {
    "rockchip": RockchipFlashStrategy,
    "allwinnera733": AllwinnerA733FlashStrategy,
    "amlogic": AmlogicFlashStrategy,
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
        """生成 flash-config.json 到 target_dir，返回文件路径。

        ``protected`` 标记规则：``type == "raw"`` 一律 True；启用 recovery 时
        ``recovery.protected_partitions`` 名单中的分区也置 True；recovery 自身
        分区始终视为受保护（设备端不允许从 recovery 内重写自己）。
        """
        platform = config.get("platform", "")
        strategy = get_flash_strategy(platform)
        image_map = strategy.partition_image_map(config)

        recovery_cfg = config.get("recovery") or {}
        protected_set: set[str] = set(recovery_cfg.get("protected_partitions") or [])
        if recovery_cfg.get("enabled", False):
            protected_set.add("recovery")

        partitions = []
        for entry in config.get("partitions", {}).get("entries", []):
            name = entry["name"]
            image = image_map.get(name, "")
            if not image:
                continue  # 跳过无镜像映射的分区（如 userdata）
            ptype = entry.get("type", "raw")
            protected = bool(ptype == "raw" or name in protected_set)
            partitions.append(FlashPartition(
                name=name,
                offset=entry.get("offset", "0x0"),
                type=ptype,
                image=image,
                protected=protected,
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

    def flash_all(self, no_wait: bool = False, no_reboot: bool = False):
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
        # 全量刷写时分区表可能变化（如新增 recovery），先把 GPT 表写下去；
        # 平台默认实现是 no-op，rockchip 通过 raw.img 前几个 sector 刷写 GPT。
        self.strategy.write_gpt(tool, self.target_dir, cfg)
        for part in cfg.partitions:
            image = self.target_dir / part.image
            if not image.exists():
                _warn(f"跳过 {part.name}: 镜像不存在")
                continue
            offset = int(part.offset, 0)
            self.strategy.write_partition(tool, offset, image)
        if no_reboot:
            _info("跳过重启（--no-reboot）")
        else:
            self.strategy.reboot(tool)
        elapsed = time.time() - start

        sep = "─" * 58
        print()
        print(_c(_WHITE, sep))
        print(_c(_GREEN, f" ✓ 刷写完成{_c(_GRAY, f'  {elapsed:.1f}s')}"))
        print(_c(_WHITE, sep))
        print()

    def flash_partition(self, name: str, no_wait: bool = False, no_reboot: bool = False):
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
        if no_reboot:
            _info("跳过重启（--no-reboot）")
        else:
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
    run_parser.add_argument("--no-reboot", action="store_true", help="刷写完成后不触发设备重启")
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
            executor.flash_partition(args.partition, no_wait=args.no_wait, no_reboot=args.no_reboot)
        else:
            executor.flash_all(no_wait=args.no_wait, no_reboot=args.no_reboot)

    elif args.command == "generate":
        config = json.loads(Path(args.config).read_text())
        gen = FlashConfigGenerator()
        gen.generate(config, Path(args.target_dir))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
