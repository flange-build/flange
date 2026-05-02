"""Radxa Cubie A7Z (Allwinner A733) 板级配置"""

# radxa-overlays 仓库内与 A733 (sun60iw2p1) 兼容的 vendor overlay 全集。
# 仓库 arch/arm64/boot/dts/allwinner/overlays/Makefile 用
# CONFIG_ARCH_SUN60IW2 圈选这一组；A523 / A527 / A537 (sun55iw3p1) 那一组
# 与本板 SoC 不兼容，故不打包。
A733_VENDOR_OVERLAYS = [
    # SoC 级（sun60iw2p1）— 通用外设 muxing
    "sun60iw2p1-i2s0-2ch.dtbo",
    "sun60iw2p1-i2s4-2ch.dtbo",
    "sun60iw2p1-pwm1-1.dtbo",
    "sun60iw2p1-pwm1-2.dtbo",
    "sun60iw2p1-pwm1-3.dtbo",
    "sun60iw2p1-pwm1-6.dtbo",
    "sun60iw2p1-pwm1-7.dtbo",
    "sun60iw2p1-spi1-spidev.dtbo",
    "sun60iw2p1-spi3-spidev.dtbo",
    "sun60iw2p1-twi2.dtbo",
    "sun60iw2p1-twi7.dtbo",
    "sun60iw2p1-uart2.dtbo",
    "sun60iw2p1-uart3.dtbo",
    "sun60iw2p1-uart4.dtbo",
    # 板级（cubie-a7a 命名，但同基线 SoC，依 Makefile 归到 sun60iw2p1）
    "cubie-a7a-enable-sunxi-ac101-sound-card.dtbo",
    "cubie-a7a-radxa-25w-poe.dtbo",
    "cubie-a7a-radxa-camera-8m-219.dtbo",
    "cubie-a7a-radxa-camera-13m-214.dtbo",
    "cubie-a7a-radxa-camera-4k-415.dtbo",
    "cubie-a7a-radxa-display-8hd.dtbo",
    "cubie-a7a-radxa-display-10fhd.dtbo",
    # cubie-a7z 板级独有
    "cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo",
]

AIC8800_RADXA_REPO = "https://github.com/radxa-pkg/aic8800.git"
AIC8800_RADXA_COMMIT = "7f42b22913b462ab6c658dfc075bae1dbfe9a71a"
AIC8800_D80_USB_FIRMWARE_FILES = [
    "fw_patch_8800d80_u02_ext0.bin",
    "fw_adid_8800d80_u02.bin",
    "fw_patch_table_8800d80_u04.bin",
    "fw_patch_8800d80_u04.bin",
    "aic_userconfig_8800d80.txt",
    "fw_patch_table_8800d80_u02.bin",
    "fw_patch_8800d80_u02.bin",
    "fmacfw_8800d80_h_u02_ipc.bin",
    "fw_ble_scan_ad_filter.bin",
    "aic_powerlimit_8800d80.txt",
    "fmacfw_8800d80_u02.bin",
    "calibmode_8800d80.bin",
    "fmacfw_8800d80_u02_ipc.bin",
    "fmacfw_8800d80_h_u02.bin",
    "lmacfw_rf_8800d80_u02.bin",
]

BOARD = {
    "board": "radxa-cubie-a7z",
    "soc": "a733",
    "platform": "allwinnera733",
    "kernel": {
        "dts": "sun60i-a733-cubie-a7z",
    },
    "boot": {
        # 把 radxa-overlays 中与 A733 兼容的全部 overlay 打入 boot.img；
        # 默认不应用（default_overlays 仍为空），运行时通过编辑
        # /boot/extlinux/extlinux.conf 的 fdtoverlays 行选用。
        "vendor_overlays": A733_VENDOR_OVERLAYS,
    },
    "wifi": {
        "aic8800_usb": True,
    },
    "kernel_device": {
        "board_dts_path": "configs/cubie_a7z/linux-5.15/board.dts",
    },
    "bootloader": {
        "target": "radxa-cubie-a7z",
    },
    "rootfs": {
        "root_password": "1234",
        # AIC8800 旧 BSP firmware helper 从 aic_fw_path 直接读取扁平文件；
        # Wi-Fi fdrv 又会在同一路径下拼接 aic8800D80/ 读取用户配置。
        # 因此同一批 Radxa D80 USB 固件同时安装为扁平目录和芯片子目录。
        "extra_firmware": [
            {
                "name": "radxa-aic8800",
                "repo": AIC8800_RADXA_REPO,
                "commit": AIC8800_RADXA_COMMIT,
                "repo_subdir": "src/USB/driver_fw/fw/aic8800D80",
                "files": AIC8800_D80_USB_FIRMWARE_FILES,
                "dest": "lib/firmware/aic8800_fw/USB",
            },
            {
                "name": "radxa-aic8800",
                "repo": AIC8800_RADXA_REPO,
                "commit": AIC8800_RADXA_COMMIT,
                "repo_subdir": "src/USB/driver_fw/fw",
                "files": [
                    f"aic8800D80/{path}"
                    for path in AIC8800_D80_USB_FIRMWARE_FILES
                ],
                "dest": "lib/firmware/aic8800_fw/USB",
            },
        ],
    },
}
