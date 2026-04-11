"""Rockchip 镜像组装策略 -- 替代 build_boot.sh + build_image.sh"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipImageBuilder(ComponentBuilder):
    component = "image"
    SECTOR_SIZE = 512
    IDBLOADER_SECTOR = 64
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000000"

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        partitions = config.get("partitions", {})
        entries = partitions.get("entries", [])

        # 计算分区偏移和镜像大小
        self._entries = self._resolve_offsets(entries)

        # 创建空镜像
        total_sectors = self._calculate_total_sectors()
        total_bytes = total_sectors * self.SECTOR_SIZE
        raw_img = self._work_dir / "raw.img"
        self.docker.run_privileged([
            "dd", "if=/dev/zero", f"of={raw_img}",
            "bs=1", "count=0", f"seek={total_bytes}",
        ])

        # GPT 分区表
        self.docker.run_privileged(
            ["parted", "-s", str(raw_img), "mklabel", "gpt"])

        for entry in self._entries:
            if entry["type"] == "raw":
                continue  # raw 分区不进分区表
            start_bytes = entry["_offset_sectors"] * self.SECTOR_SIZE
            end_bytes = (start_bytes
                         + entry["_size_sectors"] * self.SECTOR_SIZE - 1)
            self.docker.run_privileged([
                "parted", "-s", str(raw_img), "mkpart",
                entry["name"], entry["type"],
                f"{start_bytes}B", f"{end_bytes}B",
            ])

        # 设置 rootfs PARTUUID
        self.docker.run_privileged([
            "sfdisk", "--part-uuid", str(raw_img),
            "2", self.ROOTFS_PARTUUID,
        ], check=False)

        self._raw_img = raw_img

    def _resolve_offsets(self, entries):
        """将配置中的 hex 字符串偏移转为整数。"""
        resolved = []
        for entry in entries:
            e = dict(entry)
            e["_offset_sectors"] = (int(entry.get("offset", "0"), 0)
                                    if entry.get("offset") else 0)
            if entry["size"] == "remaining":
                e["_size_sectors"] = 0  # 计算时特殊处理
            else:
                e["_size_sectors"] = int(entry["size"], 0)
            resolved.append(e)
        return resolved

    def _calculate_total_sectors(self):
        """计算镜像所需总 sector 数。"""
        max_end = 0
        for entry in self._entries:
            if entry["size"] == "remaining":
                # 默认给 remaining 分配 4G
                entry["_size_sectors"] = (
                    (4 * 1024 * 1024 * 1024) // self.SECTOR_SIZE)
            end = entry["_offset_sectors"] + entry["_size_sectors"]
            if end > max_end:
                max_end = end
        return max_end + 2048  # GPT 尾部保留

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
