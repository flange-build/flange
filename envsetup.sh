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
#
# ── host 端刷写依赖（按平台）─────────────────────────────────────────────
# Rockchip:      tools/linux/upgrade_tool/upgrade_tool（仓库自带，无须安装）
# Allwinner:     dd（系统自带；SD 卡 dd 模式）
# Amlogic:       pip install pyamlboot                  # 提供 boot-g12.py 入口
#                sudo apt install android-tools-fastboot # 提供 fastboot 命令
#                Linux：  sudo apt install libusb-1.0-0  # pyusb 底层 USB 库
#                macOS：  brew install libusb android-platform-tools
#                         （pyusb 在 macOS 上不自带 libusb，缺会报 No backend
#                         available）
#                pyamlboot 详见 https://github.com/superna9999/pyamlboot
# ────────────────────────────────────────────────────────────────────────

# --- 项目根目录 ---
if [[ -n "${BASH_SOURCE[0]}" ]]; then
    FLANGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "$0" ]]; then
    FLANGE_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
export FLANGE_DIR

# --- Python venv ---
#
# 依赖校验必须**每次 source 都做**，不能只在创建 venv 时做一次：
#   - 首次 pip install 失败（jsonnet 要从源码编译，最容易栽在这一步）后，
#     .venv 目录已经存在，再 source 永远不会补装，且症状是 import 报错而
#     不是"依赖没装"
#   - pyproject.toml 新增依赖后，老 venv 同样不会跟进
# 校验本身只是一次 import 探测（毫秒级），不影响 source 速度。
_flange_venv="${FLANGE_DIR}/.venv"
_flange_dep_stamp="${_flange_venv}/.flange-deps-installed"

# 依赖是否就绪：探针 import 全部核心依赖，且 pyproject.toml 未在上次安装后改动。
_flange_deps_ready() {
    [[ -f "$_flange_dep_stamp" ]] || return 1
    [[ "${FLANGE_DIR}/pyproject.toml" -nt "$_flange_dep_stamp" ]] && return 1
    "$_flange_venv/bin/python3" -c "import _jsonnet, yaml" 2>/dev/null
}

_flange_install_deps() {
    echo "[INFO] 安装 Python 依赖..."
    if ! "$_flange_venv/bin/pip" install -e "${FLANGE_DIR}[dev]" --quiet; then
        echo "[ERROR] Python 依赖安装失败。" >&2
        echo "        jsonnet 需从源码编译，请确认 C++ 工具链可用：" >&2
        echo "          macOS         xcode-select --install" >&2
        echo "          Debian/Ubuntu sudo apt install build-essential python3-dev" >&2
        echo "        修好后重新 source envsetup.sh，或手动执行：" >&2
        echo "          ${_flange_venv}/bin/pip install -e '${FLANGE_DIR}[dev]'" >&2
        return 1
    fi
    # 只有真正装成功才落 stamp —— 失败时留空，下次 source 会重试
    : > "$_flange_dep_stamp"
    echo "[INFO] 依赖安装完成"
}

if [[ ! -d "$_flange_venv" ]]; then
    echo "[INFO] 创建 Python 虚拟环境: ${_flange_venv}"
    if ! python3 -m venv "$_flange_venv"; then
        echo "[ERROR] 创建虚拟环境失败: ${_flange_venv}" >&2
    fi
fi
if [[ ! -x "$_flange_venv/bin/python3" ]]; then
    # venv 目录在但 python 不可执行 —— 静默跳过等于把问题藏起来，
    # 症状会变成后续每条命令都 command not found。
    echo "[ERROR] 虚拟环境不完整（缺 bin/python3）: ${_flange_venv}" >&2
    echo "        删除后重新 source 可重建: rm -rf '${_flange_venv}'" >&2
elif ! _flange_deps_ready; then
    _flange_install_deps
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

# 状态的唯一真相源是 .flange/current_config —— `flange build` 读的就是它
# （builder/config/loader.py::load_current_config）。shell 里的 FLANGE_BOARD
# 等只是它的投影，用于提示符显示。两者会分叉：在另一个 shell 里 lunch 过、
# 或手工改过 env。凡是会写盘或写硬件的命令都必须以文件为准，否则
# `flange status` 显示 A 而 `flange build` 造 B，而 CLAUDE.md 的刷写安全
# 规程恰恰建立在 status 的显示上。
_flange_read_state() {
    local state="$FLANGE_DIR/.flange/current_config"
    [[ -f "$state" ]] || return 1
    python3 -c "
import json, sys
try:
    s = json.load(open('$state'))
    print(s['board'], s.get('product', 'default'), s.get('variant', 'release'))
except Exception:
    sys.exit(1)
" 2>/dev/null
}

