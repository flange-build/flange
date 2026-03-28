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
    },
    "rootfs": {
        "base": "noble",
    },
}
