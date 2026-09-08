"""UNO Q 的 QDL（高通下载工具）发布包、GPT 校验与宿主刷写。

仅接受官方 UNO Q 救援布局，所有动态 GPT 更新在宿主内存中完成。
不执行上游 patch XML，不把空文件引用解释为擦除，也不使用 allow-missing。
"""

import copy
import hashlib
import json
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from builder.flash.model import (
    DeviceInfo, FlashConfig, FlashError, FlashPartition, PreFlashConfig,
)
from builder.flash.plan import UnoQFlashPlan
from builder.flash.strategy import FlashStrategy

SECTOR = 512
BUNDLE_PATH = "image/flash-bundle"
MANIFEST = "manifest.json"
LOADER = "prog_firehose_ddr.elf"
ROOT_START = 2033984
EFI_START = 985408
USER_START = 22954552
PRESERVED = {"persist", "modemst1", "modemst2", "fsg", "fsc", "ssd",
             "devinfo", "keystore", "frp", "uefivarstore"}
SYSTEM_IMAGES = {
    "boot_a": "uboot-boot.img", "boot_b": "uboot-boot.img",
    "efi": "efi.img", "rootfs": "rootfs.img", "userdata": "userdata.img",
}


def digest(path: Path) -> str:
    """流式摘要避免把数 GiB 镜像读入内存。"""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def edl_serial(product: str) -> str:
    """QDL v2.4 按 iProduct 的 _SN: 字段匹配，而不是 USB iSerialNumber。"""
    match = re.search(r"_SN:([0-9a-fA-F]{1,16})(?:[ _]|$)", product)
    return match[1] if match else ""


