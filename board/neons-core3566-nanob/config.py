"""Neons Core3566 Nano B (RK3566) 板级配置"""

BOARD = {
    "board": "neons-core3566-nanob",
    "soc": "rk3566",
    "platform": "rockchip",
    "kernel": {
        "dts": "rk3566-neons-core-wavesharecm4-nano-b",
        "commit": "e62b45adc7f89f5c8ea1918960b8c78e7c97ebf5",
    },
    "bootloader": {
        "commit": "3c60a711e61015c1a61247837afbeaa85bd7fbf2",
    },
}
