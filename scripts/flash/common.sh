#!/bin/bash
# 刷写通用工具函数

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

log_step() {
    echo -e "${BLUE}==>${NC} $*"
}

# 确认操作
confirm_action() {
    local message="$1"
    echo -e "${YELLOW}${message}${NC}"
    read -r -p "确认继续？[y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# 检查命令是否存在
check_command() {
    local cmd="$1"
    local install_hint="$2"
    if ! command -v "$cmd" &>/dev/null; then
        log_error "未找到 $cmd"
        if [ -n "$install_hint" ]; then
            echo "  安装方法: $install_hint"
        fi
        return 1
    fi
    return 0
}

# 检查产物目录
check_image_dir() {
    local board="$1"
    local image_dir="target/${board}/image"

    if [ ! -d "$image_dir" ]; then
        log_error "产物目录不存在: $image_dir"
        echo "  请先执行构建和收集:"
        echo "    docker compose run --rm build bazel build //image --config=${board}"
        echo "    docker compose run --rm build bazel run //image:collect --config=${board}"
        return 1
    fi
    echo "$image_dir"
}
