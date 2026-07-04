"""Allwinner H3 内核构建策略 -- 主线内核，32 位 ARM 架构。"""

from pathlib import Path
from builder.kernel_base import KernelBuilder
from builder.dtb_overlay import (
    dtb_overlays,
    kernel_overlay_dir,
    overlay_make_targets,
    require_overlay_files,
)


class AllwinnerH3KernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm"
    # Docker 镜像已预装系统包 gcc-arm-linux-gnueabihf（docker/Dockerfile 第
    # 23-25 行），无需 aarch64 平台那种自定义 /opt gcc-10 工具链（该定制是为
    # 规避 gcc-13 在 RK3576 UFS 驱动上的特定 miscompile，H3 无同类已知问题，
    # 详见 design.md 决策 2）。
    CROSS = "arm-linux-gnueabihf-"

    def configure(self, src_dir: Path, config: dict):
        self._write_case_insensitive_fix(src_dir)
        for dc in self._resolve_defconfig_targets(
                src_dir, config["kernel"]["defconfig"]):
            self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        dts_dir = config["kernel"].get("dts_dir", "allwinner")
        dts = config["kernel"]["dts"]
        targets = [
            "zImage",
            f"{dts_dir}/{dts}.dtb",
            *overlay_make_targets(config, dts_dir),
            "modules",
        ]
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error"],
                  label="编译内核...")
        self._compile_oot_modules(src_dir, config, jobs)

        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(
                    f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()
        self._install_oot_modules(src_dir, config, modules_staging)

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "allwinner")
        dts = config["kernel"]["dts"]
        outputs = {
            "image": src_dir / f"arch/{self.ARCH}/boot/zImage",
            "dtb": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dts}.dtb",
            "modules": src_dir / "_modules_staging",
        }
        overlays = dtb_overlays(config)
        if overlays:
            overlay_dir = kernel_overlay_dir(src_dir, self.ARCH, dts_dir)
            require_overlay_files(overlay_dir, overlays)
            outputs["dtbos"] = overlay_dir
        return outputs
