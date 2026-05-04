"""Rockchip 内核构建策略 -- 替代 kernel/rockchip/build.sh"""

from pathlib import Path
from builder.kernel_base import KernelBuilder
from builder.dtb_overlay import (
    dtb_overlays,
    kernel_overlay_dir,
    overlay_make_targets,
    require_overlay_files,
)


class RockchipKernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        defconfig = config["kernel"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        # 单文件 dtb 目标：用 "<dts_dir>/<dts>.dtb" 这种子目录相对路径
        # （不是 basename 也不是 arch/... 完整路径）。内核顶层 Makefile
        # 的 `%.dtb: dtbs_prepare` 规则把它展开成：
        #   $(MAKE) $(build)=$(dtstree) $(dtstree)/<dts_dir>/<dts>.dtb
        # kbuild 顺着 arch/.../dts/Makefile 的 `subdir-y += <dts_dir>`
        # 递归下到子目录，再由 scripts/Makefile.build 的通用模式规则
        # `$(obj)/%.dtb: $(src)/%.dts FORCE` 直接按 .dts 源编 .dtb ——
        # 目标设备树无需在子目录 Makefile 的 dtb-y 里登记。
        dts_dir = config["kernel"].get("dts_dir", "rockchip")
        dts = config["kernel"]["dts"]
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
        # 编译 out-of-tree 模块
        self._compile_oot_modules(src_dir, config, jobs)

        # 安装 in-tree 模块（带 strip）
        modules_staging = src_dir / "_modules_staging"
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])
        # make modules_install 会在 lib/modules/<ver>/ 下创建 source/build
        # symlink 指向容器内绝对路径（/workspace/...），部署不需要且会导致
        # shutil.copytree 报错，直接删掉。
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(
                    f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()
        # 安装 out-of-tree 模块到同一 staging 目录
        self._install_oot_modules(src_dir, config, modules_staging)

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "rockchip")
        dts = config["kernel"]["dts"]
        outputs = {
            "image": src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dts}.dtb",
            "modules": src_dir / "_modules_staging",
        }
        overlays = dtb_overlays(config)
        if overlays:
            overlay_dir = kernel_overlay_dir(src_dir, self.ARCH, dts_dir)
            require_overlay_files(overlay_dir, overlays)
            outputs["dtbos"] = overlay_dir
        return outputs