def safe_file(root: Path, name: str) -> Path:
    """拒绝绝对路径、穿越、任何符号链接和非常规文件。"""
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute()
            or any(part in {".", ".."} for part in name.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)):
        raise FlashError(f"不安全的 QDL 文件路径: {name!r}")
    candidate = root
    if root.is_symlink():
        raise FlashError(f"QDL 发布目录不能是符号链接: {root}")
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise FlashError(f"QDL 文件不能经过符号链接: {candidate}")
    if not candidate.is_file():
        raise FlashError(f"缺少 QDL 必需文件: {candidate}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise FlashError(f"QDL 文件逃逸发布目录: {name}")
    return candidate


def read_xml(path: Path, tag: str, child: str) -> ET.Element:
    """只允许平坦的已知 XML，禁止 DTD（文档类型定义）和外部实体。"""
    if path.stat().st_size > 1024 * 1024:
        raise FlashError(f"QDL XML 超出大小限制: {path}")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FlashError(f"QDL XML 必须使用 UTF-8: {path}") from exc
    clean = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if len(data) > 1024 * 1024 or "\0" in text or "<!" in clean:
        raise FlashError(f"不允许的 QDL XML 声明: {path}")
    encoding = re.search(r"<\?xml\s+[^?]*encoding=['\"]([^'\"]+)", clean)
    if encoding and encoding[1].lower() not in {"utf-8", "utf8"}:
        raise FlashError(f"QDL XML 必须声明 UTF-8: {path}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FlashError(f"QDL XML 无效: {path}: {exc}") from exc
    if root.tag != tag or root.attrib or any(n.tag != child or len(n) for n in root):
        raise FlashError(f"不允许的 QDL XML 指令: {path}")
    return root


def number(text: str, *, allow_end=False, total=None) -> int:
    """只解析十进制扇区与唯一受支持的末尾 GPT 表达式。"""
    if re.fullmatch(r"[0-9]+", text or ""):
        return int(text)
    if allow_end and text == "NUM_DISK_SECTORS-33." and total is not None:
        return total - 33
    raise FlashError(f"不支持的 QDL 数值表达式: {text!r}")


@dataclass(frozen=True)
class GptEntry:
    name: str
    first: int
    last: int
    type_guid: bytes
    unique_guid: bytes
    index: int

    @property
    def sectors(self):
        return self.last - self.first + 1


@dataclass
class Gpt:
    data: bytes
    header: bytes
    entries_raw: bytes
    entries: dict[str, GptEntry]
    current: int
    alternate: int
    first_usable: int
    last_usable: int
    table_lba: int
    backup: bool

    @property
    def sectors(self):
        return (self.current if self.backup else self.alternate) + 1


def parse_gpt(data: bytes, *, backup=False, template=False) -> Gpt:
    """验证 GPT 两类元数据 CRC、分区范围、重叠和唯一性。"""
    expected = 33 * SECTOR if backup else 34 * SECTOR
    if len(data) != expected:
        raise FlashError(f"GPT 长度不符: {len(data)}，预期 {expected}")
    if not backup and (data[510:512] != b"\x55\xaa" or data[450] != 0xee):
        raise FlashError("GPT 缺少保护 MBR")
    offset = 32 * SECTOR if backup else SECTOR
    header = bytearray(data[offset:offset + 92])
    if header[:8] != b"EFI PART" or struct.unpack_from("<II", header, 8) != (0x10000, 92):
        raise FlashError("GPT 签名或版本不支持，请先用官方工具恢复 UNO Q")
    header_crc = struct.unpack_from("<I", header, 16)[0]
    struct.pack_into("<I", header, 16, 0)
    if zlib.crc32(header) != header_crc:
        raise FlashError("GPT header CRC 不符")
    current, alternate, first, last = struct.unpack_from("<4Q", header, 24)
    table_lba, count, entry_size, table_crc = struct.unpack_from("<QIII", header, 72)
    if count != 72 or entry_size != 128:
        raise FlashError("不是已支持的 UNO Q GPT 分区表格式（72 × 128）")
    total = (current if backup else alternate) + 1
    if ((alternate if backup else current) != 1 or first != 34
            or last != total - 34 or table_lba != (total - 33 if backup else 2)):
        raise FlashError("GPT 主备位置或可用容量不一致")
    start = 0 if backup else 2 * SECTOR
    entries_raw = data[start:start + count * entry_size]
    if zlib.crc32(entries_raw) != table_crc:
        raise FlashError("GPT 分区数组 CRC 不符")
    entries = {}
    unique = set()
    ordered = []
    for i in range(count):
        entry = entries_raw[i * 128:(i + 1) * 128]
        if entry[:16] == bytes(16):
            continue
        try:
            name = entry[56:128].decode("utf-16-le").rstrip("\0")
        except UnicodeError as exc:
            raise FlashError("GPT 分区名编码无效") from exc
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name) or name in entries:
            raise FlashError(f"GPT 分区名无效或重复: {name!r}")
        begin, end = struct.unpack_from("<QQ", entry, 32)
        empty_user = template and name == "userdata" and end == begin - 1
        if begin < first or end > last or (end < begin and not empty_user):
            raise FlashError(f"GPT 分区越界: {name}")
        if entry[16:32] == bytes(16) or entry[16:32] in unique:
            raise FlashError("GPT 分区 GUID 为空或重复")
        unique.add(entry[16:32])
        item = GptEntry(name, begin, end, entry[:16], entry[16:32], i)
        entries[name] = item
        if not empty_user:
            ordered.append(item)
    ordered.sort(key=lambda e: e.first)
    for left, right in zip(ordered, ordered[1:]):
        if left.last >= right.first:
            raise FlashError(f"GPT 分区重叠: {left.name}/{right.name}")
    return Gpt(data, data[offset:offset + 92], entries_raw, entries,
               current, alternate, first, last, table_lba, backup)


def validate_pair(primary: Gpt, backup: Gpt):
    """主备 GPT 必须描述同一个盘与完全相同的分区数组。"""
    if (primary.backup or not backup.backup
            or primary.sectors != backup.sectors
            or primary.header[56:72] != backup.header[56:72]
            or primary.entries_raw != backup.entries_raw):
        raise FlashError("主备 GPT 不一致，拒绝写入")


def validate_unoq(table: Gpt, *, observed=False):
    """布局事实来自已固定的 251020 官方救援包，而不是通用 9008 身份。"""
    expected = {"boot_a": (166400, 8192), "boot_b": (174592, 8192),
                "efi": (EFI_START, 1048576), "rootfs": (ROOT_START, USER_START - ROOT_START)}
    for name, (start, size) in expected.items():
        part = table.entries.get(name)
        size_matches = part is not None and (part.sectors == size or (
            observed and name == "rootfs" and part.sectors >= size))
        if part is None or part.first != start or not size_matches:
            raise FlashError(f"不是已支持的 UNO Q 官方分区布局: {name}")
    if not PRESERVED.issubset(table.entries) or table.entries.get("userdata") is None:
        raise FlashError("UNO Q GPT 缺少持久化分区")
    expected_user = table.entries["rootfs"].last + 1 if observed else USER_START
    if table.entries["userdata"].first != expected_user:
        raise FlashError("UNO Q userdata 起点不兼容；请先备份并用官方工具恢复布局")


def resize_gpt(primary: Gpt, sectors: int) -> tuple[bytes, bytes]:
    """保留全部分区标识/起点，仅扩展末尾 userdata 并重算主备 CRC。"""
    if sectors < primary.entries["userdata"].first + 33 + 1:
        raise FlashError("目标容量不足以容纳 UNO Q 分区布局")
    entries = bytearray(primary.entries_raw)
    user = primary.entries["userdata"]
    struct.pack_into("<Q", entries, user.index * 128 + 40, sectors - 34)
    table_crc = zlib.crc32(entries)
    outputs = []
    for backup in (False, True):
        output = bytearray((33 if backup else 34) * SECTOR)
        if not backup:
            output[:SECTOR] = primary.data[:SECTOR]
            # 保护 MBR（主引导记录）中的覆盖范围随设备真实容量更新。
            struct.pack_into("<I", output, 446 + 12, min(sectors - 1, 0xffffffff))
        table_offset = 0 if backup else 2 * SECTOR
        output[table_offset:table_offset + len(entries)] = entries
        header = bytearray(primary.header)
        struct.pack_into("<4Q", header, 24, sectors - 1 if backup else 1,
                         1 if backup else sectors - 1, 34, sectors - 34)
        struct.pack_into("<Q", header, 72, sectors - 33 if backup else 2)
        struct.pack_into("<I", header, 88, table_crc)
        struct.pack_into("<I", header, 16, 0)
        struct.pack_into("<I", header, 16, zlib.crc32(header))
        offset = 32 * SECTOR if backup else SECTOR
        output[offset:offset + 92] = header
        outputs.append(bytes(output))
    validate_pair(parse_gpt(outputs[0]), parse_gpt(outputs[1], backup=True))
    return tuple(outputs)


def program_nodes(path: Path, table: Gpt, *, source=False) -> list[dict]:
    """交叉核验 program XML 和 GPT；空引用永不成为写操作。"""
    allowed = {"start_sector", "size_in_KB", "physical_partition_number",
               "partofsingleimage", "file_sector_offset", "num_partition_sectors",
               "readbackverify", "filename", "sparse", "start_byte_hex",
               "SECTOR_SIZE_IN_BYTES", "label"}
    result, seen = [], set()
    for element in read_xml(path, "data", "program"):
        node = dict(element.attrib)
        if set(node) - allowed:
            raise FlashError("QDL program 含未知属性")
        label = node.get("label", "")
        if label in seen:
            raise FlashError(f"QDL 分区重复: {label}")
        seen.add(label)
        if (node.get("SECTOR_SIZE_IN_BYTES") != "512"
                or node.get("physical_partition_number") != "0"
                or node.get("file_sector_offset", "0") != "0"
                or node.get("sparse", "false") != "false"):
            raise FlashError(f"不支持的 QDL program 几何: {label}")
        start = number(node.get("start_sector", ""), allow_end=True, total=table.sectors)
        size = number(node.get("num_partition_sectors", ""))
        if label in {"PrimaryGPT", "BackupGPT"}:
            target = (0, 34) if label == "PrimaryGPT" else (table.sectors - 33, 33)
        else:
            entry = table.entries.get(label)
            if entry is None:
                raise FlashError(f"XML 引用 GPT 不存在的分区: {label}")
            target = (entry.first, entry.sectors)
        if (start, size) != target:
            raise FlashError(f"XML/GPT 几何不一致: {label}")
        name = node.get("filename", "")
        if not name:
            continue
        if label in PRESERVED:
            raise FlashError(f"禁止覆盖持久化分区: {label}")
        if source and name.startswith("../disk-sdcard.img."):
            if (label, name) not in {("efi", "../disk-sdcard.img.esp"),
                                     ("rootfs", "../disk-sdcard.img.root"),
                                     ("userdata", "../disk-sdcard.img.home")}:
                raise FlashError("救援 XML 的上级镜像引用无效")
        else:
            safe_file(path.parent, name)
        result.append(node)
    if not set(SYSTEM_IMAGES).issubset(seen) or not {"PrimaryGPT", "BackupGPT"}.issubset(seen):
        raise FlashError("QDL XML 缺少系统或 GPT 分区")
    written = {node["label"] for node in result}
    if not (set(SYSTEM_IMAGES) | {"PrimaryGPT", "BackupGPT"}).issubset(written):
        raise FlashError("QDL XML 的必需系统镜像引用为空")
    return result


def write_xml(path: Path, nodes: list[dict], *, kind="program"):
    root = ET.Element("data")
    for node in nodes:
        ET.SubElement(root, kind, node)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def build_bundle(firmware: Path, images: dict[str, Path], output: Path) -> Path:
    """将经 source 摘要校验的救援目录和构建镜像组装为独立发布目录。"""
    primary = parse_gpt(safe_file(firmware, "gpt_main0.bin").read_bytes(), template=True)
    backup = parse_gpt(safe_file(firmware, "gpt_backup0.bin").read_bytes(), backup=True, template=True)
    validate_pair(primary, backup)
    validate_unoq(primary)
    nodes = program_nodes(safe_file(firmware, "rawprogram0.xml"), primary, source=True)
    # 上游 patch 留作来源审计；执行期自行产生确定的两份 GPT，完全不执行它。
    patches = read_xml(safe_file(firmware, "patch0.xml"), "patches", "patch")
    patch_keys = {"start_sector", "byte_offset", "physical_partition_number",
                  "size_in_bytes", "value", "filename", "SECTOR_SIZE_IN_BYTES", "what"}
    if any(set(p.attrib) - patch_keys or p.get("physical_partition_number") != "0"
           or p.get("SECTOR_SIZE_IN_BYTES") != "512" for p in patches):
        raise FlashError("救援 patch XML 属性不支持")
    output.mkdir(parents=True, exist_ok=False)
    (output / "files").mkdir()
    (output / "source").mkdir()
    for name in ("rawprogram0.xml", "patch0.xml", "gpt_main0.bin", "gpt_backup0.bin",
                 "LICENSE", "LICENSE.arduino"):
        shutil.copyfile(safe_file(firmware, name), output / "source" / name)
    shutil.copyfile(safe_file(firmware, LOADER), output / "files" / LOADER)
    for label, name in SYSTEM_IMAGES.items():
        if label == "boot_b":
            continue
        image = images[label]
        if image.is_symlink() or not image.is_file() or image.stat().st_size == 0:
            raise FlashError(f"缺少有效的 {label} 镜像: {image}")
        # 镜像可能是数 GiB 的稀疏文件；GNU cp 保留空洞，避免发布副本占满磁盘。
        destination = output / "files" / name
        copy_tool = shutil.which("gcp") or "cp"
        result = subprocess.run([copy_tool, "--sparse=always", str(image), str(destination)],
                                capture_output=True, text=True)
        if result.returncode:
            raise FlashError("UNO Q 镜像组装需要 Docker 内的 GNU cp（保留稀疏文件）")
    for node in nodes:
        label, name = node["label"], node["filename"]
        if label in {"PrimaryGPT", "BackupGPT"}:
            new_name = "gpt_main0.bin" if label == "PrimaryGPT" else "gpt_backup0.bin"
            shutil.copyfile(safe_file(firmware, new_name), output / new_name)
            node["filename"] = new_name
        elif label in SYSTEM_IMAGES:
            node["filename"] = "files/" + SYSTEM_IMAGES[label]
        else:
            shutil.copyfile(safe_file(firmware, name), output / "files" / name)
            node["filename"] = "files/" + name
    write_xml(output / "rawprogram0.xml", nodes)
    files = {path.relative_to(output).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
             for path in sorted(output.rglob("*")) if path.is_file()}
    metadata = {"version": 1, "board": "arduino-uno-q", "soc": "qrb2210",
                "storage": "emmc", "sector_size": SECTOR,
                "capacity_policy": "observed-gpt-16-or-32gb",
                "files": files}
    (output / MANIFEST).write_text(json.dumps(metadata, indent=2) + "\n")
    validate_bundle(output)
    return output


def validate_bundle(bundle: Path) -> tuple[dict, Gpt, list[dict]]:
    """全量校验也是单刷的前提，防止混用两次构建的元数据。"""
    manifest_path = safe_file(bundle, MANIFEST)
    if manifest_path.stat().st_size > 1024 * 1024:
        raise FlashError("QDL manifest 超出大小限制")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (ValueError, OSError) as exc:
        raise FlashError("QDL manifest 无效") from exc
    if not isinstance(manifest, dict):
        raise FlashError("QDL manifest 必须是对象")
    if (manifest.get("version"), manifest.get("board"), manifest.get("soc"),
            manifest.get("storage"), manifest.get("sector_size")) != (
            1, "arduino-uno-q", "qrb2210", "emmc", SECTOR):
        raise FlashError("QDL manifest 平台身份不匹配")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise FlashError("QDL manifest 缺少文件清单")
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != set(files) | {MANIFEST}:
        raise FlashError("QDL 发布包文件集合与 manifest 不符")
    for name, info in files.items():
        if (not isinstance(name, str) or not isinstance(info, dict)
                or not isinstance(info.get("bytes"), int)
                or not isinstance(info.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])):
            raise FlashError("QDL manifest 文件元数据类型无效")
        path = safe_file(bundle, name)
        if path.stat().st_size != info.get("bytes") or digest(path) != info.get("sha256"):
            raise FlashError(f"QDL 文件摘要或长度不符: {name}")
    table = parse_gpt(safe_file(bundle, "gpt_main0.bin").read_bytes(), template=True)
    backup = parse_gpt(safe_file(bundle, "gpt_backup0.bin").read_bytes(), backup=True, template=True)
    validate_pair(table, backup)
    validate_unoq(table)
    safe_file(bundle, "files/" + LOADER)
    safe_file(bundle, "source/LICENSE")
    nodes = program_nodes(safe_file(bundle, "rawprogram0.xml"), table)
    for node in nodes:
        label = node["label"]
        expected_image = SYSTEM_IMAGES.get(label)
        if expected_image and node["filename"] != "files/" + expected_image:
            raise FlashError(f"QDL 系统镜像映射不一致: {label}")
        expected_gpt = {"PrimaryGPT": "gpt_main0.bin", "BackupGPT": "gpt_backup0.bin"}.get(label)
        if expected_gpt and node["filename"] != expected_gpt:
            raise FlashError(f"QDL GPT 镜像映射不一致: {label}")
        size = safe_file(bundle, node["filename"]).stat().st_size
        if size == 0:
            raise FlashError(f"QDL 镜像为空: {label}")
        if label != "userdata" and size > int(node["num_partition_sectors"]) * SECTOR:
            raise FlashError(f"QDL 镜像超出分区容量: {label}")
    return manifest, table, nodes


