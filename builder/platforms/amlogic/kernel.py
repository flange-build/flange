"""Amlogic 内核构建策略。

mainline kernel 6.12 LTS arm64，DT 路径 ``arch/arm64/boot/dts/amlogic/``。
首版聚焦 VIM3L 串口 + SSH + Wi-Fi + BT，所有驱动走 mainline in-tree
（无 OOT 模块），defconfig 直接用 arm64 generic ``defconfig``。

与 rockchip 的差异：
- 无 vendor patch 链；configure 直接 ``make defconfig``
- 无 panthor / mali_kbase 复杂度（GPU 首版 Non-Goal，用 in-tree panfrost 即可）
- defconfig 是有序 target 数组，可叠加 ``case_insensitive_fix.config`` 等 fragment
- 设备树目录由 ``kernel.device_tree.directory`` 声明
- ``KCFLAGS=-Wno-error`` 仍加，防 mainline 偶发 warning 当 error
"""

from pathlib import Path
from builder.config.canonical import kernel_arch, kernel_device_tree
from builder.kernel_base import KernelBuilder
from builder.dtb_overlay import (
    intree_overlays,
    kernel_overlay_dir,
    overlay_make_targets,
    require_overlay_files,
)


class AmlogicKernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"

    def configure(self, src_dir: Path, config: dict):
        """按序应用 defconfig target，再应用 ``kernel.config`` override。"""
        self.ARCH = kernel_arch(config)
        self._write_case_insensitive_fix(src_dir)
        for dc in self._resolve_defconfig_targets(
                src_dir, config["kernel"]["defconfig"]):
            self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS)
        override = self._write_config_override_fragment(src_dir, config)
        if override:
            self.make(src_dir, [override], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        # 单文件 dtb 目标：用 "<dts_dir>/<dts>.dtb" 的子目录相对路径，
        # kbuild 的 ``%.dtb: dtbs_prepare`` 规则会展开成
        # ``$(MAKE) $(build)=$(dtstree) $(dtstree)/<dts_dir>/<dts>.dtb``，
        # 不需要在子目录 Makefile 的 dtb-y 中登记。
        dts_dir, dts = kernel_device_tree(config)
        targets = [
            "Image",
            f"{dts_dir}/{dts}.dtb",
            *overlay_make_targets(config, dts_dir),
            "modules",
        ]
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error"],
                  label="编译内核...")

        # OOT 模块（首版 amlogic 无声明，但接口保留）
        self._compile_oot_modules(src_dir, config, jobs)

        # in-tree 模块安装到 staging 目录（带 strip）。先清掉旧 release 残留，
        # 避免跨 build kernel.release 变化导致 lib/modules/ 下累积多版本撑爆
        # 下游 rootfs / recovery 分区（详见基类注释）。
        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])
        # ``modules_install`` 在 lib/modules/<ver>/ 下创建 source/build symlink
        # 指向容器内绝对路径，部署不需要且会让 shutil.copytree 报错，删掉。
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(
                    f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()
        # OOT 模块安装到同一 staging（首版无声明时为 no-op）
        self._install_oot_modules(src_dir, config, modules_staging)

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir, dts = kernel_device_tree(config)
        outputs = {
            "image": src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dts}.dtb",
            "modules": src_dir / "_modules_staging",
        }
        overlays = intree_overlays(config)
        if overlays:
            overlay_dir = kernel_overlay_dir(src_dir, self.ARCH, dts_dir)
            require_overlay_files(overlay_dir, overlays)
            outputs["dtbos"] = overlay_dir
        return outputs
