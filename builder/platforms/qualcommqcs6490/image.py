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

        # GPT 分区表：parted/sfdisk 对 regular file 默认 512-LBA，写入 4K UFS 后
        # LBA 数值含义错位 8x → UEFI 找 ESP 找不到（实板已踩坑）。
        # 装 util-linux 2.39 的 sfdisk 还没 --sector-size；sgdisk 1.0.10 也无。
        # 解法：losetup -b <sector_size> 把 raw.img 挂成报告 self._sector LBA 的
        # loop 设备，parted/sgdisk 自动按 loop 报告的 LBA 写 GPT，结果与 UFS 4K 对齐。
        self._status(f"写 GPT 分区表（loop -b {self._sector} + parted）...")
        loop_setup = f"losetup -b {self._sector} -f --show {raw_img}"
        parted_cmds = [f"parted -s $LOOP mklabel gpt"]
        gpt_index = 0
        for entry in entries:
            gpt_index += 1
            start = entry["_offset_sectors"] * self._sector
            end = start + entry["_size_sectors"] * self._sector - 1
            label = entry.get("label", entry["name"])
            parted_cmds.append(
                f"parted -s $LOOP mkpart {label} {entry['type']} {start}B {end}B")
            if entry["name"] == "esp":
                parted_cmds.append(f"parted -s $LOOP set {gpt_index} esp on")
                parted_cmds.append(
                    f"sfdisk --part-type $LOOP {gpt_index} {ESP_TYPE_GUID}")
        script = (f"set -e; LOOP=$({loop_setup}); "
                  f"trap 'losetup -d $LOOP' EXIT; "
                  + "; ".join(parted_cmds))
        self.docker.run_privileged(["sh", "-c", script])

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
        """flange 约定 config 的 offset/size 以 512 字节扇区计；4K 介质上
        要按 self._sector 重算（offset_512 × 512 ÷ sector_size，size 同理），
        否则 rootfs "3G" 会被当作 3G/512=6.3M 个 4K 扇区 → 24GiB 整盘虚胖。"""
        FLANGE_SECTOR = 512
        resolved = []
        for entry in entries:
            e = dict(entry)
            off_512 = int(entry.get("offset", "0"), 0) if entry.get("offset") else 0
            e["_offset_sectors"] = off_512 * FLANGE_SECTOR // self._sector
            psize = resolve_image_size(entry)
            e["_size_sectors"] = psize.bytes // self._sector
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
