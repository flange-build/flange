"""外部构建环境的 compose 与内建 Ubuntu compose 保持相同的宿主凭据挂载。"""

import json
from pathlib import Path

from builder.build_environment import BuildEnvironmentSpec
from builder.docker import DockerRunner


def _runner(tmp_path: Path) -> DockerRunner:
    runner = object.__new__(DockerRunner)
    runner.context = None
    runner.project_dir = tmp_path / "tool"
    runner.environment_spec = BuildEnvironmentSpec(name="demo", image="demo:1")
    return runner


def test_environment_compose_mounts_host_ssh_keys(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    command = _runner(tmp_path).compose_command("build")

    compose = json.loads(Path(command[command.index("-f") + 1]).read_text())
    assert f"{home / '.ssh'}:/tmp/.ssh-host:ro" in compose["services"]["build"]["volumes"]


def test_environment_compose_without_ssh_dir_has_no_volume(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))

    command = _runner(tmp_path).compose_command("build")

    compose = json.loads(Path(command[command.index("-f") + 1]).read_text())
    assert "volumes" not in compose["services"]["build"]
