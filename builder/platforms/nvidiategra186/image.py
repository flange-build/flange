"""NVIDIA Tegra186 image 构建器 —— 组装自包含的 tegraflash 刷写包。

以 bootloader 组件的刷写目录为底，加入 flange 构建的 kernel-dtb 与 system.img，按 BSP
分区模板渲染 ``flash.xml``、生成 flash.sh 格式的版本文件，最后写出覆盖全部文件摘要的
``manifest.json``。system.img 与 flash.sh 相同：rootfs 扩展到 APP 分区大小后用 BSP 的
mksparse 转成稀疏镜像，只写有效数据，首次开机不需要扩容。不产出整盘 raw.img。
"""

import shutil
import time
from pathlib import Path

from builder.base import ComponentBuilder
from builder.config.canonical import kernel_device_tree
from builder.docker import BuildError
from builder.flash.model import FlashError
from builder.flash.tegra import (
    GENERATED_TOKENS, LAYOUT, SYSTEM_IMAGE, VERSION_FILE,
    flash_args, layout_partitions, render_layout, version_file, write_manifest,
)
from builder.partition.layout import PartitionLayout
from builder.partition.size import parse_size
from builder.platforms.nvidiategra186.bootloader import BOOTCTRL_FILE, UBOOT_IMAGE

BUNDLE = "tegraflash-bundle"


class Tegra186ImageBuilder(ComponentBuilder):
    component = "image"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        with self._step("收集产物"):
            return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        if self.context is None:
            raise RuntimeError("image 构建需要 WorkspaceContext")
        target = self.context.target_dir
        inputs = {
            "tegraflash": target / "bootloader" / "tegraflash",
            "kernel_dtb": target / "boot" / "kernel-dtb.dtb",
            "rootfs": target / "rootfs" / "rootfs.img",
        }
        missing = [str(path) for path in inputs.values() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"image 缺少上游产物: {', '.join(missing)}")
        tegraflash = config["bootloader"]["tegraflash"]
        declared = sorted(set(GENERATED_TOKENS) & set(tegraflash["layout_tokens"]))
        if declared:
            raise ValueError(
                f"bootloader.tegraflash.layout_tokens 不得声明由 flange 生成的 token: {', '.join(declared)}"
            )
        # PartitionLayout 的尺寸已按 image_size 覆盖（初始镜像大小）；APP 分区大小取原始 size。
        size = PartitionLayout.from_config(config).require("rootfs").raw["size"]
        if size == "remaining":
            raise ValueError("rootfs 分区（APP）必须声明固定 size，tegraflash 分区模板不支持 remaining")
        app_bytes = parse_size(size).bytes
        rootfs_bytes = inputs["rootfs"].stat().st_size
        if rootfs_bytes > app_bytes:
            raise BuildError(f"rootfs 镜像 {rootfs_bytes} B 大于 APP 分区 {app_bytes} B")

        work = self.work_dir()
        self._bundle = bundle = work / BUNDLE
        with self._step("组装刷写目录"):
            shutil.copytree(inputs["tegraflash"], bundle, symlinks=True)
            _, dtb = kernel_device_tree(config)
            # 与 flash.sh 相同的命名：kernel-dtb 分区文件为 kernel_<dtb>.dtb。
            kernel_dtb = f"kernel_{dtb}.dtb"
            shutil.copyfile(inputs["kernel_dtb"], bundle / kernel_dtb)
        with self._step("生成 system.img"):
            self._system_image(inputs["rootfs"], work / "system.img.raw", bundle, app_bytes)
        bsp_version = bundle / "bsp_version"
        # 版本文件时间戳取 BSP 发布时刻（bsp_version 在 BSP 包中的 mtime），同一输入产出相同文件。
        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime(bsp_version.stat().st_mtime))
        (bundle / VERSION_FILE).write_text(
            version_file(bsp_version.read_text(), tegraflash["identity"], stamp)
        )
        tokens = {
            **tegraflash["layout_tokens"],
            "APPSIZE": str(app_bytes),
            "APPFILE": SYSTEM_IMAGE,
            "KERNELDTB-FILE": kernel_dtb,
            "LNXFILE": UBOOT_IMAGE,
            "BOOTCTRL-FILE": BOOTCTRL_FILE,
            "VERFILE": VERSION_FILE,
        }
        template = bundle / Path(tegraflash["layout_template"]).name
        layout = render_layout(template.read_text(), tokens)
        (bundle / LAYOUT).write_text(layout)
        partitions = layout_partitions(layout)
        absent = sorted({entry["file"] for entry in partitions if not (bundle / entry["file"]).exists()})
        if absent:
            raise FlashError(f"分区布局引用的文件不在刷写包内: {', '.join(absent)}")
        with self._step("写入刷写包 manifest"):
            write_manifest(bundle, config, partitions, flash_args(tegraflash))

    def _system_image(self, rootfs: Path, raw: Path, bundle: Path, size: int) -> None:
        """rootfs 扩展到 APP 分区大小后转稀疏镜像（flash.sh 同款 mksparse）。"""
        self.docker.run(["cp", "--sparse=always", str(rootfs), str(raw)])
        # resize2fs 要求文件系统干净；刚生成的镜像只读检查即可。
        self.docker.run(["e2fsck", "-fn", str(raw)], label="检查 rootfs 文件系统")
        self.docker.run(["truncate", "-s", str(size), str(raw)])
        self.docker.run(["resize2fs", str(raw)], label="扩展到 APP 分区大小")
        self.docker.run(
            ["./mksparse", "--fillpattern=0", str(raw), SYSTEM_IMAGE],
            cwd=str(bundle), label="mksparse",
        )
        self.docker.run(["rm", "-f", str(raw)])

    def collect(self, src_dir, config: dict) -> dict:
        return {"bundle": self._bundle}
