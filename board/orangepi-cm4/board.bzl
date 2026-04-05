"""Orange Pi CM4 (RK3566) 板级配置"""

ORANGEPI_CM4_BOARD = {
    "board": "orangepi-cm4",
    "soc": "rk3566",
    "platform": "rockchip",
    "dts": "rk3566-orangepi-cm4-base",
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "",
        "defconfig": "rockchip_linux_defconfig",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "commit": "",
        "defconfig": "rk3568_defconfig",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
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
        "custom_packages": ["adbd"],
    },
}
