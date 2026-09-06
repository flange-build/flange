#!/bin/bash
# 中文入口说明：source envsetup.sh；安装后的 flange 也可直接在任意工作区使用。
# Shell 只准备 Python 环境；目标状态、路径和命令分派统一由 Python 管理。

if [ -n "${BASH_VERSION:-}" ]; then
    FLANGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -n "${ZSH_VERSION:-}" ]; then
    FLANGE_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
    echo '请使用 Bash 或 Zsh source envsetup.sh' >&2
    return 1
fi
export FLANGE_DIR

_flange_bootstrap() (
    # 只在初始化子进程启用失败退出，不输出命令跟踪，也不改变调用者的 shell 选项。
    set -e
    if [ ! -x "$FLANGE_DIR/.venv/bin/python3" ]; then
        python3 -m venv "$FLANGE_DIR/.venv" || exit 1
    fi
    if [ ! -f "$FLANGE_DIR/.venv/.flange-installed" ] || \
       [ ! -x "$FLANGE_DIR/.venv/bin/flange" ] || \
       [ "$FLANGE_DIR/pyproject.toml" -nt "$FLANGE_DIR/.venv/.flange-installed" ] || \
       ! "$FLANGE_DIR/.venv/bin/python3" -c 'import _jsonnet, yaml, builder.cli' 2>/dev/null; then
        "$FLANGE_DIR/.venv/bin/python3" -m pip install -e "${FLANGE_DIR}[dev]" || exit 1
        touch "$FLANGE_DIR/.venv/.flange-installed"
    fi
)

if ! _flange_bootstrap; then
    echo 'flange 初始化失败；修复上方 Python/安装错误后重新 source。' >&2
    return 1
fi
unset -f _flange_bootstrap
# shellcheck disable=SC1091
source "$FLANGE_DIR/.venv/bin/activate"
# 从旧 shell session 重载时，清除旧业务分派函数，使 PATH 中的安装入口生效。
unset -f flange 2>/dev/null || true
lunch() { command flange target select "$@"; }
if [ -t 1 ]; then
    "$FLANGE_DIR/.venv/bin/python3" -c 'from builder.presentation import render_ready; print(render_ready())'
fi
