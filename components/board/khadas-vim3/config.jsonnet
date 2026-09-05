// Khadas VIM3 板级配置：声明 A311D 身份、构建入口和板载硬件策略。
local product = std.extVar('product');
local common = import 'config/khadas-vim3-common.libsonnet';

{
  board: 'khadas-vim3',
  soc: 'a311d',
  platform: 'amlogic',
  products: common.products,
  variants: common.variants,
  packages: if product == 'desktop' then ['ubuntu-desktop'] else [],

  sources+: common.sources,
  kernel+: {
    config+: common.kernelConfig,
    // mainline v6.12，compatible 包含 khadas,vim3 / amlogic,a311d / g12b。
    device_tree+: { name: 'meson-g12b-a311d-khadas-vim3' },
  },
  bootloader+: {
    defconfig: ['khadas-vim3_defconfig', 'flange_fastboot.config'],
    // 必须使用 VIM3 专属 G12B blobs，不能复用 VIM3L/SM1 目录。
    fip_board_dir: 'khadas-vim3',
  },
  boot+: {
    overlays+: {
      // 默认打开 40-pin header 上的 SPICC1 用户态接口。
      board: ['vim3-spidev-spicc1.dtbo'],
      enabled: ['vim3-spidev-spicc1.dtbo'],
    },
  },

  // 首版通过 Function 键 + USB-C MaskROM 重刷，不交付 recovery 分区。
  recovery+: common.recovery,
  partitions: common.partitions,
  rootfs+: {
    // BT 由 meson-khadas-vim3.dtsi 的 serdev 节点自动绑定，无需 btattach。
    packages+: common.rootfsPackages,
    extra_firmware+: common.extraFirmware,
  },
}
