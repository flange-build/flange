// 野火鲁班猫（EmbedFire LubanCat）系列共享配置：集中定义各板相同的产品、
// 包与开发期账号策略，board 层只声明身份、SoC 与设备树。
//
// 设备树来自 flange-kernel linux-6.1-stan-rkr5.1（平台层 rockchip-kernel），
// 由野火官方 LubanCat/kernel lbc-develop-6.1 同步而来。板载无 WiFi/BT 模组
// （无线走 M.2/PCIe 扩展），首版不带 OOT 驱动与 firmware；bootloader、GPU
// fragment、console 与分区布局均沿用 SoC 层 generic 配置（eMMC 启动）。
local product = std.extVar('product');

{
  board(name, soc, dtb):: {
    board: name,
    soc: soc,
    platform: 'rockchip',
    products: ['default', 'desktop'],
    variants: ['debug', 'release'],
    packages: ['rockchip-multimedia'] +
              (if product == 'desktop' then ['ubuntu-desktop'] else []),
    kernel+: {
      device_tree+: { name: dtb },
    },
    rootfs+: {
      // ubuntu-base 默认 root 锁定；与其他 rockchip bring-up 板一致，开发期
      // 设 root 口令便于串口调试（默认 flange/flange 用户仍可 SSH）。
      root_password: '1234',
    },
  },
}
