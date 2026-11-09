"""UNO Q 镜像组件：发布 QDL 固件和独立文件系统，不产生两分区 raw.img。"""

from builder.base import ComponentBuilder
from builder.flash.unoq import build_bundle


class Qrb2210ImageBuilder(ComponentBuilder):
    component = "image"

    def build(self, config):
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config):
        pass

    def compile(self, src_dir, config):
        target = self.cache.target_dir
        self._bundle = build_bundle(
            target / "bootloader" / "firmware",
            {"boot_a": target / "bootloader" / "uboot-boot.img",
             "efi": target / "boot" / "boot.img",
             "rootfs": target / "rootfs" / "rootfs.img",
             "userdata": target / "rootfs" / "userdata.img"},
            self.work_dir() / "flash-bundle",
        )

    def collect(self, src_dir, config):
        return {"bundle": self._bundle}