def flash_partitions(nodes: list[dict]) -> list[FlashPartition]:
    """由已验证的同一份 XML 产生公共分区清单。"""
    parts = []
    for node in nodes:
        label = node["label"]
        if label in {"PrimaryGPT", "BackupGPT"}:
            continue
        parts.append(FlashPartition(
            label, hex(int(node["start_sector"])),
            "vfat" if label == "efi" else "ext4" if label in {"rootfs", "userdata"} else "raw",
            f"{BUNDLE_PATH}/{node['filename']}",
            protected=label not in {"efi", "rootfs", "userdata"},
            size=node["num_partition_sectors"],
        ))
    return parts


def make_flash_config(config: dict, target_dir: Path) -> FlashConfig:
    bundle = target_dir / BUNDLE_PATH
    _, _, nodes = validate_bundle(bundle)
    return FlashConfig(
        platform="qualcommqrb2210", flash_tool="qdl", board=config["board"],
        product=config.get("product", "default"), variant=config.get("variant", "release"),
        soc="qrb2210", storage_type="emmc", partitions=flash_partitions(nodes),
        pre_flash=PreFlashConfig(download_boot=f"{BUNDLE_PATH}/files/{LOADER}"),
        bundle_manifest=f"{BUNDLE_PATH}/{MANIFEST}", bundle_manifest_sha256=digest(bundle / MANIFEST),
    )


