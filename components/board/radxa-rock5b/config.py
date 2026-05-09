"""Radxa ROCK 5B (RK3588) 板级配置"""

BOARD = {
    "board": "radxa-rock5b",
    "soc": "rk3588",
    "platform": "rockchip",
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
    # 不用 rock-5b-rk3588_defconfig（虽然存在于 next-dev-v2024.10）的原因:
    # 该 defconfig 是 radxa 为 Android/multi-OS 调的，启用了 androidboot
    # 风格固定 bootargs，绕过 extlinux APPEND，导致 root=PARTUUID 被截
    # 成短形（如 614e0000-0000）且 console 强制切到 ttyFIQ0。
    # generic rk3588_defconfig 在 v2024.10 上完整支持 ROCK 5B 板级初始化
    # （eMMC/HS400/PMIC/USB/PCIe 全部 probe 通过），实测可用。
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
        # default_overlays 留空：panthor 路径下不需要默认应用任何板级 overlay。
        "default_overlays": [],
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
