// 野火鲁班猫 3 V2（LubanCat-3-v2，RK3576；RTC 由 i2c2 移至 i2c3）板级配置。
// 公共产品、包与账号策略见 config/embedfire-lubancat.libsonnet；
// rk3576-lubancat-3-v2.dts 位于 flange-kernel linux-6.1-stan-rkr5.1（同步自野火 lbc-develop-6.1）。
local lubancat = import 'config/embedfire-lubancat.libsonnet';

lubancat.board('embedfire-lubancat-3-v2', 'rk3576', 'rk3576-lubancat-3-v2')
