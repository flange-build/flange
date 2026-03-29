#!/bin/bash
# Rockchip 平台 Boot 分区构建脚本
#
# 由 boot_partition rule 调用（source 方式），可使用以下环境变量：
#   BOOT_KERNEL_IMAGE    — 内核镜像路径
#   BOOT_DTB             — 主 DTB 文件路径
#   BOOT_DTBOS_TAR       — dtbos.tar.gz 路径（可能为空）
#   BOOT_DTS             — DTS 名称（不含扩展名）
#   BOOT_DTS_DIR         — DTS 子目录名（如 rockchip）
#   BOOT_DEFAULT_OVERLAYS — 空格分隔的默认启用 overlay 列表
#   BOOT_KERNEL_ARGS     — 内核启动参数
#   BOOT_SIZE_MB         — boot 分区大小（MB）
#
# 脚本须设置以下变量供框架收集产物：
#   BOOT_IMG_OUTPUT      — boot.img 绝对路径

set -xe

WORK_DIR="$(mktemp -d)"
BOOT_ROOT="${WORK_DIR}/boot"
MOUNT_DIR="${WORK_DIR}/mnt"
BOOT_MOUNTED=false
LOOP_DEV=""
trap '_boot_cleanup' EXIT

_boot_cleanup() {
    echo "=== 清理 boot 分区构建环境 ==="
    if [ "$BOOT_MOUNTED" = true ]; then
        umount "${MOUNT_DIR}" 2>/dev/null || true
    fi
    if [ -n "$LOOP_DEV" ]; then
        losetup -d "$LOOP_DEV" 2>/dev/null || true
    fi
}

# --- 1. 组装 boot 目录结构 ---
echo "=== 组装 boot 目录结构 ==="
mkdir -p "${BOOT_ROOT}/dtb/${BOOT_DTS_DIR}/overlay"
mkdir -p "${BOOT_ROOT}/extlinux"

cp "${BOOT_KERNEL_IMAGE}" "${BOOT_ROOT}/Image"
cp "${BOOT_DTB}" "${BOOT_ROOT}/dtb/${BOOT_DTS_DIR}/${BOOT_DTS}.dtb"

# --- 2. 解压 DTBO 文件 ---
if [ -n "${BOOT_DTBOS_TAR}" ] && [ -f "${BOOT_DTBOS_TAR}" ]; then
    echo "=== 解压 DTB overlay 文件 ==="
    tar -xzf "${BOOT_DTBOS_TAR}" -C "${BOOT_ROOT}/dtb/${BOOT_DTS_DIR}/overlay/" 2>/dev/null || true
    DTBO_COUNT=$(find "${BOOT_ROOT}/dtb/${BOOT_DTS_DIR}/overlay/" -name "*.dtbo" 2>/dev/null | wc -l)
    echo "--- 解压了 ${DTBO_COUNT} 个 DTBO 文件 ---"
fi

# --- 3. 生成 extlinux.conf ---
echo "=== 生成 extlinux.conf ==="
{
    echo "label flange"
    echo "  kernel /Image"
    echo "  fdt /dtb/${BOOT_DTS_DIR}/${BOOT_DTS}.dtb"

    # fdtoverlays 行
    if [ -n "${BOOT_DEFAULT_OVERLAYS}" ]; then
        OVERLAY_PATHS=""
        for overlay in ${BOOT_DEFAULT_OVERLAYS}; do
            OVERLAY_PATHS="${OVERLAY_PATHS} /dtb/${BOOT_DTS_DIR}/overlay/${overlay}.dtbo"
        done
        echo "  fdtoverlays${OVERLAY_PATHS}"
    fi

    # append 行（ROOT_UUID 占位符，image 阶段回写）
    echo "  append root=ROOT_UUID rootfstype=ext4 ${BOOT_KERNEL_ARGS}"
} > "${BOOT_ROOT}/extlinux/extlinux.conf"

cat "${BOOT_ROOT}/extlinux/extlinux.conf"

# --- 4. 创建 ext4 boot.img ---
echo "=== 创建 ext4 boot.img (${BOOT_SIZE_MB}MB) ==="
BOOT_IMG="${WORK_DIR}/boot.img"
truncate -s "${BOOT_SIZE_MB}M" "${BOOT_IMG}"
mkfs.ext4 -F -L "boot" -q "${BOOT_IMG}"

# 挂载并写入内容
mkdir -p "${MOUNT_DIR}"
LOOP_DEV=$(losetup --show --find "${BOOT_IMG}")
mount "${LOOP_DEV}" "${MOUNT_DIR}"
BOOT_MOUNTED=true

cp -a "${BOOT_ROOT}/." "${MOUNT_DIR}/"

umount "${MOUNT_DIR}"
BOOT_MOUNTED=false
losetup -d "${LOOP_DEV}"
LOOP_DEV=""

# 设置产出路径
BOOT_IMG_OUTPUT="${BOOT_IMG}"

echo "=== Boot 分区构建完成: $(du -h "${BOOT_IMG_OUTPUT}" | cut -f1) ==="
