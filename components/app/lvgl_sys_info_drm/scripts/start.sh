#!/bin/bash
# lvgl_sys_info_drm 自启 wrapper
#
# systemd service 常驻 enable，但是否真正拉起面板由 config.json 的 autostart
# 标志位决定（设置页只改这个标志，不调 systemctl）。这样"开机自启"开关无需
# 运行时操作 systemd 状态，规避权限与时序复杂度。
set -xe

CONFIG=/var/lib/lvgl_sys_info_drm/config.json
BIN=/usr/bin/lvgl_sys_info_drm

# 默认启用；仅当 config 明确写 "autostart": false 时跳过拉起。
# 用 grep 解析（target rootfs 不保证有 jq/python3）。
if [ -f "$CONFIG" ] && grep -Eq '"autostart"[[:space:]]*:[[:space:]]*false' "$CONFIG"; then
    echo "[start] autostart=false，跳过面板启动"
    exit 0
fi

exec "$BIN"
