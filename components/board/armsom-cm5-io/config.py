"""ArmSoM CM5 IO (RK3576) 板级配置

首版裸机支持：核心目标是打通 RK3576 平台构建链——可构建出镜像、可启动、
GPU 走 mainline panfrost（Mali-G52 Bifrost）。板载 dts
``rk3576-armsom-cm5-io`` 已在 argon BSP linux-6.1-stan-rkr5.1 树内（含
``&gpu { status = "okay"; mali-supply = ...; }``，无需板级 overlay 使能）。

WiFi/BT（add-armsom-cm5-io-wifi-bt 变更）：板载模组 BW3752-50B1（Iton，
基于 Broadcom BCM43752，2T2R combo，等价 AP6275S）——WiFi 走 SDIO 接
Rockchip OOT bcmdhd、BT 走 UART4(ttyS4)。dtsi 已声明 wireless-wlan /
wireless-bluetooth / &sdio / &uart4 节点；本 board 层补三件套固件
（rootfs.+extra_firmware，落到 /lib/firmware/brcm/）+ 一条 kernel patch
（dts wifi_chip_type rtl8852bs→ap6275s）。bcmdhd 默认 CONFIG_BCMDHD_FW_PATH
已是 /lib/firmware/brcm/（Kconfig default，无 cm4 那种 Android 路径污染），
固件实际请求文件名由 SDIO OTP/module-name 机制决定，以实机 dmesg 为准对齐；
不复刻 cm4 的 FW_AMPAK_PATH patch（该 patch 在 REQUEST_FW=n 下是 no-op）。
不预装 BT 用户态栈。

其余暂不纳入验收的外设（HDMI/MIPI 屏/摄像头/音频/NPU/VPU）均不在 board
层显式配置，留待后续独立变更。不携带板级 dtso / board_overlays。
不覆盖 SoC 层 GPU/defconfig/bootloader 字段（沿用 rk3576 generic）。
"""

BOARD = {
    "board": "armsom-cm5-io",
    "soc": "rk3576",
    "platform": "rockchip",
    # variants 沿用 platform 层默认 ["debug", "release"]；单 product default。
    # 笛卡尔积：armsom-cm5-io-default-debug / -release。
    "products": ["default"],
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已包含 rk3576-armsom-cm5-io.dts。
        # GPU panfrost 路线由 SoC 层 rk3576_panfrost.config 决定，board 不覆盖。
        "dts": "rk3576-armsom-cm5-io",
    },
    "rootfs": {
        # ubuntu-base 默认 root 锁定（/etc/shadow 为 *），不设此字段则 root
        # 无法登录。值与其他 rockchip 板（radxa-rock5b / tspi-rk3566）一致 1234，
        # 方便首版 bring-up 切板调试（spec 首版验收要求 ssh 登录）。
        "root_password": "1234",
        # BCM43752 / AP6275S 三件套（与 orangepi-cm4 的 AP6256 同仓同机制）：
        #   - fw_bcm43752a2_ag.bin  SDIO WiFi 主固件，Rockchip bcmdhd
        #                           CONFIG_BCMDHD_AUTO_SELECT 按 chip-id 拼名后实际加载
        #   - nvram_ap6275s.txt     NVRAM 校准参数
        #   - BCM4362A2.hcd         BT patchram（btbcm；BCM43752 的 BT 子系统标识）
        # source 默认 "repo"，由 SourceManager.ensure_extra_firmware 独立 clone 到
        # .build/sources/extra-firmware/radxa/。bcmdhd 默认固件目录已是
        # /lib/firmware/brcm/（CONFIG_BCMDHD_FW_PATH Kconfig default），三件套
        # 落点与之对齐；实际请求文件名以实机 dmesg 为准（必要时加 symlink）。
        "+extra_firmware": [
            {
                "name": "radxa",
                "repo": "https://github.com/radxa-pkg/radxa-firmware",
                "branch": "main",
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    "brcm/fw_bcm43752a2_ag.bin",
                    "brcm/nvram_ap6275s.txt",
                    "brcm/BCM4362A2.hcd",
                ],
                "dest": "lib/firmware",
            },
        ],
    },
}
