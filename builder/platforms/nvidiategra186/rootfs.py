"""NVIDIA Tegra186 Rootfs 构建策略。

编排、两阶段缓存、overlay、账号配置来自 ``RootfsBuilder`` 基类。本平台的偏离：

  - **Phase 2 期间放置 L4T preinst 标记**：``nvidia-l4t-core`` 等包的 preinst 读
    ``/proc/device-tree/compatible`` 判断 SoC，chroot 里读不到会直接失败；NVIDIA
    ``nv-apply-debs.sh`` 在 rootfs 中预置这个标记跳过检查，Phase 2 结束即删除。
  - **启动文件装在 APP 分区 /boot**：U-Boot distro boot 读 ``/boot/extlinux/extlinux.conf``，
    内核为 ``/boot/Image``，initrd 用 ``nvidia-l4t-initrd`` 提供的 ``/boot/initrd``
    （stock 内核 xhci 为 built-in，固件从 initrd 加载）。DTB 由 cboot 从 kernel-dtb
    分区提供，extlinux 不写 FDT；``${cbootargs}`` 是 cboot 拼好的参数。
  - **fstab 只挂 rootfs**：没有独立 boot 分区。
"""

from pathlib import Path

from builder.docker import BuildError
from builder.extlinux import NORMAL_LABEL, LabelSpec, render_extlinux
from builder.rootfs import RootfsBuilder

# nv-apply-debs.sh 使用的标记：存在时 L4T 包 preinst 跳过 SoC 检查与启动固件更新。
L4T_PREINSTALL_MARKER = "opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall"


class Tegra186RootfsBuilder(RootfsBuilder):

    FSTAB_MOUNTS = (("LABEL=rootfs", "/", "ext4"),)

    def _build_phase2(self, rootfs_dir: Path, config: dict) -> None:
        marker = rootfs_dir / L4T_PREINSTALL_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        try:
            super()._build_phase2(rootfs_dir, config)
        finally:
            marker.unlink(missing_ok=True)

    def _post_customize(self, rootfs_dir: Path, config: dict) -> None:
        boot = rootfs_dir / "boot"
        initrd = boot / "initrd"
        if not initrd.is_file():
            raise BuildError(
                f"缺少 {initrd}：它由 nvidia-l4t-initrd 提供，请确认 rootfs.phase2_packages 包含该包"
            )
        self.docker.run_privileged(
            ["cp", str(self._target_dir() / "kernel" / "Image"), str(boot / "Image")]
        )
        extlinux = boot / "extlinux" / "extlinux.conf"
        extlinux.parent.mkdir(parents=True, exist_ok=True)
        extlinux.write_text(render_extlinux(NORMAL_LABEL, [LabelSpec(
            name=NORMAL_LABEL,
            kernel="/boot/Image",
            initrd="/boot/initrd",
            append=f"${{cbootargs}} {config['boot']['kernel_args']}",
        )]))
