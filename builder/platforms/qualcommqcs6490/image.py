"""Qualcomm QCS6490 整盘镜像组装策略。

GPT 布局（UEFI）：
  分区 1: ESP   (FAT, EFI System Partition GUID, label "efi") ← GRUB EFI + grub.cfg
  分区 2: rootfs(ext4, label "rootfs")
boot 固件（XBL/EDK2）在 SPI NOR，由 edl-ng 单刷，不在本盘镜像内。
UFS 目标按 4096 字节扇区对齐（sector_size 取自 partitions 配置）。
"""

import tempfile
from pathlib import Path

from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.partition.size import resolve_image_size

# EFI System Partition 类型 GUID
ESP_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"


class Qcs6490ImageBuilder(ComponentBuilder):
    component = "image"

    PARTITION_IMAGES = {
        "esp":    "boot/boot.img",
        "rootfs": "rootfs/rootfs.img",
    }

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        parts = config.get("partitions", {})
        self._sector = int(parts.get("sector_size", 4096))
        entries = self._resolve_entries(parts.get("entries", []))
        target_dir = self.cache.target_dir

        total_bytes = self._total_sectors(entries) * self._sector
        raw_img = self._work_dir / "raw.img"
        self._status(f"创建空镜像 ({total_bytes // (1024*1024)}MB, 扇区 {self._sector})...")
        self.docker.run(["truncate", "-s", str(total_bytes), str(raw_img)])

        # GPT 分区表（parted 按字节偏移，故 4K/512 通用）
        self._status("写 GPT 分区表...")
        self.docker.run(["parted", "-s", str(raw_img), "mklabel", "gpt"])
        gpt_index = 0
        for entry in entries:
            gpt_index += 1
            start = entry["_offset_sectors"] * self._sector
            end = start + entry["_size_sectors"] * self._sector - 1
            self.docker.run([
                "parted", "-s", str(raw_img), "mkpart",
                entry.get("label", entry["name"]), entry["type"],
                f"{start}B", f"{end}B",
            ])
            if entry["name"] == "esp":
                # 标记 ESP：设 EFI System Partition 类型 GUID + boot/esp flag
                self.docker.run(["parted", "-s", str(raw_img), "set",
                                 str(gpt_index), "esp", "on"])
                self.docker.run(["sfdisk", "--part-type", str(raw_img),
                                 str(gpt_index), ESP_TYPE_GUID])

        # dd 各分区镜像（bs=扇区大小，seek=扇区偏移，4K/512 通用）
        for entry in entries:
            image_rel = self.PARTITION_IMAGES.get(entry["name"])
            if not image_rel:
                continue
            image_path = target_dir / image_rel
            if not image_path.exists():
                self._status(f"跳过 {entry['name']}: {image_path} 不存在")
                continue
            self._ensure_partition_image_fits(image_path, entry)
            self._status(f"dd {image_rel} → 扇区 {entry['_offset_sectors']}")
            self.docker.run([
                "dd", f"if={image_path}", f"of={raw_img}",
                f"seek={entry['_offset_sectors']}", "conv=notrunc",
                f"bs={self._sector}", "status=none",
            ])

        self._raw_img = raw_img

    def _resolve_entries(self, entries: list) -> list:
        resolved = []
        for entry in entries:
            e = dict(entry)
            e["_offset_sectors"] = int(entry.get("offset", "0"), 0) if entry.get("offset") else 0
            e["_size_sectors"] = resolve_image_size(entry).sectors
            resolved.append(e)
        return resolved

    def _ensure_partition_image_fits(self, image_path: Path, entry: dict):
        max_bytes = entry["_size_sectors"] * self._sector
        image_bytes = image_path.stat().st_size
        if image_bytes > max_bytes:
            raise BuildError(
                f"{entry['name']} 镜像 {image_bytes} bytes 超过分区 {max_bytes} bytes")

    def _total_sectors(self, entries: list) -> int:
        max_end = max((e["_offset_sectors"] + e["_size_sectors"] for e in entries),
                      default=0)
        return max_end + 2048  # GPT 尾部保留

    def collect(self, src_dir, config: dict) -> dict:
        return {"image": self._raw_img}
