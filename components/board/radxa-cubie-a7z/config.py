"""Radxa Cubie A7Z (Allwinner A733) 板级配置"""

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
