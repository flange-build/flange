#!/bin/bash
# Rockchip 平台刷写模块
#
# 由 flange-flash.sh source 加载，提供以下函数：
#   flash_rockchip_check  — 检查刷写工具和设备状态
#   flash_rockchip_full   — 整盘 USB 刷写
#   flash_rockchip_component — 组件级 USB 刷写

RKDEV="rkdeveloptool"

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
            name=$(echo "$part" | grep -oP '\(\K[^)]+')
            offset=$(echo "$part" | grep -oP '@\K0x[0-9a-fA-F]+')
            case "$name" in
                uboot)  RK_UBOOT_OFFSET=$offset ;;
                boot)   RK_BOOT_OFFSET=$offset ;;
                rootfs) RK_ROOTFS_OFFSET=$offset ;;
            esac
        done
    fi
}

flash_rockchip_check() {
    check_command "$RKDEV" "sudo apt install rkdeveloptool  # 或从源码编译: https://github.com/rockchip-linux/rkdeveloptool" || return 1

    log_step "检测 Rockchip 设备..."
    if ! $RKDEV ld 2>/dev/null | grep -qi "maskrom\|loader"; then
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

flash_rockchip_full() {
    local image_dir="$1"
    _rk_parse_partitions "${image_dir}/parameter.txt"

    local idbloader="${image_dir}/idbloader.img"
    local uboot="${image_dir}/u-boot.itb"
    local boot="${image_dir}/boot.img"
    local rootfs="${image_dir}/rootfs.tar.gz"

    log_step "Rockchip USB 整盘刷写"

    # 写入 idbloader
    if [ -f "$idbloader" ]; then
        log_info "写入 idbloader.img (offset=64)..."
        $RKDEV db "$idbloader"
        sleep 1
        $RKDEV wl 64 "$idbloader"
    fi

    # 写入 u-boot.itb
    if [ -f "$uboot" ]; then
        log_info "写入 u-boot.itb (offset=$((RK_UBOOT_OFFSET)))..."
        $RKDEV wl $((RK_UBOOT_OFFSET)) "$uboot"
    fi

    # 写入 boot.img
    if [ -f "$boot" ]; then
        log_info "写入 boot.img (offset=$((RK_BOOT_OFFSET)))..."
        $RKDEV wl $((RK_BOOT_OFFSET)) "$boot"
    fi

    # rootfs 需要先转为 raw image
    # 注意：USB 刷写 rootfs 需要 rootfs.img（raw ext4），而不是 tar.gz
    # 这里使用 raw.img 中的 rootfs 部分，或者跳过（建议用 --raw 模式刷完整镜像）
    log_warn "USB 分段刷写不含 rootfs（rootfs 为 tar.gz 格式）"
    log_warn "如需刷写 rootfs，请使用 --raw 模式刷写完整镜像"

    log_info "刷写完成，重启设备..."
    $RKDEV rd
}

flash_rockchip_component() {
    local image_dir="$1"
    local component="$2"
    _rk_parse_partitions "${image_dir}/parameter.txt"

    case "$component" in
        kernel|boot)
            local boot="${image_dir}/boot.img"
            if [ ! -f "$boot" ]; then
                log_error "未找到 boot.img"
                return 1
            fi
            log_info "写入 boot.img (offset=$((RK_BOOT_OFFSET)))..."
            $RKDEV wl $((RK_BOOT_OFFSET)) "$boot"
            ;;
        bootloader)
            local idbloader="${image_dir}/idbloader.img"
            local uboot="${image_dir}/u-boot.itb"
            if [ -f "$idbloader" ]; then
                log_info "写入 idbloader.img (offset=64)..."
                $RKDEV db "$idbloader"
                sleep 1
                $RKDEV wl 64 "$idbloader"
            fi
            if [ -f "$uboot" ]; then
                log_info "写入 u-boot.itb (offset=$((RK_UBOOT_OFFSET)))..."
                $RKDEV wl $((RK_UBOOT_OFFSET)) "$uboot"
            fi
            ;;
        *)
            log_error "不支持的组件: $component"
            echo "  支持的组件: kernel, bootloader"
            return 1
            ;;
    esac

    log_info "组件 $component 刷写完成，重启设备..."
    $RKDEV rd
}