# 解析真相源到 FLANGE_TARGET_{BOARD,PRODUCT,VARIANT}，并在 shell 投影与它
# 不一致时告警。成功返回 0；未 lunch 过返回 1。
_flange_check_target() {
    local triple
    triple=$(_flange_read_state) || {
        _flange_error "未选择目标配置，请先执行 lunch"
        return 1
    }
    read -r FLANGE_TARGET_BOARD FLANGE_TARGET_PRODUCT FLANGE_TARGET_VARIANT <<< "$triple"

    local shown="${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
    local actual="${FLANGE_TARGET_BOARD}-${FLANGE_TARGET_PRODUCT}-${FLANGE_TARGET_VARIANT}"
    if [[ -n "$FLANGE_BOARD" && "$shown" != "$actual" ]]; then
        _flange_warn "本 shell 显示 ${shown}，实际目标是 ${actual}"
        _flange_warn "以 .flange/current_config 为准；在本 shell 重新 lunch 可同步显示"
    fi
    return 0
}

# 当前目标的产物目录（按真相源，不按 shell 投影）。
_flange_target_dir() {
    echo "$FLANGE_DIR/.build/target/$FLANGE_TARGET_BOARD/$FLANGE_TARGET_PRODUCT/$FLANGE_TARGET_VARIANT"
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
from builder.config.loader import save_state
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

    if [[ "$arg" == "-h" ]] || [[ "$arg" == "--help" ]]; then
        echo "  用法: lunch [target|选项]"
        echo ""
        echo "  不带参数时打开层级选择界面：按 平台 → SoC → 板 → product →"
        echo "  variant 浏览，停在末级目标上会显示它的完整配置表。"
        echo ""
        echo "    ↑↓ 移动    ←→ 折叠/展开    Enter 选中    / 过滤    q 取消"
        echo ""
        echo "  参数:"
        echo "    <board>-<product>-<variant>   直接选定目标，不进界面"
        echo "    --product=<name>              仅替换当前目标的 product"
        echo "    --variant=<name>              仅替换当前目标的 variant"
        echo "    --no-tui                      用编号列表代替界面"
        echo "    -h, --help                    显示此帮助"
        echo ""
        echo "  非 TTY 环境（管道、CI）自动回退到编号列表。"
        return 0
    fi

    # --no-tui 只是交互形式的开关，不是目标名 —— 必须在"直接指定目标"
    # 分支之前摘掉，否则会被当成 board 名去解析。
    if [[ "$arg" == "--no-tui" ]]; then
        arg=""
        local _lunch_no_tui=1
    fi

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
from builder.config.query import get_valid_targets
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
from builder.config.query import get_valid_targets
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
from builder.config.query import parse_target
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
from builder.config.query import get_valid_targets
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

    # 无参数: 优先层级 TUI，非 TTY 或 --no-tui 回退编号列表
    if [[ -z "${_lunch_no_tui:-}" ]] && [[ -t 0 ]] && [[ -t 1 ]]; then
        local _lunch_out
        _lunch_out=$(mktemp "${TMPDIR:-/tmp}/flange-lunch.XXXXXX") || return 1
        # TUI 直接占用终端；选择结果经文件回传 —— 子进程改不了父 shell 的
        # 环境变量，而 $(...) 捕获会把 curses 的输出一并吞掉。
        (cd "$FLANGE_DIR" && python3 -m builder.lunch_tui \
            --current "${FLANGE_BOARD:+${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}}" \
            --out "$_lunch_out")
        local _lunch_rc=$?
        local selected=""
        [[ -s "$_lunch_out" ]] && selected=$(<"$_lunch_out")
        rm -f "$_lunch_out"
        if [[ $_lunch_rc -eq 1 ]] || [[ -z "$selected" ]]; then
            _flange_info "已取消，当前目标不变"
            return 0
        fi
        if [[ $_lunch_rc -ne 0 ]]; then
            _flange_warn "选择界面不可用，回退到列表模式"
        else
            local parsed
            parsed=$(_flange_python "
from builder.config.query import parse_target
import json
print(json.dumps(parse_target('$selected')))
") || return 1
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
    fi

    local targets_raw
    targets_raw=$(_flange_python "
from builder.config.query import get_valid_targets
for t in get_valid_targets():
    print(t)
")
    if [[ -z "$targets_raw" ]]; then
        _flange_error "未找到任何可用的目标配置（components/board/*/config.py）"
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
from builder.config.query import parse_target
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
_flange_oot_mount_pairs() {
    # FINAL_CONFIG 中的 local_path 由宿主项目根解析；容器内项目根固定为
    # /workspace。把外部 App 所在 git worktree（无 git 时为 App 目录）映射到
    # 容器中对应的规范化路径，使整体 image/amp 构建也能消费 OOT 源。
    _flange_python '
from builder.oot_mounts import print_mount_pairs

print_mount_pairs()
'
}

_flange_docker_run() {
    local pairs=""
    local docker_args=()
    pairs=$(_flange_oot_mount_pairs) || return 1
    if [[ -n "$pairs" ]]; then
        while IFS=$'\t' read -r source target; do
            if [[ -n "$source" ]] && [[ -n "$target" ]]; then
                docker_args+=(--volume "${source}:${target}:rw")
            fi
        done <<< "$pairs"
    fi
    (cd "$FLANGE_DIR" && docker compose run --rm "${docker_args[@]}" build "$@")
}

# --- flange 子命令 ---
_flange_cmd_build() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange build [component] [options]"
        echo ""
        echo "  构建指定的组件，或者构建整个系统镜像。"
        echo ""
        echo "  组件:"
        echo "    image (默认)         构建完整的系统镜像 (包含所有依赖)"
        echo "    app                  构建所有的应用"
        echo "    app <name-or-path>   构建单个应用，参数可为名称或宿主机目录路径"
        echo "                         （含 / 或 . 或目录存在且含 app.yaml 时视为路径）"
        echo "    <component>          构建指定的组件 (如: kernel, u-boot, rootfs)"
        echo ""
        echo "  选项:"
        echo "    -f, --force    清除缓存并强制重新构建"
        echo "    -v, --verbose  显示详细的构建日志"
        echo "    -q, --quiet    静默模式，只显示错误"
        echo "    -h, --help     显示此帮助信息"
        return 0
    fi
    # 解析 -v / -q / -f 参数
    # 注：不用 ${args[0]} 取首个 positional —— bash 数组 0-indexed，zsh 默认
    # 1-indexed，下标语义不一致。envsetup.sh 同时被 bash 与 zsh source，所以
    # 边解析边捕获 positional，避开数组下标。
    local verbose=""
    local quiet=""
    local force=""
    local component_arg=""
    local app_name=""
    for arg in "$@"; do
        case "$arg" in
            -v|--verbose) verbose="True" ;;
            -q|--quiet)   quiet="True" ;;
            -f|--force)   force="1" ;;
            *)
                if [[ -z "$component_arg" ]]; then
                    component_arg="$arg"
                elif [[ -z "$app_name" ]]; then
                    app_name="$arg"
                fi
                ;;
        esac
    done

    # -f：强制重建 —— 交给引擎跳过 is_up_to_date 缓存校验（引擎在容器内以 root 跑、
    # 构建后照常 store 覆盖 .build_hash），不再由宿主用户删 root 拥有的 .build_hash：
    # 该文件及其父目录均由 Docker 以 root 建，宿主普通用户删不动（权限不够）。
    # force_py 注入下面的 engine.build(...)：None=正常缓存 / '组件'=只强制该组件 / 'all'=全部。
    local force_py="None"
    if [[ -n "$force" ]]; then
        if [[ -n "$component_arg" ]]; then
            force_py="'$component_arg'"
            _flange_info "强制重建 $component_arg（跳过缓存）"
        else
            force_py="'all'"
            _flange_info "强制重建所有组件（跳过缓存）"
        fi
    fi

    local component="${component_arg:-image}"

    # 构建 verbose/quiet 配置注入
    local output_cfg=""
    if [[ -n "$verbose" ]]; then
        output_cfg="cfg['verbose'] = True"
    elif [[ -n "$quiet" ]]; then
        output_cfg="cfg['quiet'] = True"
    fi

    # 特殊处理: flange build app [name-or-path]
    if [[ "$component" == "app" ]]; then
        if [[ -n "$app_name" ]]; then
            _flange_cmd_resource app build "$app_name"
        else
            _flange_docker_run python3 -c "
