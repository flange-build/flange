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
    # ---- 多 product 维度（屏幕模组） ----
    # variants 沿用 platform 层默认 ["debug", "release"]。
    #   radxa-cubie-a7a-default-{debug,release}
    #     →  板出厂裸机：HDMI 直出 + 板载 AC101B 音频，不挂屏（不启用
    #        meizu-e3-panel 包 / 不编 sec_ts+sgm37604a / 不加 panel overlay）。
    #   radxa-cubie-a7a-meizu-e3-bringup-{debug,release}
    #     →  挂载魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）。同一硬件特性
    #        包 meizu-e3-panel 跨 SoC 复用（rock5b=RK3588 → 本板=A733）：
    #        OOT 驱动 sec_ts/sgm37604a 零改动，仅 panel overlay 按 sunxi 显示栈
    #        重写。包 opt-in 与 panel default overlay 收编进 :meizu-e3-bringup
    #        条件键（见下方 +packages / +default_overlays）。
    "products": ["default", "meizu-e3-bringup"],
    # ---- 魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）----
    # 仅 meizu-e3-bringup product 启用 meizu-e3-panel 硬件特性包；default 裸机
    # 不挂屏、不带这些 OOT 驱动。屏自带 SGM37604A I2C 背光芯片（@0x36 挂 twi2，
    # 与载板无关），故 opt-in 同时选 sec_ts 触摸 + sgm37604a 背光两个 OOT 驱动，
    # 与 rock5b 一致。
    "+packages:meizu-e3-bringup": [
        {"name": "meizu-e3-panel", "drivers": ["sec_ts", "sgm37604a"]},
    ],
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
        # meizu-e3-panel 的 panel overlay 由 packages 机制注入
        # boot.package_overlays（仅 meizu-e3-bringup product 启用包时注入）。
        # 在此声明为默认应用，开机即点亮屏（extlinux fdtoverlays）。
        # default 裸机不挂屏，不带这条 overlay。
        "+default_overlays:meizu-e3-bringup": [
            "sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo",
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
