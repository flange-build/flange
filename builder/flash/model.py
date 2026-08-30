"""刷写数据模型（**构建期与执行期共享**）。

`flash-config.json` 的 schema 就是这里的 dataclass —— 构建期由
`builder.flash.generate` 写出，执行期由 `builder.flash.execute` 读入。
两侧共享同一份定义，schema 才不会各自漂移。

因为构建期产物依赖它，本模块**进**构建逻辑指纹。
"""

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


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
    # MTD/GPT 分区容量（512B sector 字符串）；旧配置缺省为空。
    size: str = ""


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
class FlashIdentityConfig:
    """首次持久写入前用于匹配 Rockchip 芯片与存储介质的正则。"""

    chip_patterns: list[str] = field(default_factory=list)
    storage_patterns: list[str] = field(default_factory=list)
    require_rid: bool = False


@dataclass
class FlashConfig:
    """flash-config.json 的完整数据模型。"""
    platform: str
    flash_tool: str
    board: str
    product: str
    variant: str
    # SoC 身份用于 Rockchip 首次持久写入前的设备校验；空值兼容旧清单。
    soc: str = ""
    # 目标存储逻辑块大小：eMMC/SD 为 512，UFS 为 4096。缺省 512 向前兼容
    # 旧 flash-config.json。供 write_gpt 按扇区截取 GPT。
    sector_size: int = 512
    # 目标存储介质名（Rockchip upgrade_tool SSD 列表里的名字；UFS=SATA）。
    # 非空时 flash 在 DB 后用 SSD 切到该存储，否则用 loader 默认（eMMC/SPI）。
    storage: str = ""
    # 存储介质类型（如 spinand）。与 SSD 展示名称分离，避免用工具输出文案
    # 决定 NAND 坏块安全的具名 DI 路由。
    storage_type: str = ""
    # 分区配置模型：gpt（由 entries 生成）或兼容旧 mtd parameter。
    partition_format: str = "gpt"
    # parameter 相对 target_dir 的路径与存储总容量；SPI NAND 的 GPT 配置
    # 同样生成 parameter 并记录 rootfs MTD index。
    parameter: str = ""
    storage_size: str = ""
    rootfs_mtd_index: Optional[int] = None
    # parameter 内容摘要。具名 DI 路由必须校验，避免 parameter 与清单布局漂移。
    parameter_sha256: str = ""
    partitions: list[FlashPartition] = field(default_factory=list)
    pre_flash: PreFlashConfig = field(default_factory=PreFlashConfig)
    identity: FlashIdentityConfig = field(default_factory=FlashIdentityConfig)

    def to_json(self, path: Path):
        """原子序列化为 JSON 文件。"""
        data = asdict(self)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            path,
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        )

    @classmethod
    def from_json(cls, path: Path) -> "FlashConfig":
        """从 JSON 文件反序列化。"""
        data = json.loads(path.read_text())
        partitions = [FlashPartition(**p) for p in data.get("partitions", [])]
        pre_flash = PreFlashConfig(**data.get("pre_flash", {}))
        identity = FlashIdentityConfig(**data.get("identity", {}))
        return cls(
            platform=data["platform"],
            flash_tool=data["flash_tool"],
            board=data["board"],
            product=data["product"],
            variant=data["variant"],
            soc=data.get("soc", ""),
            sector_size=data.get("sector_size", 512),
            storage=data.get("storage", ""),
            storage_type=data.get("storage_type", ""),
            partition_format=data.get("partition_format", "gpt"),
            parameter=data.get("parameter", ""),
            storage_size=data.get("storage_size", ""),
            rootfs_mtd_index=data.get("rootfs_mtd_index"),
            parameter_sha256=data.get("parameter_sha256", ""),
            partitions=partitions,
            pre_flash=pre_flash,
            identity=identity,
        )


class FlashError(Exception):
    """刷写过程中的错误。"""
    pass


def _atomic_write_text(path: Path, content: str) -> None:
    """在同目录写临时文件并原子替换，失败时不暴露半写产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@dataclass
class DeviceInfo:
    """检测到的设备信息。"""
    platform: str
    mode: str         # "maskrom", "loader" 等
    description: str