from pathlib import Path
from builder.app import AppBuilder
from builder.cache import BuildCache
from builder.docker import DockerRunner
from builder.source import SourceManager
from builder.config.loader import load_current_config
import logging
logging.basicConfig(level=logging.WARNING)
cfg = load_current_config()
${output_cfg}
root = Path('.').resolve()
source = SourceManager(project_root=root)
builder = AppBuilder(DockerRunner(), source, cfg)
builder.cache = BuildCache(cfg, project_root=root)
builder.build_all(force=bool('$force'))
"
        fi
        return $?
    fi

    _flange_docker_run python3 -c "
from builder.engine import BuildEngine
from builder.config.loader import load_current_config
import logging
logging.basicConfig(level=logging.WARNING)
cfg = load_current_config()
${output_cfg}
engine = BuildEngine(cfg)
engine.build('$component', force=$force_py)
"
}

_flange_cmd_flash() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange flash [options] [partition]"
        echo ""
        echo "  将构建好的镜像刷写到目标设备。"
        echo ""
        echo "  参数:"
        echo "    partition      指定要刷写的分区名 (例如: rootfs, boot)。如果不指定，则全量刷写。"
        echo ""
        echo "  选项:"
        echo "    --list         列出目标设备所有可刷写的分区及状态"
        echo "    --raw <DEV>    使用 dd 将整盘镜像直接刷写到块设备 (如 /dev/sdX)"
        echo "    --spi-firmware 刷写 Qualcomm SPI boot 固件（仅显式指定时执行；需 EDL 模式）"
        echo "    --provision-ufs [lun0-only|qcom]  初始化全新 Qualcomm UFS（默认 lun0-only）"
        echo "      lun0-only: 单个用户 LUN 0；qcom: 官方标准 LUN 0-7 多 LUN 布局"
        echo "    --no-wait      刷写时跳过等待设备进入烧录模式的提示"
        echo "    --no-reboot    刷写完成后不触发设备重启 (用于多次刷写或人工接管)"
        echo "    -h, --help     显示此帮助信息"
        return 0
    fi
    _flange_check_target || return 1
    local target_dir="$(_flange_target_dir)"
    if [[ ! -f "${target_dir}/flash-config.json" ]]; then
        _flange_error "未找到 flash-config.json: ${target_dir}/flash-config.json"
        _flange_error "请先执行 flange build 生成镜像"
        return 1
    fi
    _flange_step "刷写: ${FLANGE_TARGET_BOARD}-${FLANGE_TARGET_PRODUCT}-${FLANGE_TARGET_VARIANT}"
    # 刷写是破坏性操作：把"刷的是哪个 target、产物是什么时候造的"摆在眼前，
    # 而不是让用户去别处确认。
    _flange_info "产物生成于 $(date -r "${target_dir}/flash-config.json" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '未知时间')"
    python3 -m builder.flash run \
        --target-dir "$target_dir" \
        --project-dir "$FLANGE_DIR" \
        "$@"
}

