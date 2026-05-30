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
        # 应用 enable(=y builtin) / disable(裁剪) 配置覆盖。
        # ⚠️ 用「追加进 .config + olddefconfig」而非 `make <frag>.config`
        # (即 scripts/kconfig/merge_config.sh)：后者对每个 "redefined" 符号在
        # CWD(=bind 挂载的源码树) 的临时文件上反复 `sed -i`，大片段(720 项裁剪)
        # 在 Docker-for-Mac bind FS 上的 rename churn 不可靠 → 临时文件中途消失
        # ("sed: can't read ./.tmp.config.XXX: No such file or directory" → exit 2)。
        # append + olddefconfig 只对 .config 一次读、一次写，对 bind 挂载友好；
        # kconfig 解析 .config 时后值覆盖前值(disable 覆盖 base 的 =m/=y)，且被
        # select 的依赖会被 olddefconfig 自动纠正回来(不会破坏依赖)。
        self._apply_config_overrides(src_dir, config)

    def _apply_config_overrides(self, src_dir: Path, config: dict):
        """把 enable_configs(CONFIG_X=y) 与 disable_configs(# CONFIG_X is not set)
        追加进 .config 末尾后 olddefconfig 归一化。根因见 configure() 注释。
        """
        enable = config["kernel"].get("enable_configs") or []
        disable = config["kernel"].get("disable_configs") or []
        if not enable and not disable:
            return
        lines = [f"CONFIG_{sym}=y" for sym in enable]
        lines += [f"# CONFIG_{sym} is not set" for sym in disable]
        frag_rel = f"arch/{self.ARCH}/configs/flange_overrides.config"
        (src_dir / frag_rel).write_text("\n".join(lines) + "\n")
        # 追加到 .config 末尾（kconfig 后值覆盖前值）
        self.docker.run(["sh", "-c", f"cat {frag_rel} >> .config"],
                        cwd=str(src_dir), label="追加 config 覆盖")
        # olddefconfig 归一化：解析 select/依赖，写出最终 .config
        # （conf 二进制一次读写，规避 merge_config.sh 在 bind FS 上的不稳定）
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)

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
