"""Rockchip 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "rockchip",
    "flash_tool": "upgrade_tool",
    "arch": "aarch64",
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
    },
    "+rootfs": {
        "+packages:debug": ["gdb", "strace", "tcpdump", "valgrind"],
    },
}
