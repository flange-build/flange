"""Allwinner H3 SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "allwinnerh3",
    "soc": "h3",
    # Debian 架构名（App/deb 打包用），非内核 Makefile ARCH，详见
    # components/platform/allwinnerh3/config.py 同名字段注释。
    "arch": "armhf",
    "kernel": {
        "defconfig": [
            "sunxi_defconfig", "case_insensitive_fix.config",
            # USB gadget（MUSB peripheral + configfs），支撑 recoveryctl/adbd
            # 的 USB ADB 通道。NanoPi NEO 的 micro USB 口 mainline dts 已锁定
            # dr_mode="peripheral"（sun8i-h3-nanopi-neo.dts），硬件无需改造，
            # 只需内核侧打开对应驱动。EXTCON/NOP_USB_XCEIV/PHY_SUN4I_USB 是
            # USB_MUSB_SUNXI 的 "depends on"（非 select），必须显式声明，见
            # drivers/usb/musb/Kconfig。详见 design.md 决策 8。
            "CONFIG_EXTCON=y",
            "CONFIG_NOP_USB_XCEIV=y",
            "CONFIG_PHY_SUN4I_USB=y",
            "CONFIG_USB_MUSB_HDRC=y",
            "CONFIG_USB_MUSB_SUNXI=y",
            "CONFIG_USB_GADGET=y",
            "CONFIG_CONFIGFS_FS=y",
            "CONFIG_USB_CONFIGFS=y",
            "CONFIG_USB_CONFIGFS_F_FS=y",
        ],
        # mainline kernel（5.11+）把 arm32 sunxi dts 归到 arch/arm/boot/dts/allwinner/
        # 子目录下，与 arm64 dts 布局一致；沿用与 allwinnera733 相同的 dts_dir 约定。
        "dts_dir": "allwinner",
    },
    "bootloader": {
        "defconfig": [
            "nanopi_neo_defconfig",
            # U-Boot env 持久化存储：mainline sunxi 默认 ENV_IS_IN_FAT（存成
            # FAT 分区里的文件），与 flange 全平台统一用 ext4 boot 分区的约定
            # 冲突，改用 ENV_IS_IN_MMC + 不覆盖的 sunxi 默认
            # ENV_OFFSET=0xF0000/ENV_SIZE=0x10000（sector 1920-2047，恰好落在
            # spl 分区结束与 boot 分区起始之间的天然空隙）。是 recoveryctl
            # env-only recovery 进入机制（决策 6）的持久化基础。
            "CONFIG_ENV_IS_IN_MMC=y",
            "# CONFIG_ENV_IS_IN_FAT is not set",
        ],
    },
    "boot": {
        "dtb_filename": "sun8i-h3-nanopi-neo.dtb",
        "kernel_args": "console=ttyS0,115200",
    },
    # MBR 分区表（sunxi 社区惯例），而非其余平台使用的 GPT。SPL 由 BootROM
    # 固定从 sector 16（8KiB 偏移）加载，落在 MBR 分区表与首个数据分区
    # （sector 2048 / 1MiB）之间的天然空隙里，互不冲突（详见 design.md 决策 4）。
    # spl 分区止于 sector 1920（16+1904），为 U-Boot env（sector 1920-2047）
    # 让出空隙，boot 分区仍从 sector 2048 起（详见 design.md 决策 7）。
    "partitions": {
        "format": "mbr",
        "sector_size": 512,
        "entries": [
            {"name": "spl",      "offset": "0x10",    "size": "0x770",   "type": "raw"},
            {"name": "boot",     "offset": "0x800",   "size": "0x20000", "type": "ext4"},
            {"name": "recovery", "offset": "0x20800",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",   "offset": "0x120800", "size": "remaining",
             "type": "ext4", "image_size": "2G"},
        ],
    },
}