_flange_cmd_recovery() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        cat <<'EOF'
  用法: flange recovery <subcommand> [args] [options]

  通过 USB ADB 编排设备端 recoveryctl，完成在线分区刷写、备份与维护。

  模式切换:
    enter                       让设备从 normal 进入 recovery
    reboot [normal|recovery|loader]
                                请求目标模式并重启（默认 normal）

  只读查询:
    list [--json]               列出分区与挂载状态
    shell                       打开 ADB 交互式 shell

  分区操作（要求设备处于 recovery 模式）:
    flash <partition> <image>   把本机镜像写入指定分区
                                  [--force]  强制写受保护分区（需输入 YES 确认）
    backup <partition> <output> 把分区备份到本机文件
                                  [--compress=zstd|none]   默认 zstd

  典型工作流:
    flange build && flange flash                  # 首次刷写
    flange recovery enter                         # 进 recovery
    flange recovery list                          # 看分区状态
    flange recovery backup rootfs ~/bk.img.zst    # 备份 rootfs
    flange recovery flash rootfs new-rootfs.img   # 在线刷新 rootfs
    flange recovery reboot                        # 回 normal

  分区名:
    按设备 /etc/flange/recovery-config.json 命名（如 idbloader、uboot、boot、
    rootfs、recovery、userdata）。运行 `flange recovery list` 查看当前可用名。
    ⚠ 不接受裸 block device 路径（如 /dev/mmcblk0p2）。

  安全约束:
    • flash / backup 仅在 recovery 模式下生效，normal 模式下硬性拒绝
    • 进入 recovery 使用 reboot reason，由 U-Boot 选择 recovery.conf
      不持久修改 extlinux DEFAULT
    • bootloader、raw 类型分区与 recovery 自身默认受保护
    • 写入受保护分区需 --force（宿主输入字面量 YES）+ 设备端要求 --sha256
    • 写入前自动校验：分区存在 / 未挂载 / sha256 / 大小不超分区

  前提:
    宿主机 PATH 中可执行 adb；设备已通过 USB 连接并启用 USB gadget。
    详细文档与排障：docs/recovery.md

  单条子命令的详细帮助：flange recovery <subcommand> --help
