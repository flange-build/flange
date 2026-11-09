"""NVIDIA Tegra186 boot 构建器 —— 产出 kernel-dtb 分区内容。

cboot 从 ``kernel-dtb`` 分区读取内核 DTB，做运行期修正后经 U-Boot 交给内核；
Image / initrd / extlinux 在 APP 分区的 ``/boot``，由 rootfs 组件安装。
extlinux 不写 FDT，因此 DTBO 只能在这里构建期合并进 DTB。
"""

import shutil

from builder.base import ComponentBuilder
from builder.config.canonical import kernel_device_tree
from builder.dtb_overlay import build_overlays, intree_overlays

KERNEL_DTB = "kernel-dtb.dtb"


class Tegra186BootBuilder(ComponentBuilder):
    component = "boot"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        with self._step("收集产物"):
            return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        if self.context is None:
            raise RuntimeError("boot 构建需要 WorkspaceContext")
        target = self.context.target_dir
        _, name = kernel_device_tree(config)
        base = target / "kernel" / f"{name}.dtb"
        if not base.is_file() or base.stat().st_size == 0:
            raise FileNotFoundError(f"boot 缺少上游内核 DTB: {base}")
        overlays = build_overlays(config)
        intree = [item for item in overlays if item in intree_overlays(config)]
        if intree:
            raise ValueError(
                f"Tegra186 暂不支持内核树内 overlay: {', '.join(intree)}；"
                "请改用 vendor / board / package overlay"
            )
        self._dtb = self.work_dir() / KERNEL_DTB
        if not overlays:
            shutil.copyfile(base, self._dtb)
            return
        paths = [target / "device-tree-overlay" / "overlays" / item for item in overlays]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"构建期覆盖缺少 DTBO: {', '.join(missing)}")
        self.docker.run(
            ["fdtoverlay", "-i", str(base), "-o", str(self._dtb), *map(str, paths)],
            label="合并设备树覆盖",
        )

    def collect(self, src_dir, config: dict) -> dict:
        return {"kernel_dtb": self._dtb}
