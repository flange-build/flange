#!/bin/bash
# Rockchip 平台 Rootfs 构建脚本
#
# 由 rootfs_build rule 调用（source 方式），可使用以下环境变量：
#   ROOTFS_TARBALL        — ubuntu-base tarball 路径
#   ROOTFS_PACKAGES       — 空格分隔的 apt 包列表
#   ROOTFS_CUSTOM_PACKAGES — 空格分隔的自定义 deb 包组件名
#   ROOTFS_PACKAGES_DIR   — 自定义 deb 包目录路径
#   ROOTFS_OVERLAY_DIR    — board overlay 目录路径
#   ROOTFS_ARCH           — 目标架构（arm64）
#
# 脚本须设置以下变量供框架收集产物：
#   ROOTFS_OUTPUT         — rootfs.tar.gz 绝对路径

set -xe

WORK_DIR="$(mktemp -d)"
ROOTFS="${WORK_DIR}/rootfs"
trap '_rootfs_cleanup' EXIT

_rootfs_cleanup() {
    echo "=== 清理 chroot 环境 ==="
    # 卸载挂载点（忽略错误，可能未挂载）
    umount "${ROOTFS}/dev/pts" 2>/dev/null || true
    umount "${ROOTFS}/dev" 2>/dev/null || true
    umount "${ROOTFS}/proc" 2>/dev/null || true
    umount "${ROOTFS}/sys" 2>/dev/null || true
    # 不删除 WORK_DIR，产物还在里面
}

# --- 1. 解压 ubuntu-base tarball ---
echo "=== 解压 ubuntu-base tarball ==="
mkdir -p "${ROOTFS}"
tar xf "${ROOTFS_TARBALL}" -C "${ROOTFS}"

# --- 2. 设置 qemu-user-static ---
echo "=== 设置 qemu-user-static ==="
QEMU_BIN="/usr/bin/qemu-aarch64-static"
if [ -f "${QEMU_BIN}" ]; then
    cp "${QEMU_BIN}" "${ROOTFS}/usr/bin/qemu-aarch64-static"
else
    echo "警告: 未找到 ${QEMU_BIN}，跳过 qemu 设置（仅在原生架构构建时可行）"
fi

# --- 3. 挂载虚拟文件系统 ---
echo "=== 挂载虚拟文件系统 ==="
mount -t proc proc "${ROOTFS}/proc"
mount -t sysfs sys "${ROOTFS}/sys"
mount -o bind /dev "${ROOTFS}/dev"
mount -o bind /dev/pts "${ROOTFS}/dev/pts"

# 配置 DNS（使用宿主机的 resolv.conf）
cp /etc/resolv.conf "${ROOTFS}/etc/resolv.conf" 2>/dev/null || true

# --- 4. chroot 安装 apt 包 ---
if [ -n "${ROOTFS_PACKAGES}" ]; then
    echo "=== 安装 apt 包: ${ROOTFS_PACKAGES} ==="
    chroot "${ROOTFS}" apt-get update
    chroot "${ROOTFS}" apt-get install -y --no-install-recommends ${ROOTFS_PACKAGES}
fi

# --- 5. 安装自定义 deb 包 ---
if [ -n "${ROOTFS_CUSTOM_PACKAGES}" ] && [ -n "${ROOTFS_PACKAGES_DIR}" ]; then
    echo "=== 安装自定义 deb 包 ==="
    mkdir -p "${ROOTFS}/tmp/custom-debs"
    for pkg in ${ROOTFS_CUSTOM_PACKAGES}; do
        PKG_DIR="${ROOTFS_PACKAGES_DIR}/${pkg}"
        if [ -d "${PKG_DIR}" ]; then
            echo "--- 安装组件: ${pkg} ---"
            cp "${PKG_DIR}"/*.deb "${ROOTFS}/tmp/custom-debs/" 2>/dev/null || true
        else
            echo "警告: 自定义包目录不存在: ${PKG_DIR}"
        fi
    done
    if ls "${ROOTFS}/tmp/custom-debs/"*.deb 1>/dev/null 2>&1; then
        chroot "${ROOTFS}" dpkg -i /tmp/custom-debs/*.deb || true
        chroot "${ROOTFS}" apt-get install -f -y
    fi
    rm -rf "${ROOTFS}/tmp/custom-debs"
fi

# --- 6. 应用 overlay ---
if [ -n "${ROOTFS_OVERLAY_DIR}" ] && [ -d "${ROOTFS_OVERLAY_DIR}" ]; then
    # 检查 overlay 目录是否有内容
    if [ "$(ls -A "${ROOTFS_OVERLAY_DIR}" 2>/dev/null)" ]; then
        echo "=== 应用 overlay: ${ROOTFS_OVERLAY_DIR} ==="
        cp -a "${ROOTFS_OVERLAY_DIR}/." "${ROOTFS}/"
    else
        echo "=== overlay 目录为空，跳过 ==="
    fi
else
    echo "=== 无 overlay 目录，跳过 ==="
fi

# --- 7. 清理 ---
echo "=== 清理 rootfs ==="
chroot "${ROOTFS}" apt-get clean
rm -rf "${ROOTFS}/var/lib/apt/lists/"*
rm -rf "${ROOTFS}/tmp/"*
rm -f "${ROOTFS}/usr/bin/qemu-aarch64-static"
rm -f "${ROOTFS}/etc/resolv.conf"

# 卸载虚拟文件系统
umount "${ROOTFS}/dev/pts"
umount "${ROOTFS}/dev"
umount "${ROOTFS}/proc"
umount "${ROOTFS}/sys"

# --- 8. 打包 ---
echo "=== 打包 rootfs.tar.gz ==="
ROOTFS_OUTPUT="${WORK_DIR}/rootfs.tar.gz"
tar czf "${ROOTFS_OUTPUT}" -C "${ROOTFS}" .

echo "=== Rootfs 构建完成: $(du -h "${ROOTFS_OUTPUT}" | cut -f1) ==="