EOF
        return 0
    fi
    python3 -m builder.recovery_host "$@"
}

_flange_cmd_clean() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange clean [--all]"
        echo ""
        echo "  清理当前目标的构建产物（.build/target/<board>/<product>/<variant>）。"
        echo ""
        echo "  默认**不**清理这三处跨目标共享的派生物："
        echo "    .build/work/apps/       App 与包内单元的中间产物"
        echo "    .build/target/.cache/   rootfs / recovery 的 Phase 1 base 快照"
        echo "    .build/sources/         源码检出与下载缓存"
        echo "  它们重建代价高（Phase 1 以分钟计）且与当前目标无关，所以留着。"
        echo "  --all 连同前两者一起清（源码缓存始终保留，重下代价最高）。"
        return 0
    fi
    _flange_check_target || return 1
    local clean_all=""
    [[ "$1" == "--all" ]] && clean_all="1"

    local target_dir="$(_flange_target_dir)"
    _flange_step "清理构建产物: ${FLANGE_TARGET_BOARD}-${FLANGE_TARGET_PRODUCT}-${FLANGE_TARGET_VARIANT}"
    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        _flange_info "已清理: $target_dir"
    else
        _flange_info "无需清理: $target_dir 不存在"
    fi

    local work_dir="$FLANGE_DIR/.build/work/apps"
    local cache_dir="$FLANGE_DIR/.build/target/.cache"
    if [[ -n "$clean_all" ]]; then
        for extra in "$work_dir" "$cache_dir"; do
            if [[ -d "$extra" ]]; then
                rm -rf "$extra"
                _flange_info "已清理: $extra"
            fi
        done
        _flange_info "源码缓存 .build/sources/ 始终保留（重下代价最高）"
    else
        # 说实话：不列出来，用户会以为 clean 之后是干净重建。
        local kept=""
        [[ -d "$work_dir" ]] && kept="${kept}    $(du -sh "$work_dir" 2>/dev/null | cut -f1)\t.build/work/apps/\n"
        [[ -d "$cache_dir" ]] && kept="${kept}    $(du -sh "$cache_dir" 2>/dev/null | cut -f1)\t.build/target/.cache/\n"
        if [[ -n "$kept" ]]; then
            echo "  未清理（跨目标共享，用 --all 一并清理）:"
            printf "$kept"
        fi
    fi
}

_flange_cmd_why() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange why [component]"
        echo ""
        echo "  解释增量构建的缓存决策：命中，还是哪一段输入变了。"
        echo "  不带参数时依次解释全部组件。"
        echo ""
        echo "  分段含义:"
        echo "    dep:<上游>   上游组件产物变化（Merkle 级联）"
        echo "    identity     平台 / SoC / 板 / 架构等构建身份"
        echo "    config       该组件相关的配置切片"
        echo "    logic        参与构建的 builder 代码与 Docker 定义"
        echo "    own          该组件自身输入：源码、补丁、overlay、App 等"
        return 0
    fi
    _flange_docker_run python3 -c "
import json
from builder.cache import BuildCache, DEPENDENCY_GRAPH
from builder.config.loader import load_current_config

