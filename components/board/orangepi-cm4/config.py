"""Orange Pi CM4 (RK3566) 板级配置。

本轮交付范围：仅保证默认 lunch target 可启动 + WiFi/BT 硬件就绪，**不带任何
DSI 屏适配**（屏适配单独立项推进）。

- WiFi/BT 模块：板载 AP6256（Ampak 模组，封装 Broadcom BCM4345C5），WiFi 走
  SDIO 接 Rockchip OOT bcmdhd、BT 走 UART 接 hci_uart/btbcm。dtsi 已声明
  ``wifi_chip_type="ap6256"``、SDIO/BT 节点齐全；rootfs 三件套固件从
  ``radxa-pkg/radxa-firmware`` 仓拉到 ``/lib/firmware/brcm/``（与 tspi-rk3566
  同源）。三条 board 私有 kernel patch 修 bootargs / 固件路径 / NPU 启动
  panic，见 ``patches/kernel/``。
- DSI 屏：当前不接、不适配。dtsi 中 dsi1 默认 disabled，相关 panel / 路由
  节点保持 disabled。若未来接屏需单独开 change 走 board overlay + 必要的
  bridge driver 启用（参见 wiki/log.md 中的踩坑记录）。
"""

BOARD = {
    "board": "orangepi-cm4",
    "soc": "rk3566",
    "platform": "rockchip",
    "kernel": {
        # base.dts 保持空壳（仅 #include rk3566-orangepi-cm4.dtsi）；本轮无 DSI
        # 屏 overlay，dsi1 / panel 节点维持 dtsi 默认 disabled。
        "dts": "rk3566-orangepi-cm4-base",
    },
    "rootfs": {
        # 账号体系沿用 components/rootfs/config.py base 层默认。
        # AP6256 三件套（BCM4345C5 chipset）：
        #   - fw_bcm43456c5_ag.bin  WiFi 主固件，Rockchip bcmdhd CONFIG_BCMDHD_AUTO_SELECT
        #                           按 chip-id 拼名后实际加载文件
        #   - nvram_ap6256.txt      NVRAM 校准参数
        #   - BCM4345C5.hcd         BT patchram (btbcm)
        # source 默认 "repo"，由 SourceManager.ensure_extra_firmware 独立 clone 到
        # .build/sources/extra-firmware/radxa/。
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
