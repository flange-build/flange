"""Qualcomm QRB2210 bootloader 构建器 —— 消费 Arduino/armbian 预编 EDL 固件。

高通启动固件（XBL / ABL / TZ / HYP / U-Boot Android boot.img / firehose loader）
是签名 / 平台 blob，flange 不编译：仅下载预编 EDL 包并解压暂存，供
QualcommQrb2210FlashStrategy 经 edl-ng 刷写 eMMC vendor 槽（bring-up 一次性）。

⚠️ 固件包 URL（armbian/qcombin「Agatti/arduino-uno-q」）与 license/重分发条款
   待实证（见 openspec tasks §5.2）。bootloader.edl_firmware_url 为空时本步骤
   跳过下载（vendor 固件需用户自备），不阻断其余构建。
"""

import tempfile
from pathlib import Path

from builder.base import ComponentBuilder


class Qrb2210BootloaderBuilder(ComponentBuilder):
    component = "bootloader"

    def build(self, config: dict) -> dict:
        """EDL 固件无源码仓库，下载预编包即可。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-edl-"))
        self._extract_dir = self._work_dir / "edl"
        self._extract_dir.mkdir(parents=True, exist_ok=True)

        bl = config.get("bootloader", {})
        url = bl.get("edl_firmware_url")
        if not url:
            # URL 未配置（待实证）：跳过下载，留空目录。vendor 固件由用户自备
            # 放入 target/bootloader/edl-firmware/，或后续填入 URL 后重建。
            self._status(
                "bootloader.edl_firmware_url 未配置，跳过 EDL 固件下载"
                "（vendor 固件需自备；见 openspec tasks §5.2）")
            return

        zip_path = self._work_dir / "edl.zip"
        self._status("下载 Arduino/armbian 预编 EDL 固件（不编译）...")
        self.docker.run(["wget", "-q", url, "-O", str(zip_path)],
                        cwd=str(self._work_dir), label="下载 EDL 固件")
        self.docker.run(["unzip", "-q", "-o", str(zip_path), "-d", str(self._extract_dir)],
                        cwd=str(self._work_dir), label="解压 EDL 固件")

    def collect(self, src_dir, config: dict) -> dict:
        # 以 firehose loader 所在目录作为 EDL 固件根（兼容 zip 内层级差异）；
        # 未找到时回退解压根目录（含 URL 未配置的空目录场景）。
        bl = config.get("bootloader", {})
        loader = bl.get("firehose_loader", "prog_firehose_ddr.elf")
        matches = list(self._work_dir.rglob(loader))
        if matches:
            edl_dir = matches[0].parent
        else:
            edl_dir = self._extract_dir
        return {"edl": edl_dir}
