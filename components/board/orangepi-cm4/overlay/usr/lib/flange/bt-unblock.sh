#!/bin/sh
# 解除 Rockchip rfkill_rk 对板载 BT 的 soft block。
#
# rfkill_rk 建出的 bt_default 默认 soft-blocked，且 systemd-rfkill 会把该状态
# 持久化到 /var/lib/systemd/rfkill/ 并在每次开机恢复。实测 `rfkill unblock
# bluetooth` 对它无效（驱动未把 set_block 的结果回写到 soft 属性），只能直接写
# sysfs。rfkill 索引随探测顺序变化，按 name 匹配而不是写死 rfkill0。
#
# 找不到该节点不算失败：BT 可能被 dts 禁用，此时 btattach 自己会报错退出。
set -eu
for dir in /sys/class/rfkill/*; do
    [ -r "$dir/name" ] || continue
    [ "$(cat "$dir/name")" = "bt_default" ] || continue
    echo 0 > "$dir/soft"
done
exit 0
