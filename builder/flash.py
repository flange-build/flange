"""统一刷写系统 — 配置生成 + 刷写执行 + 平台策略。

双职责设计：
- 构建时（Docker 内）：FlashConfigGenerator 从 FINAL_CONFIG 生成 flash-config.json
- 刷写时（宿主机）：FlashExecutor 读取 flash-config.json，通过平台策略执行刷写
"""

import argparse
import json
import re
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
# Rockchip parameter.txt（GPT 分区表）生成
# ---------------------------------------------------------------------------

# rootfs 固定 PARTUUID，供 kernel cmdline root=PARTUUID 引用（与 image 一致）。
ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000000"


def generate_parameter_txt(entries: list, machine: str = "RK3576") -> str:
    """从 partitions.entries 生成 Rockchip parameter.txt（GPT）。

    offset/size 用 512 字节扇区单位（hex）—— 这是 Rockchip parameter 的通用
    约定，对 eMMC/UFS 一致（依据：rkbin parameter 样例注释 "per section
    512(0x200) bytes"；loader1 固定在 0x40=32KB÷512，eMMC/UFS 共用）。
    parameter 本身 device-agnostic：刷写时 `upgrade_tool di -p parameter.txt`
    由 loader 按目标设备实际块大小（UFS=4K）把 512-扇区 offset 映射成设备
    LBA 并建 GPT。flange 的 partitions offset 本就是 512-扇区，直接透传。
    （最终以实板 di -p 后的 GPT 为准。）

    所有分区都给**显式大小**（用 resolve_image_size：rootfs 取 image_size
    如 2G→0x400000 扇区），不使用 ``-``（remaining）—— 实测该 loader 的
    di -p 把 ``-`` 算成 size=0，导致 "partition too small"。rootfs 初始按
    image_size，靠 grow_on_first_boot 首启动撑满整盘。
    """
    from builder.partition.size import resolve_image_size

    segs = []
    for e in entries:
        name = e["name"]
        off = int(e.get("offset", "0"), 0) if e.get("offset") else 0
        sectors = resolve_image_size(e).sectors
        flag = ":bootable" if name == "boot" else ""
        segs.append(f"{sectors:#010x}@{off:#010x}({name}{flag})")
    cmdline = "mtdparts=rk29xxnand:" + ",".join(segs)
    lines = [
        "FIRMWARE_VER: 1.0",
        f"MACHINE_MODEL: {machine}",
        "MACHINE_ID: 007",
        f"MANUFACTURER: {machine}",
        "MAGIC: 0x5041524B",
        "ATAG: 0x00200800",
        "MACHINE: 0xffffffff",
        "CHECK_MASK: 0x80",
        "PWR_HLD: 0,0,A,0,1",
        "TYPE: GPT",
        "# in section; per section 512(0x200) bytes",
        f"CMDLINE: {cmdline}",
        f"uuid:rootfs={ROOTFS_PARTUUID}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Rockchip SPI NOR 启动固件（spi.img）合成
# ---------------------------------------------------------------------------

# SPI NOR 上的布局（字节偏移）。实板日志确认：rkbin SPL 在 SPI(MTD2) 上读
# u-boot.itb 于 sector 0x4000（= 8 MiB），与 eMMC/UFS 统一约定一致；idbloader
# 在 32 KiB（rk35xx BootROM 要求非 0 偏移）。
SPI_NOR_SIZE = 16 * 1024 * 1024          # 板载 SPI NOR 标称 16 MiB（容量上限校验用）
SPI_IDBLOADER_OFFSET = 0x8000            # 32 KiB
SPI_UBOOT_OFFSET = 0x800000             # 8 MiB（= sector 0x4000 × 512）
SPI_IMG_ALIGN = 0x10000                  # 镜像尾部上对齐 64 KiB


def build_spi_image(bootloader_dir: Path, out_path: Path,
                    idbloader_off: int = SPI_IDBLOADER_OFFSET,
                    uboot_off: int = SPI_UBOOT_OFFSET) -> Path:
    """把 idbloader.img + u-boot.itb 合成为可写入 SPI NOR 起始(LBA 0)的 spi.img。

    架构 A2：bootloader 全在 SPI（idbloader@32KiB + u-boot.itb@8MiB），UFS 只放
    OS。idbloader 用 mkimage -T rksd（RK3576 BootROM 已修复 SPI 散布 bug，无需
    rkspi）。

    镜像**只做到容纳 u-boot.itb 末端**（按 64KiB 上对齐），不填满整片 SPI ——
    SPINOR 实际可写扇区略少于标称容量（实测 32735 < 32768），写满会
    "partition too small"；尾部旧内容保留不影响启动（只用 idbloader+itb）。
    """
    idb = bootloader_dir / "idbloader.img"
    itb = bootloader_dir / "u-boot.itb"
    if not idb.exists() or not itb.exists():
        raise FlashError(f"合成 spi.img 缺少 {idb} 或 {itb}")
    idb_b = idb.read_bytes()
    itb_b = itb.read_bytes()
    end = uboot_off + len(itb_b)
    if end > SPI_NOR_SIZE:
        raise FlashError(
            f"u-boot.itb 末端 {end} 超过 SPI 容量 {SPI_NOR_SIZE}（u-boot.itb 太大）")
    size = (end + SPI_IMG_ALIGN - 1) & ~(SPI_IMG_ALIGN - 1)
    buf = bytearray(size)
    buf[idbloader_off:idbloader_off + len(idb_b)] = idb_b
    buf[uboot_off:uboot_off + len(itb_b)] = itb_b
    out_path.write_bytes(buf)
    return out_path


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
    # 目标存储逻辑块大小：eMMC/SD 为 512，UFS 为 4096。缺省 512 向前兼容
    # 旧 flash-config.json。供 write_gpt 按扇区截取 GPT。
    sector_size: int = 512
    # 目标存储介质名（Rockchip upgrade_tool SSD 列表里的名字；UFS=SATA）。
    # 非空时 flash 在 DB 后用 SSD 切到该存储，否则用 loader 默认（eMMC/SPI）。
    storage: str = ""
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
            sector_size=data.get("sector_size", 512),
            storage=data.get("storage", ""),
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

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """整盘刷写钩子（如 edl-ng write-sector 整 raw.img）。

        返回 True 表示已处理（FlashExecutor 跳过 per-partition 循环）；
        默认返回 False，走传统的逐分区 write_partition 流程。
        Qualcomm 等"整盘写"平台覆盖此方法即可，零侵入现有平台。
        """
        return False

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

    _UDEV_HINT = (
        "upgrade_tool DB 无法打开 USB（Creating Comm Object failed）——maskrom 的 "
        "BootROM USB 需要 root 权限。\n"
        "  装 udev 规则（推荐，一次性，之后免 sudo）：\n"
        "    echo 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"2207\", MODE=\"0666\", "
        "GROUP=\"plugdev\"' | sudo tee /etc/udev/rules.d/99-rockchip.rules\n"
        "    sudo udevadm control --reload-rules && sudo udevadm trigger\n"
        "    然后拔插设备重进 maskrom；或临时改用 sudo 跑 flash。")

    def _download_boot(self, tool: Path, miniloader: Path):
        """DB 上传 miniloader；comm 失败时给 udev/权限提示而非裸 traceback。"""
        _info("上传 miniloader（DB）...")
        r = subprocess.run([str(tool), "DB", str(miniloader)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            if "Comm Object" in out:
                raise FlashError(self._UDEV_HINT)
            raise FlashError(f"upgrade_tool DB 失败（exit {r.returncode}）:\n{out}")
        time.sleep(1)

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # DB (Download Boot) 仅在 maskrom 模式下上传 loader；
        # 设备已在 loader 模式时跳过，避免 "did not support this operation"
        if device is None:
            device = self.detect_device(tool)
        if device and device.mode != "maskrom":
            _info(f"设备已在 {device.mode} 模式，跳过 DB")
        elif config.pre_flash.download_boot:
            miniloader = target_dir / config.pre_flash.download_boot
            if not miniloader.exists():
                raise FlashError(f"未找到 miniloader: {miniloader}")
            self._download_boot(tool, miniloader)
        # 切目标存储（UFS=SATA）。DB 后 loader 默认存储是 SPI/eMMC，不切则 WL
        # 会写错介质。eMMC/SD 板 storage 为空，保持 loader 默认、行为不变。
        if config.storage:
            self._switch_storage(tool, config.storage)

    @staticmethod
    def _parse_storage_no(ssd_output: str, name: str) -> Optional[str]:
        """从 ``upgrade_tool SSD`` 列表解析指定存储名的编号。

        列表行形如 ``No=9\tSATA(*)``，``(*)`` 是当前激活标记，须忽略。"""
        for line in ssd_output.splitlines():
            m = re.match(r"\s*No=(\d+)\s+(\S+)", line)
            if m and m.group(2).split("(")[0].upper() == name.upper():
                return m.group(1)
        return None

    def _switch_storage(self, tool: Path, name: str):
        """把 loader 当前存储切到 name（如 UFS 的 "SATA"）。"""
        # SSD 无参时进入交互列表；喂 Q 退出以仅取列表。
        listing = subprocess.run(
            [str(tool), "SSD"], input="Q\n",
            capture_output=True, text=True)
        no = self._parse_storage_no(listing.stdout, name)
        if no is None:
            raise FlashError(
                f"upgrade_tool SSD 列表中未找到存储 {name!r}；"
                f"输出:\n{listing.stdout}")
        _info(f"切换存储到 {name}（SSD {no}）...")
        subprocess.run([str(tool), "SSD", no], check=True)
        _ok(f"存储 → {name}")

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

    # GPT primary：protective MBR 在 LBA 0，GPT header 在 LBA 1，紧随 16KiB
    # entries array（128 entry × 128 B，与扇区大小无关）。rockchip upgrade_tool
    # 拒绝 WL 0（保护 boot region），跳过 protective MBR，从 LBA 1 起写
    # header + entries 即可让 kernel 看到完整分区表。
    GPT_HEADER_LBA = 1
    GPT_ENTRY_ARRAY_BYTES = 16384  # 128 × 128，GPT 标准定长

    def _gpt_slice(self, sector: int) -> tuple[int, int]:
        """返回从 raw.img 截取 primary GPT 的 (起始字节, 长度字节)。

        起始 = LBA1 × sector；长度 = 1 个扇区 header + 16KiB entries array。
        512 时 = 512 + 16384 = 16896 = 33×512，与旧写死 33 扇区一致；
        4096 时 = 4096 + 16384 = 20480。"""
        seek = self.GPT_HEADER_LBA * sector
        length = sector + self.GPT_ENTRY_ARRAY_BYTES
        return seek, length

    def _gpt_wl_offset(self, sector: int) -> int:
        """GPT header 写入设备的 upgrade_tool WL 偏移（单位恒为 512 字节）。

        GPT primary header 位于设备 byte = GPT_HEADER_LBA × sector（4K 设备
        即 byte 4096）。WL 偏移单位是 512 字节（实板证实：idbloader entry
        offset 0x40 经 WL 64 落到 byte 32KB），故 WL 偏移 =
        GPT_HEADER_LBA × sector ÷ 512。512 设备→1（历史一致，回归安全）；
        4096 设备→8。早期版本直接传逻辑 LBA(1) 导致 4K 上 header 被写到
        byte 512，u-boot 在 byte 4096 读到垃圾 → GPT signature 错 → abort。"""
        return self.GPT_HEADER_LBA * sector // 512

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        # UFS（di 路径）：分区表由 flash_whole_disk 的 `di -p parameter.txt`
        # 写入，loader 按 4K 建 GPT，这里不再 WL raw.img 的 GPT。
        if config.storage:
            return
        raw_img = target_dir / "image" / "raw.img"
        if not raw_img.exists():
            _warn(f"未找到 raw.img: {raw_img}，跳过 GPT 刷新（旧 GPT 可能丢失新分区）")
            return
        # 从 raw.img LBA 1 起截取 header + entries —— 跳过 protective MBR。
        # 扇区大小取自 flash-config（UFS=4096，eMMC/SD=512）。
        import tempfile
        sector = config.sector_size
        seek, size = self._gpt_slice(sector)
        wl_offset = self._gpt_wl_offset(sector)
        with tempfile.NamedTemporaryFile(suffix=".gpt.bin", delete=False) as tmp:
            with raw_img.open("rb") as f:
                f.seek(seek)
                tmp.write(f.read(size))
            tmp_path = Path(tmp.name)
        try:
            _info(f"刷新 GPT 表（WL {wl_offset}, "
                  f"扇区 {sector}, {size // 1024}KB）...")
            subprocess.run(
                [str(tool), "WL", str(wl_offset), str(tmp_path)],
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

    # upgrade_tool di 的已定义分区缩写；未列出的分区用 -<分区名> 指定。
    DI_FLAGS = {
        "uboot": "-u", "boot": "-b", "recovery": "-r",
        "kernel": "-k", "misc": "-m", "trust": "-t", "system": "-s",
    }

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """UFS（di 路径）：`di -p parameter.txt` 建 GPT + `di -<abbr> img`
        逐分区，由 loader 按 4K 落盘。返回 True 跳过基类的逐分区 WL。

        非 UFS 板（config.storage 为空）返回 False，走传统 WL 逐分区。"""
        if not config.storage:
            return False
        param = target_dir / "parameter.txt"
        if not param.exists():
            raise FlashError(
                f"未找到 parameter.txt: {param}（UFS 刷写需要它，请重新 build）")
        _info("写分区表（di -p parameter.txt）...")
        subprocess.run([str(tool), "DI", "-p", str(param)], check=True)
        _ok("parameter/GPT")
        for part in config.partitions:
            image = target_dir / part.image
            if not image.exists():
                _info(f"跳过 {part.name}: {image} 不存在")
                continue
            flag = self.DI_FLAGS.get(part.name, f"-{part.name}")
            _info(f"写 {part.name}（di {flag}）...")
            subprocess.run([str(tool), "DI", flag, str(image)], check=True)
            _ok(part.name)
        return True

    def flash_spi_firmware(self, tool: Path, target_dir: Path,
                           device: Optional["DeviceInfo"] = None):
        """架构 A2：把合成的 spi.img（idbloader@32KiB + u-boot.itb@8MiB）写进
        SPI NOR。流程：DB miniloader → SSD SPINOR → WL 0 spi.img → RD。

        spi.img 由 build_spi_image 在构建期生成（board 声明 flash_spi_loader）。
        device 由调用方（wait_for_device）传入，避免在 DB 前再跑一次 LD 导致
        upgrade_tool "Creating Comm Object failed!"（与 pre_flash 同款契约）。"""
        spi = target_dir / "bootloader" / "spi.img"
        if not spi.exists():
            raise FlashError(
                f"未找到 spi.img: {spi}（board 需声明 flash_spi_loader 并重新 build）")
        if device is None:
            device = self.detect_device(tool)
        miniloader = target_dir / "bootloader" / "miniloader.bin"
        if device and device.mode == "maskrom" and miniloader.exists():
            self._download_boot(tool, miniloader)
        self._switch_storage(tool, "SPINOR")
        _info("写 SPI 启动固件（WL 0 spi.img）...")
        subprocess.run([str(tool), "WL", "0", str(spi)], check=True)
        _ok("spi.img")
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
        # amp 协处理器固件：启用时纳入刷写映射，使 flash-config.json 含 amp、
        # `flange flash amp` 可单刷（仿 recovery 的 enabled gate）。
        if (config.get("amp") or {}).get("enabled", False):
            m["amp"] = "amp/amp.img"
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
        """pyamlboot 把 u-boot 推到 SoC DDR；板已在 fastboot 模式时跳过。

        ``detect_device`` 已能区分 MaskROM 与 fastboot 两种模式：
          - ``mode="maskrom"``：板刚通过 KEY1 + USB-C 进 BootROM，需要走完整
            的 pyamlboot 推送流程把 u-boot 上 DDR；
          - ``mode="fastboot"``：板已经在 u-boot fastboot gadget 模式（典型
            场景：上一轮 ``flange flash`` 用 ``fastboot reboot bootloader``
            重回 fastboot，或 Linux 跑 ``reboot bootloader`` 后 u-boot
            PREBOOT 检测 reboot_mode 自动进 fastboot）。此时 u-boot 已在
            DDR 跑，直接进 flash 分区流程即可。

        跳过 pyamlboot 不仅省一次 sudo 提示 + ~3s 推送时间，更关键的是
        避免要求用户接串口手动敲 ``fastboot usb 0`` —— PREBOOT 条件触发
        让 u-boot 自动进 fastboot，host 端 ``flange flash`` 就能纯 USB
        无人值守完成。
        """
        if device is not None and device.mode == "fastboot":
            _info("板已在 fastboot 模式（u-boot 已在 DDR），跳过 pyamlboot 推送")
            return

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
        """``fastboot oem format`` 让 u-boot 按实际 eMMC 容量重建 GPT。

        u-boot 端约定（详见 components/platform/amlogic/s905d3/patches/
        bootloader/flange_fastboot.config）：
          - PREBOOT 设 ``partitions`` env，含 user area GPT 分区描述
            （boot + rootfs；bootloader 在 hw boot0 不入 user area GPT）
          - ``CONFIG_FASTBOOT_CMD_OEM_FORMAT=y`` 启 ``oem format`` 子命令
          - ``CONFIG_CMD_GPT=y`` + ``CONFIG_RANDOM_UUID=y`` 提供 gpt write
            子命令与 UUID 生成
        ``oem format`` 内部直接调 ``gpt write mmc <FASTBOOT_FLASH_MMC_DEV>
        ${partitions}`` —— 按当前 mmc dev 容量计算 LBA / size，避开
        "raw.img GPT 字段指向 2GB 但 eMMC 14.6GB" 的尺寸不匹配问题，写完
        u-boot 自动 rescan 分区表，后续 ``flash boot/rootfs`` 立即可找到
        分区。本步骤必须在 ``fastboot flash boot/rootfs`` 之前。
        """
        _info("用 u-boot oem format 按实际 eMMC 容量重建 GPT...")
        self._run_fastboot(tool, "oem", "format")
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


class QualcommFlashStrategy(FlashStrategy):
    """Qualcomm QCS6490 刷写策略 —— EDL 模式 + edl-ng（flange 首个高通刷写）。

    - 系统盘：``edl-ng --memory UFS write-sector 0 raw.img``（整盘，契合 flange raw.img）。
    - SPI EDK2 固件（bring-up 一次）：``edl-ng --loader prog_firehose_ddr.elf
      --memory spinor rawprogram rawprogram0.xml patch0.xml``。
    - EDL 模式需手动进入（按住 EDL 按钮 + USB3 上电）。
    """

    EDL_USB = "05c6:9008"  # Qualcomm HS-USB QDLoader 9008

    def find_tool(self, project_dir: Path) -> Path:
        """按 rockchip 同款约定 ``tools/<os>/<tool>/<tool>`` 定位；PATH 兜底。"""
        import shutil
        platform = "macos" if sys.platform == "darwin" else "linux"
        tool = project_dir / "tools" / platform / "edl-ng" / "edl-ng"
        if tool.exists():
            return tool
        exe = shutil.which("edl-ng")
        if exe:
            return Path(exe)
        raise FlashError(
            f"未找到 edl-ng。预期 {tool} 或 PATH。\n"
            "Radxa 下载：https://dl.radxa.com/q6a/images/edl-ng-dist.zip")

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """被动 USB 枚举探测 EDL 9008（不调 edl-ng，避免抢 USB 会话）。

        起因：macOS 上若 detect 先用 edl-ng 开一次 USB 会话，紧接 write-sector
        再开一次，libusb darwin 偶发 transfer timed out + Sahara 握手失败、
        设备进入 Unknown 模式。这里只读 USB 拓扑信息（VID 05c6/PID 9008），
        不触碰设备，让 edl-ng 在真正刷写时独占会话。
        """
        if sys.platform == "darwin":
            # 用 ioreg（底层实时）而非 system_profiler（有缓存延迟、可能漏报）；
            # 匹配 idVendor=1478(0x05c6) + idProduct=36872(0x9008)。
            try:
                r = subprocess.run(["ioreg", "-p", "IOUSB", "-l"],
                                   capture_output=True, text=True, timeout=5)
                out = r.stdout
                if '"idVendor" = 1478' in out and '"idProduct" = 36872' in out:
                    return DeviceInfo(platform="qualcommqcs6490", mode="edl",
                                      description="Qualcomm HS-USB QDLoader 9008")
            except Exception:
                pass
        else:  # linux：读 /sys/bus/usb/devices
            try:
                for dev in Path("/sys/bus/usb/devices").glob("*"):
                    vid = dev / "idVendor"
                    pid = dev / "idProduct"
                    if vid.exists() and pid.exists():
                        if vid.read_text().strip() == "05c6" and \
                           pid.read_text().strip() == "9008":
                            return DeviceInfo(platform="qualcommqcs6490",
                                              mode="edl",
                                              description="Qualcomm HS-USB QDLoader 9008")
            except Exception:
                pass
        return None

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # 系统盘刷写无需 pre_flash；SPI EDK2 固件单刷见 flash_spi_firmware（bring-up）。
        pass

    def write_partition(self, tool: Path, offset: int, image: Path):
        # Qualcomm 走整盘 write-sector（见 write_system_image），不逐分区写入。
        pass

    def reboot(self, tool: Path):
        try:
            subprocess.run([str(tool), "reset"], timeout=15)
        except Exception:
            _info("请手动断电重启 Q6A（退出 EDL 模式）")

    def partition_image_map(self, config: dict) -> dict[str, str]:
        # 整盘 raw.img 经 edl-ng write-sector 刷入；映射仅作 flash-config 元数据。
        return {"system": "image/raw.img"}

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """整盘 edl-ng write-sector raw.img 到 UFS/eMMC（先 Sahara 上传 firehose loader）。"""
        raw = target_dir / "image" / "raw.img"
        if not raw.exists():
            raise FlashError(f"未找到整盘镜像 {raw}；请先执行 flange build")
        loader = self._locate_loader(target_dir)
        # 目标存储介质：v1 仅 UFS（板子默认）；后续可经 board/SoC config 覆盖。
        memory = "UFS"
        self.write_system_image(tool, raw, loader=loader, memory=memory)
        return True

    def _locate_loader(self, target_dir: Path) -> Path:
        """定位 firehose loader（Radxa EDK2 SPI 固件包内）。"""
        loader = target_dir / "bootloader" / "edk2-spi-firmware" / "prog_firehose_ddr.elf"
        if not loader.exists():
            raise FlashError(
                f"未找到 firehose loader {loader}；请先执行 flange build "
                "（bootloader 组件会下载并解压 Radxa EDK2 SPI 固件包，含此 loader）")
        return loader

    # ---- Qualcomm 专有（供 flash 编排 edl-ng 分支调用；非 ABC）----

    def write_system_image(self, tool: Path, raw_img: Path,
                           loader: Path, memory: str = "UFS"):
        """整盘写系统镜像。EDL 启动后处于 Sahara 模式，需先上传 firehose loader
        让设备进入 firehose 模式，再发 write-sector 指令。"""
        _step(f"edl-ng write-sector → {memory}（loader: {loader.name}）")
        cmd = [str(tool), "--loader", str(loader),
               "--memory", memory, "write-sector", "0", str(raw_img)]
        if subprocess.run(cmd).returncode != 0:
            raise FlashError("edl-ng write-sector 失败")

    def flash_spi_firmware(self, tool: Path, target_dir: Path,
                           device: Optional["DeviceInfo"] = None,
                           memory: str = "spinor"):
        """bring-up 一次性：刷 Radxa 预编 EDK2 SPI 固件。device 参数与 Rockchip
        签名对齐（Qualcomm 走 edl，不用它）。"""
        edk2_dir = target_dir / "bootloader" / "edk2-spi-firmware"
        loader = edk2_dir / "prog_firehose_ddr.elf"
        _step("edl-ng rawprogram → SPI EDK2 固件")
        cmd = [str(tool), "--loader", str(loader), "--memory", memory,
               "rawprogram", "rawprogram0.xml", "patch0.xml"]
        if subprocess.run(cmd, cwd=str(edk2_dir)).returncode != 0:
            raise FlashError("edl-ng SPI 固件刷写失败")


# 策略注册表
_FLASH_STRATEGIES: dict[str, type[FlashStrategy]] = {
    "rockchip": RockchipFlashStrategy,
    "allwinnera733": AllwinnerA733FlashStrategy,
    "amlogic": AmlogicFlashStrategy,
    "qualcommqcs6490": QualcommFlashStrategy,
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
            sector_size=int(config.get("partitions", {}).get("sector_size", 512)),
            storage=config.get("flash_storage", ""),
            partitions=partitions,
            pre_flash=pre_flash,
        )

        output = target_dir / "flash-config.json"
        flash_config.to_json(output)

        # 为带 flash_storage（UFS）的 rockchip 板生成 parameter.txt，供刷写时
        # `upgrade_tool di -p` 在目标存储上按 4K 建 GPT。eMMC/SD 板不生成，
        # 沿用逐分区 WL + write_gpt 路径。
        if config.get("flash_storage") and config.get("platform") == "rockchip":
            entries = config.get("partitions", {}).get("entries", [])
            machine = config.get("rkbin", {}).get("mkimage_chip", "RK3576").upper()
            (target_dir / "parameter.txt").write_text(
                generate_parameter_txt(entries, machine=machine))

        # SPI 启动固件 spi.img → `flange flash --spi-firmware` 写入 SPI NOR。两条路:
        #  (a) prebuilt_spi_image：直接用 radxa bsp 预编的整体 spi.img（RK3576 ROCK
        #      4D —— RK3576 idbloader 须 boot_merger 装配含 rk3576_boost，flange 通用
        #      mkimage rksd 路径缺 boost → SPL 环境不全、u-boot 读 UFS 崩；详见 design）。
        #  (b) flash_spi_loader：flange 自编 idbloader+u-boot.itb 合成（eMMC/SD 板）。
        prebuilt = config.get("bootloader", {}).get("prebuilt_spi_image")
        spi_out = target_dir / "bootloader" / "spi.img"
        if prebuilt and config.get("platform") == "rockchip":
            # prebuilt_spi_image = {url, sha256}：从 radxa 官方下载（不入库 16MB
            # blob），ensure_prebuilt_image 原子下载 + sha256 校验、缓存到
            # .build/sources/prebuilt（幂等，缓存命中无网亦可）。
            from builder.source import SourceManager
            from builder.paths import BUILD_ROOT, PROJECT_ROOT
            src = SourceManager(sources_dir=BUILD_ROOT / "sources",
                                project_root=PROJECT_ROOT)
            img_path = src.ensure_prebuilt_image(
                config.get("board", "prebuilt"), prebuilt)
            spi_out.parent.mkdir(parents=True, exist_ok=True)
            data = img_path.read_bytes()
            # SPINOR 实际可写略少于 16MB 标称（末端 GPT backup ~33 扇区不可写）；官方
            # 预编 spi.img 填满 16MB 会触发 upgrade_tool "partition too small"，截到可
            # 写上限内即可——idbloader/u-boot.itb/primary GPT 都在头部保留，BootROM 按
            # 固定偏移找 idbloader 不依赖 GPT（flange 自编 spi.img 本就无 GPT 也能启动）。
            cap = SPI_NOR_SIZE - SPI_IMG_ALIGN
            spi_out.write_bytes(data[:cap] if len(data) > cap else data)
        elif config.get("flash_spi_loader") and config.get("platform") == "rockchip":
            build_spi_image(target_dir / "bootloader", spi_out)

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
        # 整盘刷写钩子（如 Qualcomm edl-ng write-sector raw.img）：返回 True
        # 表示已处理，跳过 per-partition 循环；默认 False，走逐分区流程。
        if not self.strategy.flash_whole_disk(tool, self.target_dir, cfg):
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
    run_parser.add_argument("--spi-firmware", action="store_true", dest="spi_firmware",
                            help="刷 SPI boot 固件（Qualcomm bring-up 一次性；需在 EDL 模式）")
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
        elif args.spi_firmware:
            # Qualcomm bring-up：edl-ng 刷 SPI EDK2 固件（仅支持该方法的策略）
            if not hasattr(executor.strategy, "flash_spi_firmware"):
                raise FlashError(
                    f"平台 {executor.config.platform} 不支持 --spi-firmware")
            tool = executor.strategy.find_tool(executor.project_dir)
            device = None
            if not args.no_wait:
                device = executor.strategy.wait_for_device(tool)
            executor.strategy.flash_spi_firmware(tool, executor.target_dir, device)
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
