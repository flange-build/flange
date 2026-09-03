"""envsetup.sh 的环境自举契约。

**为什么需要它**：依赖安装曾被写在 `if [[ ! -d "$_flange_venv" ]]` 分支里 ——
只在**首次创建 venv** 时执行一次。于是：

  - 首次 `pip install` 失败（jsonnet 要从源码编译，最容易栽在这一步）后
    `.venv` 目录已经存在，之后再怎么 source 都不会补装；
  - pyproject.toml 新增依赖，老 venv 不会跟进。

两种情况的症状都不是"依赖没装"，而是后续某条命令抛 ModuleNotFoundError，
离根因很远。而且当时 `pip install` 的退出码根本没被检查，失败照样打印
"依赖安装完成"。

这些都没法用单测跑真实的 pip，所以这里锁**结构**：校验逻辑必须在创建分支
之外、失败必须被检查、成功才落 stamp。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENVSETUP = ROOT / "envsetup.sh"


@pytest.fixture(scope="module")
def script() -> str:
    return ENVSETUP.read_text(encoding="utf-8")


def test_envsetup存在(script: str):
    assert "_flange_venv" in script


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_语法在两种shell下都合法(shell: str):
    """envsetup.sh 同时被 bash 与 zsh source，两边都要能解析。"""
    if not _has(shell):
        pytest.skip(f"{shell} 不可用")
    result = subprocess.run([shell, "-n", str(ENVSETUP)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def _has(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def _venv_creation_block(script: str) -> str:
    """截出 `if [[ ! -d "$_flange_venv" ]]` 到其 fi 之间的内容。"""
    start = script.index('if [[ ! -d "$_flange_venv" ]]')
    depth = 0
    lines = script[start:].splitlines(keepends=True)
    out = []
    for line in lines:
        out.append(line)
        stripped = line.strip()
        if stripped.startswith("if "):
            depth += 1
        elif stripped == "fi" or stripped.startswith("fi "):
            depth -= 1
            if depth == 0:
                break
    return "".join(out)


def test_依赖安装不在venv创建分支里(script: str):
    """这正是原来的 bug：venv 已存在就永远不再装依赖。"""
    block = _venv_creation_block(script)
    assert "pip" not in block, (
        "依赖安装被写进了 venv 创建分支 —— venv 已存在（首次安装失败、"
        "手工创建、依赖变更）时将永远不会补装:\n" + block)


def test_每次source都校验依赖(script: str):
    """校验必须是无条件执行的一步，而不是挂在创建分支上。"""
    assert "_flange_deps_ready" in script, "缺少依赖就绪校验"
    ready = re.search(r"_flange_deps_ready\(\)\s*\{(.*?)\n\}", script, re.S)
    assert ready, "找不到 _flange_deps_ready 定义"
    body = ready.group(1)
    assert "import" in body, "校验必须真的探测 import，而不是只看目录在不在"
    assert "_jsonnet" in body, "jsonnet 是最容易装失败的依赖，必须在探针里"


def test_pyproject变更会触发重装(script: str):
    """新增依赖后老 venv 必须跟进。"""
    ready = re.search(r"_flange_deps_ready\(\)\s*\{(.*?)\n\}", script, re.S)
    assert "pyproject.toml" in ready.group(1), (
        "依赖声明变化没有纳入校验，新增依赖时老 venv 不会跟进")


def test_安装失败必须被检查(script: str):
    """原来 pip 的退出码没人看，失败照样打印'依赖安装完成'。"""
    install = re.search(r"_flange_install_deps\(\)\s*\{(.*?)\n\}", script, re.S)
    assert install, "找不到 _flange_install_deps 定义"
    body = install.group(1)
    assert re.search(r"if\s+!\s+.*pip.*install", body), (
        "pip install 的退出码没有被检查")
    assert "return 1" in body, "安装失败必须返回非零"


def test_失败时不落stamp(script: str):
    """落了 stamp 就等于宣布装好了，下次 source 不会重试。"""
    install = re.search(r"_flange_install_deps\(\)\s*\{(.*?)\n\}", script, re.S)
    body = install.group(1)
    fail_at = body.index("return 1")
    stamp_at = body.index("_flange_dep_stamp")
    assert stamp_at > fail_at, (
        "stamp 写在失败返回之前 —— 安装失败也会被记成成功")


def test_失败提示可操作(script: str):
    """jsonnet 装不上的真实原因通常是缺 C++ 工具链，报错要说到这一层。"""
    install = re.search(r"_flange_install_deps\(\)\s*\{(.*?)\n\}", script, re.S)
    body = install.group(1)
    assert "jsonnet" in body, "没说清是哪个依赖最容易失败"
    assert "xcode-select" in body and "build-essential" in body, (
        "没有给出 macOS / Debian 两侧的修复命令")
    assert "pip install" in body, "没有给出手动重试的命令"


def test_venv损坏时明确报错而不是静默跳过(script: str):
    """venv 目录在但 bin/python3 不可执行时，静默跳过等于把问题藏起来。"""
    assert re.search(r'if \[\[ ! -x "\$_flange_venv/bin/python3" \]\]', script), (
        "没有检查 venv 是否完整")
    broken = script[script.index('! -x "$_flange_venv/bin/python3"'):]
    assert "ERROR" in broken[:400], "venv 损坏时没有报错"
    assert "rm -rf" in broken[:600], "没有告诉用户怎么重建"


def test_app与package路由到资源优先模块(script: str):
    """shell 只透传 argv，路径与 action 解析统一留给 Python。"""
    assert re.search(r"app\|package\).*?_flange_cmd_resource", script, re.S)
    resource = re.search(
        r"_flange_cmd_resource\(\)\s*\{(.*?)\n\}", script, re.S
    )
    assert resource
    assert "python3 -P -m builder.dev" in resource.group(1)
    assert '"$@"' in resource.group(1)


def test_app脚手架入口不再eval或拼python源码(script: str):
    """名称和仓库外路径属于用户输入，必须始终作为 argv 传递。"""
    create_start = script.index("_flange_cmd_create_app()")
    create_end = script.index("\n}\n", create_start)
    body = script[create_start:create_end]
    assert "eval" not in body
    assert "python3 -c" not in body


# ---------------------------------------------------------------------------
# lunch 的交互形式
# ---------------------------------------------------------------------------

def _lunch_body(script: str) -> str:
    start = script.index("\nlunch() {")
    end = script.index("\n}\n", start)
    return script[start:end]


def test_lunch无参数时走层级界面(script: str):
    body = _lunch_body(script)
    assert "builder.lunch_tui" in body, "lunch 没有接入层级选择界面"


def test_lunch在非TTY时回退编号列表(script: str):
    """管道、CI 里没有终端，curses 起不来 —— 必须还能选目标。"""
    body = _lunch_body(script)
    assert "[[ -t 0 ]]" in body and "[[ -t 1 ]]" in body, (
        "没有检查是否为 TTY，非交互环境会直接失败")
    assert "可用的目标配置" in body, "回退路径（编号列表）不见了"


def test_no_tui在解析目标之前被摘掉(script: str):
    """否则 `lunch --no-tui` 会被当成 board 名去解析。"""
    body = _lunch_body(script)
    no_tui_at = body.index('"--no-tui"')
    parse_at = body.index("parse_target")
    assert no_tui_at < parse_at


def test_界面结果经文件回传而不是stdout(script: str):
    """子进程改不了父 shell 的环境变量，而 $(...) 捕获会吞掉 curses 的绘制。"""
    body = _lunch_body(script)
    assert "--out" in body and "mktemp" in body


def test_取消时不改变当前目标(script: str):
    body = _lunch_body(script)
    assert "已取消，当前目标不变" in body


def test_lunch有帮助(script: str):
    body = _lunch_body(script)
    assert '"--help"' in body and "用法: lunch" in body
