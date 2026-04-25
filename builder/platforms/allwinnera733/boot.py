"""Allwinner A733 Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /extlinux/Image               — kernel 二进制
  /extlinux/<dtb_filename>      — 设备树（默认 sunxi.dtb）
  /extlinux/extlinux.conf       — U-Boot distro boot 配置

Allwinner U-Boot 扫描 boot 分区的 /extlinux/extlinux.conf 启动，
所有文件均放在 /extlinux/ 子目录下（与 Rockchip 布局不同）。
"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.extlinux import (
    LabelSpec,
    NORMAL_LABEL,
    RECOVERY_LABEL,
    render_extlinux,
)


class AllwinnerA733BootBuilder(ComponentBuilder):
    component = "boot"

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

        target_dir = self.cache.target_dir
        kernel_image = target_dir / "kernel" / "Image"
        dts_name = config["kernel"]["dts"]
        kernel_dtb = target_dir / "kernel" / f"{dts_name}.dtb"

        if not kernel_image.exists():
            raise FileNotFoundError(
                f"kernel Image 未找到: {kernel_image}；"
                "确认 kernel 组件构建成功且产物已收集")
        if not kernel_dtb.exists():
            raise FileNotFoundError(f"kernel DTB 未找到: {kernel_dtb}")

        # 复制到 extlinux/ 子目录
        self._status("准备 boot 分区内容...")
        shutil.copy2(kernel_image, extlinux_dir / "Image")
        dtb_filename = config.get("boot", {}).get("dtb_filename", "sunxi.dtb")
        shutil.copy2(kernel_dtb, extlinux_dir / dtb_filename)

        # 生成 extlinux.conf
        (extlinux_dir / "extlinux.conf").write_text(
            self._build_extlinux_conf(config, dtb_filename))

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
        """生成 extlinux.conf。

        根设备使用 PARTUUID 定位（由 ImageBuilder 在 GPT 分区表中写入固定
        UUID）。相比 LABEL=xxx，PARTUUID 无需 userspace udev 辅助，
        kernel 启动早期即可解析，避免 "Waiting for root device" 卡死。

        启用 recovery 时新增 recovery label；recovery 分区由 mke2fs -L recovery
        创建 ext4 label，因此 recovery 入口仍可使用 LABEL=recovery 定位（与
        Rockchip 一致），即便首版不要求 A733 实机验证 recovery 启动。
        """
        boot_cfg = config.get("boot", {})
        kernel_args = boot_cfg.get("kernel_args", "")
        root_partuuid = boot_cfg.get("root_partuuid",
                                     "614e0000-0000-4000-8000-000000000001")

        normal = LabelSpec(
            name=NORMAL_LABEL,
            kernel="/extlinux/Image",
            fdt=f"/extlinux/{dtb_filename}",
            fdt_directive="devicetree",
            append=(
                f"root=PARTUUID={root_partuuid} "
                f"rootfstype=ext4 rootwait rw {kernel_args}"
            ).rstrip(),
        )
        labels = [normal]

        if (config.get("recovery") or {}).get("enabled", False):
            recovery = LabelSpec(
                name=RECOVERY_LABEL,
                kernel="/extlinux/Image",
                fdt=f"/extlinux/{dtb_filename}",
                fdt_directive="devicetree",
                append=(
                    f"root=LABEL=recovery rootfstype=ext4 rootwait rw "
                    f"flange.mode=recovery {kernel_args}"
                ).rstrip(),
            )
            labels.append(recovery)

        return render_extlinux(NORMAL_LABEL, labels)

    def _partition_size_mb(self, config: dict, name: str) -> int:
        for entry in config.get("partitions", {}).get("entries", []):
            if entry["name"] == name:
                size_sectors = int(entry["size"], 0)
                return (size_sectors * 512) // (1024 * 1024)
        raise KeyError(f"partitions.entries 中未定义分区: {name}")

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"boot": self._boot_img}
