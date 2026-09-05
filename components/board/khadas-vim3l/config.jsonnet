// Khadas VIM3L 板级配置：声明 SM1 身份、构建入口和板载硬件策略。
local product = std.extVar('product');
local common = import 'config/khadas-vim3-common.libsonnet';

{
  board: 'khadas-vim3l',
  soc: 's905d3',
  platform: 'amlogic',
  products: common.products,
  variants: common.variants,
  packages: if product == 'desktop' then ['ubuntu-desktop'] else [],

  sources+: common.sources,
  kernel+: {
    config+: common.kernelConfig,
    // mainline v6.12，compatible = "khadas,vim3l", "amlogic,sm1"。
    device_tree+: { name: 'meson-sm1-khadas-vim3l' },
  },
  bootloader+: {
    defconfig: ['khadas-vim3l_defconfig', 'flange_fastboot.config'],
    // LibreELEC/amlogic-boot-fip 内的 VIM3L 专属 blob 目录。
    fip_board_dir: 'khadas-vim3l',
  },
  boot+: {
    overlays+: {
      // 默认打开 40-pin header 上的 SPICC1 用户态接口。
      board: ['vim3l-spidev-spicc1.dtbo'],
      enabled: ['vim3l-spidev-spicc1.dtbo'],
    },
  },

  // 首版通过 KEY1 + USB-C MaskROM 重刷，不交付 recovery 分区。
  recovery+: common.recovery,
  partitions: common.partitions,
  rootfs+: {
    packages+: common.rootfsPackages,
    extra_firmware+: common.extraFirmware,
  },
}
