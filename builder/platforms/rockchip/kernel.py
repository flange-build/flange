"""Rockchip 内核构建策略 -- 替代 kernel/rockchip/build.sh"""

from pathlib import Path
from builder.base import ComponentBuilder


class RockchipKernelBuilder(ComponentBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        defconfig = config["kernel"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        self.make(src_dir, ["Image", "dtbs", "modules"],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error"])
        # 安装模块（带 strip）
        modules_staging = src_dir / "_modules_staging"
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "rockchip")
        dts = config["kernel"]["dts"]
        return {
            "image": src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dts}.dtb",
            "modules": src_dir / "_modules_staging",
            "dtbos": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/overlay",
        }
