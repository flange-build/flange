"""Amlogic Boot 分区镜像构建策略。

产物：boot.img（ext4 文件系统镜像），内含：
  /extlinux/Image                — kernel 二进制
  /dtbs/amlogic/<dts>.dtb         — 设备树
  /dtbs/amlogic/overlay/*.dtbo    — （可选）设备树 overlay
  /extlinux/extlinux.conf         — normal 启动配置
  /extlinux/recovery.conf         — recovery 启动配置（启用 recovery 时）

mainline u-boot khadas-vim3l_defconfig 已开 BOOTSTD_DEFAULTS / 标准 distro
boot，会自动扫描 /extlinux/extlinux.conf。运行时通过 fstab 中
``LABEL=boot /boot ext4 ...`` 挂载到 rootfs 的 /boot。
"""

from pathlib import Path
from builder.base import ComponentBuilder


class AmlogicBootBuilder(ComponentBuilder):
    component = "boot"

    # boot 分区内 DTB 存放目录（相对 boot.img 根）
    DTB_VENDOR_DIR = "dtbs/amlogic"

    def build(self, config: dict) -> dict:
        """boot 镜像无需克隆源码仓库，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # boot 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        raise NotImplementedError(
            "AmlogicBootBuilder.compile 待实现（tasks 5.2）：从 kernel 产物 + "
            "config 构建 ext4 boot.img，含 extlinux.conf + Image + dtb"
        )

    def collect(self, src_dir: Path, config: dict) -> dict:
        raise NotImplementedError(
            "AmlogicBootBuilder.collect 待实现（tasks 5.2）"
        )
