"""平台无关的 rootfs 基线配置。"""

ROOTFS = {
    "rootfs": {
        "package_sets": {
            "base": [
                "systemd", "systemd-sysv", "dbus", "network-manager",
                "iputils-ping", "iproute2", "openssh-server", "sudo",
                "bash", "ca-certificates", "locales",
                "cloud-guest-utils", "gdisk", "e2fsprogs", "util-linux",
                "python3", "kmod", "wpasupplicant", "usbutils",
                "net-tools", "systemd-timesyncd", "btop",
            ],
            "debug": ["gdb", "strace", "tcpdump", "valgrind"],
            "release": [],
        },
        "package_set": ["base"],
        "+package_set:debug": ["debug"],
        "+package_set:release": ["release"],
    },
}
