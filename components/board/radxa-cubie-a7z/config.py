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
        # 把 radxa-overlays 中与 A733 兼容的全部 overlay 打入 boot.img。
        "vendor_overlays": A733_VENDOR_OVERLAYS,
        # 板私有 overlay，源文件位于 components/board/radxa-cubie-a7z/overlays/，
        # 由 device-tree-overlay 组件复用同一 cpp+dtc 流水线编译。
        "board_overlays": [
            "sun60iw2p1-spi1-st7789v-display.dtbo",
        ],
        # 开机默认应用的 overlay（按声明顺序写入 extlinux fdtoverlays）；
        # 未列入此处的 overlay 仍可通过运行时编辑 /boot/extlinux/extlinux.conf
        # 启用。
        #
        # SPI1 当前绑定 ST7789V SPI LCD（出 /dev/fb0，fbcon 接管为系统主
        # 显示）；如需改回 spidev1.0 用户态访问，把下面这行换成
        # "sun60iw2p1-spi1-spidev.dtbo"（已在 vendor_overlays 中）。
        "default_overlays": [
            "sun60iw2p1-spi1-st7789v-display.dtbo",
        ],
        # 让内核 boot log 也输出到 LCD（与串口 ttyAS0 并存）。
        "kernel_args": "console=tty1",
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
        # 板级附加包：
        #   kbd            — 提供 chvt / openvt / setfont 控制 fbcon
        #   console-setup  — 应用 /etc/default/console-setup 的字体设置
        #   fonts-terminus — Terminus 6×12 控制台字体（ST7789V 屏适配）
        "packages": [
            "kbd",
            "console-setup",
            "fonts-terminus",
        ],
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
