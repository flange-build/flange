"""UNO Q systemd-boot EFI 系统分区，独立于 boot_a/b 的 U-Boot 容器。"""

import shutil
import struct
from pathlib import Path

from builder.base import ComponentBuilder
from builder.config.canonical import kernel_device_tree
from builder.partition.layout import PartitionLayout
from builder.dtb_overlay import build_overlays, intree_overlays


def validate_arm64_efi(path: Path) -> None:
    """验证 PE（可移植可执行文件）的 ARM64 身份，避免混入宿主 EFI。"""
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"不是有效 EFI PE 文件: {path}")
    offset = struct.unpack_from("<I", data, 0x3c)[0]
    if (offset + 6 > len(data) or data[offset:offset + 4] != b"PE\0\0"
            or struct.unpack_from("<H", data, offset + 4)[0] != 0xAA64):
        raise ValueError(f"EFI 文件不是 ARM64 PE: {path}")


def render_entry(config: dict, dtb: str) -> str:
    """所有路径以 ESP 根为基准，禁止启动参数注入额外条目。"""
    args = config["boot"]["kernel_args"]
    if not args or any(char in args for char in "\r\n\0"):
        raise ValueError("boot.kernel_args 必须是非空单行文本")
    return ("title flange Arduino UNO Q\nlinux /Image\ninitrd /initrd.img\n"
            f"devicetree /dtb/{dtb}.dtb\noptions {args}\n")


class Qrb2210BootBuilder(ComponentBuilder):
    component = "boot"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        if self.context is None:
            raise RuntimeError("boot 构建需要 WorkspaceContext")
        target = self.context.target_dir
        _, dtb = kernel_device_tree(config)
        inputs = {
            "Image": target / "kernel/Image",
            f"dtb/{dtb}.dtb": target / f"kernel/{dtb}.dtb",
            "initrd.img": target / "rootfs/initrd.img",
            "EFI/BOOT/BOOTAA64.EFI": target / "rootfs/bootaa64.efi",
        }
        for path in inputs.values():
            if not path.is_file() or path.stat().st_size == 0:
                raise FileNotFoundError(f"boot 必需上游产物缺失: {path}")
        validate_arm64_efi(inputs["EFI/BOOT/BOOTAA64.EFI"])
        validate_arm64_efi(inputs["Image"])
        partition = PartitionLayout.from_config(config).get("efi")
        if partition is None or partition.size_bytes is None:
            raise ValueError("UNO Q 必须声明固定大小的 efi 分区")
        self._work = self.work_dir()
        overlays = build_overlays(config)
        if overlays:
            paths = [target / ("kernel/overlay" if name in intree_overlays(config)
                               else "device-tree-overlay/overlays") / name
                     for name in overlays]
            for path in paths:
                if not path.is_file():
                    raise FileNotFoundError(f"构建期覆盖缺少 DTBO: {path}")
            merged = self._work / f"{dtb}.dtb"
            self.docker.run(["fdtoverlay", "-i", str(inputs[f"dtb/{dtb}.dtb"]),
                             "-o", str(merged), *map(str, paths)], label="合并板级设备树覆盖")
            inputs[f"dtb/{dtb}.dtb"] = merged
        esp = self._work / "esp"
        for relative, source in inputs.items():
            destination = esp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        entries = esp / "loader/entries"
        entries.mkdir(parents=True)
        (entries / "flange.conf").write_text(render_entry(config, dtb))
        (esp / "loader/loader.conf").write_text("default flange.conf\ntimeout 3\neditor no\n")
        payload_size = sum(path.stat().st_size for path in esp.rglob("*") if path.is_file())
        if payload_size + 8 * 1024 * 1024 > partition.size_bytes:
            raise ValueError("Image/DTB/initrd 超出 efi 分区可用容量")
        self._boot = self._work / "boot.img"
        self.docker.run(["truncate", "-s", str(partition.size_bytes), str(self._boot)])
        self.docker.run(["mkfs.vfat", "-F", "32", "-n", "efi", str(self._boot)])
        for path in sorted(esp.iterdir()):
            self.docker.run(["mcopy", "-s", "-i", str(self._boot), str(path), "::/"])
        self.docker.run(["fsck.vfat", "-n", str(self._boot)], label="验证 EFI FAT 文件系统")

    def collect(self, src_dir, config: dict) -> dict:
        return {"boot": self._boot}
