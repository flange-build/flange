"""TSpi RK3566 板级配置"""

BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    "kernel": {
        "dts": "tspi-rk3566-user-v10-ext39-linux",
    },
    "rootfs": {
        "root_password": "1234",
        "extra_firmware": [
            {
                "name": "radxa",
                "repo": "https://github.com/radxa-pkg/radxa-firmware",
                "branch": "main",
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    "brcm/fw_bcm43438a1.bin",
                    "brcm/nvram_ap6212a.txt",
                    "brcm/bcm43438a1.hcd",
                    "brcm/BCM43430A1.hcd",
                ],
                "dest": "lib/firmware",
            }
        ],
    },
}
