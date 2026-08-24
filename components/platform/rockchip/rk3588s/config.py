"""RK3588S SoC 配置 -- 第二层继承

RK3588S 是 RK3588 的精简版（同 die，少 PCIe lanes / 显示通道 / USB 接口）。
u-boot 阶段（UART/eMMC/USB）行为与 RK3588 等价，故所有字段照搬 rk3588。

本配置作为 SoC 平面通路占位 — 当 ROCK 5A / 5C / 5D / CM5 等 RK3588S 实板
适配时，由 board 层以 ``bootloader.defconfig`` 覆盖为板级 defconfig（如
``rock-5a-rk3588s_defconfig``），无需在 SoC 层改动。
"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3588s",
    "arch": "aarch64",
    "vendor": "rockchip",
    "rkbin": {
        # RK3588 / RK3588S 同 die 同 BootROM，rkbin 字段全部一致。
        "ini_prefix": "RK3588",
        "trust_ini_prefix": "RK3588",
        "mkimage_chip": "rk3588",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        # 与 RK3566/RK3588 SoC 同分支（详见 rk3566/config.py 的注释）。
        "branch": "next-dev-v2026.01",
        # SoC 层 generic 默认值；RK3588S 板级 defconfig 在 v2026.01 上完整
        # 可用（rock-5a-rk3588s_defconfig / rock-5c-rk3588s_defconfig 等），
        # 真适配 RK3588S 板时由 board 层覆盖。本 SoC 通路占位仍走 generic
        # rk3588_defconfig（RK3588 与 RK3588S 同 die，u-boot 阶段无差异）。
        "defconfig": "rk3588_defconfig",
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        # 与 RK3588 同 branch（详见 rk3588/config.py 的注释）。
        "branch": "linux-6.1-stan-rkr5.1",
        # 同 RK3588 — fragment 详见 rk3588/config.py 注释。
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "rk3588_panthor.config",
            # GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
            # USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
            "CONFIG_DRM_GUD=y",
        ],
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "sha256": "04207713ece899c3740823d33690441ad3a7f0ded1101aca744e2b0f37ac7ff2",
        "extra_firmware": [
            # 同 RK3588 — Mali-G610 CSF firmware 见 rk3588/config.py 注释。
            {
                "name": "mali-csf",
                "source": "kernel",
                "repo_subdir": "drivers/gpu/arm/bifrost",
                "files": ["mali_csffw.bin"],
                "dest": "lib/firmware/arm/mali/arch10.8",
            },
        ],
    },
    "boot": {
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # RK3588S 调试串口同样在 UART2。
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 沿用 RK3566/RK3588 布局；真适配 RK3588S 板时按板存储调整。
        "entries": [
            {"name": "idbloader", "offset": "0x40",     "size": "0x2000",   "type": "raw"},
            {"name": "uboot",     "offset": "0x4000",   "size": "0x2000",   "type": "raw"},
            {"name": "boot",      "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
            {"name": "recovery",  "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",    "offset": "0x128000", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
