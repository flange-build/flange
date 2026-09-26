"""Qualcomm UFS 多 LUN 启动固件刷写包（构建期校验与宿主机刷写共用）。

RUBIK Pi 3 等板的 XBL / UEFI / TZ 等签名固件位于 UFS boot LUN（1-5），系统盘
位于 LUN0。``flange flash`` 以一次 ``edl-ng rawprogram`` 会话同时写入：

- 启动固件：板级 ``bootloader.ufs_rawprogram`` / ``ufs_patch`` 声明的官方
  rawprogramN.xml / patchN.xml（N ≥ 1），引用预编固件包内的文件；
- 系统盘：本模块生成的 ``rawprogram0.xml``，把 ``image/raw.img`` 写到 LUN0 扇区 0；
- dtb 分区：UEFI 从 ``dtb_a`` 读取的 ``dtb.bin`` 由 boot 组件用当前内核 DTB 生成。

LUN0 只由 flange 系统盘占用：固件 XML 不得写 LUN0，避免两份 GPT 互相覆盖。
"""

import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from builder.flash.model import FlashConfig, FlashError

#: 固件包根目录与系统盘，均相对 target_dir。
FIRMWARE_DIR = "bootloader/edk2-spi-firmware"
SYSTEM_IMAGE = "image/raw.img"
#: 生成的 LUN0 系统盘清单与暂存名；与官方固件包内文件名区分，避免冲突。
SYSTEM_XML = "rawprogram0.xml"
SYSTEM_STAGED = "flange-system.img"
#: rawprogram 中由 flange 组件产出、而非预编固件包提供的文件。
COMPONENT_IMAGES = {"dtb.bin": "boot/dtb.bin"}
#: Git LFS 指针文件头：GitHub 归档包不含 LFS 真实内容，误刷会写坏分区。
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"


@dataclass(frozen=True)
class Program:
    """rawprogram XML 中的一条写入。"""

    xml: str
    label: str
    lun: str
    filename: str
    sector_size: int


def read_programs(xml_path: Path) -> list[Program]:
    """解析 rawprogram XML；filename 只能是同目录单个文件名。"""
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise FlashError(f"无法解析 {xml_path}: {exc}") from exc
    programs = []
    for node in root.iter("program"):
        filename = node.get("filename", "")
        if filename and PurePosixPath(filename).name != filename:
            raise FlashError(f"{xml_path.name} 引用了非本目录文件: {filename!r}")
        try:
            sector_size = int(node.get("SECTOR_SIZE_IN_BYTES", ""))
        except ValueError as exc:
            raise FlashError(f"{xml_path.name} 的 {node.get('label')} 缺少扇区大小") from exc
        programs.append(Program(
            xml=xml_path.name,
            label=node.get("label", ""),
            lun=node.get("physical_partition_number", ""),
            filename=filename,
            sector_size=sector_size,
        ))
    return programs


def is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


def check_firmware_bundle(
    firmware_dir: Path, rawprogram: list[str], patch: list[str], sector_size: int | None
) -> list[Program]:
    """校验预编固件包能被声明的 XML 完整、安全地刷写。

    COMPONENT_IMAGES 中的文件由其他组件提供，这里不检查其存在性。bootloader
    构建期看不到分区配置，``sector_size`` 传 None 时跳过扇区大小核对。
    """
    if SYSTEM_XML in rawprogram:
        raise FlashError(f"{SYSTEM_XML} 由 flange 生成（LUN0 系统盘），不能出现在 ufs_rawprogram")
    for name in [*rawprogram, *patch]:
        if not (firmware_dir / name).is_file():
            raise FlashError(f"固件包缺少声明的 {name}: {firmware_dir}")
    for name in patch:
        try:
            nodes = list(ET.parse(firmware_dir / name).getroot().iter("patch"))
        except ET.ParseError as exc:
            raise FlashError(f"无法解析 {name}: {exc}") from exc
        if any(node.get("physical_partition_number") == "0" for node in nodes):
            raise FlashError(f"{name} 修改 LUN0；LUN0 GPT 只允许来自 flange 系统盘")
    programs = [program for name in rawprogram
                for program in read_programs(firmware_dir / name)]
    for program in programs:
        where = f"{program.xml}:{program.label}"
        if program.lun == "0":
            raise FlashError(f"{where} 写入 LUN0；LUN0 只允许 flange 系统盘")
        if sector_size is not None and program.sector_size != sector_size:
            raise FlashError(
                f"{where} 扇区大小 {program.sector_size} 与分区配置 {sector_size} 不一致")
        if not program.filename or program.filename in COMPONENT_IMAGES:
            continue
        if program.filename == SYSTEM_STAGED:
            raise FlashError(f"{where} 引用了保留文件名 {SYSTEM_STAGED}")
        source = firmware_dir / program.filename
        if not source.is_file():
            raise FlashError(f"{where} 引用的 {program.filename} 不在固件包内")
        if is_lfs_pointer(source):
            raise FlashError(
                f"{where} 引用的 {program.filename} 是 Git LFS 指针而非真实固件；"
                "请从 ufs_rawprogram 移除该 XML 或改用包含 LFS 内容的固件包")
    return programs


