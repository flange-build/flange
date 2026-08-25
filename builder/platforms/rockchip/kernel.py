"""Rockchip 内核构建策略 -- 替代 kernel/rockchip/build.sh"""

from pathlib import Path
from builder.config.canonical import kernel_arch, kernel_device_tree
from builder.kernel_base import KernelBuilder
from builder.dtb_overlay import (
    intree_overlays,
    kernel_overlay_dir,
    overlay_make_targets,
    require_overlay_files,
)


class RockchipKernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"
    DEFAULT_ARCH = "arm64"
    DEFAULT_CROSS = KernelBuilder.CROSS

    def _configure_build_context(self, config: dict) -> None:
        """从 FINAL_CONFIG 为本次构建解析架构与工具链。

        每次调用都从默认值重新计算并写入实例属性，避免同一 Python 进程复用
        builder 时把 ARM32 target 的状态泄漏给后续 ARM64 target；类属性保持
        现有 ARM64/AArch64 gcc-10 缺省值不变。
        """
        kernel = config.get("kernel", {}) or {}
        self.ARCH = kernel_arch(config)
        self.CROSS = kernel.get("cross_compile", self.DEFAULT_CROSS)

    @staticmethod
    def _dts_target(dts_dir: str, dts: str, suffix: str) -> str:
        """拼接 kernel make 的 DTS 相对目标，兼容根 DTS 目录。"""
        filename = f"{dts}.{suffix}"
        return f"{dts_dir}/{filename}" if dts_dir else filename

    def configure(self, src_dir: Path, config: dict):
        """按序应用 defconfig target，再应用 canonical Kconfig override。

        ``kernel.defconfig`` 只接受 make target/fragment 名称；symbol 覆盖统一
        从 ``kernel.config`` 生成 ``flange_overrides.config`` 并在末尾应用。

        合并步骤前先生成三个 SoC/平台级 fragment 到 ``arch/<ARCH>/configs/``：

        - ``case_insensitive_fix.config`` —— 由基类生成。大小写不敏感 FS 上
          禁用 netfilter 冲突模块；敏感 FS 上为空 fragment（保留功能）。
        - ``rk3588_panthor.config`` —— RK3588/RK3588S 上启用 mainline panthor
          DRM 驱动并关闭 BSP mali_kbase；其他 SoC 上为空 fragment。
        - ``panel_mipi_dbi.config`` —— 启用 mainline panel-mipi-dbi-spi 驱动
          （``CONFIG_DRM_PANEL_MIPI_DBI=m``）；mainline v5.18 已 in-tree，
          rkr5.1 (linux 6.1) 自带，无需 backport patch。

        三个 fragment 始终生成，由 SoC config 决定是否在 defconfig list 中
        引入。
        """
        self._configure_build_context(config)
        self._write_case_insensitive_fix(src_dir)
        self._write_panthor_fragment(src_dir, config)
        self._write_panfrost_fragment(src_dir, config)
        self._write_panel_mipi_dbi_fragment(src_dir)
        for dc in self._resolve_defconfig_targets(
                src_dir, config["kernel"]["defconfig"]):
            self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS)
        override = self._write_config_override_fragment(src_dir, config)
        if override:
            self.make(src_dir, [override], arch=self.ARCH, cross=self.CROSS)

    def _write_panthor_fragment(self, src_dir: Path, config: dict):
        """生成 rk3588_panthor.config fragment。

        RK3588/RK3588S 上：关闭 BSP mali_kbase（Bifrost fork）+ mali400/450
        utgard，启用 mainline panthor DRM 驱动。dts 上 GPU 节点 compatible
        是 ``arm,mali-valhall-csf``（rkr5.1 已切，commit ba07b020ea7d），与
        panthor of_match 直接对位。

        其他 SoC 上：写空 fragment（满足 make <name>.config 的合并要求）。

        firmware 部署不在本 fragment 内：panthor 运行时 ``request_firmware``
        会查 ``/lib/firmware/arm/mali/arch10.8/mali_csffw.bin``。BSP 内核源码
        ``drivers/gpu/arm/bifrost/mali_csffw.bin`` 已自带同 blob，后续可走
        CONFIG_EXTRA_FIRMWARE 或 rootfs overlay 部署。
        """
        fragment = src_dir / "arch" / self.ARCH / "configs" / "rk3588_panthor.config"
        soc = config.get("soc", "")
        if soc not in ("rk3588", "rk3588s"):
            fragment.write_text(
                "# 非 RK3588 系 SoC — panthor fragment 不生效\n"
            )
            self._status(f"SoC={soc}，跳过 panthor fragment")
            return
        fragment.write_text(
            "# RK3588 G610 GPU 切换到 mainline panthor 驱动\n"
            "# rkr5.1 dts 已默认走 panthor 节点 (arm,mali-valhall-csf)；\n"
            "# 但 rockchip_linux_defconfig 仍编 mali_kbase，本 fragment 把这部分\n"
            "# 翻成 panthor。\n"
            "\n"
            "# 关闭 BSP mali_kbase（Bifrost fork）—— rockchip_linux_defconfig 设为 =y\n"
            "# CONFIG_MALI_BIFROST is not set\n"
            "# CONFIG_MALI_MIDGARD is not set\n"
            "# CONFIG_MALI_CSF_SUPPORT is not set\n"
            "# CONFIG_MALI_DEBUG is not set\n"
            "# CONFIG_MALI_FENCE_DEBUG is not set\n"
            "# CONFIG_MALI_DEVFREQ is not set\n"
            "# CONFIG_MALI_DT is not set\n"
            "# CONFIG_MALI_EXPERT is not set\n"
            "# CONFIG_MALI_PLATFORM_THIRDPARTY is not set\n"
            "# CONFIG_MALI_SHARED_INTERRUPTS is not set\n"
            "# CONFIG_MALI_PWRSOFT_765 is not set\n"
            "# 关闭 mali400/450 utgard（老款 GPU 驱动，RK3588 不需要）\n"
            "# CONFIG_MALI400 is not set\n"
            "# CONFIG_MALI450 is not set\n"
            "\n"
            "# 启用 mainline panthor (DRM driver for ARM Mali CSF GPUs)\n"
            "CONFIG_DRM_PANTHOR=m\n"
        )
        self._status(f"SoC={soc}，启用 panthor fragment")

    # mainline panfrost 适用的 SoC：GPU 均为 Mali-G52（Bifrost，无 CSF），
    # dts gpu 节点 compatible 为 ``arm,mali-bifrost``，与 panfrost of_match
    # 对位（panthor 只认 valhall-csf，带不动 G52）。
    # - rk3576：gpu@27800000（rk3576.dtsi）
    # - rk3566/rk3568：gpu@fde60000（共享 rk356x.dtsi）
    PANFROST_SOCS = ("rk3566", "rk3568", "rk3576")

    def _write_panfrost_fragment(self, src_dir: Path, config: dict):
        """生成 panfrost.config fragment。

        PANFROST_SOCS（rk3566 / rk3568 / rk3576，GPU 均 Mali-G52 Bifrost）上：
        关闭 BSP mali_kbase（Bifrost fork）+ mali400/450 utgard，启用 mainline
        panfrost DRM 驱动。这些 SoC 的 dts gpu 节点 compatible 均为
        ``arm,mali-bifrost``，与 panfrost of_match 直接对位。

        其他 SoC 上：写空 fragment（满足 make <name>.config 的合并要求）。

        与 panthor 不同：panfrost 无 CSF 固件依赖，不走 request_firmware，
        rootfs 侧无需部署 mali_csffw.bin。
        """
        fragment = src_dir / "arch" / self.ARCH / "configs" / "panfrost.config"
        soc = config.get("soc", "")
        if soc not in self.PANFROST_SOCS:
            fragment.write_text(
                "# 非 Mali-G52 Bifrost SoC — panfrost fragment 不生效\n"
            )
            self._status(f"SoC={soc}，跳过 panfrost fragment")
            return
        fragment.write_text(
            "# Mali-G52 GPU 切换到 mainline panfrost 驱动\n"
            "# 对应 SoC 的 dts gpu 节点 compatible 为 arm,mali-bifrost，与 panfrost\n"
            "# of_match 对位；但 rockchip_linux_defconfig 仍编闭源 mali_kbase，\n"
            "# 本 fragment 把这部分翻成 panfrost。\n"
            "\n"
            "# 关闭 BSP mali_kbase（Bifrost fork）—— rockchip_linux_defconfig 设为 =y\n"
            "# CONFIG_MALI_BIFROST is not set\n"
            "# CONFIG_MALI_MIDGARD is not set\n"
            "# CONFIG_MALI_CSF_SUPPORT is not set\n"
            "# CONFIG_MALI_DEBUG is not set\n"
            "# CONFIG_MALI_FENCE_DEBUG is not set\n"
            "# CONFIG_MALI_DEVFREQ is not set\n"
            "# CONFIG_MALI_DT is not set\n"
            "# CONFIG_MALI_EXPERT is not set\n"
            "# CONFIG_MALI_PLATFORM_THIRDPARTY is not set\n"
            "# CONFIG_MALI_SHARED_INTERRUPTS is not set\n"
            "# CONFIG_MALI_PWRSOFT_765 is not set\n"
            "# 关闭 mali400/450 utgard（老款 GPU 驱动，RK3576 不需要）\n"
            "# CONFIG_MALI400 is not set\n"
            "# CONFIG_MALI450 is not set\n"
            "\n"
            "# 启用 mainline panfrost (DRM driver for ARM Mali Midgard/Bifrost GPUs)\n"
            "CONFIG_DRM_PANFROST=m\n"
        )
        self._status(f"SoC={soc}，启用 panfrost fragment")

    def _write_panel_mipi_dbi_fragment(self, src_dir: Path):
        """生成 config fragment 启用 mainline panel-mipi-dbi-spi 驱动。

        Mainline v5.18 已 in-tree（drivers/gpu/drm/tiny/panel-mipi-dbi.c，
        commit 48b1f5440f8c），rkr5.1 (linux 6.1) 自带，**无需 backport
        patch**——与 a733 (5.15) 那边的同名 fragment 是同语义但不同来源。

        该 fragment **总是写入**（不像 panthor 有 SoC 条件分支）；SoC 配置
        决定是否在 kernel.defconfig list 中引入。CONFIG_DRM_KMS_HELPER 在
        rockchip_linux_defconfig 中已 =y，CONFIG_DRM_MIPI_DBI 由 Kconfig
        select 自动拉入，无需在此显式声明。
        """
        fragment = src_dir / "arch" / self.ARCH / "configs" / "panel_mipi_dbi.config"
        fragment.write_text(
            "# panel-mipi-dbi-spi 通用 SPI DBI 屏 DRM 驱动\n"
            "# mainline v5.18 已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport\n"
            "CONFIG_DRM_PANEL_MIPI_DBI=m\n"
        )
        self._status("panel_mipi_dbi.config 生成")

    def compile(self, src_dir: Path, config: dict):
        self._configure_build_context(config)
        jobs = config.get("jobs", 0)
        # 单文件 dtb 目标：用 "<dts_dir>/<dts>.dtb" 这种子目录相对路径
        # （不是 basename 也不是 arch/... 完整路径）。内核顶层 Makefile
        # 的 `%.dtb: dtbs_prepare` 规则把它展开成：
        #   $(MAKE) $(build)=$(dtstree) $(dtstree)/<dts_dir>/<dts>.dtb
        # kbuild 顺着 arch/.../dts/Makefile 的 `subdir-y += <dts_dir>`
        # 递归下到子目录，再由 scripts/Makefile.build 的通用模式规则
        # `$(obj)/%.dtb: $(src)/%.dts FORCE` 直接按 .dts 源编 .dtb ——
        # 目标设备树无需在子目录 Makefile 的 dtb-y 里登记。
        dts_dir, dts = kernel_device_tree(config)
        kernel_image = config["kernel"].get("image", "Image")
        boot_format = config["kernel"].get("boot_format", "extlinux")
        extra = ["KCFLAGS=-Wno-error"]
        if boot_format == "fit":
            boot_its = config["kernel"].get("boot_its")
            if not boot_its:
                raise KeyError(
                    "kernel.boot_format=fit 时必须声明 kernel.boot_its")
            # Rockchip BSP 的 arch/arm{,64}/Makefile 中 ``%.img`` 会递归
            # 构建 DTB、kernel image 与 modules。这里若再把 ``modules`` 作为
            # 同一次 make 的并列 goal，外层与 ``%.img`` 的递归 make 会同时
            # 写同一批 .o/.d，最终触发 fixdep 丢失 depfile。FIT 路径只提交
            # ``%.img`` 单一 goal；extlinux 路径仍显式构建 modules。
            targets = [self._dts_target(dts_dir, dts, "img")]
            extra.append(f"BOOT_ITS={boot_its}")
        else:
            targets = [
                kernel_image,
                self._dts_target(dts_dir, dts, "dtb"),
                *overlay_make_targets(config, dts_dir),
                "modules",
            ]
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=extra,
                  label="编译内核...")
        # 编译 out-of-tree 模块
        self._compile_oot_modules(src_dir, config, jobs)

        # 安装 in-tree 模块（带 strip）。
        # _clean_modules_staging 清旧 kernel.release 残留，避免累积撑爆
        # 下游分区，详见基类注释。
        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
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
        self._configure_build_context(config)
        dts_dir, dts = kernel_device_tree(config)
        kernel_image = config["kernel"].get("image", "Image")
        dts_output_dir = src_dir / "arch" / self.ARCH / "boot" / "dts"
        if dts_dir:
            dts_output_dir /= dts_dir
        outputs = {
            "image": src_dir / "arch" / self.ARCH / "boot" / kernel_image,
            "dtb": dts_output_dir / f"{dts}.dtb",
            "modules": src_dir / "_modules_staging",
        }
        if config["kernel"].get("boot_format", "extlinux") == "fit":
            outputs["fit_boot"] = src_dir / "boot.img"
        overlays = intree_overlays(config)
        if overlays:
            overlay_dir = kernel_overlay_dir(src_dir, self.ARCH, dts_dir)
            require_overlay_files(overlay_dir, overlays)
            outputs["dtbos"] = overlay_dir
        return outputs
