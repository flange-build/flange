// Amlogic A311D SoC 层配置：声明 G12B 芯片级源码、Kconfig 和启动能力。
//
// A311D 是 2×Cortex-A53 + 4×Cortex-A73 的 G12B SoC。它与 S905D3/SM1
// 共用 Amlogic G12 系列构建/刷写策略，但必须使用 G12B FIP 工具和 DTB。
{
  platform: 'amlogic',
  soc: 'a311d',
  vendor: 'amlogic',

  sources+: {
    'u-boot-a311d': {
      // mainline v2024.10 含 khadas-vim3_defconfig 与标准 extlinux bootflow。
      url: 'https://github.com/u-boot/u-boot.git',
      branch: 'v2024.10',
    },
    'linux-a311d': {
      // mainline v6.12 含 meson-g12b-a311d-khadas-vim3.dts。
      url: 'https://github.com/torvalds/linux.git',
      branch: 'v6.12',
    },
    'amlogic-boot-fip': {
      // khadas-vim3 目录提供专属 BL2/DDR blobs 与 aml_encrypt_g12b。
      url: 'https://github.com/LibreELEC/amlogic-boot-fip.git',
      branch: 'master',
    },
  },

  bootloader+: {
    source: { name: 'u-boot-a311d' },
    fip_tool: 'aml_encrypt_g12b',
  },
  kernel+: {
    source: { name: 'linux-a311d' },
    defconfig: ['defconfig'],
    // GUD（Generic USB Display，通用 USB 显示）沿用全平台显式配置。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree+: { directory: 'amlogic' },
  },
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // UART_AO 由 mainline meson_uart 注册为 ttyAML0。
    kernel_args: 'earlycon console=ttyAML0,115200n8 loglevel=7',
  },
}
