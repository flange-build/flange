"""TSpi RK3566 板级配置"""

BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    "kernel": {
        "dts": "tspi-rk3566-user-v10-ext39-linux",
    },
    "bootloader": {
        "commit": "3c60a711e61015c1a61247837afbeaa85bd7fbf2",
    },
    "rootfs": {
        "root_password": "1234",
        "extra_firmware": [
            {
                "name": "armbian",
                "repo": "https://github.com/armbian/firmware",
                "branch": "master",
                "files": [
                    "brcm/brcmfmac43430-sdio.bin",
                    "brcm/brcmfmac43430-sdio.txt",
                    "brcm/brcmfmac43430-sdio.clm_blob",
                ],
                "dest": "lib/firmware",
            }
        ],
    },
}
