"""Amlogic S905D3 (SM1 family) SoC 配置 -- 第二层继承

VIM3L / aml-s905d3-cc / 等 S905D3 板共用本 SoC 配置。S905D3 是 Cortex-A55
quad-core，属 SM1 family（与 S905X3 / S905Y3 同代），mainline u-boot 自
v2019.10 起就支持，主线 kernel 自 5.10 起含 meson-sm1-*.dts。

FIP 工具链：S905D3 复用 G12A 加密工具（aml_encrypt_g12a，SM1 是 G12A
派生），LibreELEC/amlogic-boot-fip 仓库内 g12a.inc 是 family-level
include，每个 board 子目录自带 Makefile 引用它。Board 子目录名
（如 "khadas-vim3l"）由 board config 的 bootloader.fip_board_dir 声明。
"""

SOC = {
    "platform": "amlogic",
    "soc": "s905d3",
    "arch": "aarch64",
    # vendor 是 dts 子目录名（与 Linux 主线 dts 路径约定一致），device-tree-
    # overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/overlays/<stem>.dts。
    # 对 amlogic 平台与 platform 同名。
    "vendor": "amlogic",
    # 命名仓库：多组件共享同一次 clone
    "repos": {
        "u-boot": {
            "repo": "https://github.com/u-boot/u-boot.git",
            # mainline LTS 标签。v2024.10 已含 khadas-vim3l_defconfig（自
            # v2019.10 起）+ Generic Distro Boot（CONFIG_BOOTSTD_DEFAULTS
            # / CONFIG_BOOTMETH_EXTLINUX）支持。
            "branch": "v2024.10",
        },
        "linux": {
            "repo": "https://github.com/torvalds/linux.git",
            # mainline 6.12 LTS（支持到 2030）。含完整 SM1 / VIM3L 支持：
            # UART_AO / eMMC HS200 / GbE r8169 / SDIO（接 AP6398S WiFi）/
            # I²C / SPI / USB host / Mali-G31 panfrost。首版 GPU/HDMI/VPU
            # 不启用（详见 proposal Non-Goals），但相关驱动 in-tree 备用。
            "branch": "v6.12",
        },
        "amlogic-boot-fip": {
            # LibreELEC 维护的 Amlogic FIP blobs 聚合仓库，board-organized
            # （非 family-organized）。VIM3L 在 khadas-vim3l/ 子目录，含完整
            # blob 集 + aml_encrypt_g12a 工具 + Makefile（include ../g12a.inc）+
            # build-fip.sh（顶层入口脚本）。
            "repo": "https://github.com/LibreELEC/amlogic-boot-fip.git",
            "branch": "master",
        },
    },
    "bootloader": {
        "from_repo": "u-boot",
        # defconfig 是 list 形式，按序合并：先应用 base defconfig，再叠加
        # fragment。flange_fastboot.config fragment 由 AmlogicBootloaderBuilder
        # 在 configure 阶段写入 configs/，启用 fastboot gadget（mainline
        # khadas-vim3l_defconfig 默认只开 DFU，不开 fastboot；我们的 flash
        # 流程需要 fastboot）。
        "defconfig": ["khadas-vim3l_defconfig", "flange_fastboot.config"],
        # FIP 工具：SM1 family 复用 G12A 加密工具（不是 aml_encrypt_sm1，
        # LibreELEC 仓库内不存在该名称）。工具二进制在每个 board 子目录下
        # 都有一份；bootloader builder 通过 fip_board_dir 定位。
        "fip_tool": "aml_encrypt_g12a",
        # family include 文件，AmlogicBootloaderBuilder 调 build-fip.sh 时
        # 间接依赖（每个 board Makefile 内 `include ../g12a.inc`）。本字段
        # 留作显式可见的 family 标识。
        "fip_family_inc": "g12a.inc",
        # board-specific 字段：fip_board_dir（amlogic-boot-fip 仓库内 board
        # 子目录名）由 board config 声明，不在 SoC 层。
    },
    "kernel": {
        "from_repo": "linux",
        # mainline arm64 generic defconfig 已含 VIM3L 全部首版所需驱动：
        # MESON_GX_MMC / DWC_ETH_QOS / BRCMFMAC / BT_HCIUART / BT_BCM /
        # MESON_SARADC / MESON_GPIO 等。无需 fragment。
        # GUD（USB Display）host 驱动全平台默认启用；defconfig 改 list 形态以
        # 追加 raw option（由基类 _resolve_defconfig_targets 聚合进
        # flange_inline.config，区别于 fragment 文件名）。
        "defconfig": ["defconfig", "CONFIG_DRM_GUD=y"],
        "dts_dir": "amlogic",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
    },
    "boot": {
        # Device Tree Overlay 两类来源：
        # - dtb_overlays：内核源码树内 (in-tree)，由 kernel make 编译
        # - vendor_overlays：来自外部 overlay 仓库（amlogic 暂无对应 vendor
        #   仓库，留空字段保持架构一致性）
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # console=ttyAML0 是 mainline meson_uart 驱动注册的 UART_AO 设备名
        # （非标准 ttyS）。earlycon 不带地址段时由 stdout-path 自动派生
        # （meson-sm1.dtsi 的 chosen.stdout-path = "serial0"）。
        "kernel_args": "earlycon console=ttyAML0,115200n8 loglevel=7",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 与 rk3566 user area 布局同形（不含 idbloader/uboot raw 分区，
        # 因 Amlogic BootROM 走 eMMC hw boot0 而非 user area）。
        # 顺序：boot → recovery → rootfs；recovery 紧随 boot 便于维护工具
        # 固定偏移找到。
        "entries": [
            {"name": "boot",     "offset": "0x40",     "size": "0x20000",  "type": "ext4"},
            {"name": "recovery", "offset": "0x20040",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",   "offset": "0x120040", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
