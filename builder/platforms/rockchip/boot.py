"""Rockchip Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /Image                          — kernel 二进制
  /dtb/<vendor>/<dts>.dtb         — 设备树
  /dtb/<vendor>/overlay/*.dtbo    — （可选）设备树 overlay
  /extlinux/extlinux.conf         — U-Boot distro boot 配置

U-Boot distro_bootcmd 启动时自动扫描 boot 分区的 /extlinux/extlinux.conf，
读取 kernel/fdt/append 指令后加载对应文件。

运行时通过 fstab 中 `LABEL=boot /boot ext4 ...` 挂载到 rootfs 的 /boot。
"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootBuilder(ComponentBuilder):
    component = "boot"

    # boot 分区内 DTB 存放目录（相对 boot.img 根）
    DTB_VENDOR_DIR = "dtb/rockchip"

    def build(self, config: dict) -> dict:
        """boot 镜像无需克隆源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # boot 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        """从 kernel 产物 + config 构建 boot.img。"""
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-boot-"))
        staging = self._work_dir / "staging"
        staging.mkdir()

        # 读取 kernel 产物（来自前序 kernel 组件收集到的 target 目录）
        target_dir = self.cache.target_dir
        kernel_src_image = target_dir / "kernel" / "Image"
        dts_name = config["kernel"]["dts"]
        kernel_src_dtb = target_dir / "kernel" / f"{dts_name}.dtb"

        if not kernel_src_image.exists():
            raise FileNotFoundError(
                f"kernel Image 未找到: {kernel_src_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_src_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_src_dtb}")

        # 组织 boot 分区内容
        self._status("准备 boot 分区内容...")
        shutil.copy2(kernel_src_image, staging / "Image")
        dtb_dir = staging / self.DTB_VENDOR_DIR
        dtb_dir.mkdir(parents=True)
        shutil.copy2(kernel_src_dtb, dtb_dir / kernel_src_dtb.name)

        # 可选：DTB overlay（若 kernel 产物目录下提供了 overlay/）
        overlay_src = target_dir / "kernel" / "overlay"
        if overlay_src.is_dir():
            overlay_dst = dtb_dir / "overlay"
            shutil.copytree(overlay_src, overlay_dst)

        # 生成 extlinux.conf
        extlinux_dir = staging / "extlinux"
        extlinux_dir.mkdir()
        (extlinux_dir / "extlinux.conf").write_text(
            self._build_extlinux_conf(config, kernel_src_dtb.name))

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
        """生成 U-Boot distro boot 使用的 extlinux.conf。"""
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        default_overlays = boot_cfg.get("default_overlays", []) or []

        lines = ["label flange",
                 "  kernel /Image",
                 f"  fdt /{self.DTB_VENDOR_DIR}/{dtb_filename}"]
        if default_overlays:
            overlays_joined = " ".join(
                f"/{self.DTB_VENDOR_DIR}/overlay/{o}" for o in default_overlays)
            lines.append(f"  fdtoverlays {overlays_joined}")
        # root=LABEL=rootfs 依赖 rootfs.img 由 mke2fs -L rootfs 设置 filesystem label
        append = f"root=LABEL=rootfs rootfstype=ext4 rootwait rw {kernel_args}".rstrip()
        lines.append(f"  append {append}")
        return "\n".join(lines) + "\n"

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
