// 野火鲁班猫 5 V2（LubanCat-5 V2，RK3588；PWM/背光、fusb302 中断与 PCIe 使能脚调整）板级配置。
// 公共产品、包与账号策略见 config/embedfire-lubancat.libsonnet；
// rk3588-lubancat-5-v2.dts 位于 flange-kernel linux-6.1-stan-rkr5.1（同步自野火 lbc-develop-6.1）。
local lubancat = import 'config/embedfire-lubancat.libsonnet';

lubancat.board('embedfire-lubancat-5-v2', 'rk3588', 'rk3588-lubancat-5-v2')
