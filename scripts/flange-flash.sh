#!/bin/bash
# flange 刷写脚本 — 宿主机执行，从 target/<board>/image/ 读取产物
#
# 用法:
#   ./scripts/flange-flash.sh --board <board>                              # USB 分段刷写
#   ./scripts/flange-flash.sh --board <board> --raw --device /dev/sdX      # dd 整盘刷写
#   ./scripts/flange-flash.sh --board <board> --component kernel           # 组件级刷写
#   ./scripts/flange-flash.sh --board <board> --component bootloader       # 组件级刷写

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 加载通用工具
source "$SCRIPT_DIR/flash/common.sh"

# --- 参数解析 ---
BOARD=""
RAW_MODE=false
DEVICE=""
COMPONENT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --board)    BOARD="$2"; shift 2 ;;
        --raw)      RAW_MODE=true; shift ;;
        --device)   DEVICE="$2"; shift 2 ;;
        --component) COMPONENT="$2"; shift 2 ;;
        -h|--help)
            echo "用法: $0 --board <board> [选项]"
            echo ""
            echo "选项:"
            echo "  --board <board>        目标板名称（如 radxa-zero3w）"
            echo "  --raw --device <dev>   dd 整盘刷写到指定设备"
            echo "  --component <name>     组件级刷写（kernel, bootloader）"
            echo ""
            echo "示例:"
            echo "  $0 --board radxa-zero3w                          # USB 分段刷写"
            echo "  $0 --board radxa-zero3w --raw --device /dev/sdX  # dd 刷写"
            echo "  $0 --board radxa-zero3w --component kernel       # 只刷 boot 分区"
            exit 0
            ;;
        *)
            log_error "未知参数: $1"
            exit 1
            ;;
    esac
done

if [ -z "$BOARD" ]; then
    log_error "请指定 --board 参数"
    exit 1
fi

# --- 检查产物目录 ---
IMAGE_DIR=$(check_image_dir "$BOARD") || exit 1
log_info "产物目录: $IMAGE_DIR"

# --- dd 整盘刷写模式 ---
if [ "$RAW_MODE" = true ]; then
    if [ -z "$DEVICE" ]; then
        log_error "--raw 模式需要指定 --device 参数"
        exit 1
    fi

    FIRMWARE_IMG=$(find "$IMAGE_DIR" -maxdepth 1 -name "*_firmware_*.img" | head -1)
    if [ -z "$FIRMWARE_IMG" ]; then
        log_error "未找到固件镜像（*_firmware_*.img）: $IMAGE_DIR"
        exit 1
    fi

    check_command "dd" || exit 1

    IMG_NAME=$(basename "$FIRMWARE_IMG")
    IMG_SIZE=$(du -h "$FIRMWARE_IMG" | cut -f1)
    log_step "dd 整盘刷写"
    echo "  镜像: $IMG_NAME ($IMG_SIZE)"
    echo "  目标: $DEVICE"
    confirm_action "警告: 这将覆盖 $DEVICE 上的所有数据！" || exit 0

    log_info "正在刷写..."
    sudo dd if="$FIRMWARE_IMG" of="$DEVICE" bs=4M status=progress conv=fsync
    sync
    log_info "dd 刷写完成"
    exit 0
fi

# --- 检测平台 ---
PLATFORM=""
if [ -f "${IMAGE_DIR}/parameter.txt" ]; then
    PLATFORM="rockchip"
fi

if [ -z "$PLATFORM" ]; then
    log_error "无法检测目标平台（未找到 parameter.txt 等平台标识文件）"
    exit 1
fi

log_info "检测到平台: $PLATFORM"

# --- 加载平台刷写模块 ---
PLATFORM_SCRIPT="$SCRIPT_DIR/flash/${PLATFORM}.sh"
if [ ! -f "$PLATFORM_SCRIPT" ]; then
    log_error "不支持的平台: $PLATFORM（未找到 $PLATFORM_SCRIPT）"
    exit 1
fi
source "$PLATFORM_SCRIPT"

# --- 检查刷写工具和设备 ---
flash_${PLATFORM}_check || exit 1

# --- 执行刷写 ---
if [ -n "$COMPONENT" ]; then
    flash_${PLATFORM}_component "$IMAGE_DIR" "$COMPONENT"
else
    flash_${PLATFORM}_full "$IMAGE_DIR"
fi
