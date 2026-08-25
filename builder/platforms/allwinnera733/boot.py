"""Allwinner A733 Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /extlinux/Image               — kernel 二进制
  /dtbs/allwinner/<device-tree>.dtb — 设备树
  /dtbs/allwinner/overlay/*.dtbo — （可选）设备树 overlay（in-tree + vendor 平铺）
  /extlinux/extlinux.conf       — normal 启动配置
  /extlinux/recovery.conf       — recovery 启动配置（启用 recovery 时）

Allwinner 首版仍由平台 boot reason 适配决定是否扫描 recovery.conf；boot 分区
布局与 Rockchip 对齐：启动配置放在 /extlinux/，设备树放在 /dtbs/<vendor>/。

Overlay 来源同 Rockchip：boot.overlays.intree/vendor/board/package。
平铺到同一 /dtbs/allwinner/overlay/ 目录；basename 全局唯一。vendor 与 board
共用 device-tree-overlay 组件的 cpp+dtc 编译流水线与产物目录。
"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.config.canonical import kernel_device_tree
from builder.dtb_overlay import (
    board_overlays,
    copy_declared_overlays,
    intree_overlays,
    package_overlays,
    runtime_overlays,
    vendor_overlays,
)
from builder.extlinux import (
    LabelSpec,
    NORMAL_CONFIG,
    NORMAL_LABEL,
    RECOVERY_CONFIG,
    RECOVERY_LABEL,
    render_extlinux,
)


class AllwinnerA733BootBuilder(ComponentBuilder):
    component = "boot"
    DTB_VENDOR_DIR = "dtbs/allwinner"

    def build(self, config: dict) -> dict:
        """boot 镜像无需克隆源码仓库。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-boot-"))
        staging = self._work_dir / "staging"
        extlinux_dir = staging / "extlinux"
        extlinux_dir.mkdir(parents=True)
        dtb_dir = staging / self.DTB_VENDOR_DIR
        dtb_dir.mkdir(parents=True)

        target_dir = self.cache.target_dir
        kernel_image = target_dir / "kernel" / "Image"
        _, dts_name = kernel_device_tree(config)
        kernel_dtb = target_dir / "kernel" / f"{dts_name}.dtb"

        if not kernel_image.exists():
            raise FileNotFoundError(
                f"kernel Image 未找到: {kernel_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_dtb}")

        # 复制到 boot 分区标准布局
        self._status("准备 boot 分区内容...")
        shutil.copy2(kernel_image, extlinux_dir / "Image")
        _, dtb_name = kernel_device_tree(config)
        dtb_filename = f"{dtb_name}.dtb"
        shutil.copy2(kernel_dtb, dtb_dir / dtb_filename)
        # DTB overlay 三源都平铺到 /dtbs/allwinner/overlay/，撞名时
        # copy_declared_overlays 立即报错。vendor + board 共用
        # target/device-tree-overlay/overlays/ 产物目录。
        copy_declared_overlays(
            target_dir / "kernel" / "overlay",
            dtb_dir / "overlay",
            intree_overlays(config),
        )
        copy_declared_overlays(
            target_dir / "device-tree-overlay" / "overlays",
            dtb_dir / "overlay",
            vendor_overlays(config),
        )
        copy_declared_overlays(
            target_dir / "device-tree-overlay" / "overlays",
            dtb_dir / "overlay",
            board_overlays(config),
        )
        copy_declared_overlays(
            target_dir / "device-tree-overlay" / "overlays",
            dtb_dir / "overlay",
            package_overlays(config),
        )

        # 生成 normal/recovery extlinux 配置；是否读取 recovery.conf 由 U-Boot 决定。
        (extlinux_dir / NORMAL_CONFIG).write_text(
            self._build_extlinux_conf(config, dtb_filename))
        if (config.get("recovery") or {}).get("enabled", False):
            (extlinux_dir / RECOVERY_CONFIG).write_text(
                self._build_recovery_extlinux_conf(config, dtb_filename))

        # 生成 boot.img
        boot_size_mb = self._partition_size_mb(config, "boot")
        boot_img = self._work_dir / "boot.img"
        self._status(f"生成 boot.img ({boot_size_mb}MB)...")
        self.docker.run(["truncate", "-s", f"{boot_size_mb}M", str(boot_img)])
        self.docker.run([
            "mke2fs", "-t", "ext4", "-L", "boot", "-F", "-q",
            "-d", str(staging), str(boot_img),
        ])
        self._boot_img = boot_img

    def _build_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        """生成 normal extlinux.conf。

        根设备使用 PARTUUID 定位（由 ImageBuilder 在 GPT 分区表中写入固定
        UUID）。相比 LABEL=xxx，PARTUUID 无需 userspace udev 辅助，
        kernel 启动早期即可解析，避免 "Waiting for root device" 卡死。
        """
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        root_partuuid = boot_cfg.get("root_partuuid",
                                     "614e0000-0000-4000-8000-000000000001")
        overlay_names = runtime_overlays(config)

        normal = LabelSpec(
            name=NORMAL_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="devicetree",
            fdtoverlays=[
                f"/{self.DTB_VENDOR_DIR}/overlay/{name}"
                for name in overlay_names
            ],
            append=(
                f"root=PARTUUID={root_partuuid} "
                f"rootfstype=ext4 rootwait rw {kernel_args}"
            ).rstrip(),
        )
        return render_extlinux(NORMAL_LABEL, [normal])

    def _build_recovery_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        """生成 recovery.conf。"""
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        overlay_names = runtime_overlays(config)

        # 用 PARTLABEL= 而非 ext4 LABEL=：见 rockchip boot.py 的同一段说明。
        recovery = LabelSpec(
            name=RECOVERY_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="devicetree",
            fdtoverlays=[
                f"/{self.DTB_VENDOR_DIR}/overlay/{name}"
                for name in overlay_names
            ],
            append=(
                f"root=PARTLABEL=recovery rootfstype=ext4 rootwait rw "
                f"flange.mode=recovery {kernel_args}"
            ).rstrip(),
        )
        return render_extlinux(RECOVERY_LABEL, [recovery])

    def _partition_size_mb(self, config: dict, name: str) -> int:
        for entry in config.get("partitions", {}).get("entries", []):
            if entry["name"] == name:
                size_sectors = int(entry["size"], 0)
                return (size_sectors * 512) // (1024 * 1024)
        raise KeyError(f"partitions.entries 中未定义分区: {name}")

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"boot": self._boot_img}
