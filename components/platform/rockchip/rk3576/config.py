"""RK3576 SoC 配置 -- 第二层继承

与 RK3588 对齐：复用同一 argon BSP 内核 linux-6.1-stan-rkr5.1 与 base
rockchip_linux_defconfig（该分支为全 SoC BSP 树，已自带 RK3576 全套 dts、
驱动、Kconfig）。差异仅在 GPU fragment：RK3576 GPU 为 Mali-G52（Bifrost），
走 mainline panfrost（panfrost.config，由 RockchipKernelBuilder.
_write_panfrost_fragment 生成，与 rk3566/rk3568 共用），而非 RK3588 的
panthor（Valhall-CSF）。
panfrost 无需 CSF firmware，故 rootfs 不带 mali-csf extra_firmware。
"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3576",
    "arch": "aarch64",
    "vendor": "rockchip",
    "rkbin": {
        "ini_prefix": "RK3576",
        "trust_ini_prefix": "RK3576",
        # RK3576 自有 die，BootROM 识别为 rk3576（不与 rk3568/rk3588 共标签）。
        "mkimage_chip": "rk3576",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        # 与其他 rockchip SoC 统一用 next-dev-v2026.01（rk3576 UFS 控制器驱动仍是
        # ufs-rockchip.c）。SoC 层用 generic rk3576_defconfig（DT=rk3576-evb）；板级（如
        # radxa-rock-4d）须在 board 层覆盖为对板 defconfig（rock-4d-spi-rk3576_defconfig，
        # DT=rk3576-rock-4d-spi），否则产「错板」proper u-boot。详见 openspec
        # selfbuild-rk3576-spi-image。
        "branch": "next-dev-v2026.01",
        "defconfig": "rk3576_defconfig",
        # RK3576 的 idbloader 必须用 boot_merger 按 RK3576MINIALL.ini 装配（含引导级
        # rk3576_boost），而非 mkimage -T rksd —— RK35xx 里 RK3576 唯一不走 mkimage
        # （armbian rockchip64_common.inc 对 BOOT_SOC==rk3576 专走 boot_merger 分支）。
        # bootloader.py 据此分流：拾取 boot_merger 的 [OUTPUT] IDB_PATH 产物为
        # idbloader.img。SoC 级声明（与存储介质无关，所有 RK3576 板通用）。详见
        # openspec selfbuild-rk3576-spi-image。
        "idbloader_method": "boot_merger",
        # 注：u-boot 用 gcc-10 编（base ComponentBuilder.CROSS 全平台默认）——老 rockchip
        # u-boot 在 gcc-13 下二进制布局会让 RK3576 UFS DMA 读 buffer 落坏地址 → 上板崩，
        # 2026-06 逐次上板 + 反汇编坐实。详见 openspec selfbuild-rk3576-spi-image。
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        # 与 RK3588 同分支 rkr5.1（全 SoC BSP 树，含 rk3576 dts + panfrost 源码）。
        "branch": "linux-6.1-stan-rkr5.1",
        # base defconfig 与 RK3588 一致；GPU fragment 用 panfrost（对位 RK3588
        # 的 rk3588_panthor.config）。case_insensitive_fix.config 由基类生成，
        # macOS 大小写不敏感 FS 上禁用 netfilter 冲突模块。
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "panfrost.config",
        ],
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # Rockchip 多媒体加速栈（VPU + RGA + GStreamer-rockchip 插件），与
        # rk3566/rk3588 SoC 用同一组 chip-agnostic deb（rockchip-mpp 用户态按
        # chip 分发）。GPU 用户态走 panfrost（mesa gallium，随 ubuntu-base apt），
        # 不在此 deb 集合内；panfrost 无 CSF firmware 依赖，故不带 mali-csf。
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
        # RK3576 调试串口在 UART0（rk3576-linux.dtsi 的 fiq-debugger
        # rockchip,serial-id = <0>，serial0 = &uart0）。loglevel=4 (KERN_WARNING)
        # 与 RK3588 一致，仅保留 WARNING 及以上上 console。
        "kernel_args": "console=ttyS0,1500000 loglevel=4",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 沿用 RK3588 布局。顺序：boot → recovery → rootfs。首次升级整盘刷写。
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
