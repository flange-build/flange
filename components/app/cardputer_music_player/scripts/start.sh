#!/bin/bash
# 等待 Cardputer GUD/HID/UAC 完成 USB 复合枚举后启动播放器。
set -xe

timeout_s=30
elapsed=0

while [ "${elapsed}" -lt "${timeout_s}" ]; do
    has_gud=false
    has_hid=false
    has_audio=false

    if grep -q '^1 guddrmfb$' /proc/fb 2>/dev/null \
            || grep -q 'guddrmfb' /proc/fb 2>/dev/null; then
        has_gud=true
    fi
    if grep -q 'Cardputer GUD Display' /proc/bus/input/devices 2>/dev/null; then
        has_hid=true
    fi
    if grep -q 'Cardputer GUD Display' /proc/asound/cards 2>/dev/null; then
        has_audio=true
    fi

    if ${has_gud} && ${has_hid} && ${has_audio}; then
        exec /usr/bin/cardputer_music_player
    fi

    sleep 1
    elapsed=$((elapsed + 1))
done

echo "[music] 等待 30 秒后仍缺少 Cardputer GUD/HID/UAC 外设" >&2
exit 1
