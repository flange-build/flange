// Neons Core3566 NanoB 板级配置：声明设备树、产品变体和板载硬件策略。
// Neons Core3566 Nano B (RK3566) 板级配置
local product = std.extVar('product');

{
  board: 'neons-core3566-nanob',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],
  packages: ['rockchip-multimedia'] +
            (if product == 'desktop' then ['ubuntu-desktop'] else []),
  sources+: {
    'rockchip-kernel': {
      url: 'https://github.com/flange-build/kernel.git',
      branch: 'linux-6.1-stan-rkr5.1',
      commit: 'e62b45adc7f89f5c8ea1918960b8c78e7c97ebf5',
    },
  },
  kernel+: {
    device_tree+: { name: 'rk3566-neons-core-wavesharecm4-nano-b' },
  },
}
