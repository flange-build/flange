"""Rockchip 整盘镜像组装策略。

职责：将前序组件的产物按 partitions 配置组装成 raw.img（GPT 整盘镜像），
供 SD 卡/eMMC（512B 扇区）及 UFS（4096B 扇区）全盘烧录。扇区大小取自
``partitions.sector_size``，缺省 512。4096B 路径参照
``qualcommqcs6490/image.py``：用 ``losetup -b`` 把镜像挂成报告目标 LBA 的
loop 设备，让 parted 写出 4K 对齐 GPT；config 中以 512B 为单位声明的
offset/size 按目标扇区重算。

输入（从 target/<board>/<product>/<variant>/ 读取）：
  bootloader/idbloader.img
  bootloader/u-boot.itb
  boot/boot.img
  rootfs/rootfs.img

输出：
  raw.img（GPT 分区表 + 各分区镜像 dd 到对应 offset）

不负责：
  - 生成 boot.img（由 RockchipBootBuilder 负责）
  - 生成 rootfs.img（由 RockchipRootfsBuilder 负责）
"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.partition.size import resolve_image_size


class RockchipImageBuilder(ComponentBuilder):
    component = "image"
    # flange 约定 config 的 offset/size 以 512 字节为单位声明。
    FLANGE_SECTOR = 512
    # 目标逻辑块大小默认 512（eMMC/SD）；compile 按 partitions.sector_size 覆盖。
    # 类级默认让直接调 _resolve_entries（不经 compile）的调用方拿到 512 行为。
    _sector = 512
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000000"
    # 4K rk35xx UFS 上 rootfs 分区 Type-UUID 须伪装成 EFI System GUID 以规避
    # bootloader quirk（Armbian 实证）。
    EFI_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"

    # 分区名到输入镜像相对路径（相对 target_dir）的映射
    PARTITION_IMAGES = {
        "idbloader": "bootloader/idbloader.img",
        "uboot":     "bootloader/u-boot.itb",
        "boot":      "boot/boot.img",
        "rootfs":    "rootfs/rootfs.img",
        # recovery 镜像不存在时（recovery.enabled=False 或构建跳过），
        # ImageBuilder.compile 中已有"image_path 不存在则跳过"逻辑，安全。
        "recovery":  "recovery/recovery.img",
        # amp 协处理器固件 FIT（amp.enabled=False 时无 amp.img，compile 的
        # "image_path 不存在则跳过"逻辑安全跳过 amp 分区写入）。amp 分区为
        # 非 raw（ext4 占位）→ 进 GPT 具名条目，U-Boot 按名 part_get_info_by_name
        # ("amp") 定位；dd 进去的裸 FIT 块原样保留（image 全程不 mkfs）。
        "amp":       "amp/amp.img",
    }

    def build(self, config: dict) -> dict:
        """整盘组装无需克隆源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        self._sector = self._resolve_sector(config)
        entries = self._resolve_entries(
            config.get("partitions", {}).get("entries", []))
        target_dir = self.cache.target_dir

        # 计算总大小 + 创建空镜像
        total_sectors = self._total_sectors(entries)
        total_bytes = total_sectors * self._sector
        raw_img = self._work_dir / "raw.img"
        self._status(
            f"创建空镜像 ({total_bytes // (1024*1024)}MB, 扇区 {self._sector})...")
        self.docker.run(["truncate", "-s", str(total_bytes), str(raw_img)])

        # 写 GPT 分区表（raw 类型分区不进 GPT）
        if self._sector == self.FLANGE_SECTOR:
            self._write_gpt_direct(raw_img, entries)
        else:
            self._write_gpt_loop(raw_img, entries)

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
                f"bs={self._sector}",
                "status=none",
            ])

        self._raw_img = raw_img

    def _write_gpt_direct(self, raw_img: Path, entries: list):
        """512B 路径：parted 直接在 regular file 上写 GPT（默认 512-LBA）。"""
        self._status("写 GPT 分区表...")
        self.docker.run(["parted", "-s", str(raw_img), "mklabel", "gpt"])
        gpt_index = 0
        for entry in entries:
            if entry["type"] == "raw":
                continue
            gpt_index += 1
            start = entry["_offset_sectors"] * self._sector
            end = start + entry["_size_sectors"] * self._sector - 1
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

    def _write_gpt_loop(self, raw_img: Path, entries: list):
        """非 512B（UFS 4K）路径：losetup -b <sector> 把镜像挂成报告目标 LBA
        的 loop 设备，parted 据此写 4K 对齐 GPT；regular file 上 parted 默认
        512-LBA 会使 LBA 数值含义错位 → 固件找不到分区（参照 qcs6490）。"""
        self._status(f"写 GPT 分区表（loop -b {self._sector} + parted）...")
        loop_setup = f"losetup -b {self._sector} -f --show {raw_img}"
        cmds = ["parted -s $LOOP mklabel gpt"]
        gpt_index = 0
        for entry in entries:
            if entry["type"] == "raw":
                continue
            gpt_index += 1
            start = entry["_offset_sectors"] * self._sector
            end = start + entry["_size_sectors"] * self._sector - 1
            cmds.append(
                f"parted -s $LOOP mkpart {entry['name']} {entry['type']} "
                f"{start}B {end}B")
            if entry["name"] == "rootfs":
                # Type-UUID 伪装成 EFI System GUID（4K rk35xx quirk），
                # 同时保留固定 PARTUUID 供 kernel cmdline root=PARTUUID 引用。
                cmds.append(
                    f"sfdisk --part-type $LOOP {gpt_index} {self.EFI_TYPE_GUID}")
                cmds.append(
                    f"sfdisk --part-uuid $LOOP {gpt_index} {self.ROOTFS_PARTUUID}")
        script = (f"set -e; LOOP=$({loop_setup}); "
                  f"trap 'losetup -d $LOOP' EXIT; "
                  + "; ".join(cmds))
        self.docker.run_privileged(["sh", "-c", script])

    def _resolve_sector(self, config: dict) -> int:
        """目标逻辑块大小，取自 partitions.sector_size，缺省 512。"""
        return int(config.get("partitions", {}).get("sector_size", 512))

    def _resolve_entries(self, entries: list) -> list:
        """将配置中的 hex 字符串偏移/大小转为目标扇区计数。

        config 的 offset/size 以 512B 为单位声明；目标扇区 != 512 时按
        ``off_512 × 512 ÷ sector`` 重算，否则 4K 盘上 "3G" 会被当成
        3G/512 个 4K 扇区 → 整盘虚胖（参照 qcs6490）。"""
        resolved = []
        for entry in entries:
            e = dict(entry)
            off_512 = (int(entry.get("offset", "0"), 0)
                       if entry.get("offset") else 0)
            e["_offset_sectors"] = off_512 * self.FLANGE_SECTOR // self._sector
            e["_size_sectors"] = resolve_image_size(entry).bytes // self._sector
            resolved.append(e)
        return resolved

    def _ensure_partition_image_fits(self, image_path: Path, entry: dict):
        """确保分区镜像不超过初始 GPT 分区大小。"""
        max_bytes = entry["_size_sectors"] * self._sector
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

    def _status(self, msg: str):
        if self.output:
            self.output.status(msg)

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
