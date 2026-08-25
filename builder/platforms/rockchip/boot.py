"""Rockchip Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /extlinux/Image                 — kernel 二进制
  /dtbs/rockchip/<dts>.dtb        — 设备树
  /dtbs/rockchip/overlay/*.dtbo   — （可选）设备树 overlay（in-tree + vendor 平铺）
  /extlinux/extlinux.conf         — normal 启动配置
  /extlinux/recovery.conf         — recovery 启动配置（启用 recovery 时）

U-Boot distro_bootcmd 默认扫描 /extlinux/extlinux.conf；flange 的 U-Boot
补丁会在 reboot recovery 或 boot-once 请求存在时改为扫描
/extlinux/recovery.conf。

运行时通过 fstab 中 `LABEL=boot /boot ext4 ...` 挂载到 rootfs 的 /boot。

Overlay 三源：
  - boot.overlays.intree : in-tree (来自 kernel 源码树，target/kernel/overlay/)
  - boot.overlays.vendor : 来自 device-tree-overlay 组件 vendor 仓库
  - boot.overlays.board  : 来自 device-tree-overlay 组件板私有源
  - boot.overlays.package: 由硬件包展开产生

三源平铺到同一 /dtbs/<vendor>/overlay/ 目录；basename 全局唯一，
撞名时 copy_declared_overlays 立即报错。vendor 与 board 共用 device-tree-
overlay 组件的产物目录，由 OverlaysBuilder 在编译期写入。
"""

import shutil
import tempfile
from pathlib import Path
from builder.config.canonical import kernel_device_tree
from builder.base import ComponentBuilder
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


class RockchipBootBuilder(ComponentBuilder):
    component = "boot"

    # boot 分区内 DTB 存放目录（相对 boot.img 根）
    DTB_VENDOR_DIR = "dtbs/rockchip"

    def build(self, config: dict) -> dict:
        """boot 镜像无需克隆源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # boot 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        """从 kernel 产物 + config 构建 boot.img。"""
        target_dir = self.cache.target_dir
        if config.get("kernel", {}).get("boot_format", "extlinux") == "fit":
            kernel_fit = target_dir / "kernel" / "boot.img"
            if not kernel_fit.is_file():
                raise FileNotFoundError(
                    f"kernel FIT boot.img 未找到: {kernel_fit}；"
                    "确认 kernel.<dts>.img 构建成功且产物已收集")
            self._boot_img = kernel_fit
            self._status("复用 kernel vendor FIT boot.img")
            return

        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-boot-"))
        staging = self._work_dir / "staging"
        staging.mkdir()

        # 读取 kernel 产物（来自前序 kernel 组件收集到的 target 目录）
        kernel_src_image = target_dir / "kernel" / "Image"
        _, dts_name = kernel_device_tree(config)
        kernel_src_dtb = target_dir / "kernel" / f"{dts_name}.dtb"

        if not kernel_src_image.exists():
            raise FileNotFoundError(
                f"kernel Image 未找到: {kernel_src_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_src_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_src_dtb}")

        # 组织 boot 分区内容
        self._status("准备 boot 分区内容...")
        extlinux_dir = staging / "extlinux"
        extlinux_dir.mkdir()
        shutil.copy2(kernel_src_image, extlinux_dir / "Image")
        dtb_dir = staging / self.DTB_VENDOR_DIR
        dtb_dir.mkdir(parents=True)
        shutil.copy2(kernel_src_dtb, dtb_dir / kernel_src_dtb.name)

        # DTB overlay 四源都平铺到 /dtbs/rockchip/overlay/：
        # 1) in-tree  (from kernel 源码树编译 → target/kernel/overlay/)
        # 2) vendor   (from radxa-overlays 编译 → target/device-tree-overlay/overlays/)
        # 3) board    (from components/board/<board>/dtso/ 编译，与 vendor 共用产物目录)
        # 4) package  (from components/packages/<pkg>/device-tree/ 编译，同上产物目录)
        # copy_declared_overlays 内置撞名检测（dst 已存在 → ValueError）。
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
            self._build_extlinux_conf(config, kernel_src_dtb.name))
        if (config.get("recovery") or {}).get("enabled", False):
            (extlinux_dir / RECOVERY_CONFIG).write_text(
                self._build_recovery_extlinux_conf(config, kernel_src_dtb.name))

        # mke2fs -d 从 staging 目录直接生成 ext4 镜像（免 mount）
        boot_size_mb = self._partition_size_mb(config, "boot")
        boot_img = self._work_dir / "boot.img"
        self._status(f"生成 boot.img ({boot_size_mb}MB)...")
        self.docker.run([
            "truncate", "-s", f"{boot_size_mb}M", str(boot_img),
        ])
        self.docker.run([
            "mke2fs", "-t", "ext4", "-L", "boot", "-F", "-q",
            "-d", str(staging), str(boot_img),
        ])
        self._boot_img = boot_img

    def _build_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        """生成 U-Boot distro boot 使用的 normal extlinux.conf。"""
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        overlay_names = runtime_overlays(config)

        # 用 PARTLABEL= 而非 ext4 LABEL=：GPT partition name 由 parted mkpart
        # 设置为 "rootfs"/"recovery"，kernel 启动早期可直接从 GPT 表解析，
        # 不依赖文件系统 probe（避免 "Waiting for root device LABEL=..." 死等）。
        normal = LabelSpec(
            name=NORMAL_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="fdt",
            fdtoverlays=[
                f"/{self.DTB_VENDOR_DIR}/overlay/{o}" for o in overlay_names
            ],
            append=f"root=PARTLABEL=rootfs rootfstype=ext4 rootwait rw {kernel_args}".rstrip(),
        )
        return render_extlinux(NORMAL_LABEL, [normal])

    def _build_recovery_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        """生成 U-Boot distro boot 使用的 recovery.conf。"""
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        overlay_names = runtime_overlays(config)

        recovery = LabelSpec(
            name=RECOVERY_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="fdt",
            fdtoverlays=[
                f"/{self.DTB_VENDOR_DIR}/overlay/{o}" for o in overlay_names
            ],
            append=(
                f"root=PARTLABEL=recovery rootfstype=ext4 rootwait rw "
                f"flange.mode=recovery {kernel_args}"
            ).rstrip(),
        )
        return render_extlinux(RECOVERY_LABEL, [recovery])

    def _partition_size_mb(self, config: dict, name: str) -> int:
        """从 config 中读取指定分区大小（MB）。"""
        for entry in config.get("partitions", {}).get("entries", []):
            if entry["name"] == name:
                size_sectors = int(entry["size"], 0)
                return (size_sectors * 512) // (1024 * 1024)
        raise KeyError(f"partitions.entries 中未定义分区: {name}")

    def _status(self, msg: str):
        if self.output:
            self.output.status(msg)

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"boot": self._boot_img}
