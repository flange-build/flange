"""Allwinner H3 Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /extlinux/zImage                 — kernel 二进制（32 位 ARM，非 aarch64 的 Image）
  /dtbs/allwinner/<dtb_filename>   — 设备树
  /extlinux/extlinux.conf          — normal 启动配置
  /extlinux/recovery.conf          — recovery 启动配置（recovery 启用时）

H3 无 RTC/BSP reboot-mode driver，进入 recovery 走 U-Boot env-only 机制
（`recoveryctl recovery --persistent` → `flange_boot_once` env → U-Boot
`board_late_init()` 改写 `boot_syslinux_conf` 指向本文件，详见 design.md
决策 6）；extlinux.conf/recovery.conf 本身只描述"怎么启动"，不参与
"这次进哪里"的判断。

根设备用 LABEL=rootfs / LABEL=recovery 定位（而非 A733/Rockchip 的
PARTUUID）——MBR 分区表下固定 PARTUUID 需要额外工具链支持，直接复用
rootfs.py / RecoveryBuilder 已写入的 ext4 LABEL 更简单可靠。
"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.extlinux import (
    LabelSpec,
    NORMAL_CONFIG,
    NORMAL_LABEL,
    RECOVERY_CONFIG,
    RECOVERY_LABEL,
    render_extlinux,
)


class AllwinnerH3BootBuilder(ComponentBuilder):
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
        kernel_image = target_dir / "kernel" / "zImage"
        dts_name = config["kernel"]["dts"]
        kernel_dtb = target_dir / "kernel" / f"{dts_name}.dtb"

        if not kernel_image.exists():
            raise FileNotFoundError(
                f"kernel zImage 未找到: {kernel_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_dtb}")

        self._status("准备 boot 分区内容...")
        shutil.copy2(kernel_image, extlinux_dir / "zImage")
        dtb_filename = config.get("boot", {}).get(
            "dtb_filename", "sun8i-h3-nanopi-neo.dtb")
        shutil.copy2(kernel_dtb, dtb_dir / dtb_filename)

        (extlinux_dir / NORMAL_CONFIG).write_text(
            self._build_extlinux_conf(config, dtb_filename))
        if (config.get("recovery") or {}).get("enabled", False):
            (extlinux_dir / RECOVERY_CONFIG).write_text(
                self._build_recovery_extlinux_conf(config, dtb_filename))

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
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")

        normal = LabelSpec(
            name=NORMAL_LABEL,
            kernel="/extlinux/zImage",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="devicetree",
            fdtoverlays=[],
            append=(
                f"root=LABEL=rootfs rootfstype=ext4 rootwait rw {kernel_args}"
            ).rstrip(),
        )
        return render_extlinux(NORMAL_LABEL, [normal])

    def _build_recovery_extlinux_conf(self, config: dict, dtb_filename: str) -> str:
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")

        recovery = LabelSpec(
            name=RECOVERY_LABEL,
            kernel="/extlinux/zImage",
            fdt=f"/{self.DTB_VENDOR_DIR}/{dtb_filename}",
            fdt_directive="devicetree",
            fdtoverlays=[],
            append=(
                f"root=LABEL=recovery rootfstype=ext4 rootwait rw "
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
