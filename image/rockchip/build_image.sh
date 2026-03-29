#!/bin/bash
# Rockchip 平台磁盘镜像打包脚本
#
# 由 image_build rule 调用（source 方式），可使用以下环境变量：
#   IMAGE_BOOT             — boot.img 路径
#   IMAGE_BOOTLOADER_DIR   — bootloader 产物目录（含 idbloader.img, bootloader.img, miniloader.bin）
#   IMAGE_ROOTFS           — rootfs.tar.gz 路径
#   IMAGE_PARTITION_CONFIG — parameter.txt 路径（可能为空）
#
# 脚本须设置以下变量供框架收集产物：
#   IMAGE_OUTPUT           — raw.img 绝对路径

set -xe

WORK_DIR="$(mktemp -d)"
ROOTFS_MOUNTED=false
LOOP_DEV=""
trap '_image_cleanup' EXIT

_image_cleanup() {
    echo "=== 清理镜像打包环境 ==="
    if [ "$ROOTFS_MOUNTED" = true ]; then
        umount "${WORK_DIR}/rootfs_mnt" 2>/dev/null || true
    fi
    if [ -n "$LOOP_DEV" ]; then
        kpartx -d "$LOOP_DEV" 2>/dev/null || true
        losetup -d "$LOOP_DEV" 2>/dev/null || true
    fi
}

# --- 1. 解析 parameter.txt 获取分区布局 ---
echo "=== 解析分区布局 ==="

# 默认分区偏移（单位：512 字节扇区）
UBOOT_OFFSET=0x4000
BOOT_OFFSET=0x8000
BOOT_SIZE=0x20000
ROOTFS_OFFSET=0x40000
ROOTFS_SIZE=0x200000

if [ -n "${IMAGE_PARTITION_CONFIG}" ] && [ -f "${IMAGE_PARTITION_CONFIG}" ]; then
    CMDLINE=$(grep "^CMDLINE:" "${IMAGE_PARTITION_CONFIG}" | sed 's/^CMDLINE://')
    if [ -n "$CMDLINE" ]; then
        # 去掉 mtdparts=<device>: 前缀
        PARTS_STR=$(echo "$CMDLINE" | sed 's/^mtdparts=[^:]*://')
        # 解析 mtdparts 格式: 0xSIZE@0xOFFSET(name)
        for part in $(echo "$PARTS_STR" | tr ',' '\n'); do
            PART_NAME=$(echo "$part" | grep -oP '\(\K[^)]+' || true)
            PART_OFFSET=$(echo "$part" | grep -oP '@\K0x[0-9a-fA-F]+' || true)
            PART_SIZE=$(echo "$part" | grep -oP '^0x[0-9a-fA-F]+' || true)

            case "$PART_NAME" in
                uboot)  [ -n "$PART_OFFSET" ] && UBOOT_OFFSET=$PART_OFFSET ;;
                boot)   [ -n "$PART_OFFSET" ] && BOOT_OFFSET=$PART_OFFSET; [ -n "$PART_SIZE" ] && BOOT_SIZE=$PART_SIZE ;;
                rootfs) [ -n "$PART_OFFSET" ] && ROOTFS_OFFSET=$PART_OFFSET; [ -n "$PART_SIZE" ] && ROOTFS_SIZE=$PART_SIZE ;;
            esac
        done
    fi
fi

# 转换为十进制（扇区单位）
UBOOT_OFFSET_DEC=$((UBOOT_OFFSET))
BOOT_OFFSET_DEC=$((BOOT_OFFSET))
BOOT_SIZE_DEC=$((BOOT_SIZE))
ROOTFS_OFFSET_DEC=$((ROOTFS_OFFSET))
ROOTFS_SIZE_DEC=$((ROOTFS_SIZE))

echo "--- 分区布局 ---"
echo "  uboot:  offset=${UBOOT_OFFSET_DEC} sectors"
echo "  boot:   offset=${BOOT_OFFSET_DEC} sectors, size=${BOOT_SIZE_DEC} sectors"
echo "  rootfs: offset=${ROOTFS_OFFSET_DEC} sectors, size=${ROOTFS_SIZE_DEC} sectors"

# --- 2. 计算镜像大小 ---
# rootfs 大小 = tar.gz 解压后估算 * 1.3（余量）
ROOTFS_TAR_SIZE=$(stat -c%s "${IMAGE_ROOTFS}")
ROOTFS_ESTIMATED_MB=$(( (ROOTFS_TAR_SIZE * 3 / 1048576) + 100 ))  # gzip 约 1:3 压缩比 + 100MB 余量

# 镜像总大小 = rootfs 偏移 + rootfs 大小，取较大值
TOTAL_SECTORS=$(( ROOTFS_OFFSET_DEC + ROOTFS_SIZE_DEC ))
TOTAL_MB=$(( TOTAL_SECTORS * 512 / 1048576 + 2 ))  # +2MB GPT 备份头余量

