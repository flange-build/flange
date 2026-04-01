#!/bin/bash
# flange 开发环境初始化脚本
#
# 用法: source envsetup.sh
#
# 注入 lunch 和 flange 函数到当前 shell session。
# lunch 选择板级配置后，通过 flange <subcommand> 执行构建和刷写操作。

# --- 项目根目录 ---
if [[ -n "${BASH_SOURCE[0]}" ]]; then
    FLANGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "$0" ]]; then
    FLANGE_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
export FLANGE_DIR

# --- 颜色定义 ---
_FLANGE_RED='\033[0;31m'
_FLANGE_GREEN='\033[0;32m'
_FLANGE_YELLOW='\033[1;33m'
_FLANGE_BLUE='\033[0;34m'
_FLANGE_NC='\033[0m'

_flange_info()  { echo -e "${_FLANGE_GREEN}[INFO]${_FLANGE_NC} $*"; }
_flange_warn()  { echo -e "${_FLANGE_YELLOW}[WARN]${_FLANGE_NC} $*"; }
_flange_error() { echo -e "${_FLANGE_RED}[ERROR]${_FLANGE_NC} $*"; }
_flange_step()  { echo -e "${_FLANGE_BLUE}==>${_FLANGE_NC} $*"; }

# --- 前置检查 ---
_flange_check_docker() {
    if ! docker info &>/dev/null; then
        _flange_error "Docker 未运行，请先启动 Docker"
        return 1
    fi
    return 0
}

_flange_check_board() {
    if [[ -z "$FLANGE_BOARD" ]]; then
        _flange_error "未选择板级配置，请先执行 lunch"
        return 1
    fi
    return 0
}

_flange_check_all() {
    _flange_check_board || return 1
    _flange_check_docker || return 1
    return 0
}

