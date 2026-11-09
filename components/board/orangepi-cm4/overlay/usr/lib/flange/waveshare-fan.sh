#!/bin/bash
# Waveshare CM4-DISP-BASE-5A 底板风扇温控（EMC2301 @ i2c1 0x2f）。
#
# 为什么在用户态：RK3566 只有两路 tsadc，已分别被 soc-thermal / gpu-thermal
# 独占（thermal_of 一路传感器只能挂一个热区），且两个热区都跑
# power_allocator governor——它只驱动功率型 cooling device，挂上去的风扇
# 永远不会转。故按 soc-thermal 温度在这里分档写 hwmon pwm1。
#
# 由 udev 在 emc2305 hwmon 出现时拉起（见 90-waveshare-fan.rules），其它
# 底板 / product 上不会运行。
set -euo pipefail

# 档位：温度阈值(m°C) 与对应 PWM(0-255)。降档有 5°C 回差，避免频繁启停。
TRIPS=(45000 55000 65000)
PWMS=(0 102 178 255)
HYST=5000
INTERVAL=5

find_by_name() {
    # $1: sysfs class 目录通配；$2: 属性文件名；$3: 期望值
    local dir
    for dir in $1; do
        if [ -r "$dir/$2" ] && [ "$(cat "$dir/$2")" = "$3" ]; then
            echo "$dir"
            return 0
        fi
    done
    return 1
}

hwmon=$(find_by_name '/sys/class/hwmon/hwmon*' name emc2305) || {
    echo "未找到 emc2305 hwmon" >&2
    exit 1
}
zone=$(find_by_name '/sys/class/thermal/thermal_zone*' type soc-thermal) || {
    echo "未找到 soc-thermal 热区" >&2
    exit 1
}

level=0
last_pwm=-1
while :; do
    temp=$(cat "$zone/temp")
    # 升档：越过上一档阈值即升
    while [ "$level" -lt "${#TRIPS[@]}" ] && [ "$temp" -ge "${TRIPS[$level]}" ]; do
        level=$((level + 1))
    done
    # 降档：低于本档阈值减回差才降
    while [ "$level" -gt 0 ] && [ "$temp" -lt $((TRIPS[level - 1] - HYST)) ]; do
        level=$((level - 1))
    done
    pwm=${PWMS[$level]}
    if [ "$pwm" -ne "$last_pwm" ]; then
        echo "$pwm" > "$hwmon/pwm1"
        echo "soc 温度 $((temp / 1000))°C → 档位 $level，pwm1=$pwm"
        last_pwm=$pwm
    fi
    sleep "$INTERVAL"
done
