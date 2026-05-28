"""Radxa Dragon Q6A (Qualcomm QCS6490) 板级配置 -- 第三层继承

flange 首个 Qualcomm 板。platform=qualcommqcs6490 / soc=qcs6490。
启动 GRUB(grub-with-dtb)+EDK2 UEFI，刷写走 EDL/edl-ng；详见平台/SoC config。
Wi-Fi 为 AIC8800 USB 模组（与 radxa-cubie-a7a 同款，复用其固件配置）。

## 多 product 维度（屏幕模组）

variants 沿用 platform 层默认 ``["debug", "release"]``。

- ``radxa-dragon-q6a-default-{debug,release}``：板出厂裸机，不挂屏（不启用
  meizu-e3-panel 包 / 不带 panel/sec_ts/sgm37604a 三个 OOT 驱动 / dtb 直拷未合并）。
- ``radxa-dragon-q6a-meizu-e3-bringup-{debug,release}``：挂载魅族 E3 39pin
  MIPI-DSI 屏（显示 + 触摸 + 背光），与 radxa-cubie-a7a / radxa-rock5b 跨 SoC
  复用同一硬件特性包 ``meizu-e3-panel``。Q6A 走 mainline drm/msm + 包内新增
  OOT ``panel_meizu_e3`` 驱屏；背光仍走 ``sgm37604a`` I2C 路径（板载 SY7203
  boost 因 EDP_BLPWM 不被 dtso 引用而保持 disabled，与屏自带 SGM37604A 电气
  并联但功能互斥）。

## 构建期 fdtoverlay 合并

Q6A 启动链 EDK2 UEFI → GRUB(grub-with-dtb)，不支持运行时 DT overlay；故
``meizu-e3-bringup`` product 启用包后，包内 ``.dtso`` 编出的 ``.dtbo`` 由
``builder/platforms/qualcommqcs6490/rootfs.py`` 经 ``fdtoverlay`` 在构建期
合并到 base dtb，覆盖式写入 rootfs ``/boot/<dtb>.dtb``（GRUB ``grub.cfg``
不变）。详见 [[build-time-dtb-overlay-merge]]。
"""

# AIC8800 D80 USB Wi-Fi 固件（与 radxa-cubie-a7a 1:1 复用；Q6A 板载同款模组）
AIC8800_RADXA_REPO = "https://github.com/radxa-pkg/aic8800.git"
AIC8800_RADXA_COMMIT = "7f42b22913b462ab6c658dfc075bae1dbfe9a71a"

# Qualcomm PIL 固件（ADSP / CDSP）—— radxa-pkg/radxa-firmware 0.2.31
# 单文件 .mbn 格式（非 mainline .mdt + .b0X split），与 DTS patch
# 0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch 配套使用。
# 内核 qcom_mdt_bins_are_split() 自动识别单文件 ELF，无需 .b0X。
# .jsn 是 ADSP/CDSP fastrpc 服务的 routing manifest（fastrpc 用户态查找）。
RADXA_FW_REPO = "https://github.com/radxa-pkg/radxa-firmware.git"
RADXA_FW_COMMIT = "9915f1b39fb4f43807085917543dec4858820380"
RADXA_FW_Q6A_PIL_FILES = [
    "qcom/qcs6490/radxa/dragon-q6a/adsp.mbn",
    "qcom/qcs6490/radxa/dragon-q6a/adspr.jsn",
    "qcom/qcs6490/radxa/dragon-q6a/adspua.jsn",
    "qcom/qcs6490/radxa/dragon-q6a/cdsp.mbn",
    "qcom/qcs6490/radxa/dragon-q6a/cdspr.jsn",
]

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
    # ---- 多 product 维度（屏幕模组）----
    # 详见文件头 docstring；variants 沿用 platform 默认 ["debug", "release"]。
    "products": ["default", "meizu-e3-bringup"],
    # ---- 魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）----
    # 仅 meizu-e3-bringup product 启用 meizu-e3-panel 硬件特性包；default 裸机
    # 不挂屏、不带这些 OOT 驱动。Q6A 上启用三个 OOT 驱动：
    #   - sec_ts：触摸（与 a7a/rock5b 共享）
    #   - sgm37604a：屏自带 I2C 背光（与 a7a 共享；rock5b 不选它）
    #   - panel_meizu_e3：本变更新增，drm_panel 风格 OOT 驱屏，供 mainline
    #     drm/msm 消费（QCLINUX BSP 6.6.90 无通用 DSI panel driver）
    "+packages:meizu-e3-bringup": [
        {"name": "meizu-e3-panel",
         "drivers": ["sec_ts", "sgm37604a", "panel_meizu_e3"]},
    ],
    "kernel": {
        # 主线 dtb（radxa/kernel@linux-6.18.2 内 arch/arm64/boot/dts/qcom/）
        "dtb": "qcs6490-radxa-dragon-q6a",
    },
    "wifi": {
        "aic8800_usb": True,
    },
    "rootfs": {
        # AIC8800 D80 USB 固件路径布局：
        #   QCLINUX BSP 内的 aic8800_usb driver 把固件目录写死为
        #   `/lib/firmware/aic8800D80/`（见 drivers/.../aicbluetooth.c
        #   里 `snprintf("%s/aic8800D80/%s", aic_default_fw_path, name)`，
        #   aic_default_fw_path = "/lib/firmware"），不走 A733 路线的
        #   `CONFIG_AIC_FW_PATH` patch。所以这里**直接装到
        #   /lib/firmware/aic8800D80/**；不再多装一份 a7a 的
        #   /lib/firmware/aic8800_fw/USB（Q6A 用的是 BSP driver，那条对
        #   它无意义且会浪费 rootfs 空间）。
        "+extra_firmware": [
            {
                "name": "radxa-aic8800",
                "repo": AIC8800_RADXA_REPO,
                "commit": AIC8800_RADXA_COMMIT,
                "repo_subdir": "src/USB/driver_fw/fw/aic8800D80",
                "files": AIC8800_D80_USB_FIRMWARE_FILES,
                "dest": "lib/firmware/aic8800D80",
            },
            # Qualcomm ADSP/CDSP PIL 镜像 + fastrpc manifest
            #   配合 patches/kernel/0001-dts-...-PIL-firmware-paths.patch
            #   修改的 firmware-name 把 .mbn 直接喂给 qcom_q6v5_pas。
            {
                "name": "radxa-firmware-qcs6490",
                "repo": RADXA_FW_REPO,
                "commit": RADXA_FW_COMMIT,
                "repo_subdir": "radxa-firmware-qcs6490/lib/firmware",
                "files": RADXA_FW_Q6A_PIL_FILES,
                "dest": "lib/firmware",
            },
        ],
    },
}
