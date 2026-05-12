"""RK3582 SoC 配置 -- 第二层继承

RK3582 是 RK3588 的 binned die（同 silicon、同封装外形为 RK3588S BGA0698）：
两颗 Cortex-A76 与 Mali-G610 GPU 在 silicon fuse 阶段被禁用，剩余
4× Cortex-A55 + 2× Cortex-A76、NPU、VPU、RGA、ISP、显示控制器全部保留。
BootROM 标识与 RK3588/RK3588S 完全一致，u-boot / rkbin / kernel branch 沿用
rk3588s 占位即可，本配置主要差异点：

- ``kernel.defconfig`` 不引入 ``rk3588_panthor.config`` —— GPU 已熔断，不需
  要切换到 mainline panthor，rockchip_linux_defconfig 自带的 BSP mali_kbase
  在 rk3582 上 probe 会因 fuse 失败而 fail-soft，不影响 userspace boot。
- ``rootfs.extra_firmware`` 不部署 ``mali_csffw.bin`` —— 没 GPU 不需要
  CSF firmware，``arm/mali/arch10.8/`` 目录留空可避免 panthor 模块（若被
  误装）尝试加载。
- ``rootfs.+extra_debs`` 仍部署 mpp / RGA / GStreamer-rockchip 整套多媒体
  加速栈：VPU / RGA / 显示控制器物理存在，与 RK3588S 同 ABI，rkr5.1 BSP 上
  实测可用（H.264/H.265 8K 解码、4K 编码、RGA 2D 加速全部命中硬件路径）。

board 层（如 radxa-rock5c-lite）应通过 kernel.dts 指定具体 dts；当 dts 文件
名复用 RK3588S 板（如 ``rk3588s-rock-5c``）时，dts 内的 GPU / 大核 cluster
节点会被 BSP 默认启用，但因 fuse 锁定运行时 probe 失败，不影响系统启动。
"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3582",
    "arch": "aarch64",
    "vendor": "rockchip",
    "rkbin": {
        # RK3582 / RK3588S / RK3588 同 die 同 BootROM，rkbin 字段全部一致。
        "ini_prefix": "RK3588",
        "trust_ini_prefix": "RK3588",
        "mkimage_chip": "rk3588",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        # 与 RK3566/RK3588/RK3588S SoC 同分支（详见 rk3566/config.py 的注释）。
        "branch": "next-dev-v2026.01",
        # SoC 层 generic 默认值；RK3582 板级 defconfig 在 v2026.01 上完整可用
        # （rock-5c-rk3588s_defconfig 与 rock-5c-lite 共用），真适配时由 board
        # 层覆盖。本 SoC 通路占位仍走 generic rk3588_defconfig（同 die，
        # u-boot 阶段对禁用大核/GPU 不敏感）。
        "defconfig": "rk3588_defconfig",
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        # 与 RK3588/RK3588S 同 branch（详见 rk3588/config.py 的注释）。
        "branch": "linux-6.1-stan-rkr5.1",
        # 与 RK3588/RK3588S 共用基础 defconfig，但去掉 panthor fragment
        # ——RK3582 GPU 熔断，无需切 panthor 也无需关 mali_kbase。
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            # 启用 mainline panel-mipi-dbi-spi 驱动 (CONFIG_DRM_PANEL_MIPI_DBI=m)，
            # 用于 Rock 5C Lite + Waveshare 1.3" LCD HAT (ST7789VM SPI 屏) 等
            # 板级 SPI display；fragment 由 RockchipKernelBuilder 在
            # configure() 阶段写到 arch/arm64/configs/panel_mipi_dbi.config。
            "panel_mipi_dbi.config",
        ],
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # 不部署 mali-csf firmware —— GPU 已熔断（RK3588/RK3588S 配置中的
        # arm/mali/arch10.8/mali_csffw.bin 在此略去）。
        # 多媒体加速栈整套保留：VPU / RGA / 显示控制器物理存在，rk3588 deb
        # 通用，详见 rk3588/config.py 的逐 deb 注释。
        "+extra_debs": [
            {
                "name": "rockchip-mpp",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/rockchip-mpp_1.3.9_arm64.deb",
                "sha256": "f1bc1826e054821bf268eb6fb31958695909f35807e25445dced1b6e4fc2a9e2",
            },
            {
                "name": "rockchip-mpp-dev",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/rockchip-mpp-dev_1.3.9_arm64.deb",
                "sha256": "fcaa62bb7d35b028ea01b904e9c928c222d89bdf5b0eacc448e0d043215ec7fd",
            },
            {
                "name": "librga2",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/librga2_2.1.0_arm64.deb",
                "sha256": "ec2343f42a323bf518c1bb4f36dbfd94349fad24a3e1a9c620e47aedd6ee2b54",
            },
            {
                "name": "librga-dev",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/librga-dev_2.1.0_arm64.deb",
                "sha256": "ac6530b803e3606394006a93d60998846ca318c65df2ec57bd3b6e68ad2b73d4",
            },
            {
                "name": "libgstreamer1.0-0",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/libgstreamer1.0-0_1.24.2_arm64.deb",
                "sha256": "23cd246e5c5472936c596d314ca8e9e887cd323a586c22b90224467198262e69",
            },
            {
                "name": "gstreamer1.0-plugins-base",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-base_1.24.2_arm64.deb",
                "sha256": "c736643550e5b9922c5020281d96e39cfee82b42de996484f330e10c2e5fe409",
            },
            {
                "name": "gstreamer1.0-plugins-good",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-good_1.24.2_arm64.deb",
                "sha256": "5324e07b23a90510024454b96eb98e6c64c76c85e54e15d6a2c9077c2239033b",
            },
            {
                "name": "gstreamer1.0-plugins-bad",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-bad_1.24.2_arm64.deb",
                "sha256": "6854bb699b4bb7fcc4fe23e51306c6c57c2e69dea3aaa9776cba537f6d46c3c2",
            },
            {
                "name": "gstreamer1.0-rockchip",
                "url": "https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-rockchip_1.0-1_arm64.deb",
                "sha256": "4e8a6fdb195d3acd7b16c59c81b3b9a263d16324753fba4f700b2217d5139c32",
            },
        ],
    },
    "boot": {
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # RK3582 调试串口同 RK3588S：UART2，1.5M baud。
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 沿用 RK3588 / RK3588S 布局；真适配 RK3582 板时按板存储调整。
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
