"""Radxa ROCK 5B (RK3588) 板级配置"""

BOARD = {
    "board": "radxa-rock5b",
    "soc": "rk3588",
    "platform": "rockchip",
    # ---- 多 product 维度（屏幕模组） ----
    # variants 沿用 platform 层默认 ["debug", "release"]。
    # 笛卡尔积:
    #   radxa-rock5b-default-debug / -release
    #     →  板出厂裸机配置：仅板载 RTL8852BE WiFi/BT，不挂屏（不启用
    #        meizu-e3-panel 包 / 不编 sec_ts+sgm37604a OOT 驱动 / 不加 panel
    #        overlay）。
    #   radxa-rock5b-meizu-e3-bringup-debug / -release
    #     →  挂载魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）的 product。
    #        meizu-e3-panel 硬件特性包、panel default overlay 统一收编进
    #        :meizu-e3-bringup 条件键（见下方 +packages / +default_overlays）。
    #        其余配置（kernel、bootloader、firmware）与 default 共用。
    "products": ["default", "meizu-e3-bringup"],
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已包含 rk3588-rock-5b.dts。
        "dts": "rk3588-rock-5b",
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
                    # 关闭 PHL/RTW 调试日志总开关：vendor Makefile 默认
                    # CONFIG_RTW_DEBUG=y（L154），连带把 PHL/RTW 两套日志默认
                    # 等级烧成 4=INFO（CONFIG_RTW_LOG_LEVEL / _PHL_LOG_LEVEL，
                    # L157-158），导致扫描期 [DBG_RFK]/[SCAN]/[cmd_scan]/
                    # MSG_EVT_*/scan_ch_ready_cb 等 INFO 级日志持续刷屏。
                    # 命令行赋值优先级高于 Makefile 内 `=`，置 n 后
                    # `-DCONFIG_RTW_DEBUG` 不再注入，phl_debug.h / rtw_debug.h
                    # 里所有 PHL_*/RTW_* 宏退化为 no-op，日志全部编译期消除
                    # （.ko 更小、零运行开销）。两套 log_level 符号的定义与全部
                    # 引用都一致包在 #ifdef CONFIG_RTW_DEBUG 内（rtw_cfg.c
                    # L1372/1745、wifi_regd.c L760），关掉不会产生未定义符号。
                    "CONFIG_RTW_DEBUG=n",
                ],
                "ko_pattern": [
                    "{rkwifibt_src}/drivers/rtl8852be/8852be.ko",
                ],
            },
        ],
    },
    # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全锁定
    # (root_password=None + disable_root_login=True)，默认用户 flange/flange
    # 入 sudo group。如需开放 root 或改用户在此处加 rootfs 块覆盖。
    # 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
    # rk3588_defconfig，走 Generic Distro Boot（extlinux.conf）流程，
    # 与 RK3566 板保持一致。
    #
    # 不用 rock-5b-rk3588_defconfig（虽然存在于 next-dev-v2026.01）的原因:
    # 该 defconfig 是 radxa 为 Android/multi-OS 调的，启用了 androidboot
    # 风格固定 bootargs，绕过 extlinux APPEND，导致 root=PARTUUID 被截
    # 成短形（如 614e0000-0000）且 console 强制切到 ttyFIQ0。
    # generic rk3588_defconfig 在 v2026.01 上完整支持 ROCK 5B 板级初始化
    # （eMMC/HS400/PMIC/USB/PCIe 全部 probe 通过），实测可用。
    #
    # ---- 魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）----
    # 仅 meizu-e3-bringup product 启用 meizu-e3-panel 硬件特性包；default 裸机
    # 不挂屏，不带这些 OOT 驱动。这块屏自带 SGM37604A I2C 背光芯片（@0x36 挂
    # i2c6，与 rock-5c 同），**不**走 rock5b 板载 MP3302/pwm-backlight。故 opt-in
    # 同时选 sec_ts 触摸 + sgm37604a 背光两个 OOT 驱动。
    "+packages:meizu-e3-bringup": [
        {"name": "meizu-e3-panel", "drivers": ["sec_ts", "sgm37604a"]},
    ],
    "boot": {
        # 板私有 overlay：源文件位于 components/board/radxa-rock5b/dtso/<stem>.dtso，
        # 由 device-tree-overlay 组件用 cpp+dtc 编译为 <stem>.dtbo，打到 boot 分区
        # /dtbs/rockchip/overlay/。
        "board_overlays": [
            # mali-valhall-compat：把 GPU 节点 compatible 从 "arm,mali-valhall-csf"
            # 改回 "arm,mali-valhall"，让 BSP mali_kbase fork 能绑（其 of_match
            # 表只识别 -valhall 不识别 -valhall-csf）。
            #
            # 当前主线已切到 mainline panthor 驱动（详见 SoC config 的 panthor
            # fragment），dts 原始 compatible (arm,mali-valhall-csf) 直接被 panthor
            # of_match 命中，**不需要**这个 overlay。dtbo 仍编进 boot 分区作为
            # emergency rollback：万一 panthor 起不来需要紧急切回 mali_kbase，
            # 可手动改 /boot/extlinux/extlinux.conf 加 fdtoverlays 启用。
            "rk3588-rock-5b-mali-valhall-compat.dtbo",
        ],
        # meizu-e3-panel 的 panel overlay 由 packages 机制注入 boot.package_overlays
        # （仅 meizu-e3-bringup product 启用包时注入）。在此声明为默认应用，开机即
        # 点亮屏（extlinux fdtoverlays）。default 裸机不挂屏，不带这条 overlay。
        "+default_overlays:meizu-e3-bringup": [
            "rk3588-rock-5b-meizu-e3-panel.dtbo",
        ],
    },
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
