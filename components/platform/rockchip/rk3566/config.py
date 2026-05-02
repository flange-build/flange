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
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "defconfig": "rk3568_defconfig",
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "defconfig": "rockchip_linux_defconfig",
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
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
