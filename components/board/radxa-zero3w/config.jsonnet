// Radxa ZERO 3W 板级配置：声明设备树、产品变体和板载硬件策略。
// Radxa Zero 3W (RK3566) 板级配置
{
  board: 'radxa-zero3w',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default'],
  variants: ['debug', 'release'],
  kernel+: { device_tree+: { name: 'rk3566-radxa-zero-3w' } },
}
