"""Qualcomm QCS6490 Rootfs 构建策略。

编排、两阶段缓存、overlay、固件、账号配置来自 `RootfsBuilder` 基类。
本平台的两处真实偏离：

  - **fstab 只挂 rootfs**。ESP 由 UEFI/GRUB 在启动期读取，flange 不在运行时
    mount /boot/efi。实测 Q6A 的 4096 字节 LBA UFS 上，mkfs.vfat 默认 512-sector
    FAT 会让内核 vfat 驱动判 superblock 无效，强行写 4K-sector FAT 又不被 EDK2
    识别；而重刷模型本就不需要运行时修改 ESP。去掉 ESP 行后 boot-efi.mount
    不存在，local-fs.target 干净，systemd 不 degraded。
  - **内核 Image 与 dtb 要装进 rootfs 的 /boot**，供 GRUB(grub-with-dtb) 加载。
"""

from pathlib import Path

from builder.config.canonical import kernel_device_tree
from builder.dtb_overlay import build_overlays
from builder.rootfs import RootfsBuilder


class Qcs6490RootfsBuilder(RootfsBuilder):

    #: 只挂 rootfs（见模块 docstring 的 ESP 说明）。
    FSTAB_MOUNTS = (("LABEL=rootfs", "/", "ext4"),)

    def _post_customize(self, rootfs_dir: Path, config: dict) -> None:
        self._install_kernel_boot(rootfs_dir, config)

    def _install_kernel_boot(self, rootfs_dir: Path, config: dict) -> None:
        """把内核 Image 与 dtb 安装到 rootfs /boot，供 GRUB 加载。

        grub.cfg 由 boot 组件生成；这里只负责把构建产物落到 /boot：
          /boot/vmlinuz   ← kernel Image
          /boot/<dtb>.dtb ← 设备树（GRUB devicetree 指令加载）
        initrd 由后续 boot 阶段在 chroot 内 update-initramfs 生成（按需）。

        ## 构建期 fdtoverlay 合并（grub-with-dtb 平台专用）

        GRUB 不支持运行时 DT overlay。当 board 经 `packages` 启用硬件特性包、
        且 ``kernel.device_tree.build_overlays`` 非空时，这里先用 `fdtoverlay`
        把 base dtb 与声明的 `.dtbo` 合成一份 merged dtb，**覆盖式**写到
        /boot/<dtb>.dtb（与 grub.cfg 的 `devicetree /boot/<dtb>.dtb` 配套）。
        无 overlay 时走直拷路径，与未启用本能力前字节等价。

        参见 [[build-time-dtb-overlay-merge]] 规格。
        """
        target_dir = self._target_dir()
        boot = rootfs_dir / "boot"
        boot.mkdir(exist_ok=True)
        image = target_dir / "kernel" / "Image"
        _, dtb_name = kernel_device_tree(config)
        dtb = target_dir / "kernel" / f"{dtb_name}.dtb"
        if image.exists():
            self.docker.run_privileged(
                ["cp", str(image), str(boot / "vmlinuz")])
        if not dtb.exists():
            return

        overlays = build_overlays(config)
        if not overlays:
            # 无 overlay：直拷 base dtb，与本能力启用前字节等价
            self.docker.run_privileged(["cp", str(dtb), str(boot / dtb.name)])
            return

        overlay_dir = target_dir / "device-tree-overlay" / "overlays"
        missing = [name for name in overlays
                   if not (overlay_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"fdtoverlay 缺 .dtbo: {missing}（预期在 {overlay_dir}/）。"
                "请确认 device-tree-overlay 组件已构建且包内 .dtso 已编译。"
            )

        merged = self._work_dir / dtb.name
        self._status(
            f"fdtoverlay 合并 {len(overlays)} 个 overlay 到 "
            f"{dtb.name}：{', '.join(overlays)}"
        )
        # fdtoverlay 失败时 stderr 不被吞：docker.run 在非零退出码时把 stderr
        # 含进异常信息向上抛，便于排查 base dtb 缺 __symbols__ 或 .dtbo
        # __fixups__ 解析不上等场景。
        self.docker.run([
            "fdtoverlay",
            "-i", str(dtb),
            "-o", str(merged),
            *[str(overlay_dir / name) for name in overlays],
        ], label=f"fdtoverlay {dtb.name}")

        self.docker.run_privileged(["cp", str(merged), str(boot / dtb.name)])
