"""Radxa Zero 3W (RK3566) 板级配置"""

RADXA_ZERO3W_BOARD = {
    "board": "radxa-zero3w",
    "soc": "rk3566",
    "platform": "rockchip",
    "dts": "rk3566-radxa-zero-3w",
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "defconfig": "rockchip_linux_defconfig",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-buildroot",
        "defconfig": "rk3568_defconfig",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=4",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "packages": [
            "systemd",
            "systemd-sysv",
            "dbus",
            "network-manager",
            "iputils-ping",
            "iproute2",
            "openssh-server",
            "sudo",
            "bash",
            "ca-certificates",
            "locales",
        ],
        "custom_packages": [],
    },
}
