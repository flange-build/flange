// Neons Core3566 NanoB 板级配置：声明设备树、产品变体和板载硬件策略。
// Neons Core3566 Nano B (RK3566) 板级配置
{
  board: 'neons-core3566-nanob',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default'],
  variants: ['debug', 'release'],
  sources+: {
    'rockchip-kernel': {
      url: 'ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git',
      branch: 'linux-6.1-stan-rkr5.1',
      commit: 'e62b45adc7f89f5c8ea1918960b8c78e7c97ebf5',
    },
    'rockchip-u-boot': {
      url: 'https://github.com/radxa/u-boot',
      branch: 'next-dev-v2026.01',
      // next-dev-v2026.01 tip 当前 commit。原 pin 3c60a711 上的
      // arch/arm/mach-rockchip/decode_bl31.py 仍是 ``#!/usr/bin/env python2``
      // 旧版（容器无 python2 → 静默失败 → 无 bl31_0x*.bin →
      // u-boot.its 缺 atf-N 节点 → u-boot.itb 不含 BL31 → SPL 跳 U-Boot
      // 后无 EL3 secure monitor，串口在 ``Jumping to U-Boot(0x00a00000)``
      // 之后立刻挂）。上游已把 shebang 改 python3 并加 ``BL31`` env 支持，
      // 同分支同期 tspi-rk3566 / rp-pro-rk3568-h 都已在更新的 pin 上稳定，
      // neons 跟齐到 next-dev-v2026.01 tip。
      commit: '2742c75cc288537cdd720391a557b7dcf035b240',
    },
  },
  kernel+: {
    device_tree+: { name: 'rk3566-neons-core-wavesharecm4-nano-b' },
  },
}
