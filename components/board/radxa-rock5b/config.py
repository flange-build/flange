"""Radxa ROCK 5B (RK3588) 板级配置"""

BOARD = {
    "board": "radxa-rock5b",
    "soc": "rk3588",
    "platform": "rockchip",
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已包含 rk3588-rock-5b.dts。
        "dts": "rk3588-rock-5b",
    },
    # rootfs.root_password 由 components/rootfs/config.py base 层默认为 "1234"，
    # 此板无特殊需求继承默认。生产前如需强密码可在此处加 rootfs 块覆盖。
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
}
