"""Rockchip 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "rockchip",
    "flash_tool": "upgrade_tool",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rkbin": {
        "repo": "https://github.com/radxa/rkbin",
        "branch": "develop-v2024.10",
    },
    "rootfs": {
        "packages": [
            "systemd", "systemd-sysv", "dbus", "network-manager",
            "iputils-ping", "iproute2", "openssh-server", "sudo",
            "bash", "ca-certificates", "locales",
        ],
        # recoveryctl 需要在 normal 系统中也能调用（`recoveryctl reboot recovery`
        # 用来从 normal 进入 recovery，由 `flange recovery enter` 通过 ADB
        # 触发）；flash/backup 子命令会在 normal 模式下硬性拒绝，安全。
        "custom_packages": ["adbd", "recoveryctl"],
    },
    "+rootfs": {
        "+packages:debug": ["gdb", "strace", "tcpdump", "valgrind"],
    },
    # Recovery 维护系统（独立 rootfs，独立分区）默认开启；
    # 如某个板子存储紧张可在 board 配置覆盖 enabled: False。
    # SoC/board 层需在 partitions.entries 中提供 recovery 分区，
    # 否则 validate_config 会拒绝配置。
    "recovery": {
        "enabled": True,
        "packages": [
            "systemd", "systemd-sysv", "udev", "dbus",
            "python3-minimal",
            "util-linux", "e2fsprogs", "dosfstools",
            "parted", "gptfdisk",
            "zstd", "coreutils",
            "ca-certificates",
        ],
        "custom_packages": ["adbd", "recoveryctl"],
        "transport": "adb",
        # raw 类型分区由设备端按 type 自动保护，这里补充 recovery 自身。
        "protected_partitions": ["recovery"],
    },
}
