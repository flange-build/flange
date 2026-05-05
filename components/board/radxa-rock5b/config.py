"""Radxa ROCK 5B (RK3588) 板级配置"""

BOARD = {
    "board": "radxa-rock5b",
    "soc": "rk3588",
    "platform": "rockchip",
    "kernel": {
        # argon BSP linux-6.1-stan-rkr4.1-buildroot 已包含 rk3588-rock-5b.dts。
        "dts": "rk3588-rock-5b",
    },
    # 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
    # rk3588_defconfig，走 Generic Distro Boot（extlinux.conf）流程，
    # 与 RK3566 板保持一致。
    #
    # 不用 rock-5b-rk3588_defconfig（虽然存在于 next-dev-v2024.10）的原因：
    # 该 defconfig 是 radxa 为 Android/multi-OS 调的，启用了 androidboot
    # 风格固定 bootargs，绕过 extlinux APPEND，导致 root=PARTUUID 被截
    # 成短形（如 614e0000-0000）且 console 强制切到 ttyFIQ0。
    # generic rk3588_defconfig 在 v2024.10 上完整支持 ROCK 5B 板级初始化
    # （eMMC/HS400/PMIC/USB/PCIe 全部 probe 通过），实测可用。
}
