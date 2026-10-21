// 野火鲁班猫 3（LubanCat-3，RK3576）板级配置。
// 公共产品、包与账号策略见 config/embedfire-lubancat.libsonnet；
// rk3576-lubancat-3.dts 位于 flange-kernel linux-6.1-stan-rkr5.1（同步自野火 lbc-develop-6.1）。
local lubancat = import 'config/embedfire-lubancat.libsonnet';

lubancat.board('embedfire-lubancat-3', 'rk3576', 'rk3576-lubancat-3')
