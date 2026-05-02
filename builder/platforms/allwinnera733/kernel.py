"""Allwinner A733 内核构建策略 — BSP 集成模式。

构建前需要将外部 BSP 仓库和 device 仓库集成到内核源码树中：
  1. BSP 仓库 symlink 到内核 bsp/ 目录（内核 Makefile 已内置 drivers-y += bsp/）
  2. BSP DTSI 文件 symlink 到内核 DTS 目录（使 board.dts 的 #include 可解析）
  3. device 仓库的 board.dts 复制到内核 DTS 目录
"""

import shutil
from pathlib import Path
from builder.base import ComponentBuilder
from builder.dtb_overlay import (
    dtb_overlays,
    kernel_overlay_dir,
    overlay_make_targets,
    require_overlay_files,
)


class AllwinnerA733KernelBuilder(ComponentBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"
    # BSP Kconfig 通过 $(BSP_TOP) 引用路径，必须在所有 make 调用中传递。
    # KERNEL_SRC 供 bsp/modules/nand/ Makefile 使用（需要知道内核源码路径）。
    BSP_MAKE_VARS = ["BSP_TOP=bsp/", "KERNEL_SRC=."]

    def build(self, config: dict) -> dict:
        """重写 build 流程，使用 linux-a733 聚合仓库 + 上游原始 patches。

        源码来自 linux-a733 聚合仓库的子路径：
          - kernel    → src/
          - BSP       → bsp/
          - device    → device-a733/

        Patches 直接应用 linux-a733/debian/patches/series 中声明的补丁，
        不再手动适配路径前缀。
        """
        src_dir = self.source.ensure(self.component, config)
        self._status("内核源码就绪")

        bsp_dir = self.source.ensure_extra(
            "kernel_bsp", config["kernel_bsp"], config=config)
        self._status("BSP 源码就绪")
        device_dir = self.source.ensure_extra(
            "kernel_device", config["kernel_device"], config=config)
        self._status("Device 源码就绪")

        # 聚合仓库根（用于 debian/patches 应用）
        repo_root = self._locate_aggregate_root(src_dir, config)

        # 源码重置（主仓库 + 子模块）
        if not config.get("_local_mode", {}).get(self.component):
            self._reset_aggregate_repo(repo_root)
            self._apply_upstream_patches(repo_root)

        # BSP 集成与 DTS 准备
        self._integrate_bsp(src_dir, bsp_dir, config)
        self._write_aic8800_usb_firmware_path_override(bsp_dir)
        self._integrate_dts(src_dir, bsp_dir, device_dir, config)

        self._write_case_insensitive_fix(src_dir)
        self._write_aic8800_wlan_override(src_dir)
        self._write_usb_gadget_override(src_dir)
        self.configure(src_dir, config)
        self.compile(src_dir, config)
        result = self.collect(src_dir, config)
        self._status("产物收集")
        return result

    def _locate_aggregate_root(self, src_dir: Path, config: dict) -> Path:
        """定位聚合仓库根目录。

        from_repo 模式下 src_dir 是 .build/sources/repos/<name>/<subpath>，
        聚合仓库根是其上两级（去掉 subpath）。直接 clone 场景下
        src_dir 自身就是 Git 仓库根。
        """
        subpath = config.get("kernel", {}).get("subpath", "")
        if subpath:
            parts = subpath.split("/")
            root = src_dir
            for _ in parts:
                root = root.parent
            return root
        return src_dir

    def _reset_aggregate_repo(self, repo_root: Path):
        """重置聚合仓库及所有子模块到干净状态。

        用 `;` 而非 `&&` 分隔命令 — macOS 大小写不敏感 FS 上 git checkout
        会对仅大小写不同的文件报错退出非零，但实际已完成重置。使用 `;`
        避免短路，确保后续的 git clean -fd 清理 patch 创建的 untracked 文件
        （如 radxa.config）。
        """
        # 主仓库
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(repo_root),
                        check=False)
        # 子模块（src/、bsp/、device-a733/ 都是 submodule）
        self.docker.run(
            ["git", "submodule", "foreach", "--recursive",
             "git checkout -f .; git clean -fd"],
            cwd=str(repo_root), check=False,
        )

    def _apply_upstream_patches(self, repo_root: Path):
        """应用 linux-a733/debian/patches/series 声明的上游补丁。

        patches 路径包含 src/、bsp/ 等前缀，在聚合仓库根应用时
        git apply -p1 即可正确匹配，无需路径前缀改写。
        """
        series_file = repo_root / "debian" / "patches" / "series"
        if not series_file.exists():
            return
        patches = [
            line.strip()
            for line in series_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not patches:
            return
        patches_dir = repo_root / "debian" / "patches"
        applied = 0
        for rel in patches:
            patch_path = patches_dir / rel
            if not patch_path.exists():
                self._status(f"警告：补丁不存在 {rel}")
                continue
            try:
                self.docker.run(["git", "apply", str(patch_path)],
                                cwd=str(repo_root))
            except Exception:
                self.docker.run(["patch", "-p1", "-i", str(patch_path)],
                                cwd=str(repo_root))
            applied += 1
        if applied:
            self._status(f"补丁应用 ({applied} patches from debian/patches/series)")

    def _integrate_bsp(self, src_dir: Path, bsp_dir: Path, config: dict):
        """将 BSP 仓库 symlink 到内核源码树的 bsp/ 目录。"""
        bsp_link = src_dir / "bsp"
        if bsp_link.is_symlink():
            bsp_link.unlink()
        elif bsp_link.exists():
            shutil.rmtree(bsp_link)
        bsp_link.symlink_to(bsp_dir.resolve())

        # BSP 的 dt-bindings 头文件需要在内核 include 路径中可见，
        # 因为 DTS 编译使用独立的 include 路径，不继承 CFLAGS 的 -I。
        # 内核自带 include/dt-bindings/clock/ 等目录，不能整目录替换，
        # 需要将 BSP 的头文件逐个 symlink 进去。
        bsp_dt_bindings = bsp_dir / "include" / "dt-bindings"
        kernel_dt_bindings = src_dir / "include" / "dt-bindings"
        if bsp_dt_bindings.is_dir():
            for sub in bsp_dt_bindings.iterdir():
                if sub.is_dir():
                    target_sub = kernel_dt_bindings / sub.name
                    target_sub.mkdir(parents=True, exist_ok=True)
                    for header in sub.iterdir():
                        link = target_sub / header.name
                        if link.is_symlink():
                            link.unlink()
                        if not link.exists():
                            link.symlink_to(header.resolve())

        # 生成 bsp/include/sunxi-autogen.h
        # BSP 驱动 ccu_common.c 等 #include <sunxi-autogen.h> 定义 AW_BSP_VERSION
        # 此文件不随源码分发（bsp/.gitignore 排除），需构建时动态生成
        autogen = bsp_dir / "include" / "sunxi-autogen.h"
        autogen.parent.mkdir(parents=True, exist_ok=True)
        autogen.write_text(
            '#define AW_BSP_VERSION "flange-build, RadxaOS SDK"\n'
        )
        self._status("sunxi-autogen.h 生成")

        self._status("BSP 集成完成")

    def _integrate_dts(self, src_dir: Path, bsp_dir: Path, device_dir: Path,
                       config: dict):
        """集成 DTS/DTSI 文件到内核 DTS 目录。

        1. 将 BSP 的 DTSI 文件 symlink 到内核 DTS allwinner/ 目录
        2. 将 device 仓库的 board.dts 复制到内核 DTS 目录并重命名
        """
        dts_dir_name = config["kernel"].get("dts_dir", "allwinner")
        kernel_dts_dir = src_dir / "arch" / self.ARCH / "boot" / "dts" / dts_dir_name
        kernel_dts_dir.mkdir(parents=True, exist_ok=True)

        # BSP DTSI 链接
        bsp_dtsi_dir = config["kernel_bsp"].get("dtsi_dir", "configs/linux-5.15")
        dtsi_src = bsp_dir / bsp_dtsi_dir
        if dtsi_src.is_dir():
            for dtsi_file in dtsi_src.glob("*.dtsi"):
                link = kernel_dts_dir / dtsi_file.name
                if link.is_symlink():
                    link.unlink()
                elif link.exists():
                    link.unlink()
                link.symlink_to(dtsi_file.resolve())
            self._status(f"BSP DTSI 链接完成 ({len(list(dtsi_src.glob('*.dtsi')))} 个)")

        # Device board.dts 复制
        board_dts_path = config["kernel_device"].get("board_dts_path", "")
        dts_name = config["kernel"]["dts"]
        if board_dts_path:
            board_dts_src = device_dir / board_dts_path
            board_dts_dst = kernel_dts_dir / f"{dts_name}.dts"
            if board_dts_src.exists():
                shutil.copy2(board_dts_src, board_dts_dst)
                self._status(f"DTS 复制: {dts_name}.dts")
            else:
                raise FileNotFoundError(
                    f"board.dts 不存在: {board_dts_src}")

        # BSP defconfig 复制到 arch/arm64/configs/ 使 make bsp_defconfig 生效
        bsp_defconfig_path = config["kernel_device"].get("bsp_defconfig_path", "")
        if bsp_defconfig_path:
            bsp_dc_src = device_dir / bsp_defconfig_path
            bsp_dc_dst = src_dir / "arch" / self.ARCH / "configs" / "bsp_defconfig"
            if bsp_dc_src.exists():
                shutil.copy2(bsp_dc_src, bsp_dc_dst)
                self._status("bsp_defconfig 复制到内核 configs/")
            else:
                raise FileNotFoundError(
                    f"bsp_defconfig 不存在: {bsp_dc_src}")

    def _is_case_insensitive_fs(self, path: Path) -> bool:
        """通过 git config core.ignoreCase 判断 FS 是否大小写不敏感。

        git clone 时会自动探测并写入 core.ignoreCase，这正是我们需要的语义
        ——"git checkout 是否会因大小写碰撞丢文件"。比自建探针更可靠，
        不受 Docker volume 元数据缓存影响。

        path 可以是仓库任意子路径，git config 会向上查找 .git 目录。
        若 path 不在 git 仓库内或探测失败，默认返回 True（保守禁用模块）。
        """
        import subprocess
        try:
            result = subprocess.run(
                ["git", "config", "--get", "core.ignoreCase"],
                cwd=str(path), capture_output=True, text=True, check=False,
                timeout=10,
            )
            value = result.stdout.strip().lower()
            if value in ("true", "false"):
                return value == "true"
        except Exception as e:
            self._status(f"git config 探测失败（{e}），默认启用 fix")
        return True  # 保守策略

    def _write_case_insensitive_fix(self, src_dir: Path):
        """生成 config fragment 禁用大小写不敏感 FS 上文件名冲突的模块。

        Linux 内核中存在仅大小写不同的 .c/.h 文件对（xt_MARK.c / xt_mark.c 等），
        在 macOS (HFS+/APFS 默认) 上是同一个文件，git checkout 后只保留一个，
        导致模块编译失败。

        只在检测到大小写不敏感 FS 时才禁用这些模块；在 Linux ext4 等
        大小写敏感 FS 上写入空 fragment，保留这些功能。

        冲突文件对（git checkout warning 显示的完整列表）：
          xt_CONNMARK.h/c     xt_connmark.h/c
          xt_DSCP.h/c         xt_dscp.h/c
          xt_MARK.h/c         xt_mark.h/c
          xt_RATEEST.h/c      xt_rateest.h/c
          xt_TCPMSS.h/c       xt_tcpmss.h/c
          ipt_ECN.h/c         ipt_ecn.h/c
          ipt_TTL.h/c         ipt_ttl.h/c
          ip6t_HL.h/c         ip6t_hl.h/c
        """
        fix_config = src_dir / "arch" / self.ARCH / "configs" / "case_insensitive_fix.config"
        if not self._is_case_insensitive_fs(src_dir):
            # 大小写敏感 FS — 无需禁用，保留 netfilter 功能。
            # 写入空 fragment 以满足 defconfig 合并步骤（make <name>.config 需要文件存在）。
            fix_config.write_text(
                "# 大小写敏感文件系统 — 无需禁用冲突模块\n"
            )
            self._status("FS 大小写敏感，跳过 case_insensitive_fix")
            return
        fix_config.write_text(
            "# macOS 大小写不敏感 FS 上文件名冲突的 netfilter 模块 — 全部禁用\n"
            "# 伞形配置（实际驱动构建规则的入口）——优先禁用\n"
            "# xt_mark.c / xt_mark.h 冲突 xt_MARK.h\n"
            "CONFIG_NETFILTER_XT_MARK=n\n"
            "CONFIG_NETFILTER_XT_TARGET_MARK=n\n"
            "CONFIG_NETFILTER_XT_MATCH_MARK=n\n"
            "# xt_connmark.c / xt_connmark.h 冲突 xt_CONNMARK.h\n"
            "CONFIG_NETFILTER_XT_CONNMARK=n\n"
            "CONFIG_NETFILTER_XT_TARGET_CONNMARK=n\n"
            "CONFIG_NETFILTER_XT_MATCH_CONNMARK=n\n"
            "# xt_DSCP.c / xt_dscp.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_DSCP=n\n"
            "CONFIG_NETFILTER_XT_MATCH_DSCP=n\n"
            "# xt_HL.c / xt_hl.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_HL=n\n"
            "CONFIG_NETFILTER_XT_MATCH_HL=n\n"
            "# xt_RATEEST.c / xt_rateest.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_RATEEST=n\n"
            "CONFIG_NETFILTER_XT_MATCH_RATEEST=n\n"
            "# xt_TCPMSS.c / xt_tcpmss.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_TCPMSS=n\n"
            "# ipt/ip6t 头文件冲突（ipt_ECN.h vs ipt_ecn.h 等）\n"
            "CONFIG_IP_NF_TARGET_ECN=n\n"
            "CONFIG_IP_NF_MATCH_ECN=n\n"
            "CONFIG_IP_NF_TARGET_TTL=n\n"
            "CONFIG_IP_NF_MATCH_TTL=n\n"
            "CONFIG_IP6_NF_TARGET_HL=n\n"
            "CONFIG_IP6_NF_MATCH_HL=n\n"
        )
        self._status("FS 大小写不敏感，启用 case_insensitive_fix")

    def _write_usb_gadget_override(self, src_dir: Path):
        """生成 config fragment 强制 USB gadget + FunctionFS 为内建。

        上游 radxa.config 将 CONFIG_USB_CONFIGFS 降为 =m，导致 usbdevice.service
        启动前必须 modprobe configfs，启动时序脆弱。通过在 defconfig 合并尾部
        追加此 fragment 恢复为内建，使 adbd 开箱可用。

        合并顺序由 platform/allwinnera733/a733/config.py 的 kernel.defconfig 列表保证：
          defconfig → bsp_defconfig → radxa.config → radxa_custom.config
          → aic8800_wlan.config → usb_gadget.config (本 fragment)
          → case_insensitive_fix.config
        """
        override = src_dir / "arch" / self.ARCH / "configs" / "usb_gadget.config"
        override.write_text(
            "# USB gadget + FunctionFS 内建覆盖（由 AllwinnerA733KernelBuilder 生成）\n"
            "# 用途：覆盖 radxa.config 的 CONFIG_USB_CONFIGFS=m，恢复为内建\n"
            "CONFIG_CONFIGFS_FS=y\n"
            "CONFIG_USB_GADGET=y\n"
            "CONFIG_USB_CONFIGFS=y\n"
            "CONFIG_USB_CONFIGFS_F_FS=y\n"
        )
        self._status("usb_gadget.config 生成")

    def _write_aic8800_wlan_override(self, src_dir: Path):
        """生成 config fragment 启用 AIC8800 USB Wi-Fi 模块。

        上游 radxa.config 将 CONFIG_AIC_WLAN_SUPPORT 关闭，以便使用
        DKMS 包。flange 使用内核 modules_install 产物进入 rootfs，因此这里
        重新启用 BSP 内的 USB Wi-Fi 驱动和 firmware helper。
        """
        override = src_dir / "arch" / self.ARCH / "configs" / "aic8800_wlan.config"
        override.write_text(
            "# AIC8800 USB Wi-Fi 启用覆盖（由 AllwinnerA733KernelBuilder 生成）\n"
            "# 用途：覆盖 radxa.config 的 CONFIG_AIC_WLAN_SUPPORT=n，使用内核模块产物\n"
            "CONFIG_AIC_WLAN_SUPPORT=y\n"
            "CONFIG_AIC8800_USB=y\n"
            "# CONFIG_AIC8800_SDIO is not set\n"
            "CONFIG_AIC_LOADFW_SUPPORT=m\n"
            "CONFIG_AIC8800_WLAN_SUPPORT=m\n"
            "# CONFIG_AIC_BTUSB_SUPPORT is not set\n"
        )
        self._status("aic8800_wlan.config 生成")

    def _write_aic8800_usb_firmware_path_override(self, bsp_dir: Path):
        """修正 AIC8800 USB Wi-Fi 子模块中硬编码的固件路径。

        USB 驱动源码仍带 Android 风格 `/vendor/etc/firmware` 默认值。
        flange 在 A733 上使用 Radxa aic8800 仓库提供的 USB 固件，安装
        到 `/lib/firmware/aic8800_fw/USB`；旧 BSP loader 从该目录读取
        扁平 D80 固件，fdrv 再从其 `aic8800D80/` 子目录读取配置文件。
        """
        makefile = (
            bsp_dir
            / "drivers"
            / "net"
            / "wireless"
            / "aic8800"
            / "usb"
            / "aic8800_fdrv"
            / "Makefile"
        )
        if not makefile.exists():
            return
        old_paths = {
            'CONFIG_AIC_FW_PATH = "/vendor/etc/firmware"',
            'CONFIG_AIC_FW_PATH = "/lib/firmware/aic8800"',
        }
        new_path = 'CONFIG_AIC_FW_PATH = "/lib/firmware/aic8800_fw/USB"'
        text = makefile.read_text()

        lines = text.splitlines()
        changed = False
        has_new_active = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if line.lstrip().startswith("#"):
                continue
            if stripped == new_path:
                has_new_active = True
                continue
            if stripped in old_paths:
                lines[index] = line.replace(stripped, new_path)
                changed = True

        if not changed and has_new_active:
            self._status("AIC8800 USB 固件路径已是 Radxa USB 目录")
            return
        if not changed:
            raise RuntimeError(f"AIC8800 USB 固件路径配置格式非预期: {makefile}")

        suffix = "\n" if text.endswith("\n") else ""
        makefile.write_text("\n".join(lines) + suffix)
        self._status("AIC8800 USB 固件路径修正到 Radxa USB 目录")

    def configure(self, src_dir: Path, config: dict):
        """支持多步 defconfig 合并。"""
        defconfig = config["kernel"]["defconfig"]
        if isinstance(defconfig, list):
            for dc in defconfig:
                self.make(src_dir, [dc], arch=self.ARCH, cross=self.CROSS,
                          extra=self.BSP_MAKE_VARS)
        else:
            self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS,
                      extra=self.BSP_MAKE_VARS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        dts_dir = config["kernel"].get("dts_dir", "allwinner")
        dts = config["kernel"]["dts"]
        targets = [
            "Image",
            f"{dts_dir}/{dts}.dtb",
            *overlay_make_targets(config, dts_dir),
            "modules",
        ]
        self.make(src_dir, targets,
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=self.BSP_MAKE_VARS + ["KCFLAGS=-Wno-error"],
                  label="编译内核...")
        # 安装模块（带 strip）
        modules_staging = src_dir / "_modules_staging"
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=self.BSP_MAKE_VARS + [
                      f"INSTALL_MOD_PATH={modules_staging}",
                      "INSTALL_MOD_STRIP=1"])
        # 清理 source/build symlink
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(
                    f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "allwinner")
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
