"""Radxa Cubie A7A (Allwinner A733) 板级配置"""

# radxa-overlays 仓库内与 A733 (sun60iw2p1) 兼容的 vendor overlay 全集。
# 与 a7z 配置故意保持"显式重复 -1"关系：基于 sun60iw2p1 SoC 圈选的一组
# overlay 完全照搬，仅剔除 a7z 私有的
# `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`（a7a 板载 AC101B
# 直挂 i2c@3e，不需要 HDMI→TypeC-DP 音频 reroute）。
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
    # 板级（cubie-a7a 命名；上游 radxa-overlays 以 a7a 为基线，a7z 反而是复用方）
    "cubie-a7a-enable-sunxi-ac101-sound-card.dtbo",
    "cubie-a7a-radxa-25w-poe.dtbo",
    "cubie-a7a-radxa-camera-8m-219.dtbo",
    "cubie-a7a-radxa-camera-13m-214.dtbo",
    "cubie-a7a-radxa-camera-4k-415.dtbo",
    "cubie-a7a-radxa-display-8hd.dtbo",
    "cubie-a7a-radxa-display-10fhd.dtbo",
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
    "board": "radxa-cubie-a7a",
    "soc": "a733",
    "platform": "allwinnera733",
    "kernel": {
        "dts": "sun60i-a733-cubie-a7a",
    },
    "boot": {
        # 把 radxa-overlays 中与 A733 兼容的全部 overlay 打入 boot.img；
        # 详见上方 A733_VENDOR_OVERLAYS 注释。
        "vendor_overlays": A733_VENDOR_OVERLAYS,
        # 开机默认应用的 overlay（按声明顺序写入 extlinux fdtoverlays）。
        # a7a 主显示走 HDMI 直出（无需 overlay）；MIPI DSI 主屏首版不点亮
        # （board.dts 中 panel@0 为 allwinner,virtual-panel placeholder，
        # 需具体面板 init 序列方可点亮，归后续变更）。
        # 仅启板载 AC101B 音频以便上电即可用，camera / PoE / display
        # 等外设按需运行时编辑 /boot/extlinux/extlinux.conf 启用。
        "default_overlays": [
            "cubie-a7a-enable-sunxi-ac101-sound-card.dtbo",
        ],
    },
    "wifi": {
        "aic8800_usb": True,
    },
    "kernel_device": {
        "board_dts_path": "configs/cubie_a7a/linux-5.15/board.dts",
    },
    "bootloader": {
        "target": "radxa-cubie-a7a",
    },
    "rootfs": {
        # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全
        # 锁定 + 默认用户 flange/flange。如需开放 root 在此处覆盖。
        # AIC8800 旧 BSP firmware helper 从 aic_fw_path 直接读取扁平文件；
        # Wi-Fi fdrv 又会在同一路径下拼接 aic8800D80/ 读取用户配置。
        # 因此同一批 Radxa D80 USB 固件同时安装为扁平目录和芯片子目录。
        # 与 a7z 字段 1:1 等价（用户确认 a7a 板载 Wi-Fi 模组同款）。
        "+extra_firmware": [
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
