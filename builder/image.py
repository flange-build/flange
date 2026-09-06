"""GptImageBuilder — 整盘 GPT 镜像装配的公共实现。

装配本身是平台无关的：按 `partitions.entries` 算出总容量、建空镜像、写 GPT
分区表、把各分区镜像 dd 到对应偏移。平台之间真正不同的只有三件事，各自有
一个声明位：

  - `PARTITION_IMAGES` / `_partition_images(config)`：分区名 → 产物相对路径。
    Rockchip 的 idbloader/u-boot 写在 user area 所以进 raw.img；Amlogic 走
    硬件 boot0 分区，bootloader 不进 raw.img。
  - `ROOTFS_PARTUUID`：给 rootfs 分区钉一个固定 PARTUUID，供 kernel cmdline
    的 `root=PARTUUID=` 引用。
  - `_gpt_partition_ops(...)`：某个分区在 `mkpart` 之后的额外 GPT 操作
    （ESP 标记、Type-UUID 伪装等启动固件 quirk）。

`raw` 类型的分区表示"这块区域不是文件系统，直接 dd 裸数据"，因此不进 GPT
分区表 —— 这条规则对所有平台一致。
"""

from pathlib import Path

from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.graph import component_enabled
from builder.partition.layout import PartitionLayout, ResolvedPartition


