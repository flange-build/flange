"""NanoPi NEO (FriendlyElec, Allwinner H3) 板级配置"""

BOARD = {
    "board": "nanopi-neo",
    "soc": "h3",
    "platform": "allwinnerh3",
    "products": ["default"],
    "variants": ["debug", "release"],
    "kernel": {
        "repo": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
        "branch": "linux-6.6.y",
        "dts": "sun8i-h3-nanopi-neo",
    },
    "bootloader": {
        "repo": "https://github.com/u-boot/u-boot.git",
        # 钉稳定 tag v2024.01：与 Armbian 在本板实证能出串口的版本完全一致
        # （Armbian config/sources/families/include/sunxi_common.inc:13
        # BOOTBRANCH="tag:v2024.01"，同一 nanopi_neo_defconfig）。此前 "master"
        # 会拉到未发布的 2026.07-rc 开发版，是串口零输出的头号嫌疑。已核实：
        # 本平台 recovery patch 能干净 apply 到 v2024.01 board.c，且 v2024.01
        # 已有 boot_syslinux_conf env 机制，recovery 功能不受影响。
        "tag": "v2024.01",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-armhf.tar.gz",
    },
}
