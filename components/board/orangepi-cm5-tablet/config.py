"""OrangePi CM5 Tablet (RK3588S) 板级配置

首版交付范围：**console + WiFi/BT 硬件就绪**，与 [[orangepi-cm4]] / [[radxa-rock5b]]
/ [[orangepi-5-plus]] 三板「不点屏」惯例对齐。Tablet 形态特有外设——DSI LCD
（rkr5.1 已含 ``rk3588s-orangepi-cm5-tablet-lcd.dtsi``）、触屏控制器、电池/充电
PMIC、MIPI CSI 相机（``-tablet-camera{1,2,3}.dtsi``）—— 全部不在首版范围，靠
dts 默认 disabled 自然屏蔽。

承担两项额外职责：

1. RK3588S SoC 通路（``components/platform/rockchip/rk3588s/config.py``）首次原生
   实板验证——之前仅 RK3582 通过 ``radxa-rock5c-lite`` 共享 dts 路径覆盖。
2. AP6256（Ampak 模组、Broadcom BCM4345C5 die）在 RK3588S 上的可用性证明。
   WiFi/BT 链路与 ``orangepi-cm4`` **完全同源**：固件三件套来自 radxa-pkg/
   radxa-firmware 仓，驱动走 in-tree Rockchip bcmdhd
   （``drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/``）。

板级 patch 仅一份：``patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch``
（逐字节复用 cm4 同名 patch）—— 启用 ``-DFW_AMPAK_PATH="\"brcm\""``，让驱动按
``/lib/firmware/brcm/<file>`` 查 AP6256 固件，与 ``+extra_firmware`` 部署路径
对齐。**不**移植 cm4 0001（dtsi bootargs，dts 路径不通用）与 0003（NPU disable，
cm5-tablet 上 NPU 状态未验，apply 阶段 dmesg 判断后视情起独立 change）。
"""

BOARD = {
    "board": "orangepi-cm5-tablet",
    "soc": "rk3588s",
    "platform": "rockchip",
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已含完整 rk3588s-orangepi-cm5-tablet.dts
        # 及配套 -tablet-lcd.dtsi / -tablet-camera{1,2,3}.dtsi（dts 默认 disabled
        # 状态使首版自然屏蔽）。
        "dts": "rk3588s-orangepi-cm5-tablet",
        # 不声明 oot_sources / +oot_modules：AP6256 走 SoC 层 kernel.defconfig
        # fragment 链启用的 in-tree Rockchip bcmdhd，与 cm4 同路径。
    },
    # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全锁定，默认
    # 用户 flange/flange 入 sudo group。
    # 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
    # rk3588_defconfig。RK3588 / RK3588S 同 die 同 BootROM，u-boot 阶段无差异；
    # 若 apply 阶段 SPL 无 UART 输出 / DDR init 失败，备胎是切到 radxa-pkg
    # u-boot 已有的 radxa-cm5-io-rk3588s_defconfig，最后才考虑 patch 新 defconfig
    # （见 change design Risk R1）。
    #
    # 板级 dtso 与 boot.board_overlays 一律不携带：SoC 层已切 mainline panthor
    # 驱动，dts 自带 ``arm,mali-valhall-csf`` compatible 可直接绑 panthor；
    # tablet 形态外设留待后续独立 change。
    "rootfs": {
        # AP6256 三件套（BCM4345C5 chipset）：
        #   - fw_bcm43456c5_ag.bin  WiFi 主固件，Rockchip bcmdhd CONFIG_BCMDHD_AUTO_SELECT
        #                           按 chip-id 拼名后实际加载文件
        #   - nvram_ap6256.txt      NVRAM 校准参数
        #   - BCM4345C5.hcd         BT patchram (btbcm)
        # 完整复用 orangepi-cm4 同名字段；驱动到固件路径的对齐由
        # patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch 保证
        # （driver 拼接 brcm/ 子目录 = +extra_firmware 部署的 brcm/ 子目录）。
        "+extra_firmware": [
            {
                "name": "radxa",
                "repo": "https://github.com/radxa-pkg/radxa-firmware",
                "branch": "main",
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    "brcm/fw_bcm43456c5_ag.bin",
                    "brcm/nvram_ap6256.txt",
                    "brcm/BCM4345C5.hcd",
                ],
                "dest": "lib/firmware",
            },
        ],
    },
}
