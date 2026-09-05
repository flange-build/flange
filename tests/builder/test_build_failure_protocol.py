"""宿主与构建容器的失败回执：只合并有证据的重复诊断。"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from builder.build_result import read_failure
from builder.cli import main
from builder.docker import DockerRunner
from builder.workspace import Target, init_workspace, save_target


def receipt(request_id="current", code=2):
    return {
        "schema_version": 1,
        "request_id": request_id,
        "exit_code": code,
        "kind": "configuration",
        "message": "App 运行入口未安装或不可执行：/usr/bin/recoveryctl",
        "reported": True,
    }


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"request_id": "previous"}, {"exit_code": 1},
    {"reported": False}, {"kind": "unknown"}, {"message": ""},
])
def test_不匹配的回执不能静默Docker失败(tmp_path, change):
    path = tmp_path / "failure.json"
    path.write_text(json.dumps({**receipt(), **change}))
    assert read_failure(path, request_id="current", code=2) is None


@pytest.mark.parametrize("machine", [False, True])
@pytest.mark.parametrize("valid", [False, True])
def test_宿主仅对本次已呈现错误去重(tmp_path, capsys, monkeypatch, machine, valid):
    init_workspace(tmp_path)
    save_target(tmp_path, Target("khadas-vim3", "default", "debug"))
    monkeypatch.setattr("builder.docker._is_inside_container", lambda: False)
    paths = []

    def run(self, command, **kwargs):
        env = kwargs["env"]
        assert shlex.split(env["FLANGE_BUILD_RETRY_COMMAND"]) == [
            "flange", "-C", str(tmp_path.resolve()), "build",
        ]
        path = Path(env["FLANGE_BUILD_RESULT_FILE"])
        paths.append(path)
        if valid:
            payload = receipt(env["FLANGE_BUILD_REQUEST_ID"])
            path.write_text(json.dumps(payload))
            print(payload["message"])
        else:
            print("Cannot connect to the Docker daemon")
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(DockerRunner, "run", run)
    flags = ["--json"] if machine else []
    code = main([*flags, "-C", str(tmp_path), "build"])
    terminal = capsys.readouterr()
    assert code == (2 if valid else 1)
    assert all(not path.parent.exists() for path in paths)
    if valid:
        assert terminal.err.count(receipt()["message"]) == 1
        assert "Docker 命令失败" not in terminal.err
    else:
        assert "Cannot connect to the Docker daemon" in terminal.err
        if not machine:
            assert "构建容器执行失败" in terminal.err
    if machine:
        value = json.loads(terminal.out)
        assert value["ok"] is False
        assert value["error"]["exit_code"] == code
        assert value["error"]["message"] == (receipt()["message"] if valid else
            "构建容器执行失败（退出码 2），请检查上方 Docker 诊断")
    else:
        assert terminal.out == ""
    assert "\033" not in terminal.out + terminal.err


@pytest.mark.parametrize("machine", [False, True])
def test_组件已呈现错误保留退出码和机器结果(tmp_path, capsys, monkeypatch, machine):
    failure = ValueError("App 运行入口未安装或不可执行：/usr/bin/recoveryctl")
    failure._flange_reported = True
    path = tmp_path / "failure.json"
    monkeypatch.setenv("FLANGE_BUILD_RESULT_FILE", str(path))
    monkeypatch.setenv("FLANGE_BUILD_REQUEST_ID", "current")

    def dispatch(*args):
        raise failure

    monkeypatch.setattr("builder.cli._dispatch", dispatch)
    assert main([*(["--json"] if machine else []), "build"]) == 2
    terminal = capsys.readouterr()
    assert terminal.err == ""
    if machine:
        assert json.loads(terminal.out)["error"]["message"] == str(failure)
    else:
        assert terminal.out == ""
    assert read_failure(path, request_id="current", code=2) is not None


@pytest.mark.parametrize("resource", ["_build-app", "_build-package"])
@pytest.mark.parametrize("reported", [False, True])
def test_独立资源容器入口与宿主共用单次失败回执(tmp_path, capsys, monkeypatch, resource, reported):
    from builder import dev
    from builder.build_result import BuildFailure, run_build_container
    from builder.workspace import load_workspace

    init_workspace(tmp_path)
    save_target(tmp_path, Target("khadas-vim3", "default", "debug"))
    context = load_workspace(tmp_path)
    message = "资源产物校验失败"

    def execute(*args, **kwargs):
        failure = ValueError(message)
        failure._flange_reported = reported
        if reported:
            print(message, file=sys.stderr)
        raise failure

    monkeypatch.setattr(dev, "execute", execute)

    def run(self, command, **kwargs):
        with monkeypatch.context() as environment:
            for key, value in kwargs["env"].items():
                environment.setenv(key, value)
            code = dev.main([resource, "request.json"])
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(DockerRunner, "run", run)
    with pytest.raises(BuildFailure) as failed:
        run_build_container(DockerRunner(context=context), ["python3", "-m", "builder.dev", resource])
    assert failed.value.code == 1
    assert failed.value._flange_reported is True
    terminal = capsys.readouterr()
    assert terminal.err.count(message) == 1
    assert terminal.out == ""
    assert list(context.build_root.glob(".build-result-*")) == []
