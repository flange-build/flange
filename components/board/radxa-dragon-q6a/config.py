"""Radxa Dragon Q6A (Qualcomm QCS6490) 板级配置 -- 第三层继承

flange 首个 Qualcomm 板。platform=qualcommqcs6490 / soc=qcs6490。
启动 GRUB(grub-with-dtb)+EDK2 UEFI，刷写走 EDL/edl-ng；详见平台/SoC config。
Wi-Fi 为 AIC8800 USB 模组（与 radxa-cubie-a7a 同款，复用其固件配置）。
"""

# AIC8800 D80 USB Wi-Fi 固件（与 radxa-cubie-a7a 1:1 复用；Q6A 板载同款模组）
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
    "board": "radxa-dragon-q6a",
    "soc": "qcs6490",
    "platform": "qualcommqcs6490",
    # products / variants 沿用 platform 默认：
    #   radxa-dragon-q6a-default-{debug,release}
    "kernel": {
        # 主线 dtb（radxa/kernel@linux-6.18.2 内 arch/arm64/boot/dts/qcom/）
        "dtb": "qcs6490-radxa-dragon-q6a",
    },
    "wifi": {
        "aic8800_usb": True,
    },
    "rootfs": {
        # AIC8800 D80 USB 固件：扁平目录 + 芯片子目录双装（与 a7a 同款）。
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
