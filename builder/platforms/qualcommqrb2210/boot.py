"""Qualcomm QRB2210 Boot 分区镜像构建策略（U-Boot extlinux/sysboot）。

产物：boot.img（**FAT32** 文件系统镜像，写入 vendor GPT 的 `efi` 分区），内含：
  /extlinux/extlinux.conf          — normal 启动配置
  /extlinux/Image                  — kernel 二进制
  /dtbs/qcom/<dtb_filename>        — 设备树（qrb2210-arduino-imola.dtb）

U-Boot（ABL 链加载的 Android boot.img，在 vendor `boot_a` 分区）经 sysboot
扫描本分区的 /extlinux/extlinux.conf 引导内核——复用 builder/extlinux.py。

FAT 而非 ext4：vendor rawprogram（armbian/qcombin Agatti/arduino-uno-q）把可启动
OS 内容放在 label `efi` 的分区、镜像名 `disk-sdcard.img.esp`（FAT ESP）；预编
U-Boot 的 distro/boot 脚本按该 FAT ESP 扫描，故 flange 产 FAT 与之对齐。用 mtools
（mkfs.vfat/mmd/mcopy）免特权写 FAT，与 Q6A GRUB ESP 同款工具链。

⚠️ U-Boot load 地址需规避 ABL 保留内存区（Armbian 用定制 boot-qrb2210.cmd）。
   v1 依赖预编 U-Boot boot.img 的 distro_bootcmd 默认地址；若实板冲突，需在
   bootloader 层提供平台 boot 脚本（见 openspec tasks §4.2）。本构建器只产出
   标准 extlinux 内容，不涉及 load 地址。
"""

import tempfile
from pathlib import Path

from builder.base import ComponentBuilder
from builder.extlinux import (
    LabelSpec,
    NORMAL_CONFIG,
    NORMAL_LABEL,
    render_extlinux,
)


class Qrb2210BootBuilder(ComponentBuilder):
    component = "boot"
    DTB_VENDOR_DIR = "dtbs/qcom"

    def build(self, config: dict) -> dict:
        """boot 镜像无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-boot-"))

        target_dir = self.cache.target_dir
        kernel_image = target_dir / "kernel" / "Image"
        dtb_stem = config["kernel"]["dtb"]
        kernel_dtb = target_dir / "kernel" / f"{dtb_stem}.dtb"

        if not kernel_image.exists():
            raise FileNotFoundError(
                f"kernel Image 未找到: {kernel_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_dtb}")

        dtb_filename = config.get("boot", {}).get(
            "dtb_filename", f"{dtb_stem}.dtb")

        # 生成 extlinux.conf 到临时文件，供 mcopy 注入
        conf_path = self._work_dir / "extlinux.conf"
        conf_path.write_text(self._build_extlinux_conf(config, dtb_filename))

        # 生成 FAT32 boot.img，用 mtools 建目录树并拷文件（免特权）
        boot_size_mb = self._partition_size_mb(config, "boot")
        boot_img = self._work_dir / "boot.img"
        self._status(f"生成 boot.img (FAT32, {boot_size_mb}MB)...")
        self.docker.run(["truncate", "-s", f"{boot_size_mb}M", str(boot_img)])
        self.docker.run(["mkfs.vfat", "-F", "32", "-n", "efi", str(boot_img)])
        self.docker.run(["mmd", "-i", str(boot_img),
                         "::/extlinux", "::/dtbs", f"::/{self.DTB_VENDOR_DIR}"])
        self.docker.run(["mcopy", "-i", str(boot_img), str(kernel_image),
                         "::/extlinux/Image"])
        self.docker.run(["mcopy", "-i", str(boot_img), str(kernel_dtb),
                         f"::/{self.DTB_VENDOR_DIR}/{dtb_filename}"])
        self.docker.run(["mcopy", "-i", str(boot_img), str(conf_path),
                         "::/extlinux/extlinux.conf"])
        self._boot_img = boot_img

    def _build_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        """生成 normal extlinux.conf。

        根设备使用 PARTLABEL=rootfs 定位（vendor GPT 既有 rootfs 分区 label）。
        PARTLABEL 无需 userspace udev 辅助，kernel 启动早期即可解析。
        """
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")

        normal = LabelSpec(
            name=NORMAL_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="devicetree",
            append=(
                f"root=PARTLABEL=rootfs rootfstype=ext4 rootwait rw "
                f"{kernel_args}"
            ).rstrip(),
        )
        return render_extlinux(NORMAL_LABEL, [normal])

    def _partition_size_mb(self, config: dict, name: str) -> int:
        for entry in config.get("partitions", {}).get("entries", []):
            if entry["name"] == name:
                size_sectors = int(entry["size"], 0)
                return (size_sectors * 512) // (1024 * 1024)
        raise KeyError(f"partitions.entries 中未定义分区: {name}")

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"boot": self._boot_img}
