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
- AMP：额外提供 amp / amp-rtt 两个 product，cpu3 交给从核固件。Orange Pi CM4
  40pin 未引出 tspi-rk3566 既有 demo 使用的 UART4_M1，故本板 AMP 从核 console
  改用 40pin 可引出的 UART7_M2（GPIO4_A2/TX、GPIO4_A3/RX）。
"""

_AMP_PARTITIONS = {
    "format": "gpt",
    "sector_size": 512,
    "entries": [
        {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
        {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
        {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
        {"name": "recovery", "offset": "0x28000", "size": "0x100000", "type": "ext4"},
        {"name": "amp", "offset": "0x128000", "size": "0x8000", "type": "ext4"},
        {
            "name": "rootfs",
            "offset": "0x130000",
            "size": "remaining",
            "type": "ext4",
            "image_size": "2G",
            "grow_on_first_boot": True,
        },
    ],
}

BOARD = {
    "board": "orangepi-cm4",
    "soc": "rk3566",
    "platform": "rockchip",
    "products": ["default", "amp", "amp-rtt"],
    "amp": {
        "enabled:amp": True,
        "mode:amp": "hal",
        "app:amp": "rk3568_amp_uart7_demo",
        "enabled:amp-rtt": True,
        "mode:amp-rtt": "rt-thread",
        "app:amp-rtt": "rk3568_amp_uart7_rtt_demo",
    },
    "kernel": {
        # base.dts 保持空壳（仅 #include rk3566-orangepi-cm4.dtsi）；本轮无 DSI
        # 屏 overlay，dsi1 / panel 节点维持 dtsi 默认 disabled。
        "dts": "rk3566-orangepi-cm4-base",
        # amp / amp-rtt 共用专用 AMP dts：基础板 dts + rk3568-amp.dtsi +
        # UART7_M2 console + cpu3 摘除 + rpmsg link-id 0x10。
        "dts:amp": "rk3566-orangepi-cm4-amp",
        "dts:amp-rtt": "rk3566-orangepi-cm4-amp",
        "+defconfig:amp": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"],
        "+defconfig:amp-rtt": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"],
    },
    "bootloader": {
        "+defconfig:amp": ["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"],
        "+defconfig:amp-rtt": ["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"],
    },
    "partitions:amp": _AMP_PARTITIONS,
    "partitions:amp-rtt": _AMP_PARTITIONS,
    "boot": {
        # i2c2 切到 m1 引脚组：i2c2_sda_m1=GPIO4_B4 / i2c2_scl_m1=GPIO4_B5。
        # overlay 源自 radxa-overlays（device-tree-overlay 组件统一拉取），
        # rk356x 全系 pinctrl 同源，rk3568- 前缀文件适用于 rk3566；编译为
        # .dtbo 后由 extlinux 挂载。值必须带 .dtbo 后缀（dtb_overlay 校验），
        # 编译时去后缀回仓库取 rk3568-i2c2-m1.dts。
        "vendor_overlays": ["rk3568-i2c2-m1.dtbo"],
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
