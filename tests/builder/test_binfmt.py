"""跨架构检测、按需注册和失败传播。"""

import json
import subprocess

import pytest

from builder.binfmt import ensure_binfmt
from builder.docker import BuildError


def responses(monkeypatch, values):
    calls = []
    results = iter(values)

    def run(command, **kwargs):
        calls.append(command)
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    monkeypatch.setattr("builder.binfmt.subprocess.run", run)
    return calls


@pytest.mark.parametrize("arch,platform", [
    ("armhf", "linux/arm/v7"), ("aarch64", "linux/arm64"),
    ("x86_64", "linux/amd64"), ("riscv64", "linux/riscv64"),
])
def test_supported_does_not_register(monkeypatch, arch, platform):
    calls = responses(monkeypatch, [{"supported": ["linux/amd64", platform]}])
    ensure_binfmt(arch)
    assert len(calls) == 1
    assert "--install" not in calls[0]


def test_missing_registers_and_rechecks_each_build(monkeypatch):
    ready = {"supported": ["linux/amd64", "linux/arm/v7"]}
    calls = responses(monkeypatch, [
        {"supported": ["linux/amd64"]}, ready, ready, ready,
    ])
    ensure_binfmt("armhf")
    ensure_binfmt("armhf")
    assert len(calls) == 4
    assert calls[1][-2:] == ["--install", "arm"]


def test_build_platform_is_also_required(monkeypatch):
    ready = {"supported": ["linux/arm64", "linux/amd64"]}
    calls = responses(monkeypatch, [{"supported": ["linux/arm64"]}, ready, ready])
    ensure_binfmt("aarch64")
    assert calls[1][-2:] == ["--install", "amd64"]


def test_unsuccessful_registration_stops_build(monkeypatch):
    responses(monkeypatch, [{"supported": ["linux/amd64"]}] * 3)
    with pytest.raises(BuildError, match="注册后仍无法执行"):
        ensure_binfmt("armhf")


@pytest.mark.parametrize("result", [
    {}, {"supported": "linux/arm64"},
    subprocess.CalledProcessError(1, "docker", stderr="permission denied"),
    subprocess.TimeoutExpired("docker", 180),
])
def test_invalid_probe_stops_build(monkeypatch, result):
    responses(monkeypatch, [result])
    with pytest.raises(BuildError, match="binfmt"):
        ensure_binfmt("armhf")


def test_cli_probe_failure_prevents_build_container(tmp_path, monkeypatch, capsys):
    from builder.cli import main
    from builder.docker import DockerRunner
    from builder.workspace import Target, init_workspace, save_target

    init_workspace(tmp_path)
    save_target(tmp_path, Target("khadas-vim3", "default", "debug"))
    monkeypatch.setattr("builder.docker._is_inside_container", lambda: False)

    def fail(*args):
        raise BuildError("binfmt 注册失败：permission denied")

    def unexpected(*args, **kwargs):
        pytest.fail("binfmt 失败后不应启动构建容器")

    monkeypatch.setattr("builder.binfmt.ensure_binfmt", fail)
    monkeypatch.setattr(DockerRunner, "run", unexpected)
    assert main(["--json", "-C", str(tmp_path), "build"]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["error"]["message"] == "binfmt 注册失败：permission denied"
