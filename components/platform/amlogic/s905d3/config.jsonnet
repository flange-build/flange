// Amlogic S905D3 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// Amlogic S905D3 (SM1 family) SoC 配置 -- SoC overlay
//
// VIM3L / aml-s905d3-cc / 等 S905D3 板共用本 SoC 配置。S905D3 是 Cortex-A55
// quad-core，属 SM1 family（与 S905X3 / S905Y3 同代），mainline u-boot 自
// v2019.10 起就支持，主线 kernel 自 5.10 起含 meson-sm1-*.dts。
//
// FIP 工具链：S905D3 复用 G12A 加密工具（aml_encrypt_g12a，SM1 是 G12A
// 派生），LibreELEC/amlogic-boot-fip 仓库内 g12a.inc 是 family-level
// include，每个 board 子目录自带 Makefile 引用它。Board 子目录名
// （如 "khadas-vim3l"）由 board config 的 bootloader.fip_board_dir 声明。
{
  platform: 'amlogic',
  soc: 's905d3',
  // vendor 是 dts 子目录名（与 Linux 主线 dts 路径约定一致），device-tree-
  // overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/overlays/<stem>.dts。
  // 对 amlogic 平台与 platform 同名。
  vendor: 'amlogic',
  sources+: {
    'u-boot-s905d3': {
      // 命名仓库：多组件共享同一次 clone
      url: 'https://github.com/u-boot/u-boot.git',
      // mainline LTS 标签。v2024.10 已含 khadas-vim3l_defconfig（自
      // v2019.10 起）+ Generic Distro Boot（CONFIG_BOOTSTD_DEFAULTS
      // / CONFIG_BOOTMETH_EXTLINUX）支持。
      branch: 'v2024.10',
    },
    'linux-s905d3': {
      url: 'https://github.com/torvalds/linux.git',
      // mainline 6.12 LTS（支持到 2030）。含完整 SM1 / VIM3L 支持：
      // UART_AO / eMMC HS200 / GbE r8169 / SDIO（接 AP6398S WiFi）/
      // I²C / SPI / USB host / Mali-G31 panfrost。首版 GPU/HDMI/VPU
      // 不启用（详见 proposal Non-Goals），但相关驱动 in-tree 备用。
      branch: 'v6.12',
    },
    'amlogic-boot-fip': {
      // LibreELEC 维护的 Amlogic FIP blobs 聚合仓库，board-organized
      // （非 family-organized）。VIM3L 在 khadas-vim3l/ 子目录，含完整
      // blob 集 + aml_encrypt_g12a 工具 + Makefile（include ../g12a.inc）+
      // build-fip.sh（顶层入口脚本）。
      url: 'https://github.com/LibreELEC/amlogic-boot-fip.git',
      branch: 'master',
    },
  },
  bootloader+: {
    source: { name: 'u-boot-s905d3' },
    // defconfig 是 list 形式，按序合并：先应用 base defconfig，再叠加
    // fragment。flange_fastboot.config fragment 由 AmlogicBootloaderBuilder
    // 在 configure 阶段写入 configs/，启用 fastboot gadget（mainline
    // khadas-vim3l_defconfig 默认只开 DFU，不开 fastboot；我们的 flash
    // 流程需要 fastboot）。
    // FIP 工具：SM1 family 复用 G12A 加密工具（不是 aml_encrypt_sm1，
    // LibreELEC 仓库内不存在该名称）。工具二进制在每个 board 子目录下
    // 都有一份；bootloader builder 通过 fip_board_dir 定位，board Makefile
    // 自行 include ../g12a.inc，无需额外 family 配置字段。
    fip_tool: 'aml_encrypt_g12a',
  },
  kernel+: {
    source: { name: 'linux-s905d3' },
    defconfig: ['defconfig'],
    // mainline arm64 generic defconfig 已含 VIM3L 全部首版所需驱动：
    // MESON_GX_MMC / DWC_ETH_QOS / BRCMFMAC / BT_HCIUART / BT_BCM /
    // MESON_SARADC / MESON_GPIO 等。无需 fragment。
    // GUD（USB Display）host 驱动通过统一 kernel.config 显式启用，公共
    // renderer 将其写入末尾 flange_overrides.config，不混入 defconfig。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree+: { directory: 'amlogic' },
  },
  boot+: {
    // Device Tree Overlay 按来源拆分：overlays.intree 由 kernel make 编译；
    // overlays.vendor 来自外部仓库。Amlogic 当前没有 vendor overlay，保持空数组。
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // console=ttyAML0 是 mainline meson_uart 驱动注册的 UART_AO 设备名
    // （非标准 ttyS）。earlycon 不带地址段时由 stdout-path 自动派生
    // （meson-sm1.dtsi 的 chosen.stdout-path = "serial0"）。
    kernel_args: 'earlycon console=ttyAML0,115200n8 loglevel=7',
  },
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      // 与 rk3566 user area 布局同形（不含 idbloader/uboot raw 分区，
      // 因 Amlogic BootROM 走 eMMC hw boot0 而非 user area）。
      // 顺序：boot → recovery → rootfs；recovery 紧随 boot 便于维护工具
      // 固定偏移找到。
      { name: 'boot', offset: '0x40', size: '0x20000', type: 'ext4' },
      { name: 'recovery', offset: '0x20040', size: '0x100000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x120040', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },
}
