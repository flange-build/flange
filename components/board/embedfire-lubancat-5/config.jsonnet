// 野火鲁班猫 5（LubanCat-5，RK3588）板级配置。
// 公共产品、包与账号策略见 config/embedfire-lubancat.libsonnet；
// rk3588-lubancat-5.dts 位于 flange-kernel linux-6.1-stan-rkr5.1（同步自野火 lbc-develop-6.1）。
local lubancat = import 'config/embedfire-lubancat.libsonnet';

lubancat.board('embedfire-lubancat-5', 'rk3588', 'rk3588-lubancat-5') + lubancat.schedutil + {
  // M.2 槽位插 Intel BE200 Wi-Fi 7 网卡
  packages+: ['intel-be200'],
}
