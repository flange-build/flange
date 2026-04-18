"""Allwinner A733 (allwinnera733) 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "allwinnera733",
    "flash_tool": "dd",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        "packages": [
            "systemd", "systemd-sysv", "dbus", "network-manager",
            "iputils-ping", "iproute2", "openssh-server", "sudo",
            "bash", "ca-certificates", "locales",
        ],
        "custom_packages": ["adbd"],
    },
    "+rootfs": {
        "+packages:debug": ["gdb", "strace", "tcpdump", "valgrind"],
    },
}
