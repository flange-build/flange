"""UNO Q 官方前级固件与自编 U-Boot Android 启动容器。"""

import gzip
import hashlib
import re
import shutil
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath

from builder.base import ComponentBuilder
from builder.kconfig import render_kconfig


def extract_firmware(archive_path: Path, destination: Path, loader: str) -> Path:
    """解包已校验的官方救援资源；拒绝逃逸、链接、重复和缺失加载器。"""
    loader_path = PurePosixPath(loader)
    if loader_path.name != loader or loader in {"", ".", ".."}:
        raise ValueError("Firehose 加载器必须是单个文件名")
    seen = set()
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            relative = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (relative.is_absolute() or ".." in relative.parts
                    or "\\" in item.filename or relative in seen
                    or stat.S_ISLNK(mode)):
                raise ValueError(f"救援固件包含不安全路径: {item.filename}")
            seen.add(relative)
            target = destination.joinpath(*relative.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod((mode & 0o777) or 0o644)
    matches = list(destination.rglob(loader))
    if len(matches) != 1 or matches[0].stat().st_size == 0:
        raise ValueError("救援固件必须包含唯一且非空的 Firehose 加载器")
    root = matches[0].parent
    if not list(root.glob("rawprogram*.xml")) or not list(root.glob("patch*.xml")):
        raise ValueError("救援固件缺少 rawprogram/patch XML")
    return root


def pack_uboot_payload(binary: Path, dtb: Path, output: Path) -> None:
    """复现官方 gzip(U-Boot 无 DTB 二进制) + DTB，固定 gzip 时间戳。"""
    for path in (binary, dtb):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"缺少 U-Boot 启动输入: {path}")
    with output.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with binary.open("rb") as source:
                shutil.copyfileobj(source, compressed)
        with dtb.open("rb") as source:
            shutil.copyfileobj(source, stream)


def pack_android_v0(payload: Path, output: Path) -> None:
    """按 AOSP boot_img_hdr_v0 打包 UNO Q 的空 ramdisk 启动容器。

    格式来源：platform/system/tools/mkbootimg/include/bootimg/bootimg.h。
    仅实现该板已固定的 v0、4 KiB 页与地址布局，不承担通用 Android 打包。
    Ubuntu noble 的 mkbootimg 缺少顶层导入的 gki 模块，连 v0 调用也失败。
    """
    page_size = 4096
    data = payload.read_bytes()
    padded_size = (len(data) + page_size - 1) // page_size * page_size
    if not data or padded_size + page_size > 4 * 1024 * 1024:
        raise ValueError("U-Boot 负载为空或超过官方 4 MiB boot 分区")
    # SHA1 是此版本头规定的镜像 ID，不是用于验证下载安全性的 SHA256。
    identity = hashlib.sha1(data + struct.pack("<III", len(data), 0, 0)).digest()
    header = struct.pack(
        "<8s10I16s512s32s1024s", b"ANDROID!", len(data), 0x80008000,
        0, 0, 0, 0, 0x80000100, page_size, 0, 0,
        b"", b"root=/dev/notreal", identity, b"",
    )
    with output.open("wb") as stream:
        stream.write(header.ljust(page_size, b"\0"))
        stream.write(data)
        stream.write(b"\0" * (padded_size - len(data)))


class Qrb2210BootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        self.CROSS = config["bootloader"].get("cross_compile", self.CROSS)
        for target in config["bootloader"]["defconfig"]:
            self.make(src_dir, [target], arch="arm", cross=self.CROSS)
        lines = render_kconfig(config["bootloader"].get("config"), "bootloader.config")
        if lines:
            with (src_dir / ".config").open("a") as stream:
                stream.write("\n" + "\n".join(lines) + "\n")
            self.make(src_dir, ["olddefconfig"], arch="arm", cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        bl = config["bootloader"]
        device_tree = bl["device_tree"]
        tree_path = PurePosixPath(device_tree)
        if (tree_path.is_absolute() or ".." in tree_path.parts
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", device_tree)):
            raise ValueError("bootloader.device_tree 不得越出设备树目录")
        self.make(src_dir, [], arch="arm", cross=self.CROSS, jobs=config.get("jobs", 0),
                  extra=[f"DEVICE_TREE={device_tree}"], label="编译 UNO Q U-Boot")
        self._work = self.work_dir()
        payload = self._work / "u-boot.gz-dtb"
        pack_uboot_payload(src_dir / "u-boot-nodtb.bin",
                           src_dir / f"dts/upstream/src/arm64/{device_tree}.dtb", payload)
        self._uboot = self._work / "uboot-boot.img"
        # 官方 Qualcomm ABL 接口：Android v0，4 KiB 页，0x80000000 基址。
        pack_android_v0(payload, self._uboot)
        # 用独立 AOSP 解包器验证负载，防止打包实现与官方读法发生偏差。
        unpacked = self._work / "unpacked-uboot"
        self.docker.run(["unpack_bootimg", "--boot_img", str(self._uboot),
                         "--out", str(unpacked)], label="验证 Android v0 启动容器")
        if ((unpacked / "kernel").read_bytes() != payload.read_bytes()
                or (unpacked / "ramdisk").stat().st_size != 0):
            raise ValueError("Android 启动容器独立解包结果与输入不一致")
        archive = self.source.ensure_prebuilt_image(
            f"{config['board']}-recovery", bl["recovery_firmware"])
        self._firmware = extract_firmware(archive, self._work / "rescue", bl["firehose_loader"])

    def collect(self, src_dir, config: dict) -> dict:
        return {"uboot": self._uboot, "firmware": self._firmware}
