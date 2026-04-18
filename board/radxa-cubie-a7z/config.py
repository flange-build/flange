"""Radxa Cubie A7Z (Allwinner A733) 板级配置"""

BOARD = {
    "board": "radxa-cubie-a7z",
    "soc": "a733",
    "platform": "allwinner",
    "kernel": {
        "dts": "sun60i-a733-cubie-a7z",
    },
    "kernel_device": {
        "board_dts_path": "configs/cubie_a7z/linux-5.15/board.dts",
    },
    "bootloader": {
        "target": "radxa-cubie-a7z",
    },
    "rootfs": {
        "root_password": "1234",
    },
}
