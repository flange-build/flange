"""TSpi RK3566 板级配置"""

TSPI_RK3566_BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    "dts": "tspi-rk3566-user-v10-ext39-linux",
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "d425e02d22a75945fc79a10e736c1de76ca615c8",
        "defconfig": "rockchip_linux_defconfig",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-buildroot",
        "commit": "3c60a711e61015c1a61247837afbeaa85bd7fbf2",
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