cfg = load_current_config()
cache = BuildCache(cfg)
wanted = ['$1'] if '$1' else list(DEPENDENCY_GRAPH)
print()
for component in wanted:
    report = cache.explain(component)
    mark = '命中' if report['up_to_date'] else '需重建'
    print(f\"  {component:<20} {mark}\")
    if report['note']:
        print(f\"      {report['note']}\")
    for reason in report['reasons']:
        print(f\"      变化: {reason['segment']}\")
    if not report['up_to_date'] and component == 'app':
        for name in cache._app_names_for_explain():
            state = '命中' if cache.is_app_up_to_date(name) else '需重建'
            print(f\"        App {name:<32} {state}\")
print()
"
}

_flange_cmd_status() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange status"
        echo ""
        echo "  显示当前的开发环境配置和构建状态。"
        return 0
    fi
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
        local target_dir="$(_flange_target_dir)"
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
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange shell [command]"
        echo ""
        echo "  进入 Docker 构建环境的交互式 Shell，或者在 Docker 中执行指定命令。"
        return 0
    fi
    _flange_step "进入构建环境 shell"
    _flange_docker_run bash "$@"
}

# --- flange list apps 子命令 ---
_flange_cmd_list_apps() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        echo "  用法: flange list apps"
        echo ""
        echo "  列出项目中所有可用的应用 (Apps)。"
        return 0
    fi
    _flange_python "
from pathlib import Path
try:
    import yaml  # noqa: F401 —— builder.app_list 内按需使用
except ImportError:
    print('  [错误] 缺少依赖：请安装 PyYAML（pip install pyyaml）')
    raise SystemExit(1)

from builder.app_list import list_all, format_lines

# 尝试加载当前 lunch 选择的 config；无 lunch 时 config=None，仅列本地 App
config = None
try:
    from builder.config.loader import load_current_config
    config = load_current_config()
except FileNotFoundError:
    pass
except Exception as e:
    print(f'  [警告] 当前配置无法加载（{type(e).__name__}），仅列出本地 App')

entries = list_all(project_root=Path('$FLANGE_DIR'), config=config)

print('')
print('  可用的 App:')
print('  ─────────────────────────────')
for line in format_lines(entries):
    print(line)
print('')
"
}

# --- App / Package 资源优先命令 ---
_flange_cmd_resource() {
    local resource="$1"
    shift
    local action="${1:---help}"
    local show_help=""
    if [[ $# -gt 0 ]]; then
        shift
    fi

    for arg in "$@"; do
        case "$arg" in
            -h|--help) show_help="1" ;;
        esac
    done
    if [[ -z "$show_help" ]]; then
        case "$action" in
            ""|-h|--help|create) ;;
            build) _flange_check_all || return 1 ;;
            *) _flange_check_target || return 1 ;;
        esac
    fi

    PYTHONPATH="$FLANGE_DIR${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -P -m builder.dev "$resource" "$action" "$@"
}