# --- lunch 函数 ---
lunch() {
    local board="$1"

    # 扫描可用板子
    local boards=()
    for bzl in "$FLANGE_DIR"/board/*/board.bzl; do
        if [[ -f "$bzl" ]]; then
            local name
            name="$(basename "$(dirname "$bzl")")"
            boards+=("$name")
        fi
    done

    if [[ ${#boards[@]} -eq 0 ]]; then
        _flange_error "未找到任何板级配置（board/*/board.bzl）"
        return 1
    fi

    # 直接指定板子
    if [[ -n "$board" ]]; then
        local found=false
        for b in "${boards[@]}"; do
            if [[ "$b" == "$board" ]]; then
                found=true
                break
            fi
        done
        if ! $found; then
            _flange_error "板子不存在: $board"
            echo "  可用的板级配置:"
            for b in "${boards[@]}"; do
                echo "    - $b"
            done
            return 1
        fi
        export FLANGE_BOARD="$board"
        _flange_info "已选择: $FLANGE_BOARD"
        return 0
    fi

    # 交互式菜单
    echo ""
    echo "  可用的板级配置:"
    local i=1
    for b in "${boards[@]}"; do
        echo "    $i. $b"
        ((i++))
    done
    echo ""
    read -r -p "  请选择 (1-${#boards[@]}): " choice

    if [[ -z "$choice" ]] || [[ "$choice" -lt 1 ]] || [[ "$choice" -gt ${#boards[@]} ]] 2>/dev/null; then
        _flange_error "无效的选择: $choice"
        return 1
    fi

    export FLANGE_BOARD="${boards[$((choice-1))]}"
    _flange_info "已选择: $FLANGE_BOARD"
}

# --- Docker Compose 执行封装 ---
_flange_docker_run() {
    (cd "$FLANGE_DIR" && docker compose run --rm --build build "$@")
}

# --- flange 子命令 ---
_flange_cmd_build() {
    _flange_step "构建完整镜像: $FLANGE_BOARD"
    _flange_docker_run bazel build //image --config="$FLANGE_BOARD" "$@"
}

_flange_cmd_kernel() {
    _flange_step "构建内核: $FLANGE_BOARD"
    _flange_docker_run bazel build //kernel --config="$FLANGE_BOARD" "$@"
}

_flange_cmd_bootloader() {
    _flange_step "构建 Bootloader: $FLANGE_BOARD"
    _flange_docker_run bazel build //bootloader --config="$FLANGE_BOARD" "$@"
}

_flange_cmd_rootfs() {
    _flange_step "构建 Rootfs: $FLANGE_BOARD"
    _flange_docker_run bazel build //rootfs --config="$FLANGE_BOARD" "$@"
}

_flange_cmd_collect() {
    _flange_step "收集构建产物: $FLANGE_BOARD"
    _flange_docker_run bazel run //image:collect --config="$FLANGE_BOARD" "$@"
}

_flange_cmd_flash() {
    _flange_check_board || return 1
    _flange_step "刷写: $FLANGE_BOARD"
    "$FLANGE_DIR/scripts/flange-flash.sh" --board "$FLANGE_BOARD" "$@"
}

_flange_cmd_shell() {
    _flange_step "进入构建环境 shell"
    _flange_docker_run bash "$@"
}

_flange_cmd_sync() {
    local board_bzl="$FLANGE_DIR/board/$FLANGE_BOARD/board.bzl"
    if [[ ! -f "$board_bzl" ]]; then
        _flange_error "未找到: $board_bzl"
        return 1
    fi

    _flange_step "同步源码版本: $FLANGE_BOARD"

    local updated=false

    for section in kernel bootloader; do
        # 从 board.bzl 提取 repo 和 branch
        local repo branch current latest
        repo=$(awk -v s="\"$section\"" '$0 ~ s{f=1} f && /"repo"/{print; exit}' "$board_bzl" | sed 's/.*"repo": *"\([^"]*\)".*/\1/')
        branch=$(awk -v s="\"$section\"" '$0 ~ s{f=1} f && /"branch"/{print; exit}' "$board_bzl" | sed 's/.*"branch": *"\([^"]*\)".*/\1/')

        if [[ -z "$repo" || -z "$branch" ]]; then
            continue
        fi

        # 查询远端最新 commit
        latest=$(git ls-remote "$repo" "refs/heads/$branch" 2>/dev/null | cut -f1)
        if [[ -z "$latest" ]]; then
            _flange_warn "$section: 无法获取 $repo $branch 的最新 commit"
            continue
        fi

        # 读取当前锁定的 commit
        current=$(awk -v s="\"$section\"" '$0 ~ s{f=1} f && /"commit"/{print; exit}' "$board_bzl" | sed 's/.*"commit": *"\([^"]*\)".*/\1/')

        if [[ "$current" == "$latest" ]]; then
            _flange_info "$section: 已是最新 (${latest:0:12})"
            continue
        fi

        # 用 awk 更新对应 section 内的 commit
        awk -v s="\"$section\"" -v c="$latest" '
            $0 ~ s && /{/ { in_s = 1 }
            in_s && /"commit"/ {
                sub(/"commit": "[^"]*"/, "\"commit\": \"" c "\"")
                in_s = 0
            }
            { print }
        ' "$board_bzl" > "$board_bzl.tmp" && mv "$board_bzl.tmp" "$board_bzl"

        _flange_info "$section: ${current:0:12} → ${latest:0:12}"
        updated=true
    done

    if $updated; then
        _flange_info "board.bzl 已更新，下次构建将自动拉取新版本"
    else
        _flange_info "所有源码均为最新"
    fi
}

_flange_cmd_clean() {
    _flange_step "清理构建产物: $FLANGE_BOARD"
    local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD"
    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        _flange_info "已清理: $target_dir"
    fi
    _flange_docker_run bazel clean "$@"
}

_flange_cmd_status() {
    echo ""
    echo "  flange 构建状态"
    echo "  ─────────────────────────────"
    echo "  板级配置:  ${FLANGE_BOARD:-（未选择，请执行 lunch）}"
    echo "  项目目录:  $FLANGE_DIR"
    echo ""

    # Docker 状态
    if docker info &>/dev/null; then
        echo -e "  Docker:    ${_FLANGE_GREEN}运行中${_FLANGE_NC}"
    else
        echo -e "  Docker:    ${_FLANGE_RED}未运行${_FLANGE_NC}"
    fi

    # 构建产物状态
    if [[ -n "$FLANGE_BOARD" ]]; then
        local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD"
        echo ""
        echo "  构建产物 ($target_dir):"
        if [[ -d "$target_dir/image" ]]; then
            echo -e "    image/     ${_FLANGE_GREEN}✓${_FLANGE_NC}"
            ls -lh "$target_dir/image/" 2>/dev/null | tail -n +2 | awk '{print "      " $NF " (" $5 ")"}'
        else
            echo -e "    image/     ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
        fi
        if [[ -d "$target_dir/kernel" ]]; then
            echo -e "    kernel/    ${_FLANGE_GREEN}✓${_FLANGE_NC}"
        else
            echo -e "    kernel/    ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
        fi
        if [[ -d "$target_dir/bootloader" ]]; then
            echo -e "    bootloader/ ${_FLANGE_GREEN}✓${_FLANGE_NC}"
        else
            echo -e "    bootloader/ ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
        fi
    fi
    echo ""
}

# --- flange 主入口 ---
flange() {
    local subcmd="$1"

    if [[ -z "$subcmd" ]]; then
        echo ""
        echo "  用法: flange <subcommand> [参数...]"
        echo ""
        echo "  构建命令:"
        echo "    build        构建完整镜像"
        echo "    kernel       构建内核"
        echo "    bootloader   构建 Bootloader"
        echo "    rootfs       构建 Rootfs"
        echo "    collect      收集构建产物到 target/ 目录"
        echo ""
        echo "  刷写命令:"
        echo "    flash        刷写到目标设备"
        echo ""
        echo "  工具命令:"
        echo "    sync         同步当前板子的源码仓库（内核/bootloader/rootfs）"
        echo "    shell        进入 Docker 构建环境 shell"
        echo "    clean        清理构建产物"
        echo "    status       显示当前状态"
        echo ""
        echo "  当前板子: ${FLANGE_BOARD:-（未选择，请执行 lunch）}"
        echo ""
        return 0
    fi

    shift

    case "$subcmd" in
        build|kernel|bootloader|rootfs|collect|clean)
            _flange_check_all || return 1
            "_flange_cmd_$subcmd" "$@"
            ;;
        sync)
            _flange_check_board || return 1
            _flange_cmd_sync "$@"
            ;;
        flash)
            _flange_cmd_flash "$@"
            ;;
        shell)
            _flange_check_docker || return 1
            _flange_cmd_shell "$@"
            ;;
        status)
            _flange_cmd_status
            ;;
        *)
            _flange_error "未知子命令: $subcmd"
            flange
            return 1
            ;;
    esac
}

# --- 初始化消息 ---
_flange_info "flange 开发环境已加载"
echo "  执行 lunch 选择板级配置，然后使用 flange <subcommand> 构建"
