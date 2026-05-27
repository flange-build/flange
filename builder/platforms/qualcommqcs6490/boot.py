"""Qualcomm QCS6490 boot 组件 —— GRUB(grub-with-dtb) ESP 镜像。

flange 无 UEFI/GRUB 先例（现有平台皆 U-Boot/extlinux），本模块为全新实现。
产出 boot.img = ESP(FAT) 内容：
  /EFI/BOOT/BOOTAA64.EFI   ← grub-mkimage 生成的独立 GRUB（arm64-efi）
  /EFI/BOOT/grub.cfg       ← search rootfs + linux/initrd/devicetree（acpi=off ttyMSM0）
内核 Image/dtb/initrd 在 rootfs /boot（GRUB 经 ext2 模块读 rootfs 分区加载）。

⚠️ 需构建/实板验证：grub-mkimage 模块集、initrd 生成、devicetree 加载、acpi=off
   下 DT 启动链。grub-efi-arm64-bin + grub-common + mtools 需在构建 Docker 镜像内。
"""

import tempfile
from pathlib import Path

from builder.base import ComponentBuilder

# grub-mkimage 嵌入的模块集：GPT/FAT/ext2 读盘 + label 搜索 + linux/devicetree 加载。
# 注：Ubuntu 的 grub-efi-arm64-bin 把 `devicetree` 命令打包在 fdt.mod 里
# （上游 GRUB 模块命名不一致），故此处模块名是 `fdt`，但 grub.cfg 里命令仍写 `devicetree`。
GRUB_MODULES = [
    "part_gpt", "fat", "ext2", "search", "search_label", "search_fs_uuid",
    "linux", "fdt", "normal", "configfile", "boot", "echo", "ls",
    "cat", "test", "all_video", "gfxterm", "serial", "terminal",
]


class Qcs6490BootBuilder(ComponentBuilder):
    component = "boot"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-boot-"))
        esp = self._work_dir / "esp"
        efi_boot = esp / "EFI" / "BOOT"
        efi_boot.mkdir(parents=True)

        dtb = config["kernel"]["dtb"]
        kargs = config["boot"].get(
            "kernel_args", "acpi=off console=ttyMSM0,115200 root=LABEL=rootfs rootwait")

        # grub.cfg：search 到 rootfs 分区，从其 /boot 加载内核 + dtb（grub-with-dtb）
        grub_cfg = efi_boot / "grub.cfg"
        grub_cfg.write_text(
            "set timeout=3\n"
            "insmod all_video\n"
            "search --no-floppy --label rootfs --set=root\n"
            'menuentry "Radxa Dragon Q6A (Linux)" {\n'
            f"    linux /boot/vmlinuz {kargs}\n"
            "    if [ -f /boot/initrd.img ]; then initrd /boot/initrd.img; fi\n"
            f"    devicetree /boot/{dtb}.dtb\n"
            "}\n"
        )

        # 生成独立 GRUB EFI（prefix 指向 /EFI/BOOT，使其找到同目录 grub.cfg）
        bootaa64 = efi_boot / "BOOTAA64.EFI"
        self._status("grub-mkimage 生成 BOOTAA64.EFI...")
        self.docker.run([
            "grub-mkimage", "-O", "arm64-efi", "-p", "/EFI/BOOT",
            "-o", str(bootaa64), *GRUB_MODULES,
        ], label="grub-mkimage")

        # 组装 ESP FAT 镜像（boot.img），用 mtools 填充（免特权挂载）
        esp_mb = self._esp_size_mb(config)
        self._boot_img = self._work_dir / "boot.img"
        self._status(f"生成 ESP boot.img ({esp_mb}MB)...")
        self.docker.run(["truncate", "-s", f"{esp_mb}M", str(self._boot_img)])
        self.docker.run(["mkfs.vfat", "-F", "32", "-n", "efi", str(self._boot_img)])
        # mmd/mcopy：建 /EFI/BOOT 并拷入 EFI + grub.cfg
        self.docker.run(["mmd", "-i", str(self._boot_img), "::/EFI", "::/EFI/BOOT"])
        self.docker.run(["mcopy", "-i", str(self._boot_img),
                         str(bootaa64), "::/EFI/BOOT/BOOTAA64.EFI"])
        self.docker.run(["mcopy", "-i", str(self._boot_img),
                         str(grub_cfg), "::/EFI/BOOT/grub.cfg"])

    def _esp_size_mb(self, config: dict) -> int:
        """ESP 大小 → MB。config 的 size 按 flange 约定是 **512 字节扇区**计，
        故直接 ×512 转字节（与介质 sector_size 无关）。不足 64MB 兜底。"""
        parts = config.get("partitions", {})
        for e in parts.get("entries", []):
            if e["name"] == "esp" and e.get("size"):
                mb = int(e["size"], 0) * 512 // (1024 * 1024)
                return max(mb, 64)
        return 256

    def collect(self, src_dir, config: dict) -> dict:
        return {"boot": self._boot_img}
