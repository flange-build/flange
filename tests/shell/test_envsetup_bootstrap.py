"""通过真实 Bash/Zsh 进程验证薄引导层，不锁定函数的文本实现。"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["bash", "zsh"])
def shell(request):
    path = shutil.which(request.param)
    if path is None:
        pytest.skip(f"{request.param} 不可用")
    return path


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "带空格 tool"
    binary = root / ".venv" / "bin"
    binary.mkdir(parents=True)
    shutil.copy2(ROOT / "envsetup.sh", root / "envsetup.sh")
    (root / "pyproject.toml").write_text("[project]\nname='flange'\n")
    (binary / "activate").write_text('export PATH="$FLANGE_DIR/.venv/bin:$PATH"\n')
    python = binary / "python3"
    python.write_text('''#!/bin/sh
if [ "$1" = "-c" ]; then
    [ "${FLANGE_TEST_IMPORT_FAILURE:-0}" = 0 ]
    exit $?
fi
if [ "$1" = "-m" ] && [ "$2" = pip ]; then
    echo install >> "$FLANGE_TEST_CALLS"
    [ "${FLANGE_TEST_INSTALL_FAILURE:-0}" = 0 ] || exit 19
    exit 0
fi
exit 23
''')
    python.chmod(0o755)
    command = binary / "flange"
    command.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    command.chmod(0o755)
    return root


def run(shell, root, code, **environment):
    env = {**os.environ, "FLANGE_TEST_CALLS": str(root / "calls"), **environment}
    return subprocess.run([shell, "-c", code, "flange-test", str(root)],
                          env=env, capture_output=True, text=True, timeout=15)


def test_可从任意调用目录引导且lunch仅转发(shell, checkout):
    result = run(shell, checkout, 'source "$1/envsetup.sh" >/dev/null || exit; lunch board-product-release')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["target", "select", "board-product-release"]
    assert (checkout / ".venv/.flange-installed").exists()


def test_安装失败不发布就绪状态且下次会重试(shell, checkout):
    first = run(shell, checkout, 'source "$1/envsetup.sh"', FLANGE_TEST_INSTALL_FAILURE="1")
    assert first.returncode != 0
    assert not (checkout / ".venv/.flange-installed").exists()
    second = run(shell, checkout, 'source "$1/envsetup.sh"')
    assert second.returncode == 0, second.stderr
    assert (checkout / "calls").read_text().splitlines() == ["install", "install"]


def test_已安装且依赖正常时不重复安装(shell, checkout):
    assert run(shell, checkout, 'source "$1/envsetup.sh"').returncode == 0
    assert run(shell, checkout, 'source "$1/envsetup.sh"').returncode == 0
    assert (checkout / "calls").read_text().splitlines() == ["install"]


def test_依赖损坏触发修复(shell, checkout):
    assert run(shell, checkout, 'source "$1/envsetup.sh"').returncode == 0
    repaired = run(shell, checkout, 'source "$1/envsetup.sh"', FLANGE_TEST_IMPORT_FAILURE="1")
    assert repaired.returncode == 0, repaired.stderr
    assert (checkout / "calls").read_text().splitlines() == ["install", "install"]


def test_不改变调用者工作目录与shell选项(shell, checkout):
    result = run(shell, checkout, 'before_dir=$PWD; before_flags=$-; source "$1/envsetup.sh" >/dev/null; test "$PWD" = "$before_dir" && test "$-" = "$before_flags"')
    assert result.returncode == 0, result.stderr