class UnoQFlashStrategy(UnoQFlashPlan, FlashStrategy):
    """QDL 的所有写入前必须完成串号绑定、主备 GPT 读取及身份核验。"""

    allow_protected = False
    no_reboot = False
    supports_no_reboot = False
    uses_named_partitions = True

    def find_tool(self, project_dir: Path) -> Path:
        host = "macos" if sys.platform == "darwin" else "linux"
        candidate = project_dir / "tools" / host / "qdl" / "qdl"
        found = str(candidate) if candidate.is_file() else shutil.which("qdl")
        if not found:
            raise FlashError("未找到 QDL；请安装 Arduino qdl-packing v2.4-26 或兼容版本")
        return Path(found)

    def _usb_devices(self) -> list[DeviceInfo]:
        devices = []
        if sys.platform == "darwin":
            run = subprocess.run(["ioreg", "-p", "IOUSB", "-a"], capture_output=True, check=True, timeout=5)
            def visit(items):
                for node in items:
                    if node.get("idVendor") == 0x05c6 and node.get("idProduct") == 0x9008:
                        devices.append(DeviceInfo("qualcommqrb2210", "edl", "UNO Q EDL 候选设备",
                                                  serial=edl_serial(str(node.get("USB Product Name", "")))))
                    visit(node.get("IORegistryEntryChildren", []))
            visit(plistlib.loads(run.stdout))
        else:
            for node in Path("/sys/bus/usb/devices").glob("*"):
                if not (node / "idVendor").is_file() or not (node / "idProduct").is_file():
                    continue
                if (node / "idVendor").read_text().strip() == "05c6" and (node / "idProduct").read_text().strip() == "9008":
                    product = (node / "product").read_text().strip() if (node / "product").is_file() else ""
                    serial = edl_serial(product)
                    devices.append(DeviceInfo("qualcommqrb2210", "edl", "UNO Q EDL 候选设备", serial=serial))
        return devices

    def detect_device(self, tool: Path):
        devices = self._usb_devices()
        if len(devices) > 1:
            raise FlashError("检测到多个 Qualcomm EDL 设备；请只连接目标 UNO Q")
        if not devices:
            return None
        device = devices[0]
        if not re.fullmatch(r"[0-9a-fA-F]{1,16}", device.serial):
            raise FlashError("EDL 设备缺少可绑定的十六进制串号，拒绝自动选择")
        return device

    def preflight(self, target_dir, config, partitions):
        self.__dict__.pop("observed_gpt", None)
        if config.board != "arduino-uno-q" or config.soc != "qrb2210" or config.storage_type != "emmc":
            raise FlashError("UNO Q flash-config 身份不符")
        bundle = target_dir / BUNDLE_PATH
        if (config.bundle_manifest != f"{BUNDLE_PATH}/{MANIFEST}"
                or digest(safe_file(target_dir, config.bundle_manifest)) != config.bundle_manifest_sha256):
            raise FlashError("QDL manifest 与 flash-config 摘要不符")
        _, table, nodes = validate_bundle(bundle)
        canonical = flash_partitions(nodes)
        expected = {p.name: p for p in canonical}
        if config.partitions != canonical:
            raise FlashError("flash-config 与 QDL 分区计划不一致")
        for part in partitions:
            if expected.get(part.name) != part:
                raise FlashError("单刷分区不是完整计划中的原始条目")
        self.bundle, self.table, self.nodes = bundle, table, nodes
        self.manifest_digest = config.bundle_manifest_sha256
        self.all_names = set(expected)
        self.selected = [p.name for p in partitions]
        self.target_dir = target_dir
        if any(p.protected for p in partitions) and not self.allow_protected:
            raise FlashError("本次会写入受保护启动固件；核对 UNO Q 发布包后使用 --yes 明确确认")

    def _run(self, tool: Path, directory: Path, xml: Path, *, timeout=60):
        command = [str(tool), "--storage", "emmc", "--serial", self.device.serial,
                   str(self.bundle / "files" / LOADER), str(xml)]
        try:
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlashError(f"QDL 执行失败或超时（不自动重试）: {exc}") from exc
        (directory / (xml.stem + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise FlashError(f"QDL 失败，日志: {directory / (xml.stem + '.log')}")

    def pre_flash(self, tool, target_dir, config, device=None):
        self.__dict__.pop("observed_gpt", None)
        # --no-wait 仅跳过等待，不能跳过枚举、身份或容量检查。
        observed = self.detect_device(tool)
        if observed is None or (device and observed.serial != device.serial):
            raise FlashError("UNO Q EDL 设备未连接或串号发生变化")
        self.device = observed
        records = target_dir / "flash-records"
        records.mkdir(exist_ok=True)
        self.record_dir = Path(tempfile.mkdtemp(prefix="unoq-", dir=records))
        read = self.record_dir / "read-gpt.xml"
        write_xml(read, [
            {"SECTOR_SIZE_IN_BYTES": "512", "filename": "primary.bin", "physical_partition_number": "0",
             "num_partition_sectors": "34", "start_sector": "0"},
            {"SECTOR_SIZE_IN_BYTES": "512", "filename": "backup.bin", "physical_partition_number": "0",
             "num_partition_sectors": "33", "start_sector": "NUM_DISK_SECTORS-33."},
        ], kind="read")
        self._run(tool, self.record_dir, read)
        try:
            primary = parse_gpt((self.record_dir / "primary.bin").read_bytes())
            backup = parse_gpt((self.record_dir / "backup.bin").read_bytes(), backup=True)
        except OSError as exc:
            raise FlashError("QDL 未返回主备 GPT；请先用官方工具恢复 UNO Q") from exc
        validate_pair(primary, backup)
        validate_unoq(primary, observed=True)
        if set(primary.entries) != set(self.table.entries):
            raise FlashError("目标 GPT 分区集合不符合 UNO Q 身份")
        for name, expected in self.table.entries.items():
            actual = primary.entries[name]
            if (actual.type_guid != expected.type_guid
                    or (name != "userdata" and actual.first != expected.first)
                    or (name not in {"rootfs", "userdata"} and actual.last != expected.last)):
                raise FlashError(f"目标 GPT 身份或分区几何不匹配: {name}")
        capacity = primary.sectors * SECTOR
        # 容量只取读回且主备一致的 GPT；区间仅用于拒绝非 16/32GB 型号。
        if not (14 * 1024 ** 3 <= capacity <= 16_000_000_000
                or 28 * 1024 ** 3 <= capacity <= 32_000_000_000):
            raise FlashError(f"未支持的 UNO Q 实际容量: {capacity} 字节")
        userdata = safe_file(self.bundle, "files/userdata.img")
        if userdata.stat().st_size > primary.entries["userdata"].sectors * SECTOR:
            raise FlashError("userdata 镜像超出目标实际剩余容量")
        self.observed_gpt = primary
        record = {"board": config.board, "serial": observed.serial, "capacity_bytes": capacity,
                  "sectors": primary.sectors, "manifest_sha256": config.bundle_manifest_sha256,
                  "selected": self.selected, "status": "identity-verified"}
        (self.record_dir / "record.json").write_text(json.dumps(record, indent=2) + "\n")

    def _write(self, tool, names, *, full):
        if not hasattr(self, "observed_gpt"):
            raise FlashError("写入前尚未完成 UNO Q 身份验证")
        if not set(names).issubset(self.selected) or (full and set(names) != self.all_names):
            raise FlashError("写入范围超出本次已核验的分区计划")
        # 读取 GPT 后 QDL 会复位；保留 JCTL 跳线并等待同串号重新枚举。
        current = self.wait_for_device(tool)
        if current is None or current.serial != self.device.serial:
            raise FlashError("写入前目标设备发生变化")
        # 校验与 QDL 打开文件之间不再调用可修改发布包的流程。
        if digest(safe_file(self.bundle, MANIFEST)) != self.manifest_digest:
            raise FlashError("设备握手后 QDL manifest 发生变化，拒绝写入")
        validate_bundle(self.bundle)
        nodes = []
        primary, backup = resize_gpt(self.observed_gpt, self.observed_gpt.sectors)
        for original in self.nodes:
            label = original["label"]
            is_gpt = label in {"PrimaryGPT", "BackupGPT"}
            if (is_gpt and not full) or (not is_gpt and label not in names):
                continue
            node = copy.deepcopy(original)
            if is_gpt:
                filename = "gpt_main0.bin" if label == "PrimaryGPT" else "gpt_backup0.bin"
                (self.record_dir / filename).write_bytes(primary if label == "PrimaryGPT" else backup)
                node["filename"] = filename
                node["start_sector"] = "0" if label == "PrimaryGPT" else str(self.observed_gpt.sectors - 33)
            else:
                # 执行期生成的绝对路径仅指向此前校验的发布文件；不消费外来路径。
                node["filename"] = str(safe_file(self.bundle, node["filename"]).resolve())
                if label in {"rootfs", "userdata"}:
                    node["start_sector"] = str(self.observed_gpt.entries[label].first)
                image_size = Path(node["filename"]).stat().st_size
                node["num_partition_sectors"] = str((image_size + SECTOR - 1) // SECTOR)
            # 这些说明字段不参与协议，去掉防止运行期数值更新后留旧值。
            node.pop("size_in_KB", None)
            node.pop("start_byte_hex", None)
            nodes.append(node)
        if not nodes:
            raise FlashError("没有可执行的 QDL 分区写入")
        xml = self.record_dir / "program.xml"
        write_xml(xml, nodes)
        record_path = self.record_dir / "record.json"
        record = json.loads(record_path.read_text())
        record["status"] = "writing"
        record["program_sha256"] = digest(xml)
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        try:
            self._run(tool, self.record_dir, xml, timeout=3600)
        except FlashError:
            record["status"] = "failed"
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            raise
        record["status"] = "written"
        record_path.write_text(json.dumps(record, indent=2) + "\n")

    def flash_whole_disk(self, tool, target_dir, config):
        self._write(tool, self.selected, full=True)
        return True

    def write_named_partition(self, tool, part, image, config):
        self._write(tool, [part.name], full=False)

    def write_partition(self, tool, offset, image):
        raise FlashError("UNO Q 必须通过已校验的具名分区计划刷写")

    def reboot(self, tool):
        # QDL 自身的 Firehose reset 行为取决于工具版本，不能另起未绑定会话。
        from builder.flash.console import _info
        _info("请移除 JCTL EDL 跳线并重新上电 UNO Q")
