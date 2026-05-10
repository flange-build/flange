"""Amlogic 完整镜像构建策略。

产物：raw.img — 完整 user area GPT 镜像，含 boot / recovery / rootfs
三个 GPT 分区数据。

关键差异（对比 Rockchip）：
  - Rockchip 的 ``idbloader.img`` / ``u-boot.itb`` 写在 user area 的 raw
    分区（BootROM 读 user area 起点），所以会进 raw.img；
  - Amlogic eMMC 启动靠硬件 boot0 hw 分区（offset 0x200），
    ``u-boot.bin.sd.bin`` **不写在 raw.img 内** —— 由 flash 阶段单独通过
    fastboot 写入 ``bootloader`` 目标。SD 卡启动模式（首版 Non-Goal）下需
    把 ``u-boot.bin.sd.bin`` 直接 dd 到 SD 的 offset 0x200，本变更不涉及。

所以 ``PARTITION_IMAGES`` 只映射 boot / recovery / rootfs 三个 GPT 分区，
``partitions.entries`` 中也不含 ``raw`` 类型 entry。
"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.partition.size import resolve_image_size


class AmlogicImageBuilder(ComponentBuilder):
    component = "image"
    SECTOR_SIZE = 512
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000002"

    # 分区名到输入镜像相对路径（相对 target_dir）的映射。
    # 不含 bootloader：Amlogic BootROM 走 hw boot0，bootloader 在 user area
    # GPT 之外，不通过 raw.img 写入。
    PARTITION_IMAGES = {
        "boot":     "boot/boot.img",
        "rootfs":   "rootfs/rootfs.img",
        # recovery 镜像不存在时（recovery.enabled=False 或构建跳过），
        # 下方 compile 中"image_path 不存在则跳过"逻辑兜底。
        "recovery": "recovery/recovery.img",
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

        # 计算总大小 + 创建空镜像
        total_sectors = self._total_sectors(entries)
        total_bytes = total_sectors * self.SECTOR_SIZE
        raw_img = self._work_dir / "raw.img"
        self._status(f"创建空镜像 ({total_bytes // (1024*1024)}MB)...")
        self.docker.run(["truncate", "-s", str(total_bytes), str(raw_img)])

        # 写 GPT 分区表（首版 amlogic 不含 raw 类型分区，但保留判断与 rockchip 同形）
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
            # rootfs 分区设置固定 PARTUUID（便于 kernel cmdline 引用）
            if entry["name"] == "rootfs":
                self.docker.run([
                    "sfdisk", "--part-uuid", str(raw_img),
                    str(gpt_index), self.ROOTFS_PARTUUID,
                ])

        # 按 partitions entries 顺序把各分区镜像 dd 进 raw.img
        for entry in entries:
            image_rel = self.PARTITION_IMAGES.get(entry["name"])
            if not image_rel:
                continue  # userdata 等无镜像的分区
            image_path = target_dir / image_rel
            if not image_path.exists():
                self._status(f"跳过 {entry['name']}: {image_path} 不存在")
                continue
            self._ensure_partition_image_fits(image_path, entry)
            offset_sectors = entry["_offset_sectors"]
            self._status(
                f"dd {image_rel} → sector {offset_sectors}")
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
        """将配置中的 hex 字符串偏移/大小转为整数。"""
        resolved = []
        for entry in entries:
            e = dict(entry)
            e["_offset_sectors"] = (int(entry.get("offset", "0"), 0)
                                    if entry.get("offset") else 0)
            e["_size_sectors"] = resolve_image_size(entry).sectors
            resolved.append(e)
        return resolved

    def _ensure_partition_image_fits(self, image_path: Path, entry: dict):
        """确保分区镜像不超过初始 GPT 分区大小。"""
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
        return max_end + 2048  # GPT 尾部保留

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