# --- 旧 verb-first App 命令：委托给同一资源优先实现 ---
_flange_cmd_create_app() {
    local has_dir=""
    for arg in "$@"; do
        case "$arg" in
            --dir|--dir=*) has_dir="1" ;;
        esac
    done
    if [[ -n "$has_dir" ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        _flange_cmd_resource app create "$@"
    else
        _flange_cmd_resource app create "$@" --dir "$FLANGE_DIR/components/app"
    fi
}

_flange_cmd_push() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        _flange_cmd_resource app deploy --help
        return $?
    fi
    if [[ "$1" != "app" ]]; then
        _flange_error "用法: flange push app <name-or-path>"
        return 1
    fi
    shift
    if [[ $# -eq 0 ]]; then
        _flange_error "用法: flange push app <name-or-path>"
        return 1
    fi
    _flange_cmd_resource app deploy "$@"
}

_flange_cmd_run() {
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        _flange_cmd_resource app run --help
        return $?
    fi
    if [[ "$1" != "app" ]]; then
        _flange_error "用法: flange run app <name-or-path>"
        return 1
    fi
    shift
    if [[ $# -eq 0 ]]; then
        _flange_error "用法: flange run app <name-or-path>"
        return 1
    fi
    _flange_cmd_resource app run "$@"
}

# --- flange docker 子命令 ---
_flange_cmd_docker() {
    local docker_sub="$1"

    if [[ "$docker_sub" == "-h" ]] || [[ "$docker_sub" == "--help" ]] || [[ -z "$docker_sub" ]]; then
        echo "  用法: flange docker <subcommand>"
        echo ""
        echo "  管理构建环境的 Docker 镜像。"
        echo ""
        echo "  子命令:"
        echo "    build     构建 Docker 镜像"
        echo "    rebuild   重新构建 Docker 镜像（不使用缓存）"
        echo "    status    显示 Docker 镜像当前状态"
        echo "    -h, --help 显示此帮助信息"
        return 0
    fi

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
            echo "未知子命令: $docker_sub"
            _flange_cmd_docker --help
            return 1
            ;;
    esac
}

# --- flange 主入口 ---
flange() {
    local subcmd="$1"

    if [[ -z "$subcmd" ]] || [[ "$subcmd" == "-h" ]] || [[ "$subcmd" == "--help" ]]; then
        echo ""
        echo "  flange - 嵌入式 Linux 系统构建框架"
        echo "  =================================="
        echo "  用法: flange <command> [args...] [options]"
        echo ""
        echo "  核心模块 (Modules):"
        echo "    app        App 的创建、构建、部署、运行、调试与日志"
        echo "    package    Package 的创建、构建、部署、运行、调试与日志"
        echo "    build      [构建] 编译系统组件或应用"
        echo "    flash      [刷写] 将镜像烧录到目标设备"
        echo "    recovery   [线刷] USB ADB 通道线刷 / 备份 / 维护设备"
        echo "    push       [部署] 热部署单个应用到目标设备"
        echo "    run        [调试] 热部署并立即运行单个应用"
        echo "    create     [脚手架] 生成新的应用或组件模板"
        echo "    list       [查询] 列出可用的应用列表"
        echo ""
        echo "  环境与工具 (Environment & Tools):"
        echo "    docker     管理 Docker 构建环境镜像"
        echo "    shell      进入构建环境 (Docker) 的交互式 Shell"
        echo "    clean      清理当前目标的构建产物（--all 连同共享缓存）"
        echo "    status     显示当前配置和构建状态"
        echo "    why        解释缓存决策：哪一段输入变了导致重建"
        echo ""
        if [[ -n "$FLANGE_BOARD" ]]; then
            echo "  当前目标: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}"
        else
            echo "  当前目标: （未选择，请执行 lunch）"
        fi
        echo ""
        echo "  获取更多帮助:"
        echo "    flange <command> --help"
        echo ""
        return 0
    fi

    shift

    case "$subcmd" in
        app|package)
            _flange_cmd_resource "$subcmd" "$@"
            ;;
        build)
            _flange_check_all || return 1
            _flange_cmd_build "$@"
            ;;
        flash)
            _flange_cmd_flash "$@"
            ;;
        recovery)
            _flange_cmd_recovery "$@"
            ;;
        clean)
            _flange_cmd_clean "$@"
            ;;
        push)
            _flange_cmd_push "$@"
            ;;
        run)
            _flange_cmd_run "$@"
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
        why)
            _flange_check_docker || return 1
            _flange_cmd_why "$@"
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

# --- 便捷软链接：target -> .build/target（幂等创建，已 gitignore） ---
# 保留根目录 target 入口，便于刷写/查看产物，无需键入完整 .build/target/ 路径。
# 策略：
#   - 已是指向 .build/target 的符号链接：无操作
#   - 不存在：创建链接（目标目录 .build/target 可不存在，链接允许暂时悬空）
#   - 是其他符号链接：修正为正确目标
#   - 是普通文件/目录：打印 WARN 并跳过，由用户手动处置，避免误删数据
_flange_ensure_target_link() {
    local link_path="$FLANGE_DIR/target"
    local link_target=".build/target"
    if [[ -L "$link_path" ]]; then
        local current
        current=$(readlink "$link_path")
        if [[ "$current" == "$link_target" ]]; then
            return 0
        fi
        rm "$link_path"
        ln -s "$link_target" "$link_path"
        return 0
    fi
    if [[ -e "$link_path" ]]; then
        _flange_warn "target 位置已有非链接文件/目录，跳过软链接创建: $link_path"
        return 0
    fi
    ln -s "$link_target" "$link_path"
}
_flange_ensure_target_link

# --- 初始化：恢复上次配置 ---
if _flange_load_config; then
    _flange_info "flange 开发环境已加载（恢复上次配置: ${FLANGE_BOARD}-${FLANGE_PRODUCT}-${FLANGE_VARIANT}）"
else
    _flange_info "flange 开发环境已加载"
fi
echo "  执行 lunch 选择目标配置，然后使用 flange <subcommand> 构建"
