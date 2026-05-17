"""OrangePi 5 Plus (RK3588) 板级配置

硬件外设与 [[radxa-rock5b]] 等价（首版验收范围内）：同 SoC（RK3588）、同 PMIC
（RK806）、同 UART2 1500000 调试 console、同 eMMC 启动路径；M.2 E-Key 槽位插
RTL8852BE WiFi6+BT5.2 combo 卡走 rkwifibt OOT 路线，与 ROCK 5B 共用同一驱动栈。
板载特有外设（双 2.5G PCIe RTL8125 网卡、双 HDMI、4-lane MIPI CSI、PCIe Gen3 x4
M-key SSD、RGB LED、PWM 风扇）首版均不显式配置：RTL8125 在 linux-6.1-stan-rkr5.1
已含 r8169 主线驱动自动 probe；其余外设留待后续变更。
"""

BOARD = {
    "board": "orangepi-5-plus",
    "soc": "rk3588",
    "platform": "rockchip",
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已包含 rk3588-orangepi-5-plus.dts。
        "dts": "rk3588-orangepi-5-plus",
        # ---- M.2 E-Key 槽位 RTL8852BE WiFi6+BT5.2 combo 卡支持 ----
        # 走 OOT 路线（rkr5.1 in-tree rtw89 driver 不含 8852BE 子驱动：
        # Kconfig 没有 RTW89_8852B/BE，Makefile 也没引用 rtw8852b/be 源文件，
        # 配套 _rfk/_table 文件缺失。8852BE 是 mainline 6.2 才进的，6.1 LTS
        # 没回移）。直接用 Radxa 维护的 rkwifibt 仓库——内含 vendor 私有
        # WiFi/BT stack（不依赖 mac80211/rtw89），编出 8852be.ko 即可。
        # 板载 BT 驱动走 in-tree btusb（CONFIG_BT_HCIBTUSB=y +
        # CONFIG_BT_HCIBTUSB_RTL=y 在 rockchip_linux_defconfig 已启用）。
        "oot_sources": {
            "rkwifibt": {
                "repo": "https://github.com/radxa/rkwifibt.git",
                # develop 分支跟踪远端最新；cache._mix_kernel_oot_sources
                # 用 git HEAD 触发 kernel 重 build。锁 commit 改成
                # "commit": "<sha>" 即可。
                "branch": "develop",
            },
        },
        "+oot_modules": [
            {
                "dir": "{rkwifibt_src}/drivers/rtl8852be",
                "label": "rtl8852be (rkwifibt vendor driver)",
                "make_args": [
                    "ARCH=arm64",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                    "KSRC={kernel_src}",
                    # M= 指定 OOT 模块源 = 编译目录。Makefile 默认开关
                    # CONFIG_RTL8852B=y + CONFIG_PCI_HCI=y → 输出 8852be.ko
                    "M={rkwifibt_src}/drivers/rtl8852be",
                ],
                "ko_pattern": [
                    "{rkwifibt_src}/drivers/rtl8852be/8852be.ko",
                ],
            },
        ],
    },
    "boot": {
        # 30-pin DSI FPC 板载接口的 HX8399-A 1080×1920 portrait 面板 +
        # GT911 5-point 电容触摸 overlay。默认即应用（写进 extlinux.conf
        # 的 fdtoverlays）。
        # rollback：改 /boot/extlinux/extlinux.conf 去掉 fdtoverlays 一行，
        # 或重刷无此 overlay 的镜像。
        # 接线依据 vendor rk3588-orangepi-5-plus-lcd.dtsi；触摸 cfg blob
        # 通过 board overlay/lib/firmware/goodix_911_cfg.bin 走 _install_overlays
        # 现成 cp -a 机制部署，mainline goodix.c 启动时 request_firmware
        # 拉文件下发。
        "board_overlays": [
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
        ],
        "default_overlays": [
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
        ],
    },
    # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全锁定
    # (root_password=None + disable_root_login=True)，默认用户 flange/flange
    # 入 sudo group。如需开放 root 或改用户在此处加 rootfs 块覆盖。
    # 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
    # rk3588_defconfig，走 Generic Distro Boot（extlinux.conf）流程，
    # 与 RK3566 板及 ROCK 5B 保持一致。
    #
    # 板级 dtso 与 boot.board_overlays 一律不携带：SoC 层已切 mainline panthor
    # 驱动（rk3588_panthor.config fragment + dts 自带 arm,mali-valhall-csf
    # compatible），ROCK 5B 上保留的 mali-valhall-compat emergency rollback
    # dtbo 至今未触发使用，第二块 RK3588 板不再背同款备胎；若未来需要
    # rollback，可一并起独立变更同时补 rock5b 与本板。
    "rootfs": {
        # RTL8852BE BT 部分固件：rkwifibt 仓库 firmware/realtek/RTL8852BE/
        # 提供 ``rtl8852bu_fw`` 和 ``rtl8852bu_config``（命名沿用 USB 接口
        # 历史，内容是 PCIe 卡通用的 BT8852B blob）。in-tree btusb-rtl 驱动
        # 加载路径硬编码 /lib/firmware/rtl_bt/<name>.bin，因此安装时统一
        # 补 .bin 后缀。
        # WiFi 部分固件 baked-in 进 8852be.ko（rkwifibt 编译期 firmware-
        # binary linkage），不需要 /lib/firmware 部署。
        "+extra_firmware": [
            {
                "name": "rkwifibt-rtl8852be",
                "source": "oot:rkwifibt",  # 复用 kernel.oot_sources 已 ensure 的源
                "repo_subdir": "firmware/realtek/RTL8852BE",
                "files": [
                    {"src": "rtl8852bu_fw",     "dest": "rtl8852bu_fw.bin"},
                    {"src": "rtl8852bu_config", "dest": "rtl8852bu_config.bin"},
                ],
                "dest": "lib/firmware/rtl_bt",
            },
        ],
    },
}
