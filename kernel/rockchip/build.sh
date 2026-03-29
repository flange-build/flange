#!/bin/bash
# Rockchip 平台内核构建脚本
#
# 由 kernel_build rule 调用（source 方式），可使用以下环境变量：
#   KERNEL_DIR       — 内核源码目录（已 cd 进入，已应用补丁）
#   KERNEL_DEFCONFIG — defconfig 名称
#   KERNEL_DTS       — DTS 文件名（不含扩展名）
#   KERNEL_DTS_DIR   — DTS 子目录名
#
# 脚本须设置以下变量供框架收集产物：
#   KERNEL_IMAGE — 内核镜像绝对路径
#   KERNEL_DTB   — DTB 文件绝对路径

ARCH=arm64
CROSS_COMPILE=aarch64-linux-gnu-

echo "=== Rockchip 内核配置: ${KERNEL_DEFCONFIG} ==="
make ARCH=${ARCH} CROSS_COMPILE=${CROSS_COMPILE} ${KERNEL_DEFCONFIG}

echo "=== Rockchip 内核编译: Image + DTB + modules (jobs=${KERNEL_JOBS}) ==="
make -j${KERNEL_JOBS} ARCH=${ARCH} CROSS_COMPILE=${CROSS_COMPILE} KCFLAGS="-Wno-error" Image dtbs modules

echo "=== Rockchip 内核模块安装 ==="
MODULES_STAGING="${KERNEL_DIR}/_modules_install"
rm -rf "${MODULES_STAGING}"
make ARCH=${ARCH} CROSS_COMPILE=${CROSS_COMPILE} \
    INSTALL_MOD_PATH="${MODULES_STAGING}" \
    INSTALL_MOD_STRIP=1 \
    modules_install

# 设置产出路径供框架收集
KERNEL_IMAGE="${KERNEL_DIR}/arch/${ARCH}/boot/Image"
KERNEL_DTB="${KERNEL_DIR}/arch/${ARCH}/boot/dts/${KERNEL_DTS_DIR}/${KERNEL_DTS}.dtb"
KERNEL_MODULES_DIR="${MODULES_STAGING}"
