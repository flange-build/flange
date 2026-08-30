"""Rockchip Rootfs 构建策略。

编排、两阶段缓存、overlay、固件、账号配置来自 `RootfsBuilder` 基类。
本平台的唯一偏离是 **SPI NAND 的 UBI 路由**：``rootfs.image_format: ubi``
时产出 UBIFS + UBI volume 而非 ext4 镜像，且根文件系统由 kernel bootargs
（``ubi.mtd=<n>``）挂载，因此 fstab 不声明任何挂载项。
"""

from pathlib import Path

from builder.config.validate import validate_mtd_ubi
from builder.docker import BuildError
from builder.partition.rockchip import parse_parameter_file
from builder.partition.size import parse_size, resolve_image_size
from builder.paths import PROJECT_ROOT
from builder.rootfs import RootfsBuilder


class RockchipRootfsBuilder(RootfsBuilder):

    def _fstab_mounts(self, config: dict) -> tuple:
        """UBI rootfs 由 kernel bootargs 挂载，不声明 ext4 挂载项。"""
        if (config.get("rootfs") or {}).get("image_format") == "ubi":
            return ()
        return super()._fstab_mounts(config)

    def _build_image(self, rootfs_dir: Path, config: dict) -> None:
        """按 image_format 路由：ext4 走基类，ubi 走 UBIFS + ubinize。"""
        if (config.get("rootfs") or {}).get("image_format", "ext4") == "ubi":
            self._build_ubi(rootfs_dir, config)
        else:
            super()._build_image(rootfs_dir, config)

    def collect(self, src_dir: Path, config: dict) -> dict:
        if config.get("rootfs", {}).get("image_format", "ext4") == "ubi":
            return {"ubi": self._output}
        return {"rootfs": self._output}

    def _build_ubi(self, rootfs_dir: Path, config: dict) -> None:
        """用显式 NAND 几何生成 UBIFS 与 UBI volume。"""
        validate_mtd_ubi(config)
        ubi = config["rootfs"]["ubi"]
        min_io = int(ubi["min_io_size"], 0) if isinstance(
            ubi["min_io_size"], str) else int(ubi["min_io_size"])
        peb = int(ubi["peb_size"], 0) if isinstance(
            ubi["peb_size"], str) else int(ubi["peb_size"])
        subpage = int(ubi["subpage_size"], 0) if isinstance(
            ubi["subpage_size"], str) else int(ubi["subpage_size"])
        vid = int(ubi["vid_hdr_offset"], 0) if isinstance(
            ubi["vid_hdr_offset"], str) else int(ubi["vid_hdr_offset"])
        leb = int(ubi["leb_size"], 0) if isinstance(
            ubi["leb_size"], str) else int(ubi["leb_size"])
        max_leb = int(ubi["max_leb_count"], 0) if isinstance(
            ubi["max_leb_count"], str) else int(ubi["max_leb_count"])
        volume_size = parse_size(ubi["volume_size"]).bytes

        self._ensure_rootfs_fits_ubi(rootfs_dir, volume_size)
        ubifs = self._work_dir / "rootfs.ubifs"
        self._status("生成 rootfs.ubifs...")
        mkfs_command = [
            "mkfs.ubifs",
            "-r", str(rootfs_dir),
            "-o", str(ubifs),
            "-m", str(min_io),
            "-e", str(leb),
            "-c", str(max_leb),
        ]
        if ubi.get("space_fixup", False):
            # 部分 USB 刷写器会把全 0xFF NAND page 也实际编程；-F 让
            # UBIFS 首次挂载先修复空闲区，避免后续写入形成二次编程。
            mkfs_command.append("-F")
        self.docker.run(mkfs_command)
        self._ensure_file_fits(
            ubifs, volume_size, "UBIFS", "rootfs.ubi.volume_size")

        ubinize_cfg = self._work_dir / "ubinize.cfg"
        ubinize_cfg.write_text(
            "[rootfs]\n"
            "mode=ubi\n"
            f"image={ubifs}\n"
            "vol_id=0\n"
            "vol_type=dynamic\n"
            "vol_name=rootfs\n"
            f"vol_size={volume_size}\n"
        )
        self._output = self._work_dir / "rootfs.ubi"
        self._status("生成 rootfs.ubi...")
        self.docker.run([
            "ubinize",
            "-o", str(self._output),
            "-m", str(min_io),
            "-p", str(peb),
            "-s", str(subpage),
            "-O", str(vid),
            str(ubinize_cfg),
        ])
        physical_limit = self._ubi_physical_limit(config, peb)
        self._ensure_file_fits(
            self._output, physical_limit, "UBI", "rootfs MTD 可用容量")

    def _ensure_rootfs_fits_ubi(
        self,
        rootfs_dir: Path,
        volume_size: int,
    ) -> None:
        """在 mkfs.ubifs 前以 staging apparent size 做逻辑容量门禁。"""
        result = self.docker.run(
            ["du", "-sb", str(rootfs_dir)], capture=True)
        used_bytes = int(result.stdout.split()[0])
        if used_bytes > volume_size:
            raise BuildError(
                f"rootfs staging 内容 {used_bytes} bytes 超过 UBI volume "
                f"{volume_size} bytes；请精简 rootfs 或增大 volume_size。")

    @staticmethod
    def _ensure_file_fits(
        path: Path,
        limit: int,
        label: str,
        limit_label: str,
    ) -> None:
        """拒绝截断超过逻辑/物理容量的 UBIFS/UBI 产物。"""
        if not path.is_file():
            raise FileNotFoundError(f"{label} 产物未生成: {path}")
        size = path.stat().st_size
        if size > limit:
            raise BuildError(
                f"{label} 产物 {size} bytes 超过 {limit_label} "
                f"{limit} bytes；禁止截断写入。")

    @staticmethod
    def _ubi_physical_limit(config: dict, peb_size: int) -> int:
        """返回扣除显式坏块余量后的 rootfs MTD 物理容量。"""
        partitions = config["partitions"]
        if partitions.get("format", "gpt") == "mtd":
            parameter = Path(partitions["parameter"])
            if not parameter.is_absolute():
                parameter = PROJECT_ROOT / parameter
            entries = parse_parameter_file(parameter)
            rootfs = next(entry for entry in entries if entry.name == "rootfs")
            storage_bytes = parse_size(config["storage"]["size"]).bytes
            partition_bytes = rootfs.size_bytes(storage_bytes)
            assert partition_bytes is not None
        else:
            rootfs_entry = next(
                entry for entry in partitions["entries"]
                if entry["name"] == "rootfs")
            # Rockchip GPT parameter 生成器会把 remaining 展开为 image_size，
            # 因此物理门禁必须使用同一解析规则。
            partition_bytes = resolve_image_size(rootfs_entry).bytes
        reserved_value = config["rootfs"]["ubi"]["reserved_pebs"]
        reserved = int(reserved_value, 0) if isinstance(
            reserved_value, str) else int(reserved_value)
        return partition_bytes - reserved * peb_size
