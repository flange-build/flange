"""Allwinner H3 Bootloader 构建策略 -- 主线 U-Boot sunxi 流程。

与 A733 平台的私有 boot0/dragonsecboot 工具链不同，H3 走标准主线 sunxi
BROM+SPL 流程：``make nanopi_neo_defconfig && make`` 直接产出单一文件
``u-boot-sunxi-with-spl.bin``，无需签名、无需专有打包工具（详见
design.md 决策 1）。
"""

import shlex
from pathlib import Path
from builder.base import ComponentBuilder


class AllwinnerH3BootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"
    # gcc-10（kernel.org crosstool nolibc arm-linux-gnueabi，见 docker/Dockerfile）。
    # 起初用系统 gcc-13（arm-linux-gnueabihf-）编 v2024.01 U-Boot，NanoPi NEO 上板
    # 串口零输出、连 FEL 灌 SPL 都无 banner；配置与反汇编均证明正确、Armbian 同版本
    # 实证能出串口 → 排查矛头指向 gcc-13 隐蔽 miscompile（ROCK 4D 前科：gcc-13 让低层
    # u-boot 二进制布局变化致早期崩）。切回 gcc-10 与全平台 aarch64 约定一致。
    CROSS = "/opt/arm-gcc10/bin/arm-linux-gnueabi-"

    def configure(self, src_dir: Path, config: dict):
        """支持单 defconfig 字符串或多步 defconfig 合并 list（对齐 rockchip
        bootloader.py 的既有模式）：list 中含 "=" 或 "# CONFIG_" 的项是 raw
        u-boot option，聚合后追加进 .config 再 olddefconfig 归一化；其余是
        defconfig/fragment make 目标。H3 用它注入 CONFIG_ENV_IS_IN_MMC 等
        env 持久化选项（详见 design.md 决策 7）。
        """
        defconfig = config["bootloader"]["defconfig"]
        if isinstance(defconfig, str):
            defconfig = [defconfig]
        targets = [d for d in defconfig
                   if "=" not in d and not d.lstrip().startswith("# CONFIG_")]
        raw_options = [d for d in defconfig
                       if "=" in d or d.lstrip().startswith("# CONFIG_")]
        self.make(src_dir, targets, arch=self.ARCH, cross=self.CROSS)
        if raw_options:
            self._apply_inline_defconfig(src_dir, raw_options)

    def _apply_inline_defconfig(self, src_dir: Path, options: list):
        """把 raw u-boot option 追加进 .config 再 olddefconfig 归一化。"""
        payload = "".join(o.rstrip("\n") + "\n" for o in options)
        self.docker.run(
            ["sh", "-c", "printf '%s' " + shlex.quote(payload) + " >> .config"],
            cwd=str(src_dir))
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)
        self._status(f"u-boot inline defconfig（{len(options)} 项 option）")

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        self.make(src_dir, [], arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  label="编译 U-Boot...")

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"spl": src_dir / "u-boot-sunxi-with-spl.bin"}
