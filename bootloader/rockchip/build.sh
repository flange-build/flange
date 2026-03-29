#!/bin/bash
# Rockchip 平台 Bootloader 构建脚本
#
# 由 bootloader_build rule 调用（source 方式），可使用以下环境变量：
#   BOOTLOADER_DIR       — U-Boot 源码目录（已 cd 进入，已应用补丁）
#   BOOTLOADER_DEFCONFIG — U-Boot defconfig 名称
#   BOOTLOADER_JOBS      — make 并行任务数
#   FIRMWARE_DIR         — rkbin 固件仓库路径
#   RKBIN_INI_PREFIX     — rkbin INI 文件前缀（如 RK3566）
#
# 脚本须设置以下变量供框架收集产物：
#   BOOTLOADER_IDBLOADER — idbloader.img 绝对路径
#   BOOTLOADER_ITB       — u-boot.itb 绝对路径

# U-Boot 中 64 位 ARM 的 ARCH 是 arm（不同于 Linux 内核的 arm64）
ARCH=arm
CROSS_COMPILE=aarch64-linux-gnu-

# --- 从 RKTRUST INI 解析 BL31 路径 ---
TRUST_PREFIX="${RKBIN_TRUST_INI_PREFIX:-${RKBIN_INI_PREFIX}}"
TRUST_INI="${FIRMWARE_DIR}/RKTRUST/${TRUST_PREFIX}TRUST.ini"
if [ ! -f "${TRUST_INI}" ]; then
    echo "错误: 找不到 TRUST INI 文件: ${TRUST_INI}" >&2
    exit 1
fi

BL31_REL=$(grep "^PATH=" "${TRUST_INI}" | grep -i "bl31" | head -1 | cut -d= -f2 | tr -d '\r ')
if [ -z "${BL31_REL}" ]; then
    echo "错误: 无法从 ${TRUST_INI} 解析 BL31 路径" >&2
    exit 1
fi
BL31="${FIRMWARE_DIR}/${BL31_REL}"
echo "=== BL31: ${BL31} ==="

# --- 编译 U-Boot ---
echo "=== Rockchip Bootloader 配置: ${BOOTLOADER_DEFCONFIG} ==="
cd "${BOOTLOADER_DIR}"
make ARCH=${ARCH} CROSS_COMPILE=${CROSS_COMPILE} ${BOOTLOADER_DEFCONFIG}

echo "=== Rockchip Bootloader 编译 (jobs=${BOOTLOADER_JOBS}) ==="

# make_fit_atf.sh 期望 bl31.elf 在源码根目录，tee.bin 可选（不使用 OP-TEE）
cp "${BL31}" "${BOOTLOADER_DIR}/bl31.elf"
touch "${BOOTLOADER_DIR}/tee.bin"

make -j${BOOTLOADER_JOBS} ARCH=${ARCH} CROSS_COMPILE=${CROSS_COMPILE} \
    KCFLAGS="-Wno-error" \
    BL31="${BOOTLOADER_DIR}/bl31.elf" \
    u-boot.itb

# --- 使用 boot_merger 生成 idbloader.img ---
LOADER_INI="${FIRMWARE_DIR}/RKBOOT/${RKBIN_INI_PREFIX}MINIALL.ini"
if [ ! -f "${LOADER_INI}" ]; then
    echo "错误: 找不到 RKBOOT INI 文件: ${LOADER_INI}" >&2
    exit 1
fi

BOOT_MERGER="${FIRMWARE_DIR}/tools/boot_merger"
if [ ! -x "${BOOT_MERGER}" ]; then
    chmod +x "${BOOT_MERGER}"
fi

echo "=== 生成 idbloader.img (boot_merger) ==="
cd "${FIRMWARE_DIR}"
"${BOOT_MERGER}" "${LOADER_INI}"

# boot_merger 输出文件名从 INI 的 [OUTPUT] 段读取，通常在 FIRMWARE_DIR 下
LOADER_OUTPUT=$(grep "^PATH=" "${LOADER_INI}" | tail -1 | cut -d= -f2 | tr -d '\r ')
if [ -f "${FIRMWARE_DIR}/${LOADER_OUTPUT}" ]; then
    cp "${FIRMWARE_DIR}/${LOADER_OUTPUT}" "${BOOTLOADER_DIR}/idbloader.img"
else
    # 回退：查找 boot_merger 生成的文件
    MERGER_OUTPUT=$(find "${FIRMWARE_DIR}" -maxdepth 1 -name "*_loader_*.bin" -newer "${LOADER_INI}" | head -1)
    if [ -n "${MERGER_OUTPUT}" ]; then
        cp "${MERGER_OUTPUT}" "${BOOTLOADER_DIR}/idbloader.img"
    else
        echo "错误: boot_merger 未生成预期的输出文件" >&2
        exit 1
    fi
fi

# --- 设置产出路径供框架收集 ---
BOOTLOADER_IDBLOADER="${BOOTLOADER_DIR}/idbloader.img"
BOOTLOADER_ITB="${BOOTLOADER_DIR}/u-boot.itb"
