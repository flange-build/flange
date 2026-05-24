"""Allwinner A733 (sun60iw2p1) SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "allwinnera733",
    "soc": "a733",
    "arch": "aarch64",
    # vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
    # 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
    # overlays/<stem>.dts。allwinnera733 平台对应 vendor 子目录是 "allwinner"。
    "vendor": "allwinner",
    # 命名仓库：多组件共享同一次 clone
    "repos": {
        "linux-a733": {
            "repo": "https://github.com/radxa-pkg/linux-a733.git",
            "branch": "main",
            "recurse_submodules": True,
        },
        "u-boot-aw2501": {
            "repo": "https://github.com/radxa-pkg/u-boot-aw2501.git",
            "branch": "main",
            "recurse_submodules": True,
        },
    },
    "kernel": {
        "from_repo": "linux-a733",
        "subpath": "src",
        # bsp_defconfig 包含 CONFIG_AW_BSP / CONFIG_ARCH_SUN60IW2 /
        # CONFIG_AW_UART_NG 等关键 SoC 驱动；必须合并否则 UART 等外设不工作
        "defconfig": ["defconfig", "bsp_defconfig", "radxa.config",
                      "radxa_custom.config", "aic8800_wlan.config",
                      "usb_gadget.config", "panel_mipi_dbi.config",
                      "case_insensitive_fix.config"],
        "dts_dir": "allwinner",
        # out-of-tree 内核模块：源码在内核树外，使用独立构建系统编译
        # 每个声明包含：
        #   dir         — 构建入口目录，支持 {kernel_src} 模板变量
        #   label       — 显示名
        #   make_args   — 传给 make 的参数，支持 {kernel_src} 模板变量
        #   ko_pattern  — glob 模式匹配编译产物 .ko，支持 {kernel_src} 模板变量
        #   pre_build   — 编译前 shell 命令（如临时补丁），支持 {kernel_src}
        #   post_build  — 编译后 shell 命令（如恢复补丁，无论成败都执行），支持 {kernel_src}
        "oot_modules": [
            {
                "dir": "{kernel_src}/bsp/modules/gpu/img-bxm/linux/rogue_km/build/linux/sunxi_linux",
                "label": "img-bxm (PowerVR BXM GPU)",
                "make_args": [
                    "BUILD=release",
                    "ARCH=arm64",
                    "KERNELDIR={kernel_src}",
                    "KERNEL_CC=aarch64-linux-gnu-gcc",
                    "KERNEL_LD=aarch64-linux-gnu-ld",
                    "KERNEL_NM=aarch64-linux-gnu-nm",
                    "KERNEL_OBJCOPY=aarch64-linux-gnu-objcopy",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                ],
                "ko_pattern": [
                    "{kernel_src}/bsp/modules/gpu/img-bxm/linux/rogue_km/"
                    "binary_sunxi_linux_nulldrmws_release/"
                    "target_aarch64/kbuild/pvrsrvkm.ko",
                ],
            },
        ],
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # PowerVR DDK（下方 xserver-xorg-img-bxm）的运行时依赖：该 deb 的
        # control 没有 Depends 字段，dpkg -i 又不解析依赖，ubuntu-base 也不带，
        # 故必须在此显式 apt 安装，否则 libEGL.so.1 因 libdrm.so.2 等缺失而
        # 根本无法 dlopen（实板 ldd 验证缺 12 个 .so）。这些都是低层库（libdrm /
        # xcb / x11-xcb / xshmfence / wayland），非 GL 实现，不与 PVR EGL 冲突。
        "+packages": [
            "libdrm2",
            "libxcb1", "libxcb-dri2-0", "libxcb-dri3-0", "libxcb-randr0",
            "libxcb-xfixes0", "libxcb-present0", "libxcb-sync1",
            "libx11-xcb1", "libxshmfence1",
            "libwayland-server0", "libwayland-client0",
        ],
        # 以下 deb 不在 Ubuntu 官方源中，通过 URL 直下 + sha256 校验安装
        # — 来自 radxa-pkg/allwinner-prebuilt-extra
        "+extra_debs": [
            {
                "name": "xserver-xorg-img-bxm",
                "url": "https://github.com/radxa-pkg/allwinner-prebuilt-extra/releases/download/0.1.10/xserver-xorg-img-bxm_1.21.1-2_arm64.deb",
                "sha256": "c8e606db1abdea40a5b97f7905ea86901b50c5fe1b76a55356ab70dde3304c3a",
            },
            {
                # Allwinner CedarC VE 硬件解码用户态库（libcedarc v2.0）：
                # OMX 组件、VDecoder/VEncoder API、各格式解码插件（H.264/H.265/
                # VP9/VP8/MPEG2/MPEG4/MJPEG/AVS/AVS2）、demo 程序
                "name": "libcedarc-dev",
                "url": "https://github.com/radxa-pkg/allwinner-prebuilt-extra/releases/download/0.1.10/libcedarc-dev_2.0.0_arm64_new-f7cf8b546b8a5337c1ea19451972b3f1.deb",
                "sha256": "24a5d7669cc382f79ec51ba6139be0ef3a54fc54d8843dbe150a4426d3dc6a99",
            },
        ],
    },
    "kernel_bsp": {
        "from_repo": "linux-a733",
        "subpath": "bsp",
        "dtsi_dir": "configs/linux-5.15",
    },
    "kernel_device": {
        "from_repo": "linux-a733",
        "subpath": "device-a733",
        "bsp_defconfig_path": "configs/default/linux-5.15/bsp_defconfig",
    },
    "bootloader": {
        "from_repo": "u-boot-aw2501",
        "toolchain_tarball": "gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz",
        "toolchain_url": "https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz",
        "riscv_tarball": "riscv64-elf-x86_64-20201104.tar.gz",
        "riscv_url": "https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/riscv64-elf-x86_64-20201104.tar.gz",
    },
    "boot": {
        "dtb_filename": "sunxi.dtb",
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
        # Allwinner BSP 内核使用自定义 earlyprintk=sunxi-uart（非标准 earlycon）
        # CONFIG_AW_UART_NG 驱动注册设备名为 ttyAS（非标准 ttyS），
        # 所以 console 必须是 ttyAS0 才能从 earlycon 平滑切换
        "kernel_args": "earlyprintk=sunxi-uart,0x2500000 console=ttyAS0,115200 loglevel=8 initcall_debug=0",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 顺序：boot_package → boot → recovery → rootfs；与 Rockchip 平台一致，
        # recovery 紧随 boot，rootfs 拉到末尾。首版仅做静态预留，A733 端的 image
        # dd 与 flash-config 落地由 §5.2 / §5.4 决定。
        "entries": [
            {"name": "boot0",         "offset": "0x100",    "size": "0x700",    "type": "raw"},
            {"name": "boot0_ufs",     "offset": "0x810",    "size": "0x700",    "type": "raw"},
            {"name": "boot_package",  "offset": "0x6000",   "size": "0x2000",   "type": "raw"},
            {"name": "boot",          "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
            {"name": "recovery",      "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",        "offset": "0x128000", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