def system_program_xml(size: int, sector_size: int) -> str:
    """生成把整盘镜像写到 LUN0 扇区 0 的 rawprogram0.xml。"""
    sectors = size // sector_size
    return (
        '<?xml version="1.0" ?>\n'
        "<data>\n"
        f'  <program SECTOR_SIZE_IN_BYTES="{sector_size}" file_sector_offset="0"'
        f' filename="{SYSTEM_STAGED}" label="flange-system"'
        f' num_partition_sectors="{sectors}" partofsingleimage="false"'
        ' physical_partition_number="0" readbackverify="false"'
        f' size_in_KB="{size // 1024}.0" sparse="false" start_byte_hex="0x0"'
        ' start_sector="0"/>\n'
        "</data>\n"
    )


def _bundle_sources(target_dir: Path, config: FlashConfig) -> dict[str, Path]:
    """返回暂存目录文件名 → 实际产物路径，并完成全部本地校验。"""
    firmware = config.ufs_firmware
    firmware_dir = target_dir / FIRMWARE_DIR
    loader = firmware_dir / firmware.loader
    if not firmware.loader or not loader.is_file():
        raise FlashError(f"未找到 firehose loader：{loader}；请先执行 flange build bootloader")
    programs = check_firmware_bundle(
        firmware_dir, firmware.rawprogram, firmware.patch, config.sector_size)
    raw = target_dir / SYSTEM_IMAGE
    if not raw.is_file():
        raise FlashError(f"未找到整盘镜像 {raw}；请先执行 flange build")
    if raw.stat().st_size % config.sector_size:
        raise FlashError(f"{raw} 大小不是 {config.sector_size} 字节扇区的整数倍")

    sources = {name: firmware_dir / name for name in [*firmware.rawprogram, *firmware.patch]}
    for program in programs:
        if not program.filename:
            continue
        component = COMPONENT_IMAGES.get(program.filename)
        source = target_dir / component if component else firmware_dir / program.filename
        if not source.is_file():
            raise FlashError(f"{program.xml}:{program.label} 需要的 {source} 不存在；请先执行 flange build")
        sources[program.filename] = source
    sources[SYSTEM_STAGED] = raw
    return sources


def validate_bundle(target_dir: Path, config: FlashConfig) -> None:
    """设备写入前的本地 preflight：不等待设备、不写任何分区。"""
    _bundle_sources(target_dir, config)


def stage_bundle(target_dir: Path, config: FlashConfig, stage_dir: Path) -> list[str]:
    """在 stage_dir 组装刷写目录，返回 edl-ng rawprogram 的 XML 参数。

    patch XML 含 ``filename="gpt_mainN.bin"`` 的主机侧文件补丁；为免刷写工具经
    符号链接改写已发布产物，固件与 dtb.bin 一律复制。只有多 GB 的系统盘用符号
    链接——没有任何 patch 指向它。
    """
    for name, source in _bundle_sources(target_dir, config).items():
        if name == SYSTEM_STAGED:
            os.symlink(source.resolve(), stage_dir / name)
        else:
            shutil.copyfile(source, stage_dir / name)
    raw_size = (target_dir / SYSTEM_IMAGE).stat().st_size
    (stage_dir / SYSTEM_XML).write_text(system_program_xml(raw_size, config.sector_size))
    return [SYSTEM_XML, *config.ufs_firmware.rawprogram, *config.ufs_firmware.patch]
