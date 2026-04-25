"""Allwinner A733 整盘镜像组装策略。

将 bootloader 固件和分区镜像按 SD 卡分区表布局组装成 raw.img。

Allwinner A733 SD 卡布局：
  sector 256  (128KB):  boot0_sdcard.bin
  sector 2064 (~1MB):   boot0_ufs.bin（UFS 兼容）
  sector 24576 (12MB):  boot_package.fex
  分区 1:               boot.img (ext4)
  分区 2:               rootfs.img (ext4)
"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder


class AllwinnerA733ImageBuilder(ComponentBuilder):
    component = "image"
    SECTOR_SIZE = 512
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000001"

    PARTITION_IMAGES = {
        "boot0":         "bootloader/boot0_sdcard.bin",
        "boot0_ufs":     "bootloader/boot0_ufs.bin",
        "boot_package":  "bootloader/boot_package.fex",
        "boot":          "boot/boot.img",
        "rootfs":        "rootfs/rootfs.img",
        # 首版 A733：recovery 镜像由共用 RecoveryBuilder 产出后随 raw.img 一并
        # dd 到 SD 卡；compile 中"镜像不存在即跳过"逻辑覆盖未生成场景。
        "recovery":      "recovery/recovery.img",
    }

    def build(self, config: dict) -> dict:
        """整盘组装无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        entries = self._resolve_entries(
            config.get("partitions", {}).get("entries", []))
        target_dir = self.cache.target_dir

        total_sectors = self._total_sectors(entries)
        total_bytes = total_sectors * self.SECTOR_SIZE
        raw_img = self._work_dir / "raw.img"
        self._status(f"创建空镜像 ({total_bytes // (1024*1024)}MB)...")
        self.docker.run(["truncate", "-s", str(total_bytes), str(raw_img)])

        # GPT 分区表
        self._status("写 GPT 分区表...")
        self.docker.run(["parted", "-s", str(raw_img), "mklabel", "gpt"])
        gpt_index = 0
        for entry in entries:
            if entry["type"] == "raw":
                continue
            gpt_index += 1
            start = entry["_offset_sectors"] * self.SECTOR_SIZE
            end = start + entry["_size_sectors"] * self.SECTOR_SIZE - 1
            self.docker.run([
                "parted", "-s", str(raw_img), "mkpart",
                entry["name"], entry["type"],
                f"{start}B", f"{end}B",
            ])
            if entry["name"] == "rootfs":
                self.docker.run([
                    "sfdisk", "--part-uuid", str(raw_img),
                    str(gpt_index), self.ROOTFS_PARTUUID,
                ])

        # dd 各分区镜像
        for entry in entries:
            image_rel = self.PARTITION_IMAGES.get(entry["name"])
            if not image_rel:
                continue
            image_path = target_dir / image_rel
            if not image_path.exists():
                self._status(f"跳过 {entry['name']}: {image_path} 不存在")
                continue
            offset_sectors = entry["_offset_sectors"]
            self._status(f"dd {image_rel} → sector {offset_sectors}")
            self.docker.run([
                "dd",
                f"if={image_path}",
                f"of={raw_img}",
                f"seek={offset_sectors}",
                "conv=notrunc",
                "bs=512",
                "status=none",
            ])

        self._raw_img = raw_img

    def _resolve_entries(self, entries: list) -> list:
        resolved = []
        for entry in entries:
            e = dict(entry)
            e["_offset_sectors"] = (int(entry.get("offset", "0"), 0)
                                    if entry.get("offset") else 0)
            if entry["size"] == "remaining":
                e["_size_sectors"] = (4 * 1024 * 1024 * 1024) // self.SECTOR_SIZE
            else:
                e["_size_sectors"] = int(entry["size"], 0)
            resolved.append(e)
        return resolved

    def _total_sectors(self, entries: list) -> int:
        max_end = 0
        for e in entries:
            end = e["_offset_sectors"] + e["_size_sectors"]
            if end > max_end:
                max_end = end
        return max_end + 2048  # GPT 尾部保留

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
