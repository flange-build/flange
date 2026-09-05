"""工作区与命令行的边界验证：状态隔离、失败恢复和机器可组合性。"""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from builder.cli import main
from builder.paths import PROJECT_ROOT
from builder.term import display_width, supports_color, terminal_width, truncate
from builder.workspace import (
    Target,
    WorkspaceError,
    init_workspace,
    load_workspace,
    save_target,
    workspace_settings,
)


TARGET = Target("radxa-zero3w", "default", "release")


@pytest.mark.parametrize("directory_args", [["--dir", "apps"], ["--dir=apps"]])
def test_create相对输出路径遵守工作区覆盖(tmp_path, capsys, directory_args):
    init_workspace(tmp_path)
    assert main(["--json", "-C", str(tmp_path), "app", "create", "hello", *directory_args]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result["data"]["path"]) == tmp_path.resolve() / "apps/hello"


def test_create使用工作区目标架构(tmp_path, capsys):
    import yaml

    init_workspace(tmp_path)
    save_target(tmp_path, Target("atk-rk3506b", "default", "debug"))
    assert main(["--json", "-C", str(tmp_path), "app", "create", "hello"]) == 0
    result = json.loads(capsys.readouterr().out)
    manifest = yaml.safe_load((Path(result["data"]["path"]) / "app.yaml").read_text())
    assert manifest["app"]["arch"] == ["armhf"]


def test_用户程序help参数不被当作工具帮助(tmp_path, capsys, monkeypatch):
    from builder import dev

    init_workspace(tmp_path)
    save_target(tmp_path, TARGET)
    calls = []

    def execute(argv, *, context):
        calls.append((argv, context))
        return {"exit_code": 3, "status": "failed"}

    monkeypatch.setattr(dev, "execute", execute)
    monkeypatch.setattr("builder.cli._container_environment", lambda context: None)
    assert main(["--json", "-C", str(tmp_path), "app", "run", "hello", "--", "--help"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert calls[0][0] == ["app", "run", "hello", "--", "--help"]
    assert calls[0][1].target == TARGET


def test_工作区状态与输出隔离且发现不写文件(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    init_workspace(left)
    init_workspace(right)
    save_target(left, TARGET)
    save_target(right, Target("radxa-zero3w", "default", "debug"))
    nested = left / "apps" / "hello"
    nested.mkdir(parents=True)
    context = load_workspace(nested)
    assert context.workspace_root == left.resolve()
    assert context.target == TARGET
    assert context.target_dir == left.resolve() / ".build/target/radxa-zero3w/default/release"
    assert load_workspace(right).target.variant == "debug"
    assert not context.build_root.exists()
    overridden = load_workspace(left, target=Target("radxa-zero3w", "default", "debug"))
    assert overridden.target.variant == "debug"
    assert load_workspace(left).target == TARGET


def test_路径以清单为基准而非调用目录(tmp_path):
    init_workspace(tmp_path)
    manifest = tmp_path / "flange.toml"
    manifest.write_text(manifest.read_text().replace("[apps]", '[apps]\nhello="src/hello"'))
    save_target(tmp_path, TARGET)
    nested = tmp_path / "nested"
    nested.mkdir()
    context = load_workspace(nested)
    assert context.apps["hello"] == (tmp_path / "src/hello").resolve()
    assert context.invocation_dir == nested.resolve()
    with pytest.raises(TypeError):
        context.apps["x"] = nested


@pytest.mark.parametrize("addition", ["unknown=true", 'app_dirs="apps"', "schema_version=true"])
def test_错误清单在入口拒绝(tmp_path, addition):
    init_workspace(tmp_path)
    manifest = tmp_path / "flange.toml"
    text = manifest.read_text().split("[apps]")[0]
    key = addition.split("=")[0]
    text = "\n".join(line for line in text.splitlines() if not line.startswith(key))
    manifest.write_text(text + "\n" + addition + "\n")
    with pytest.raises(WorkspaceError):
        workspace_settings(tmp_path)


def test_重复init不会覆盖用户声明(tmp_path):
    manifest = init_workspace(tmp_path)
    original = manifest.read_bytes()
    with pytest.raises(WorkspaceError):
        init_workspace(tmp_path)
    assert manifest.read_bytes() == original


def test_json错误保持机器格式并给出恢复命令(tmp_path, capsys):
    init_workspace(tmp_path)
    assert main(["--json", "-C", str(tmp_path), "build"]) == 2
    streams = capsys.readouterr()
    value = json.loads(streams.out)
    assert value["schema_version"] == 1
    assert value["ok"] is False
    assert value["error"]["exit_code"] == 2
    assert "target select" in value["error"]["message"]
    assert "Traceback" not in streams.out + streams.err


def test_非交互选择不会等待读取输入(tmp_path, capsys, monkeypatch):
    init_workspace(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("不得提示"))
    assert main(["-C", str(tmp_path), "--no-interaction", "target", "select"]) == 2
    assert "target list" in capsys.readouterr().err


def test_未知选项不静默忽略(capsys):
    assert main(["--json", "build", "--froce"]) == 2
    value = json.loads(capsys.readouterr().out)
    assert "--froce" in value["error"]["message"]


def test_全局选项可放在命令之后(tmp_path, capsys):
    init_workspace(tmp_path)
    assert main(["status", "-C", str(tmp_path), "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["data"]["target"] is None
    assert value["data"]["workspace_root"] == str(tmp_path.resolve())


def test_doctor诊断失败的机器状态与退出码一致(tmp_path, capsys, monkeypatch):
    init_workspace(tmp_path)
    monkeypatch.setattr("builder.commands.shutil.which", lambda name: None)
    assert main(["--json", "-C", str(tmp_path), "doctor"]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["ok"] is False
    assert value["data"]["ready"] is False
    docker = next(check for check in value["data"]["checks"] if check["name"] == "Docker")
    assert docker["fix"] == "启动 Docker Desktop 或 Docker Engine"


def test_模块入口可独立于source调用(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "builder", "--json", "-C", str(tmp_path), "init"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
    assert (tmp_path / "flange.toml").exists()


def test_中文组合字符和无颜色能力(monkeypatch):
    assert display_width("中文e\u0301") == 5
    assert truncate("中文e\u0301abcd", 6) == "中文e\u0301…"
    monkeypatch.setenv("NO_COLOR", "")
    assert supports_color() is False
    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda fallback: __import__("os").terminal_size((24, 20))
    )
    assert terminal_width() == 24
