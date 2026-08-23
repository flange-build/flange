"""Qualcomm QCS6490 bootloader 构建器 —— 消费 Radxa 预编 EDK2 SPI 固件。

高通启动固件（XBL / EDK2 UEFI(PILFv) / TZ / HYP / AOP / firehose loader）是签名
blob，flange 不编译：仅下载 Radxa 预编 flat_build 包并解压暂存，供 QualcommFlashStrategy
经 edl-ng 刷写 SPI NOR（bring-up 一次性）。
"""

import tempfile
import zipfile
from pathlib import Path

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
        url = bl.get("edk2_firmware_url")
        sha256 = bl.get("edk2_firmware_sha256")
        if not url or not sha256:
            raise ValueError(
                "bootloader.edk2_firmware_url/edk2_firmware_sha256 未配置")

        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-edk2-"))
        extract_dir = self._work_dir / "edk2"
        extract_dir.mkdir(parents=True, exist_ok=True)

        self._status("下载并校验 Radxa 预编 EDK2 SPI 固件（不编译）...")
        zip_path = self.source.ensure_prebuilt_image(
            f"{config['board']}-edk2",
            {"url": url, "sha256": sha256},
        )
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

    def collect(self, src_dir, config: dict) -> dict:
        # flat_build/spinor/<board>/ 下含 firehose loader + rawprogram*.xml + 固件 blob。
        # 以 firehose loader 所在目录作为 EDK2 固件根（兼容 zip 内层级差异）。
        bl = config.get("bootloader", {})
        loader = bl.get("firehose_loader", "prog_firehose_ddr.elf")
        matches = list(self._work_dir.rglob(loader))
        if matches:
            edk2_dir = matches[0].parent
        else:
            self._status(f"警告：未在固件包中找到 {loader}，回退解压根目录")
            edk2_dir = self._work_dir / "edk2"
        return {"edk2": edk2_dir}
