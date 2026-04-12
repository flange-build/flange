#!/bin/bash
# flange 开发环境初始化脚本
#
# 用法: source envsetup.sh
#
# 注入 lunch 和 flange 函数到当前 shell session。
# lunch 选择目标配置后，通过 flange <subcommand> 执行构建和刷写操作。
#
# 目标格式: <board>-<product>-<variant>
#   例: radxa-zero3w-default-release

# --- 项目根目录 ---
if [[ -n "${BASH_SOURCE[0]}" ]]; then
    FLANGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "$0" ]]; then
    FLANGE_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
export FLANGE_DIR

# --- Python venv ---
_flange_venv="${FLANGE_DIR}/.venv"
if [[ ! -d "$_flange_venv" ]]; then
    echo "[INFO] 创建 Python 虚拟环境: ${_flange_venv}"
    python3 -m venv "$_flange_venv"
    "$_flange_venv/bin/pip" install -e "${FLANGE_DIR}[dev]" --quiet
    echo "[INFO] 依赖安装完成"
fi
# shellcheck disable=SC1091
source "$_flange_venv/bin/activate"

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

# --- .flange 状态目录 ---
_FLANGE_STATE_DIR="$FLANGE_DIR/.flange"
_FLANGE_CONFIG_FILE="$_FLANGE_STATE_DIR/current_config"

_flange_ensure_state_dir() {
    if [[ ! -d "$_FLANGE_STATE_DIR" ]]; then
        mkdir -p "$_FLANGE_STATE_DIR"
    fi
}

# --- 前置检查 ---
_flange_check_docker() {
    if ! docker info &>/dev/null; then
        _flange_error "Docker 未运行，请先启动 Docker"
        return 1
    fi
    return 0
}

_flange_check_target() {
    if [[ -z "$FLANGE_BOARD" ]] || [[ -z "$FLANGE_PRODUCT" ]] || [[ -z "$FLANGE_VARIANT" ]]; then
        _flange_error "未选择目标配置，请先执行 lunch"
        return 1
    fi
    return 0
}

_flange_check_all() {
    _flange_check_target || return 1
    _flange_check_docker || return 1
    return 0
}

# --- Python 调用封装 ---
_flange_python() {
    (cd "$FLANGE_DIR" && python3 -c "$1")
}

# --- 持久化：保存当前 target 选择到 .flange/current_config ---
# current_config 只存 state pointer（board/product/variant），
# 不缓存完整 resolved config。build/flash/app 调用时通过
# config.loader.load_current_config() 每次重新 resolve，
# 确保 config 源文件变更立即生效。
_flange_save_config() {
    _flange_ensure_state_dir
    _flange_python "
from config.loader import save_state
save_state('$FLANGE_BOARD', '$FLANGE_PRODUCT', '$FLANGE_VARIANT')
"
    if [[ $? -ne 0 ]]; then
        _flange_error "保存 target 选择失败"
        return 1
    fi
    return 0
}

