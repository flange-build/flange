"""Qualcomm QCS6490 bootloader 构建器 —— 消费预编启动固件包。

高通启动固件（XBL / EDK2 UEFI(PILFv) / TZ / HYP / AOP / firehose loader）是签名
blob，flange 不编译：下载板厂预编 flat build 包（Radxa SPI 固件，或 RUBIK Pi 3
等位于 UFS boot LUN 的固件）及可选 UFS 资源，供 QualcommFlashStrategy 经 edl-ng 刷写。
声明 ``ufs_rawprogram`` 时在构建期校验固件包可被完整、安全地刷写。
"""

import shutil
import zipfile

from builder.base import ComponentBuilder
from builder.flash.qualcomm_ufs import check_firmware_bundle


class Qcs6490BootloaderBuilder(ComponentBuilder):
    component = "bootloader"

    def build(self, config: dict) -> dict:
        """EDK2 SPI 固件无源码仓库，下载预编包即可。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        bl = config.get("bootloader", {})
        firmware = bl.get("edk2_firmware")
        if not isinstance(firmware, dict):
            raise ValueError("bootloader.edk2_firmware 未配置")

        self._work_dir = self.work_dir()
        extract_dir = self._work_dir / "edk2"
        extract_dir.mkdir(parents=True, exist_ok=True)

        self._status("下载并校验预编启动固件包（不编译）...")
        zip_path = self.source.ensure_prebuilt_image(
            f"{config['board']}-edk2",
            firmware,
        )
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        ufs_firehose = bl.get("ufs_firehose")
        ufs_provisions = bl.get("ufs_provisions") or {}
        if bool(ufs_firehose) != bool(ufs_provisions):
            raise ValueError("bootloader.ufs_firehose/ufs_provisions 必须同时配置")
        self._ufs_assets = []
        if ufs_firehose:
            self._ufs_assets.append(
                self.source.ensure_prebuilt_image(f"{config['board']}-ufs-firehose", ufs_firehose)
            )
        for profile, asset in ufs_provisions.items():
            if not isinstance(asset, dict) or not asset.get("url"):
                continue
            self._ufs_assets.append(
                self.source.ensure_prebuilt_image(
                    f"{config['board']}-ufs-provision-{profile}", asset
                )
            )

    def collect(self, src_dir, config: dict) -> dict:
        # flat_build/spinor/<board>/ 下含 firehose loader + rawprogram*.xml + 固件 blob。
        # 以 firehose loader 所在目录作为 EDK2 固件根（兼容 zip 内层级差异）。
        bl = config.get("bootloader", {})
        loader = bl.get("firehose_loader", "prog_firehose_ddr.elf")
        matches = list(self._work_dir.rglob(loader))
        if matches:
            edk2_dir = matches[0].parent
        else:
            raise FileNotFoundError(f"固件包缺少声明的 firehose loader: {loader}")
        for asset in self._ufs_assets:
            shutil.copy2(asset, edk2_dir / asset.name)
        if bl.get("ufs_rawprogram"):
            check_firmware_bundle(
                edk2_dir, bl["ufs_rawprogram"], bl.get("ufs_patch") or [], None)
        return {"edk2": edk2_dir}
