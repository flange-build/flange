"""Amlogic S905Y2 (G12A family) SoC 配置 -- 第二层继承

Radxa Zero 1.5 / 等 S905Y2 板共用本 SoC 配置。S905Y2 是 Cortex-A53
quad-core，属 G12A family（与 S905X2 / S905D2 同代），mainline u-boot 自
v2019.10 起含 radxa-zero_defconfig，主线 kernel 自 5.7 起含
meson-g12a-radxa-zero.dts（v6.12 LTS 支持完整）。

FIP 工具链：S905Y2 是 G12A native（不像 SM1 是 G12A 派生），加密工具
即 aml_encrypt_g12a，LibreELEC/amlogic-boot-fip 仓库内 g12a.inc 是
family-level include，每个 board 子目录自带 Makefile 引用它（radxa-zero/
Makefile 实测 `include ../g12a.inc`）。Board 子目录名（如 "radxa-zero"）
由 board config 的 bootloader.fip_board_dir 声明。

与 s905d3（SM1）的差异：U-Boot defconfig（radxa-zero_defconfig）、kernel
DTS（board 层声明 meson-g12a-radxa-zero）、FIP board 目录均不同；但 G12A
与 SM1 同走 aml_encrypt_g12a + g12a.inc + ttyAML0 console，故 SoC 层结构
与 s905d3 高度同形。
"""

SOC = {
    "platform": "amlogic",
    "soc": "s905y2",
    "arch": "aarch64",
    # vendor 是 dts 子目录名（与 Linux 主线 dts 路径约定一致），device-tree-
    # overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/overlays/<stem>.dts。
    # 对 amlogic 平台与 platform 同名。
    "vendor": "amlogic",
    # 命名仓库：多组件共享同一次 clone
    "repos": {
        "u-boot": {
            "repo": "https://github.com/u-boot/u-boot.git",
            # mainline LTS 标签。v2024.10 已含 radxa-zero_defconfig（自
            # v2019.10 起）。注：radxa-zero_defconfig 实测仅开 DFU_RAM，
            # 不开 fastboot —— flange flash 流程需要的 fastboot gadget 由
            # flange_fastboot.config fragment 叠加启用（见 bootloader.defconfig）。
            "branch": "v2024.10",
        },
        "linux": {
            "repo": "https://github.com/torvalds/linux.git",
            # mainline 6.12 LTS（支持到 2030）。含完整 G12A / Radxa Zero 支持：
            # UART_AO（ttyAML0）/ eMMC HS200（sd_emmc_c）/ SDIO（sd_emmc_a 接
            # AW-CM256SM WiFi，brcmf wifi@1 compatible "brcm,bcm4329-fmac"）/
            # BT serdev（uart_A 子节点 compatible "brcm,bcm43438-bt" 自动绑定）/
            # USB（dwc3）/ Mali-G31 panfrost。首版 GPU/HDMI/VPU 不启用
            # （详见 proposal Non-Goals），但相关驱动 in-tree 备用。
            "branch": "v6.12",
        },
        "amlogic-boot-fip": {
            # LibreELEC 维护的 Amlogic FIP blobs 聚合仓库，board-organized
            # （非 family-organized）。Radxa Zero 在 radxa-zero/ 子目录，含完整
            # blob 集（bl2/bl30/bl301/bl31 + DDR firmware）+ aml_encrypt_g12a
            # 工具 + Makefile（include ../g12a.inc）+ build-fip.sh（顶层入口）。
            "repo": "https://github.com/LibreELEC/amlogic-boot-fip.git",
            "branch": "master",
        },
    },
    "bootloader": {
        "from_repo": "u-boot",
        # defconfig 是 list 形式，按序合并：先应用 base defconfig，再叠加
        # fragment。flange_fastboot.config fragment 由 AmlogicBootloaderBuilder
        # 在 configure 阶段从 components/platform/amlogic/s905y2/patches/
        # bootloader/ 复制进 configs/，启用 fastboot gadget（mainline
        # radxa-zero_defconfig 默认只开 DFU_RAM，不开 fastboot；我们的 flash
        # 流程需要 fastboot）。
        "defconfig": ["radxa-zero_defconfig", "flange_fastboot.config"],
        # FIP 工具：G12A native 加密工具。工具二进制在每个 board 子目录下
        # 都有一份；bootloader builder 通过 fip_board_dir 定位。
        "fip_tool": "aml_encrypt_g12a",
        # family include 文件，AmlogicBootloaderBuilder 调 build-fip.sh 时
        # 间接依赖（radxa-zero/Makefile 内 `include ../g12a.inc`）。本字段
        # 留作显式可见的 family 标识。
        "fip_family_inc": "g12a.inc",
        # board-specific 字段：fip_board_dir（amlogic-boot-fip 仓库内 board
        # 子目录名）由 board config 声明，不在 SoC 层。
    },
    "kernel": {
        "from_repo": "linux",
        # mainline arm64 generic defconfig 已含 Radxa Zero 全部首版所需驱动：
        # MESON_GX_MMC / BRCMFMAC / BT_HCIUART / BT_BCM / MESON_SARADC /
        # MESON_GPIO / DWC3 USB 等。无需 fragment。
        # GUD（USB Display）host 驱动全平台默认启用；defconfig 改 list 形态以
        # 追加 raw option（由基类 _resolve_defconfig_targets 聚合进
        # flange_inline.config，区别于 fragment 文件名）。
        "defconfig": ["defconfig", "CONFIG_DRM_GUD=y"],
        "dts_dir": "amlogic",
        # board 层声明 kernel.dts = "meson-g12a-radxa-zero"。
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
        # （非标准 ttyS）。Radxa Zero DTS aliases serial0 = &uart_AO，
        # stdout-path = "serial0:115200n8"。
        "kernel_args": "earlycon console=ttyAML0,115200n8 loglevel=7",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 与 s905d3 同形的 SoC 层通用布局（boot → recovery → rootfs）。
        # 不含 idbloader/uboot raw 分区，因 Amlogic BootROM 走 eMMC hw boot0
        # 而非 user area。recovery 默认随平台层 enabled=True 保留；小板
        # （如 Radxa Zero）在 board 层 enabled=False 并收敛分区表。
        "entries": [
            {"name": "boot",     "offset": "0x40",     "size": "0x20000",  "type": "ext4"},
            {"name": "recovery", "offset": "0x20040",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",   "offset": "0x120040", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
