"""Qualcomm QRB2210 内核构建器。

标准 mainline 构建（mainline Linux tag v7.0，单仓库）：
  make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- defconfig
  （按需追加 enable_configs / disable_configs，append + olddefconfig 归一化）
  make Image qcom/qrb2210-arduino-imola.dtb modules
开源 Adreno 走内核 in-tree drm/msm；Wi-Fi 走 mainline ath10k —— 均无 OOT 模块。
"""

from pathlib import Path

from builder.kernel_base import KernelBuilder


class Qrb2210KernelBuilder(KernelBuilder):
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
        # 用「追加进 .config + olddefconfig」而非 merge_config.sh：对 bind 挂载
        # 更可靠（详见 qualcommqcs6490/kernel.py 同段注释）。
        self._apply_config_overrides(src_dir, config)

    def _apply_config_overrides(self, src_dir: Path, config: dict):
        """把 enable_configs(CONFIG_X=y) 与 disable_configs(# CONFIG_X is not set)
        追加进 .config 末尾后 olddefconfig 归一化。
        """
        enable = config["kernel"].get("enable_configs") or []
        disable = config["kernel"].get("disable_configs") or []
        if not enable and not disable:
            return
        lines = [f"CONFIG_{sym}=y" for sym in enable]
        lines += [f"# CONFIG_{sym} is not set" for sym in disable]
        frag_rel = f"arch/{self.ARCH}/configs/flange_overrides.config"
        (src_dir / frag_rel).write_text("\n".join(lines) + "\n")
        self.docker.run(["sh", "-c", f"cat {frag_rel} >> .config"],
                        cwd=str(src_dir), label="追加 config 覆盖")
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        dts_dir = config["kernel"].get("dts_dir", "qcom")
        dtb = config["kernel"]["dtb"]

        targets = ["Image", f"{dts_dir}/{dtb}.dtb", "modules"]
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error"],
                  label="编译内核...")

        # 安装 in-tree 模块（strip）到 staging，供 rootfs 收取
        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}",
                         "INSTALL_MOD_STRIP=1"])
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