class GptImageBuilder(ComponentBuilder):
    """按分区表把前序组件的产物装配成整盘 raw.img。"""

    component = "image"

    #: flange 约定 config 的 offset/size 以 512 字节为单位声明。
    FLANGE_SECTOR = 512

    #: 目标介质的逻辑块大小默认值；`partitions.sector_size` 可覆盖
    #: （UFS 是 4096，写 GPT 必须按它算，否则 LBA 数值含义错位 8 倍）。
    SECTOR_SIZE = 512

    #: rootfs 分区的固定 PARTUUID；None 表示不钉。
    ROOTFS_PARTUUID: str | None = None

    #: 分区名 → 产物相对路径（相对 target_dir）。
    PARTITION_IMAGES: dict[str, str] = {}

    def __init__(self, docker, source):
        super().__init__(docker, source)
        # compile() 会按 partitions.sector_size 覆盖；先给出类级默认，让直接
        # 调用 _resolve_entries 一类方法（不经 compile）的调用方也拿到确定的
        # 扇区大小。
        self._sector = self.SECTOR_SIZE

    def build(self, config: dict) -> dict:
        """整盘组装无源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = self.work_dir()
        self._sector = self._sector_size(config)
        # 几何解析只在这一处发生：config 按 512B 声明，换算到目标介质的逻辑
        # 块大小由 PartitionLayout 统一完成。
        layout = self._layout(config)
        entries = list(layout)

        total_bytes = (layout.total_sectors + 2048) * self._sector
        raw_img = self._work_dir / "raw.img"
        self._status(f"创建空镜像 ({total_bytes // (1024 * 1024)}MB, 扇区 {self._sector})...")
        self.docker.run(["truncate", "-s", str(total_bytes), str(raw_img)])

        self._write_gpt(raw_img, entries)
        self._write_partitions(raw_img, entries, config)
        self._raw_img = raw_img

    # ------------------------------------------------------------------
    # 平台声明位
    # ------------------------------------------------------------------

    def _layout(self, config: dict) -> PartitionLayout:
        """本次装配的分区几何，已换算到目标介质的逻辑块大小。

        几何解析只在这一处发生 —— 消费方拿到的是数字，不再各自解析
        `partitions.entries` 里的字符串。
        """
        return PartitionLayout.from_config(config).for_sector_size(self._sector_size(config))

    def _sector_size(self, config: dict) -> int:
        """目标逻辑块大小。"""
        return int((config.get("partitions") or {}).get("sector_size", self.SECTOR_SIZE))

    def _partition_images(self, config: dict) -> dict:
        """分区名 → 产物相对路径。平台可按配置路由（UBI / recovery 开关等）。"""
        return {
            name: path
            for name, path in self.PARTITION_IMAGES.items()
            if component_enabled(config, name)
        }

    def _gpt_partition_ops(
        self,
        entry: ResolvedPartition,
        gpt_index: int,
        device: str,
    ) -> list[list[str]]:
        """该分区在 mkpart 之后的额外 GPT 操作。

        默认只给 rootfs 钉固定 PARTUUID（供 kernel cmdline 的
        `root=PARTUUID=` 引用）。启动固件 quirk 由平台覆写补充。
        """
        if entry.name == "rootfs" and self.ROOTFS_PARTUUID:
            return [["sfdisk", "--part-uuid", device, str(gpt_index), self.ROOTFS_PARTUUID]]
        return []

    # ------------------------------------------------------------------
    # 装配
    # ------------------------------------------------------------------

    def _write_gpt(self, raw_img: Path, entries: list) -> None:
        """写 GPT 分区表。

        512 字节扇区可以让 parted 直接在普通文件上写；非 512（UFS 4K）必须
        先 `losetup -b <sector>` 把镜像挂成报告目标 LBA 的 loop 设备 ——
        parted/sfdisk 对普通文件一律按 512-LBA 处理，写进 4K 介质后 LBA
        数值含义错位 8 倍，固件找不到分区（实板踩过）。
        """
        gpt_entries = [e for e in entries if not e.is_raw]
        if self._sector == self.FLANGE_SECTOR:
            self._status("写 GPT 分区表...")
            self.docker.run(["parted", "-s", str(raw_img), "mklabel", "gpt"])
            for gpt_index, entry in enumerate(gpt_entries, start=1):
                for command in self._mkpart_ops(entry, gpt_index, str(raw_img)):
                    self.docker.run(command)
            return

        self._status(f"写 GPT 分区表（loop -b {self._sector} + parted）...")
        commands = ["parted -s $LOOP mklabel gpt"]
        for gpt_index, entry in enumerate(gpt_entries, start=1):
            commands.extend(" ".join(op) for op in self._mkpart_ops(entry, gpt_index, "$LOOP"))
        script = (
            f"set -e; LOOP=$(losetup -b {self._sector} -f --show {raw_img}); "
            f"trap 'losetup -d $LOOP' EXIT; " + "; ".join(commands)
        )
        self.docker.run_privileged(["sh", "-c", script])

    def _mkpart_ops(
        self,
        entry: ResolvedPartition,
        gpt_index: int,
        device: str,
    ) -> list[list[str]]:
        """一个分区的 mkpart 及其后续 GPT 操作。"""
        start = entry.offset_sectors * self._sector
        end = start + entry.size_sectors * self._sector - 1
        ops = [["parted", "-s", device, "mkpart", entry.label, entry.type, f"{start}B", f"{end}B"]]
        ops.extend(self._gpt_partition_ops(entry, gpt_index, device))
        return ops

    def _write_partitions(
        self,
        raw_img: Path,
        entries: list,
        config: dict,
    ) -> None:
        """按 entries 顺序把各分区镜像 dd 到对应偏移。"""
        image_map = self._partition_images(config)
        target_dir = self.cache.target_dir
        for entry in entries:
            image_rel = image_map.get(entry.name)
            if not image_rel:
                continue  # userdata 等无镜像的分区
            image_path = target_dir / image_rel
            if not image_path.exists():
                raise BuildError(f"启用分区 {entry.name} 的产物缺失: {image_path}")
            self._ensure_partition_image_fits(image_path, entry)
            offset_sectors = entry.offset_sectors
            self._status(f"dd {image_rel} → sector {offset_sectors}")
            self.docker.run(
                [
                    "dd",
                    f"if={image_path}",
                    f"of={raw_img}",
                    f"seek={offset_sectors}",
                    # sparse：rootfs.img 声明尺寸远大于实占（ext4 实测 8GiB 声明
                    # 只用 2.7GiB），写全零块既慢又让 raw.img 失去稀疏性。
                    # notrunc 保证不截断已写入的 GPT 与前序分区。
                    "conv=notrunc,sparse",
                    f"bs={self._sector}",
                    "status=none",
                ]
            )

    def _ensure_partition_image_fits(
        self,
        image_path: Path,
        entry: ResolvedPartition,
    ) -> None:
        """确保分区镜像不超过初始 GPT 分区大小。"""
        max_bytes = entry.size_sectors * self._sector
        image_bytes = image_path.stat().st_size
        if image_bytes > max_bytes:
            raise BuildError(
                f"{entry.name} 镜像 {image_bytes} bytes 超过初始分区大小 "
                f"{max_bytes} bytes，请增大 image_size 或分区 size。"
            )