# --- 持久化：从 .flange/current_config 恢复状态 ---
_flange_load_config() {
    if [[ ! -f "$_FLANGE_CONFIG_FILE" ]]; then
        return 1
    fi
    local board product variant
    board=$(_flange_python "
import json
with open('.flange/current_config') as f:
    cfg = json.load(f)
print(cfg.get('board', ''))
")
    product=$(_flange_python "
import json
with open('.flange/current_config') as f:
    cfg = json.load(f)
print(cfg.get('product', ''))
")
    variant=$(_flange_python "
import json
with open('.flange/current_config') as f:
    cfg = json.load(f)
print(cfg.get('variant', ''))
")
    if [[ -n "$board" ]] && [[ -n "$product" ]] && [[ -n "$variant" ]]; then
        export FLANGE_BOARD="$board"
        export FLANGE_PRODUCT="$product"
        export FLANGE_VARIANT="$variant"
        return 0
    fi
    return 1
}

# --- lunch 函数 ---
lunch() {
    local arg="$1"
    local board="" product="" variant=""

    # 解析 --variant=X / --product=X 部分覆盖
    if [[ "$arg" == --variant=* ]]; then
        if [[ -z "$FLANGE_BOARD" ]]; then
            _flange_error "尚未选择板子，无法使用 --variant 覆盖。请先执行 lunch <board>-<product>-<variant>"
            return 1
        fi
        variant="${arg#--variant=}"
        board="$FLANGE_BOARD"
        product="$FLANGE_PRODUCT"
        # 验证 variant 合法性
        local valid
        valid=$(_flange_python "
from config.query import get_valid_targets
targets = get_valid_targets()
found = any(t == '${board}-${product}-${variant}' for t in targets)
print('yes' if found else 'no')
")
        if [[ "$valid" != "yes" ]]; then
            _flange_error "无效的 variant: $variant（目标 ${board}-${product}-${variant} 不存在）"
            return 1
        fi
        export FLANGE_BOARD="$board"
        export FLANGE_PRODUCT="$product"
        export FLANGE_VARIANT="$variant"
        _flange_save_config || return 1
        _flange_info "已选择: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
        return 0
    fi

    if [[ "$arg" == --product=* ]]; then
        if [[ -z "$FLANGE_BOARD" ]]; then
            _flange_error "尚未选择板子，无法使用 --product 覆盖。请先执行 lunch <board>-<product>-<variant>"
            return 1
        fi
        product="${arg#--product=}"
        board="$FLANGE_BOARD"
        variant="$FLANGE_VARIANT"
        # 验证 product 合法性
        local valid
        valid=$(_flange_python "
from config.query import get_valid_targets
targets = get_valid_targets()
found = any(t == '${board}-${product}-${variant}' for t in targets)
print('yes' if found else 'no')
")
        if [[ "$valid" != "yes" ]]; then
            _flange_error "无效的 product: $product（目标 ${board}-${product}-${variant} 不存在）"
            return 1
        fi
        export FLANGE_BOARD="$board"
        export FLANGE_PRODUCT="$product"
        export FLANGE_VARIANT="$variant"
        _flange_save_config || return 1
        _flange_info "已选择: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
        return 0
    fi

    # 直接指定完整目标: lunch <board>-<product>-<variant>
    if [[ -n "$arg" ]]; then
        local parsed
        parsed=$(_flange_python "
from config.query import parse_target
import json
try:
    result = parse_target('$arg')
    print(json.dumps(result))
except ValueError as e:
    print('ERROR:' + str(e))
")
        if [[ "$parsed" == ERROR:* ]]; then
            _flange_error "${parsed#ERROR:}"
            echo ""
            echo "  可用的目标配置:"
            _flange_python "
from config.query import get_valid_targets
for t in get_valid_targets():
    print('    - ' + t)
"
            return 1
        fi
        board=$(_flange_python "import json; d=json.loads('$parsed'); print(d['board'])")
        product=$(_flange_python "import json; d=json.loads('$parsed'); print(d['product'])")
        variant=$(_flange_python "import json; d=json.loads('$parsed'); print(d['variant'])")

        export FLANGE_BOARD="$board"
        export FLANGE_PRODUCT="$product"
        export FLANGE_VARIANT="$variant"
        _flange_save_config || return 1
        _flange_info "已选择: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
        return 0
    fi

    # 无参数: 交互式菜单
    local targets_raw
    targets_raw=$(_flange_python "
from config.query import get_valid_targets
for t in get_valid_targets():
    print(t)
")
    if [[ -z "$targets_raw" ]]; then
        _flange_error "未找到任何可用的目标配置（board/*/config.py）"
        return 1
    fi

    # 将输出读入数组（兼容 bash/zsh）
    local targets=()
    while IFS= read -r line; do
        targets+=("$line")
    done <<< "$targets_raw"

    if [[ ${#targets[@]} -eq 0 ]]; then
        _flange_error "未找到任何可用的目标配置"
        return 1
    fi

    echo ""
    echo "  可用的目标配置:"
    local i=1
    for t in "${targets[@]}"; do
        echo "    $i. $t"
        ((i++))
    done
    echo ""
    read -r -p "  请选择 (1-${#targets[@]}): " choice

    if [[ -z "$choice" ]] || [[ "$choice" -lt 1 ]] || [[ "$choice" -gt ${#targets[@]} ]] 2>/dev/null; then
        _flange_error "无效的选择: $choice"
        return 1
    fi

    local selected="${targets[$((choice-1))]}"
    # zsh 数组从 1 开始，bash 从 0 开始
    if [[ -z "$selected" ]] && [[ -n "${targets[$choice]}" ]]; then
        selected="${targets[$choice]}"
    fi

    local parsed
    parsed=$(_flange_python "
from config.query import parse_target
import json
result = parse_target('$selected')
print(json.dumps(result))
")
    board=$(_flange_python "import json; d=json.loads('$parsed'); print(d['board'])")
    product=$(_flange_python "import json; d=json.loads('$parsed'); print(d['product'])")
    variant=$(_flange_python "import json; d=json.loads('$parsed'); print(d['variant'])")

    export FLANGE_BOARD="$board"
    export FLANGE_PRODUCT="$product"
    export FLANGE_VARIANT="$variant"
    _flange_save_config || return 1
    _flange_info "已选择: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
}

# --- Docker Compose 执行封装 ---
_flange_docker_run() {
    (cd "$FLANGE_DIR" && docker compose run --rm build "$@")
}

# --- flange 子命令 ---
_flange_cmd_build() {
    # 解析 -v / -q 参数
    local verbose=""
    local quiet=""
    local args=()
    for arg in "$@"; do
        case "$arg" in
            -v|--verbose) verbose="True" ;;
            -q|--quiet)   quiet="True" ;;
            *)            args+=("$arg") ;;
        esac
    done
    local component="${args[0]:-image}"

    # 构建 verbose/quiet 配置注入
    local output_cfg=""
    if [[ -n "$verbose" ]]; then
        output_cfg="cfg['verbose'] = True"
    elif [[ -n "$quiet" ]]; then
        output_cfg="cfg['quiet'] = True"
    fi

    # 特殊处理: flange build app [name]
    if [[ "$component" == "app" ]]; then
        local app_name="${args[1]:-}"
        if [[ -n "$app_name" ]]; then
            _flange_docker_run python3 -c "
from builder.app import AppBuilder
from builder.docker import DockerRunner
from config.loader import load_current_config
import logging
logging.basicConfig(level=logging.WARNING)
cfg = load_current_config()
${output_cfg}
builder = AppBuilder(DockerRunner(), None, cfg)
builder.build_one('$app_name')
"
        else
            _flange_docker_run python3 -c "
from builder.app import AppBuilder
from builder.docker import DockerRunner
from config.loader import load_current_config
import logging
logging.basicConfig(level=logging.WARNING)
cfg = load_current_config()
${output_cfg}
builder = AppBuilder(DockerRunner(), None, cfg)
builder.build_all()
"
        fi
        return $?
    fi

    _flange_docker_run python3 -c "
from builder.engine import BuildEngine
from config.loader import load_current_config
import logging
logging.basicConfig(level=logging.WARNING)
cfg = load_current_config()
${output_cfg}
engine = BuildEngine(cfg)
engine.build('$component')
"
}

_flange_cmd_flash() {
    _flange_check_target || return 1
    local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
    if [[ ! -f "${target_dir}/flash-config.json" ]]; then
        _flange_error "未找到 flash-config.json: ${target_dir}/flash-config.json"
        _flange_error "请先执行 flange build 生成镜像"
        return 1
    fi
    _flange_step "刷写: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
    python3 -m builder.flash run \
        --target-dir "$target_dir" \
        --project-dir "$FLANGE_DIR" \
        "$@"
}

_flange_cmd_clean() {
    _flange_check_target || return 1
    local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
    _flange_step "清理构建产物: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        _flange_info "已清理: $target_dir"
    else
        _flange_info "无需清理: $target_dir 不存在"
    fi
}

_flange_cmd_status() {
    echo ""
    echo "  flange 构建状态"
    echo "  ─────────────────────────────"
    if [[ -n "$FLANGE_BOARD" ]]; then
        echo "  板级配置:  $FLANGE_BOARD"
        echo "  产品类型:  ${FLANGE_PRODUCT:-（未设置）}"
        echo "  构建变体:  ${FLANGE_VARIANT:-（未设置）}"
        echo "  目标:      ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
    else
        echo "  目标配置:  （未选择，请执行 lunch）"
    fi
    echo "  项目目录:  $FLANGE_DIR"
    echo ""

    # Docker 状态
    if docker info &>/dev/null; then
        echo -e "  Docker:    ${_FLANGE_GREEN}运行中${_FLANGE_NC}"
        # Docker 镜像状态
        local image_name
        image_name=$(cd "$FLANGE_DIR" && docker compose config --images 2>/dev/null | head -1)
        if [[ -n "$image_name" ]]; then
            local image_id
            image_id=$(docker images -q "$image_name" 2>/dev/null)
            if [[ -n "$image_id" ]]; then
                echo -e "  构建镜像:  ${_FLANGE_GREEN}已构建${_FLANGE_NC} ($image_name)"
            else
                echo -e "  构建镜像:  ${_FLANGE_YELLOW}未构建${_FLANGE_NC} (执行 flange docker build)"
            fi
        fi
    else
        echo -e "  Docker:    ${_FLANGE_RED}未运行${_FLANGE_NC}"
    fi

    # 构建产物状态
    if [[ -n "$FLANGE_BOARD" ]] && [[ -n "$FLANGE_PRODUCT" ]] && [[ -n "$FLANGE_VARIANT" ]]; then
        local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
        echo ""
        echo "  构建产物 ($target_dir):"
        if [[ -d "$target_dir" ]]; then
            for comp_dir in "$target_dir"/*/; do
                if [[ -d "$comp_dir" ]]; then
                    local comp_name
                    comp_name="$(basename "$comp_dir")"
                    echo -e "    ${comp_name}/  ${_FLANGE_GREEN}✓${_FLANGE_NC}"
                fi
            done
            # 列出顶层文件（如 flash.sh）
            for f in "$target_dir"/*; do
                if [[ -f "$f" ]]; then
                    local fname fsize
                    fname="$(basename "$f")"
                    fsize="$(ls -lh "$f" | awk '{print $5}')"
                    echo "    $fname ($fsize)"
                fi
            done
        else
            echo -e "    ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
        fi
    fi
    echo ""
}

_flange_cmd_shell() {
    _flange_step "进入构建环境 shell"
    _flange_docker_run bash "$@"
}

# --- flange list apps 子命令 ---
_flange_cmd_list_apps() {
    _flange_python "
from pathlib import Path
try:
    import yaml
except ImportError:
    print('  [错误] 缺少依赖：请安装 PyYAML（pip install pyyaml）')
    raise SystemExit(1)

print('')
print('  可用的 App:')
print('  ─────────────────────────────')
app_dir = Path('app')
found = False
if app_dir.exists():
    for d in sorted(app_dir.iterdir()):
        if not d.is_dir():
            continue
        yaml_file = d / 'app.yaml'
        if yaml_file.exists():
            with open(yaml_file) as f:
                spec = yaml.safe_load(f)
            app = spec.get('app', {}) if spec else {}
            name = app.get('name', d.name)
            app_type = app.get('type', 'unknown')
            version = app.get('version', '')
            desc = app.get('description', '')
            print(f'    {name:20s} {app_type:10s} {version:10s} {desc}')
            found = True
if not found:
    print('    （未找到任何 App，请在 app/ 目录下创建 App）')
print('')
"
}

# --- flange create app 子命令 ---
_flange_cmd_create_app() {
    local app_name="${1:-}"
    shift 2>/dev/null

    if [[ -z "$app_name" ]]; then
        _flange_error "用法: flange create app <name> [--type=<type>] [--build-system=<system>]"
        return 1
    fi

    # 解析可选参数 --type 和 --build-system
    local app_type="exec"
    local build_system="cmake"
    local app_version="0.1.0"
    local app_description=""
    for arg in "$@"; do
        case "$arg" in
            --type=*)         app_type="${arg#--type=}"              ;;
            --build-system=*) build_system="${arg#--build-system=}"  ;;
            --version=*)      app_version="${arg#--version=}"        ;;
            --description=*)  app_description="${arg#--description=}";;
        esac
    done

    _flange_step "生成 App 脚手架：name=$app_name  type=$app_type  build-system=$build_system"

    # 调用 Python 脚手架生成器
    python3 -c "
import sys
sys.path.insert(0, '$FLANGE_DIR')
from builder.scaffold import AppScaffold, ScaffoldError
from pathlib import Path
try:
    s = AppScaffold(project_root=Path('$FLANGE_DIR'))
    dest = s.create(
        name='$app_name',
        app_type='$app_type',
        build_system='$build_system',
        version='$app_version',
        description='$app_description',
    )
    print(dest)
except ScaffoldError as e:
    print(f'错误：{e}', file=sys.stderr)
    sys.exit(1)
"
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        _flange_info "App 脚手架已生成：app/$app_name/"
    else
        _flange_error "脚手架生成失败"
        return 1
    fi
}

# --- flange docker 子命令 ---
_flange_cmd_docker() {
    local docker_sub="$1"
    shift 2>/dev/null

    case "$docker_sub" in
        build)
            _flange_step "构建 Docker 镜像"
            (cd "$FLANGE_DIR" && docker compose build "$@")
            if [[ $? -eq 0 ]]; then
                _flange_info "Docker 镜像构建完成"
            else
                _flange_error "Docker 镜像构建失败"
                return 1
            fi
            ;;
        rebuild)
            _flange_step "重新构建 Docker 镜像（无缓存）"
            (cd "$FLANGE_DIR" && docker compose build --no-cache "$@")
            if [[ $? -eq 0 ]]; then
                _flange_info "Docker 镜像重新构建完成"
            else
                _flange_error "Docker 镜像重新构建失败"
                return 1
            fi
            ;;
        status)
            echo ""
            echo "  Docker 环境状态"
            echo "  ─────────────────────────────"
            if docker info &>/dev/null; then
                echo -e "  Docker 守护进程: ${_FLANGE_GREEN}运行中${_FLANGE_NC}"
            else
                echo -e "  Docker 守护进程: ${_FLANGE_RED}未运行${_FLANGE_NC}"
                echo ""
                return 1
            fi
            local image_name
            image_name=$(cd "$FLANGE_DIR" && docker compose config --images 2>/dev/null | head -1)
            if [[ -n "$image_name" ]]; then
                local image_info
                image_info=$(docker images --format "{{.ID}}\t{{.Size}}\t{{.CreatedAt}}" "$image_name" 2>/dev/null | head -1)
                if [[ -n "$image_info" ]]; then
                    echo "  镜像名称:       $image_name"
                    echo "  镜像 ID:        $(echo "$image_info" | cut -f1)"
                    echo "  镜像大小:       $(echo "$image_info" | cut -f2)"
                    echo "  创建时间:       $(echo "$image_info" | cut -f3)"
                else
                    echo -e "  构建镜像:       ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
                    echo "  执行 flange docker build 来构建镜像"
                fi
            fi
            echo ""
            ;;
        *)
            echo ""
            echo "  用法: flange docker <subcommand>"
            echo ""
            echo "    build     构建 Docker 镜像"
            echo "    rebuild   重新构建 Docker 镜像（无缓存）"
            echo "    status    显示 Docker 镜像状态"
            echo ""
            return 1
            ;;
    esac
}

# --- flange 主入口 ---
flange() {
    local subcmd="$1"

    if [[ -z "$subcmd" ]]; then
        echo ""
        echo "  用法: flange <subcommand> [参数...]"
        echo ""
        echo "  构建命令:"
        echo "    build [component]       构建组件（默认: image）"
        echo "    build app               构建所有 App"
        echo "    build app <name>        构建单个 App"
        echo "    clean                   清理构建产物"
        echo ""
        echo "  刷写命令:"
        echo "    flash                   全量刷写到目标设备"
        echo "    flash <partition>       刷写指定分区（如 rootfs, boot）"
        echo "    flash --list            列出可刷写分区"
        echo "    flash --raw /dev/sdX    dd 整盘刷写"
        echo "    flash --no-wait         跳过设备等待"
        echo ""
        echo "  App 命令:"
        echo "    list apps               列出所有可用 App"
        echo "    create app <name>       生成 App 脚手架"
        echo "      [--type=<type>]         App 类型（binary/service/daemon，默认: binary）"
        echo "      [--build-system=<sys>]  构建系统（cmake/make/meson，默认: cmake）"
        echo ""
        echo "  工具命令:"
        echo "    shell                   进入 Docker 构建环境 shell"
        echo "    status                  显示当前状态"
        echo "    docker <cmd>            管理 Docker 镜像（build/rebuild/status）"
        echo ""
        if [[ -n "$FLANGE_BOARD" ]]; then
            echo "  当前目标: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
        else
            echo "  当前目标: （未选择，请执行 lunch）"
        fi
        echo ""
        return 0
    fi

    shift

    case "$subcmd" in
        build)
            _flange_check_all || return 1
            _flange_cmd_build "$@"
            ;;
        flash)
            _flange_cmd_flash "$@"
            ;;
        clean)
            _flange_cmd_clean "$@"
            ;;
        list)
            # flange list apps
            local list_target="${1:-}"
            case "$list_target" in
                apps)
                    _flange_cmd_list_apps
                    ;;
                *)
                    _flange_error "用法: flange list apps"
                    return 1
                    ;;
            esac
            ;;
        create)
            # flange create app <name> [--type=<type>] [--build-system=<system>]
            local create_target="${1:-}"
            shift 2>/dev/null
            case "$create_target" in
                app)
                    _flange_cmd_create_app "$@"
                    ;;
                *)
                    _flange_error "用法: flange create app <name>"
                    return 1
                    ;;
            esac
            ;;
        shell)
            _flange_check_docker || return 1
            _flange_cmd_shell "$@"
            ;;
        status)
            _flange_cmd_status
            ;;
        docker)
            _flange_cmd_docker "$@"
            ;;
        *)
            _flange_error "未知子命令: $subcmd"
            flange
            return 1
            ;;
    esac
}

# --- 初始化：恢复上次配置 ---
if _flange_load_config; then
    _flange_info "flange 开发环境已加载（恢复上次配置: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}）"
else
    _flange_info "flange 开发环境已加载"
fi
echo "  执行 lunch 选择目标配置，然后使用 flange <subcommand> 构建"
