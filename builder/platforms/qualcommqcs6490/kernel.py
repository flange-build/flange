"""Qualcomm QCS6490 内核构建器。

标准 mainline 风格构建（radxa/kernel@linux-6.18.2，单仓库，非 a733 的 BSP 聚合）：
  make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- qcom_module_defconfig
  make Image qcom/qcs6490-radxa-dragon-q6a.dtb modules
开源 Adreno 走内核 in-tree drm/msm，无 out-of-tree 模块。
"""

from pathlib import Path

from builder.kernel_base import KernelBuilder


class Qcs6490KernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        # 大小写不敏感 FS 适配（macOS 宿主挂载卷上 git checkout 会丢同名异写文件）
        self._write_case_insensitive_fix(src_dir)

        defconfig = config["kernel"]["defconfig"]
        if isinstance(defconfig, str):
            defconfig = [defconfig]
        for dc in defconfig:
            self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS)
        # 合并大小写适配 fragment（敏感 FS 上为空，无副作用）
        self.make(src_dir, ["case_insensitive_fix.config"],
                  arch=self.ARCH, cross=self.CROSS)
        # 裁剪 Q6A 用不到的大驱动（如 DRM_NOUVEAU），加速编译
        self._apply_disable_configs(src_dir, config)

    def _apply_disable_configs(self, src_dir: Path, config: dict):
        """把 kernel.disable_configs 写成 config 片段并合并（# CONFIG_X is not set）。"""
        disable = config["kernel"].get("disable_configs") or []
        if not disable:
            return
        frag = src_dir / f"arch/{self.ARCH}/configs/flange_trim.config"
        frag.write_text(
            "".join(f"# CONFIG_{sym} is not set\n" for sym in disable))
        self.make(src_dir, ["flange_trim.config"],
                  arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        dts_dir = config["kernel"].get("dts_dir", "qcom")
        dtb = config["kernel"]["dtb"]

        targets = ["Image", f"{dts_dir}/{dtb}.dtb", "modules"]
        # DTC_FLAGS_<basetarget>=-@：经 scripts/Makefile.lib:369 的
        #   DTC_FLAGS += $(DTC_FLAGS_$(basetarget))
        # 给本 dtb 启用 `-@`，产生 `__symbols__` 节点，使构建期
        # `fdtoverlay` 能解析 .dtbo 的 `__fixups__`。
        # 见 [[build-time-dtb-overlay-merge]]：base dtb 必须含 __symbols__。
        # QCLINUX BSP 默认 `dtb-y`（非 `base-dtb-y`），不带 -@，需显式加。
        dtc_at_arg = f"DTC_FLAGS_{dtb}=-@"
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error", dtc_at_arg],
                  label="编译内核...")

        # 编译 out-of-tree 模块（由 [[硬件特性包]] 注入 kernel.oot_modules，
        # 典型如 meizu-e3-panel 的 sec_ts / sgm37604a / panel_meizu_e3 三件套）。
        # 复用 KernelBuilder 基类的 OOT 流水线；本平台仅需调度。
        self._compile_oot_modules(src_dir, config, jobs)

        # 安装 in-tree 模块（strip）到 staging，供 rootfs 收取
        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])
        # 安装 out-of-tree 模块到同一 staging 目录（updates/）
        self._install_oot_modules(src_dir, config, modules_staging)
        # 清理 source/build symlink（指向构建树绝对路径，打包无意义）
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(
                    f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "qcom")
        dtb = config["kernel"]["dtb"]
        return {
            "image":   src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb":     src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dtb}.dtb",
            "modules": src_dir / "_modules_staging",
        }
