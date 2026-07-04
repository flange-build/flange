"""Allwinner H3 整盘镜像组装策略。

将 SPL(u-boot-sunxi-with-spl.bin) 和分区镜像按 SD 卡分区表布局组装成
raw.img。与其余平台不同，H3 使用 **MBR**（而非 GPT）分区表，遵循 sunxi
社区惯例（详见 design.md 决策 4）：

  sector 16   (8KiB):   u-boot-sunxi-with-spl.bin（BootROM 固定加载位置）
  分区 1（sector 2048/1MiB 起）: boot.img (ext4)
  分区 2:                        rootfs.img (ext4)

先建 MBR 分区表、再 dd 写入 SPL 与各分区镜像——顺序颠倒会被 `parted
mklabel`/`mkpart` 清空 SPL 区域（已本地验证，见 tasks.md 1.1）。
"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.partition.size import resolve_image_size


class AllwinnerH3ImageBuilder(ComponentBuilder):
    component = "image"
    SECTOR_SIZE = 512

    PARTITION_IMAGES = {
        "spl":      "bootloader/u-boot-sunxi-with-spl.bin",
        "boot":     "boot/boot.img",
        "recovery": "recovery/recovery.img",
        "rootfs":   "rootfs/rootfs.img",
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

        # MBR 分区表（先建表，再 dd 写 SPL；顺序不可颠倒，见模块 docstring）
        self._status("写 MBR 分区表...")
        self.docker.run(["parted", "-s", str(raw_img), "mklabel", "msdos"])
        for entry in entries:
            if entry["type"] == "raw":
                continue
            start = entry["_offset_sectors"] * self.SECTOR_SIZE
            end = start + entry["_size_sectors"] * self.SECTOR_SIZE - 1
            self.docker.run([
                "parted", "-s", str(raw_img), "mkpart", "primary",
                entry["type"], f"{start}B", f"{end}B",
            ])

        # dd 各分区/固件镜像（含 raw 类型的 SPL）
        for entry in entries:
            image_rel = self.PARTITION_IMAGES.get(entry["name"])
            if not image_rel:
                continue
            image_path = target_dir / image_rel
            if not image_path.exists():
                self._status(f"跳过 {entry['name']}: {image_path} 不存在")
                continue
            self._ensure_partition_image_fits(image_path, entry)
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
            e["_size_sectors"] = resolve_image_size(entry).sectors
            resolved.append(e)
        return resolved

    def _ensure_partition_image_fits(self, image_path: Path, entry: dict):
        max_bytes = entry["_size_sectors"] * self.SECTOR_SIZE
        image_bytes = image_path.stat().st_size
        if image_bytes > max_bytes:
            raise BuildError(
                f"{entry['name']} 镜像 {image_bytes} bytes 超过初始分区大小 "
                f"{max_bytes} bytes，请增大 image_size 或分区 size。"
            )

    def _total_sectors(self, entries: list) -> int:
        max_end = 0
        for e in entries:
            end = e["_offset_sectors"] + e["_size_sectors"]
            if end > max_end:
                max_end = end
        return max_end + 2048  # 尾部保留

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
