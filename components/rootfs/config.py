"""平台无关的 rootfs 基线配置。"""

ROOTFS = {
    "rootfs": {
        # 跨平台默认开发期 root 密码。不设此字段时 ubuntu-base tarball 默认
        # /etc/shadow 中 root 字段为 "*"（锁定态），串口与 SSH 都无法登录；
        # adb 不走 PAM 登录所以 adbd 仍能 root shell，掩盖问题直到第一次
        # 真正去串口登录才暴露（如 ROCK 5B 首版适配踩过这个坑）。
        # 板级 BOARD["rootfs"]["root_password"] 可覆盖此值；生产镜像应改为
        # 强随机密码或迁 SSH key 体系。
        "root_password": "1234",
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
