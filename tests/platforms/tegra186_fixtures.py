"""Tegra186 测试共用夹具：最小分区模板、tegraflash 配置与刷写目录。

模板覆盖真实 BSP 模板中出现的几类情况：带 ``_b`` 后缀的 token、签名 / 非签名分区、
由 flange 生成文件的 token，以及值为空（保留分区但不写入）的文件 token。
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE = """<?xml version="1.0"?>
<partition_layout version="01.00.0000">
    <device type="sdmmc_boot" instance="3" sector_size="512" num_sectors="16384">
        <partition name="TBCNAME" type="TBCTYPE" oem_sign="true">
            <size> 2097152 </size>
            <filename> TBCFILE </filename>
        </partition>
        <partition name="TBCNAME_b" type="TBCTYPE" oem_sign="true">
            <size> 2097152 </size>
            <filename> TBCFILE </filename>
        </partition>
    </device>
    <device type="sdmmc_user" instance="3" sector_size="512" num_sectors="61071360">
        <partition name="APP" type="data">
            <size> APPSIZE </size>
            <unique_guid> APPUUID </unique_guid>
            <filename> APPFILE </filename>
        </partition>
        <partition name="LNXNAME" type="data" oem_sign="true">
            <size> 83886080 </size>
            <filename> LNXFILE </filename>
        </partition>
        <partition name="KERNELDTB-NAME" type="data" oem_sign="true">
            <size> 524288 </size>
            <filename> KERNELDTB-FILE </filename>
        </partition>
        <partition name="kernel-bootctrl" type="data">
            <size> 262144 </size>
            <filename> BOOTCTRL-FILE </filename>
        </partition>
        <partition name="VER" type="data">
            <size> 1048576 </size>
            <filename> VERFILE </filename>
        </partition>
        <partition name="RECNAME" type="data" oem_sign="true">
            <size> 66060288 </size>
            <filename> RECFILE </filename>
        </partition>
    </device>
</partition_layout>
"""

TOKENS = {
    "TBCNAME": "cpu-bootloader", "TBCTYPE": "bootloader", "TBCFILE": "cboot.bin",
    "LNXNAME": "kernel", "KERNELDTB-NAME": "kernel-dtb", "RECNAME": "recovery",
    "RECFILE": "", "APPUUID": "",
}

BSP_VERSION = "BSP_BRANCH=32\nBSP_MAJOR=7\nBSP_MINOR=6\n"

DTB = "tegra186-quill-p3310-1000-c03-00-base"


def tegraflash_config() -> dict:
    return {
        "chip": "0x18",
        "odmdata": "0x1090000",
        "bl": "nvtboot_recovery_cpu.bin",
        "applet": "mb1_recovery_prod.bin",
        "layout_template": "bootloader/t186ref/cfg/flash_l4t_t186.xml",
        "layout_tokens": dict(TOKENS),
        "bct_configs": {"sdram_config": "sdram.cfg", "dev_params": "emmc.cfg",
                        "misc_config": "misc.cfg"},
        "bins": [{"type": "mb2_bootloader", "file": "nvtboot_recovery.bin"},
                 {"type": "bpmp_fw", "file": "bpmp.bin"}],
        "extra_files": [],
        "uboot": "bootloader/t186ref/p2771-0000/500/u-boot.bin",
        "identity": {"board_id": "3310", "board_sku": "1000", "fabs": ["B02"]},
    }


def image_config(**extra) -> dict:
    return {
        "board": "nvidia-jetson-tx2",
        "product": "default",
        "variant": "release",
        "platform": "nvidiategra186",
        "soc": "tegra186",
        "kernel": {"device_tree": {"directory": "", "name": DTB}},
        "bootloader": {"tegraflash": tegraflash_config()},
        "partitions": {"format": "gpt", "sector_size": 512, "entries": [
            {"name": "rootfs", "label": "APP", "type": "ext4", "size": "1G", "image_size": "8M"},
        ]},
        **extra,
    }


def upstream(target: Path, rootfs_bytes: int = 4096) -> None:
    """预置 image 组件的三类上游产物。"""
    tree = target / "bootloader" / "tegraflash"
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "flash_l4t_t186.xml").write_text(TEMPLATE)
    (tree / "bsp_version").write_text(BSP_VERSION)
    for name in ("tegraflash.py", "mksparse", "cboot.bin", "boot.img", "kernel_bootctrl.bin",
                 "tos-trusty.img"):
        (tree / name).write_bytes(name.encode())
    (tree / "tos.img").symlink_to("tos-trusty.img")
    (target / "boot").mkdir(parents=True, exist_ok=True)
    (target / "boot" / "kernel-dtb.dtb").write_bytes(b"\xd0\x0d\xfe\xed dtb")
    (target / "rootfs").mkdir(parents=True, exist_ok=True)
    (target / "rootfs" / "rootfs.img").write_bytes(b"\0" * rootfs_bytes)


def fake_mksparse(command, **kwargs):
    """docker mock：mksparse 在 cwd（刷写包）中写出 system.img。"""
    if command and command[0] == "./mksparse":
        (Path(kwargs["cwd"]) / command[-1]).write_bytes(b"sparse")
    from unittest.mock import MagicMock
    return MagicMock()
