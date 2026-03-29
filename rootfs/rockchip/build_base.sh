#!/bin/bash
# Rockchip 平台 Base Rootfs 构建脚本
#
# 由 rootfs_base rule 调用（source 方式），可使用以下环境变量：
#   ROOTFS_TARBALL        — ubuntu-base tarball 路径
#   ROOTFS_PACKAGES       — 空格分隔的 apt 包列表
#   ROOTFS_APT_CACHE_DIR  — APT 下载缓存目录路径（宿主机持久化）
#   ROOTFS_ARCH           — 目标架构（arm64）
#
# 脚本须设置以下变量供框架收集产物：
#   ROOTFS_BASE_OUTPUT    — base-rootfs.tar.zst 绝对路径

set -xe

WORK_DIR="$(mktemp -d)"
ROOTFS="${WORK_DIR}/rootfs"
APT_CACHE_MOUNTED=false
trap '_base_cleanup' EXIT

_base_cleanup() {
    echo "=== 清理 base chroot 环境 ==="
    # 卸载 APT 缓存
    if [ "$APT_CACHE_MOUNTED" = true ]; then
        umount "${ROOTFS}/var/cache/apt/archives" 2>/dev/null || true
    fi
    # 卸载虚拟文件系统
    umount "${ROOTFS}/dev/pts" 2>/dev/null || true
    umount "${ROOTFS}/dev" 2>/dev/null || true
    umount "${ROOTFS}/proc" 2>/dev/null || true
    umount "${ROOTFS}/sys" 2>/dev/null || true
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

# --- 4. 挂载 APT 下载缓存 ---
if [ -n "${ROOTFS_APT_CACHE_DIR}" ] && [ -d "${ROOTFS_APT_CACHE_DIR}" ]; then
    echo "=== 挂载 APT 下载缓存: ${ROOTFS_APT_CACHE_DIR} ==="
    mkdir -p "${ROOTFS}/var/cache/apt/archives"
    mount --bind "${ROOTFS_APT_CACHE_DIR}" "${ROOTFS}/var/cache/apt/archives"
    APT_CACHE_MOUNTED=true
else
    echo "=== APT 缓存目录不存在，跳过缓存挂载 ==="
fi

# --- 5. chroot 安装 apt 包 ---
if [ -n "${ROOTFS_PACKAGES}" ]; then
    echo "=== 安装 apt 包: ${ROOTFS_PACKAGES} ==="
    chroot "${ROOTFS}" apt-get update
    chroot "${ROOTFS}" apt-get install -y --no-install-recommends ${ROOTFS_PACKAGES}
fi

# --- 6. 清理 ---
echo "=== 清理 base rootfs ==="
chroot "${ROOTFS}" apt-get clean
rm -rf "${ROOTFS}/var/lib/apt/lists/"*
rm -rf "${ROOTFS}/tmp/"*
rm -f "${ROOTFS}/usr/bin/qemu-aarch64-static"
rm -f "${ROOTFS}/etc/resolv.conf"

# 卸载 APT 缓存（清理前卸载，保留缓存文件）
if [ "$APT_CACHE_MOUNTED" = true ]; then
    umount "${ROOTFS}/var/cache/apt/archives"
    APT_CACHE_MOUNTED=false
fi

# 卸载虚拟文件系统
umount "${ROOTFS}/dev/pts"
umount "${ROOTFS}/dev"
umount "${ROOTFS}/proc"
umount "${ROOTFS}/sys"

# --- 7. 打包（zstd 压缩） ---
echo "=== 打包 base-rootfs.tar.zst ==="
ROOTFS_BASE_OUTPUT="${WORK_DIR}/base-rootfs.tar.zst"
tar -I "zstdmt -5" -cf "${ROOTFS_BASE_OUTPUT}" -C "${ROOTFS}" .

echo "=== Base rootfs 构建完成: $(du -h "${ROOTFS_BASE_OUTPUT}" | cut -f1) ==="