# 确保镜像大到能容纳 rootfs 内容
ROOTFS_START_MB=$(( ROOTFS_OFFSET_DEC * 512 / 1048576 ))
NEEDED_MB=$(( ROOTFS_START_MB + ROOTFS_ESTIMATED_MB ))
if [ "$NEEDED_MB" -gt "$TOTAL_MB" ]; then
    TOTAL_MB=$NEEDED_MB
fi

echo "--- 镜像大小: ${TOTAL_MB}MB ---"

# --- 3. 创建空白镜像并建立 GPT 分区表 ---
echo "=== 创建空白镜像 ==="
RAW_IMG="${WORK_DIR}/raw.img"
truncate -s "${TOTAL_MB}M" "${RAW_IMG}"

echo "=== 创建 GPT 分区表 ==="
BOOT_START_BYTES=$(( BOOT_OFFSET_DEC * 512 ))
BOOT_END_BYTES=$(( (BOOT_OFFSET_DEC + BOOT_SIZE_DEC) * 512 - 1 ))
ROOTFS_START_BYTES=$(( ROOTFS_OFFSET_DEC * 512 ))
ROOTFS_END_BYTES=$(( (ROOTFS_OFFSET_DEC + ROOTFS_SIZE_DEC) * 512 - 1 ))

parted -s "${RAW_IMG}" mklabel gpt
parted -s "${RAW_IMG}" mkpart boot ext4 ${BOOT_START_BYTES}B ${BOOT_END_BYTES}B
parted -s "${RAW_IMG}" mkpart rootfs ext4 ${ROOTFS_START_BYTES}B ${ROOTFS_END_BYTES}B

# 设置 rootfs 分区 PARTUUID（Rockchip 平台固定值）
echo "=== 设置 rootfs PARTUUID ==="
sfdisk --part-uuid "${RAW_IMG}" 2 614e0000-0000-4000-8000-000000000000
echo "--- rootfs PARTUUID: 614e0000-0000-4000-8000-000000000000 ---"

# --- 4. 写入 bootloader ---
echo "=== 写入 bootloader ==="
IDBLOADER="${IMAGE_BOOTLOADER_DIR}/idbloader.img"
BOOTLOADER_IMG="${IMAGE_BOOTLOADER_DIR}/bootloader.img"

if [ -f "${IDBLOADER}" ]; then
    dd if="${IDBLOADER}" of="${RAW_IMG}" seek=64 conv=notrunc status=none
    echo "--- idbloader.img 已写入 offset=64 sectors ---"
fi

if [ -f "${BOOTLOADER_IMG}" ]; then
    dd if="${BOOTLOADER_IMG}" of="${RAW_IMG}" seek=${UBOOT_OFFSET_DEC} conv=notrunc status=none
    echo "--- bootloader.img 已写入 offset=${UBOOT_OFFSET_DEC} sectors ---"
fi

# --- 5. 写入 boot 分区 ---
echo "=== 写入 boot 分区 ==="
dd if="${IMAGE_BOOT}" of="${RAW_IMG}" seek=${BOOT_OFFSET_DEC} conv=notrunc status=none
echo "--- boot.img 已写入 offset=${BOOT_OFFSET_DEC} sectors ---"

# --- 6. 创建 rootfs 分区 ---
echo "=== 创建 rootfs ext4 分区 ==="
ROOTFS_IMG="${WORK_DIR}/rootfs.img"
truncate -s "${ROOTFS_ESTIMATED_MB}M" "${ROOTFS_IMG}"
mkfs.ext4 -F -L "rootfs" -q "${ROOTFS_IMG}"

# 挂载并写入 rootfs 内容
mkdir -p "${WORK_DIR}/rootfs_mnt"
LOOP_DEV=$(losetup --show --find "${ROOTFS_IMG}")
mount "${LOOP_DEV}" "${WORK_DIR}/rootfs_mnt"
ROOTFS_MOUNTED=true

tar xzf "${IMAGE_ROOTFS}" -C "${WORK_DIR}/rootfs_mnt"

umount "${WORK_DIR}/rootfs_mnt"
ROOTFS_MOUNTED=false
losetup -d "${LOOP_DEV}"
LOOP_DEV=""

# --- 7. 写入 rootfs 到镜像 ---
echo "=== 写入 rootfs 到镜像 ==="
dd if="${ROOTFS_IMG}" of="${RAW_IMG}" seek=${ROOTFS_OFFSET_DEC} conv=notrunc status=none
echo "--- rootfs.img 已写入 offset=${ROOTFS_OFFSET_DEC} sectors ---"

# 设置产出路径
IMAGE_OUTPUT="${RAW_IMG}"

echo "=== 镜像打包完成: $(du -h "${IMAGE_OUTPUT}" | cut -f1) ==="
