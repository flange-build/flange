#!/usr/bin/env bash
# backport-iwlwifi 构建前准备：校验目标内核、按内核实际 API 修正兼容层、生成 .config。
#
# 用法：prepare-backport.sh <backport_src> <kernel_src> <arch> <cross_compile>
#
# backport 的兼容层按内核版本号判断是否补齐新 API，但 stable / 厂商 BSP 内核常把
# 新 API 回移到旧版本号里，导致兼容层与内核重复定义。这里直接检测内核头文件，
# 不依赖版本号。每次构建前 backport 源会被 git reset，修正需幂等。
set -xeuo pipefail

bp_src=$1
kernel_src=$2
arch=$3
cross_compile=$4

kconfig="$kernel_src/.config"
if [ ! -f "$kconfig" ]; then
    echo "错误：内核未配置（缺 $kconfig）" >&2
    exit 1
fi

# backport 自带 cfg80211/mac80211，与内建版本同名冲突；内核侧必须为模块或关闭。
for sym in CFG80211 MAC80211; do
    if grep -q "^CONFIG_${sym}=y" "$kconfig"; then
        echo "错误：内核 CONFIG_${sym}=y（内建），intel-be200 要求为 m。" >&2
        echo "      通常是某个内建无线驱动 select 了它，需在 board/platform 层关掉该驱动。" >&2
        exit 1
    fi
done

# timer_delete()：主线 6.2 引入，6.1.84 等 stable 已回移；内核已提供时去掉兼容层定义。
if grep -q "int timer_delete(struct timer_list \*timer);" "$kernel_src/include/linux/timer.h"; then
    python3 - "$bp_src/backport-include/linux/timer.h" <<'EOF'
import sys
path = sys.argv[1]
text = open(path).read()
old = "#if LINUX_VERSION_IS_LESS(6,2,0)\nstatic inline int timer_delete(struct timer_list *timer)"
new = "#if 0 /* 目标内核已提供 timer_delete() */\nstatic inline int timer_delete(struct timer_list *timer)"
open(path, "w").write(text.replace(old, new))
EOF
fi

# 驱动修正补丁：已应用则跳过（反向可应用），否则必须能干净应用。
shopt -s nullglob
for patch in "$(dirname "$0")"/patches/*.patch; do
    if git -C "$bp_src" apply --reverse --check "$patch" 2>/dev/null; then
        continue
    fi
    git -C "$bp_src" apply "$patch"
done

make -C "$bp_src" KLIB_BUILD="$kernel_src" KLIB="$kernel_src" \
    ARCH="$arch" CROSS_COMPILE="$cross_compile" defconfig-iwlwifi-public
