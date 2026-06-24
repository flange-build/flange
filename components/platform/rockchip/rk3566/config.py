"""RK3566 SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3566",
    "arch": "aarch64",
    # vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
    # 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
    # overlays/<stem>.dts。对 rockchip 平台恰好与 platform 同名。
    "vendor": "rockchip",
    "rkbin": {
        "ini_prefix": "RK3566",
        "trust_ini_prefix": "RK3568",
        # mkimage 打包 idbloader 时塞给 BootROM 的 chip 标签。
        # RK3566 与 RK3568 同 die，BootROM 识别为 rk3568。
        "mkimage_chip": "rk3568",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        # next-dev-v2026.01 — Radxa u-boot 当前活跃维护分支。flange 曾因
        # 早期 v2026.01 缺 rock-5b 等 RK3588 板级 defconfig 而 pin 在更早
        # 的 v2024.10；2026 Q1 后 Radxa 已把所有 rock 系列板级 defconfig
        # 回填进 v2026.01。tspi-rk3566 在 v2024.10 上实测 USB OTG configfs
        # gadget 起不来（vendor BSP DTS 与该分支 USB 路径不兼容），整平台
        # 切到 v2026.01 收敛。
        # v2026.01 上游已用 python3 shebang 调 decode_bl31.py，platform 层
        # 旧 0001-decode_bl31-use-python3-shebang.patch 已删除。
        "branch": "next-dev-v2026.01",
        "defconfig": "rk3568_defconfig",
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr5.1",
        # GPU 走 mainline panfrost：RK3566 GPU 为 Mali-G52（Bifrost），dts gpu
        # 节点（rk356x.dtsi gpu@fde60000）compatible 为 arm,mali-bifrost，与
        # panfrost of_match 对位。panfrost.config 由 _write_panfrost_fragment
        # 生成（rk3566/rk3568/rk3576 共用），关闭闭源 mali_kbase 并启用 panfrost。
        "defconfig": [
            "rockchip_linux_defconfig",
            "panfrost.config",
            # GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
            # USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
            "CONFIG_DRM_GUD=y",
        ],
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # Rockchip 多媒体加速栈（VPU + RGA + GStreamer-rockchip 插件），来自
        # CmST0us/rockchip-multimedia-ubuntu release 1.0.0 的 prebuilt deb。
        # 与 rk3588 SoC 用同一组 deb：rockchip-mpp 是用户态 chip 抽象层
        # （内部按 mpp_platform_check 分发 RK3568 vepu540c / vdpu341 与
        # RK3588 vepu120 / vdpu382c），RGA 库与 gstreamer-rockchip 插件均
        # chip-agnostic，noble 24.04 base 自带 gstreamer 1.24.2 上游版本但
        # 缺 gstreamer1.0-rockchip 私有 plugin 且作者打包的 1.24.2 与
        # plugin ABI 锁定，core/plugins-{base,good,bad} 必须用本仓库重打包
        # 保持 ABI 一致。安装顺序：runtime 库 → 开发头 → gstreamer core
        # → plugins → 厂商插件，dpkg -i 一次性传入做依赖 unrolling。
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
        # Device Tree Overlay（设备树覆盖）有两类来源：
        # - dtb_overlays：内核源码树内 (in-tree)，由 kernel make 编译
        # - vendor_overlays：来自 radxa-overlays 仓库，由 device-tree-overlay
        #   组件用 cpp + dtc 编译
        # 两源 basename 必须全局唯一；打包时平铺到 /dtbs/<vendor>/overlay/。
        # default_overlays 是 extlinux 默认启动时按顺序应用的子集，
        # 可跨两源引用，无需前缀。
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 顺序：boot → recovery → rootfs；recovery 紧随 boot 便于维护工具固定
        # 偏移找到。userdata 移除，rootfs 直接拉到 emmc 末尾（remaining）。
        # 首次升级到该布局必须整盘刷写。
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
