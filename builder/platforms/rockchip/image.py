"""Rockchip 整盘镜像组装策略。

装配逻辑来自 `GptImageBuilder` 基类。本平台的三处偏离：

  - **SPI NAND 不产整片镜像**。NAND 的 OOB / ECC / 坏块无法用一张 raw 镜像
    表达，因此 MTD 与 spinand 路由改为产出 `parameter.txt` 与具名分区刷写
    清单，由刷写器逐个具名写入。
  - **产物路由**：rootfs 按 `image_format` 在 ext4 / UBI 之间切换；recovery
    与 amp 未启用时不进分区映射。
  - **4K 扇区的 Type-UUID 伪装**：rk35xx UFS 上 rootfs 分区的 Type-UUID 必须
    伪装成 EFI System GUID 才能绕过 bootloader quirk（Armbian 实证）。
"""

import json
import re
import shutil
from pathlib import Path

from builder.config.canonical import kernel_device_tree
from builder.config.validate import validate_mtd_ubi
from builder.docker import BuildError
from builder.image import GptImageBuilder
from builder.partition.rockchip import (
    generate_parameter_txt,
    parse_parameter_file,
    validate_parameter_capacity,
)
from builder.partition.size import parse_size


class RockchipImageBuilder(GptImageBuilder):
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000000"

    #: 4K rk35xx UFS 上 rootfs 分区 Type-UUID 须伪装成 EFI System GUID 以
    #: 规避 bootloader quirk（Armbian 实证）。
    EFI_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"

    PARTITION_IMAGES = {
        "idbloader": "bootloader/idbloader.img",
        "uboot": "bootloader/u-boot.itb",
        "boot": "boot/boot.img",
        "rootfs": "rootfs/rootfs.img",
        # recovery / amp 未启用时由 _partition_images 摘掉。
        "recovery": "recovery/recovery.img",
        "amp": "amp/amp.img",
    }

    def compile(self, src_dir: Path, config: dict):
        if self._uses_named_nand_bundle(config):
            self._work_dir = self.work_dir()
            self._compile_mtd_bundle(config)
            return
        super().compile(src_dir, config)

    def collect(self, src_dir: Path, config: dict) -> dict:
        if self._uses_named_nand_bundle(config):
            return {
                "bundle": self._bundle_manifest,
                "parameter": self._parameter,
            }
        return super().collect(src_dir, config)

    def _gpt_partition_ops(self, entry, gpt_index, device):
        """4K 介质上给 rootfs 额外伪装 Type-UUID（见类常量说明）。"""
        ops = []
        if entry.name == "rootfs" and self._sector != self.FLANGE_SECTOR:
            ops.append(["sfdisk", "--part-type", device, str(gpt_index), self.EFI_TYPE_GUID])
        ops.extend(super()._gpt_partition_ops(entry, gpt_index, device))
        return ops

    @staticmethod
    def _uses_named_nand_bundle(config: dict) -> bool:
        """SPI NAND 始终使用 parameter + 具名 DI，不生成整片 raw.img。"""
        partition_format = (config.get("partitions") or {}).get("format", "gpt")
        storage_type = (config.get("storage") or {}).get("type")
        return partition_format == "mtd" or storage_type == "spinand"

    def _compile_mtd_bundle(self, config: dict) -> None:
        """校验并生成 SPI NAND 具名分区刷写清单，不拼整片 raw.img。"""
        validate_mtd_ubi(config)
        parameter = self._work_dir / "parameter.txt"
        partition_format = config["partitions"].get("format", "gpt")
        if partition_format == "mtd":
            parameter_source = Path(config["partitions"]["parameter"])
            if not parameter_source.is_absolute():
                parameter_source = self.context.tool_root / parameter_source
            shutil.copy2(parameter_source, parameter)
        else:
            machine = (config.get("rkbin") or {}).get("mkimage_chip", "rockchip").upper()
            parameter.write_text(
                generate_parameter_txt(
                    config["partitions"].get("entries") or [],
                    machine=machine,
                )
            )

        entries = parse_parameter_file(parameter)
        storage_bytes = parse_size(config["storage"]["size"]).bytes
        validate_parameter_capacity(entries, storage_bytes)
        by_name = {entry.name: entry for entry in entries}
        image_map = self._partition_images(config)
        target_dir = self.cache.target_dir
        manifest_parts = []
        required_names = {"uboot", "boot", "rootfs"}
        for name in ("amp", "recovery"):
            if (config.get(name) or {}).get("enabled", False):
                required_names.add(name)

        for entry in entries:
            name = entry.name
            relative = image_map.get(name)
            if not relative:
                continue
            image = target_dir / relative
            if not image.is_file():
                raise FileNotFoundError(f"MTD 分区 {name} 的镜像不存在: {image}")
            limit = entry.size_bytes(storage_bytes)
            if limit is None or image.stat().st_size > limit:
                raise BuildError(
                    f"{name} 镜像 {image.stat().st_size} bytes 超过 MTD 分区 {limit} bytes"
                )
            manifest_parts.append(
                {
                    "name": name,
                    "offset": f"0x{entry.offset:x}",
                    "size": "remaining" if entry.size is None else f"0x{entry.size:x}",
                    "image": relative,
                    "image_bytes": image.stat().st_size,
                }
            )
        missing_names = required_names - set(by_name)
        if missing_names:
            raise BuildError(
                "MTD parameter 缺少必需的具名分区: " + ", ".join(sorted(missing_names))
            )

        rootfs_index = next(index for index, entry in enumerate(entries) if entry.name == "rootfs")
        self._validate_dtb_ubi_mtd(target_dir, config, rootfs_index)
        bootloader_artifacts = [
            "bootloader/miniloader.bin",
            "bootloader/idbloader.img",
            "bootloader/u-boot.itb",
        ]
        missing_bootloader = [
            relative for relative in bootloader_artifacts if not (target_dir / relative).is_file()
        ]
        if missing_bootloader:
            raise FileNotFoundError(
                "MTD 刷写包缺少 bootloader 产物: " + ", ".join(missing_bootloader)
            )
        manifest = {
            "format": partition_format,
            "storage_type": (config.get("storage") or {}).get("type", ""),
            "storage": config["storage"],
            "parameter": "parameter.txt",
            "flash_config": "flash-config.json",
            "rootfs_mtd_index": rootfs_index,
            "bootloader_artifacts": bootloader_artifacts,
            "partitions": manifest_parts,
        }
        self._bundle_manifest = self._work_dir / "mtd-bundle.json"
        self._bundle_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        self._parameter = parameter

    def _partition_images(self, config: dict) -> dict[str, str]:
        """按 rootfs/recovery/AMP 路由返回分区镜像映射。"""
        mapping = dict(self.PARTITION_IMAGES)
        if config.get("rootfs", {}).get("image_format") == "ubi":
            mapping["rootfs"] = "rootfs/rootfs.ubi"
        if not (config.get("recovery") or {}).get("enabled", False):
            mapping.pop("recovery", None)
        if not (config.get("amp") or {}).get("enabled", False):
            mapping.pop("amp", None)
        return mapping

    def _validate_dtb_ubi_mtd(
        self,
        target_dir: Path,
        config: dict,
        rootfs_index: int,
    ) -> None:
        """从最终 DTB chosen.bootargs 交叉校验 ``ubi.mtd``。"""
        _, dts = kernel_device_tree(config)
        dtb = target_dir / "kernel" / f"{dts}.dtb"
        if not dtb.is_file():
            raise FileNotFoundError(f"MTD 启动参数校验所需 DTB 不存在: {dtb}")
        result = self.docker.run(
            ["fdtget", "-t", "s", str(dtb), "/chosen", "bootargs"],
            capture=True,
        )
        match = re.search(r"(?:^|\s)ubi\.mtd=(\d+)(?:\s|$)", result.stdout.strip())
        if not match:
            raise BuildError(f"目标 DTB {dtb.name} chosen.bootargs 缺少 ubi.mtd=<index>")
        actual = int(match.group(1))
        if actual != rootfs_index:
            raise BuildError(f"DTB ubi.mtd={actual} 与 parameter rootfs=mtd{rootfs_index} 不一致")
