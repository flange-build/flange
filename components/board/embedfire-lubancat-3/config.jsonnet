// 野火鲁班猫 3（LubanCat-3，RK3576）板级配置。
// 公共产品、包与账号策略见 config/embedfire-lubancat.libsonnet；
// rk3576-lubancat-3.dts 位于 flange-kernel linux-6.1-stan-rkr5.1（同步自野火 lbc-develop-6.1）。
local lubancat = import 'config/embedfire-lubancat.libsonnet';
local common = import 'config/rockchip.libsonnet';

lubancat.board('embedfire-lubancat-3', 'rk3576', 'rk3576-lubancat-3') + {
  // M.2 槽位插 RTL8852BE WiFi6+BT5.2 网卡：rkr5.1 in-tree rtw89 不含 8852B
  // 子驱动（mainline 6.2 才合入），与 ROCK 5B 相同走 rkwifibt vendor OOT 驱动；
  // BT 走 in-tree btusb-rtl，只需部署 rtl_bt 固件。
  sources+: {
    rkwifibt: { url: 'https://github.com/radxa/rkwifibt.git', branch: 'develop' },
  },
  kernel+: {
    oot_sources: { rkwifibt: { source: { name: 'rkwifibt' } } },
    oot_modules+: [common.rtl8852beModule],
  },
  rootfs+: {
    extra_firmware+: [common.rtl8852beFirmware],
  },
}
