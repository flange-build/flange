"""RK3566 SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3566",
    "arch": "aarch64",
    "rkbin": {
        "ini_prefix": "RK3566",
        "trust_ini_prefix": "RK3568",
    },
    "bootloader": {
        "defconfig": "rk3568_defconfig",
    },
    "kernel": {
        "defconfig": "rockchip_linux_defconfig",
        "dts_dir": "rockchip",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        "entries": [
            {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
            {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
            {"name": "userdata", "offset": "0x240000", "size": "remaining", "type": "ext4"},
        ],
    },
}
