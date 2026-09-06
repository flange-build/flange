"""Qualcomm QCS6490 bootloader 构建器 —— 消费 Radxa 预编 EDK2 SPI 固件。

高通启动固件（XBL / EDK2 UEFI(PILFv) / TZ / HYP / AOP / firehose loader）是签名
blob，flange 不编译：下载 Radxa 预编 flat_build 包及可选 UFS 资源，供
QualcommFlashStrategy 经 edl-ng 刷写。
"""

import shutil
import zipfile

from builder.base import ComponentBuilder


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

        self._status("下载并校验 Radxa 预编 EDK2 SPI 固件（不编译）...")
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
        return {"edk2": edk2_dir}
