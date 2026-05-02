"""Allwinner A733 (allwinnera733) 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "allwinnera733",
    "flash_tool": "dd",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        # 同 Rockchip：normal 系统也安装 recoveryctl，便于 ADB 触发模式切换。
        "custom_packages": ["adbd", "recoveryctl", "flange-rootfs-grow"],
    },
    # Recovery 子系统：与 Rockchip 平台等价的默认值。首版主要在 RK3566 上
    # 落地，A733 的 image 端集成（image dd / flash-config）按"静态预留"
    # 处理（详见 §5.2 / §5.4）。boards 可通过 enabled: False 关闭。
    "recovery": {
        "enabled": True,
        "packages": [
            "systemd", "systemd-sysv", "udev", "dbus",
            "python3",
            "util-linux", "e2fsprogs", "dosfstools",
            "parted", "gdisk",
            "zstd", "coreutils",
            "ca-certificates",
        ],
        "custom_packages": ["adbd", "recoveryctl"],
        "transport": "adb",
        "protected_partitions": ["recovery"],
    },
}
