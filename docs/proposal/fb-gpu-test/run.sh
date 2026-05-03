#!/bin/bash
set -xe

# 编译并运行 fb_triangle
# 需要在设备上执行

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_DIR="/tmp/fb_triangle"

adb shell "mkdir -p ${REMOTE_DIR}"
adb push "${REPO_DIR}/tools/fb_triangle/main.c" "${REMOTE_DIR}/"

adb shell "cd ${REMOTE_DIR} && \
    gcc -o fb_triangle main.c \
        -I/usr/include \
        -L/usr/lib/aarch64-linux-gnu \
        -lEGL -lGLESv2 -ldrm -lgbm -lm \
        -Wl,-rpath,/usr/lib/aarch64-linux-gnu && \
    echo '编译成功'"

echo "运行 fb_triangle (Ctrl+C 停止)..."
adb shell "cd ${REMOTE_DIR} && ./fb_triangle"
