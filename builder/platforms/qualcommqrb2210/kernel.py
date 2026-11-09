"""UNO Q 官方 ARM64 内核、合成设备树与匹配模块构建。"""

import shutil
from pathlib import Path

from builder.config.canonical import kernel_device_tree
from builder.kernel_base import KernelBuilder
from builder.dtb_overlay import intree_overlays, build_overlays, copy_declared_overlays


class Qrb2210KernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        self.CROSS = config["kernel"].get("cross_compile", self.CROSS)
        self._write_case_insensitive_fix(src_dir)
        # 此位置由 component_plan 纳入内容哈希，不能读取未声明的临时片段。
        fragment_dir = (self.components_root / "board" / config["board"]
                        / "patches" / "kernel")
        for fragment in sorted(fragment_dir.glob("*.config")):
            shutil.copyfile(fragment, src_dir / "arch/arm64/configs" / fragment.name)
        targets = self._resolve_defconfig_targets(src_dir, config["kernel"]["defconfig"])
        for target in targets:
            self.make(src_dir, [target], arch=self.ARCH, cross=self.CROSS)
        override = self._write_config_override_fragment(src_dir, config)
        if override:
            self.make(src_dir, [override], arch=self.ARCH, cross=self.CROSS)
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        directory, name = kernel_device_tree(config)
        # 7.0 的最终 DTB 由内核 Makefile 合成 base + USB-C 音视频 overlay。
        overlays = intree_overlays(config)
        extra = [f"CC=ccache {self.CROSS}gcc", "HOSTCC=ccache gcc"]
        if build_overlays(config):
            extra.append("DTC_FLAGS=-@")
        self.make(src_dir, ["Image", f"{directory}/{name}.dtb", "modules"]
                  + [f"{directory}/{overlay}" for overlay in overlays],
                  arch=self.ARCH, cross=self.CROSS, jobs=config.get("jobs", 0),
                  extra=extra,
                  label="编译 UNO Q 内核、设备树和模块")
        self._compile_oot_modules(src_dir, config, config.get("jobs", 0))
        staging = src_dir / "_modules_staging"
        self._clean_modules_staging(staging)
        staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"], arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={staging}", "INSTALL_MOD_STRIP=1"])
        self._install_oot_modules(src_dir, config, staging)
        for name in ("source", "build"):
            for link in (staging / "lib/modules").glob(f"*/{name}"):
                if link.is_symlink():
                    link.unlink()

    def collect(self, src_dir: Path, config: dict) -> dict:
        directory, name = kernel_device_tree(config)
        outputs = {
            "image": src_dir / "arch/arm64/boot/Image",
            "dtb": src_dir / f"arch/arm64/boot/dts/{directory}/{name}.dtb",
            "modules": src_dir / "_modules_staging",
            "config": src_dir / ".config",
        }
        names = intree_overlays(config)
        if names:
            stage = self.work_dir("kernel-overlays")
            copy_declared_overlays(src_dir / f"arch/arm64/boot/dts/{directory}", stage, names)
            outputs["dtbos"] = stage
        return outputs
