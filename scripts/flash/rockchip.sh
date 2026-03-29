#!/bin/bash
# Rockchip 平台刷写模块
#
# 由 flange-flash.sh source 加载，提供以下函数：
#   flash_rockchip_check  — 检查刷写工具和设备状态
#   flash_rockchip_full   — 整盘 USB 刷写
#   flash_rockchip_component — 组件级 USB 刷写

# 根据宿主机系统选择 upgrade_tool 路径
case "$(uname -s)" in
    Linux)  _RK_TOOL_PLATFORM="linux" ;;
    Darwin) _RK_TOOL_PLATFORM="macos" ;;
    *)      echo "错误: 不支持的系统: $(uname -s)" >&2; return 1 ;;
esac
RKDEV="${FLANGE_DIR}/tools/${_RK_TOOL_PLATFORM}/upgrade_tool/upgrade_tool"

# 解析 parameter.txt 获取分区偏移
_rk_parse_partitions() {
    local param_file="$1"
    # 默认值（扇区单位）
    RK_UBOOT_OFFSET=0x4000
    RK_BOOT_OFFSET=0x8000
    RK_ROOTFS_OFFSET=0x40000

    if [ -f "$param_file" ]; then
        local cmdline
        cmdline=$(grep "^CMDLINE:" "$param_file" | sed 's/^CMDLINE://')
        for part in $(echo "$cmdline" | tr ',' '\n'); do
            local name offset
            name=$(echo "$part" | sed -n 's/.*(\([^)]*\)).*/\1/p')
            offset=$(echo "$part" | sed -n 's/.*@\(0x[0-9a-fA-F]*\).*/\1/p')
            case "$name" in
                uboot)  RK_UBOOT_OFFSET=$offset ;;
                boot)   RK_BOOT_OFFSET=$offset ;;
                rootfs) RK_ROOTFS_OFFSET=$offset ;;
            esac
        done
    fi
}

flash_rockchip_check() {
    if [ ! -x "$RKDEV" ]; then
        log_error "未找到 upgrade_tool: $RKDEV"
        return 1
    fi

    log_step "检测 Rockchip 设备..."
    if ! "$RKDEV" LD 2>/dev/null | grep -qi "maskrom\|loader"; then
        log_error "未检测到 Rockchip 设备（Maskrom/Loader 模式）"
        echo "  请将设备连接到 USB 并进入 Maskrom 或 Loader 模式:"
        echo "    1. 按住 Maskrom 按钮"
        echo "    2. 短按 Reset 按钮"
        echo "    3. 松开 Maskrom 按钮"
        return 1
    fi
    log_info "已检测到 Rockchip 设备"
    return 0
}

# 上传 miniloader 初始化设备存储访问
_rk_download_boot() {
    local image_dir="$1"
    local miniloader="${image_dir}/miniloader.bin"

    if [ ! -f "$miniloader" ]; then
        log_error "未找到 miniloader.bin: $miniloader"
        return 1
    fi

    log_info "上传 miniloader（DB）..."
    "$RKDEV" DB "$miniloader"
    sleep 1
}

flash_rockchip_full() {
    local image_dir="$1"

    # 查找 *_firmware_*.img
    local firmware_img
    firmware_img=$(find "$image_dir" -maxdepth 1 -name "*_firmware_*.img" | head -1)
    if [ -z "$firmware_img" ]; then
        log_error "未找到固件镜像（*_firmware_*.img）: $image_dir"
        return 1
    fi

    _rk_download_boot "$image_dir" || return 1

    local img_name img_size
    img_name=$(basename "$firmware_img")
    img_size=$(du -h "$firmware_img" | cut -f1)
    log_step "Rockchip USB 整盘刷写: $img_name ($img_size)"

    log_info "写入 $img_name..."
    "$RKDEV" WL 0 "$firmware_img"

    log_info "刷写完成，重启设备..."
    "$RKDEV" RD
}

flash_rockchip_component() {
    local image_dir="$1"
    local component="$2"
    _rk_parse_partitions "${image_dir}/parameter.txt"

    _rk_download_boot "$image_dir" || return 1

    case "$component" in
        kernel|boot)
            local boot="${image_dir}/boot.img"
            if [ ! -f "$boot" ]; then
                log_error "未找到 boot.img"
                return 1
            fi
            log_info "写入 boot.img (offset=$((RK_BOOT_OFFSET)))..."
            "$RKDEV" WL $((RK_BOOT_OFFSET)) "$boot"
            ;;
        bootloader)
            local idbloader="${image_dir}/idbloader.img"
            local bootloader_img="${image_dir}/bootloader.img"
            if [ -f "$idbloader" ]; then
                log_info "写入 idbloader.img (offset=64)..."
                "$RKDEV" WL 64 "$idbloader"
            fi
            if [ -f "$bootloader_img" ]; then
                log_info "写入 bootloader.img (offset=$((RK_UBOOT_OFFSET)))..."
                "$RKDEV" WL $((RK_UBOOT_OFFSET)) "$bootloader_img"
            fi
            ;;
        *)
            log_error "不支持的组件: $component"
            echo "  支持的组件: kernel, bootloader"
            return 1
            ;;
    esac

    log_info "组件 $component 刷写完成，重启设备..."
    "$RKDEV" RD
}
