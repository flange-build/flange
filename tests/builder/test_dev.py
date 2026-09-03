"""资源优先 App/Package 开发命令的最小回归测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from builder import dev


_CONFIG = {
    "board": "demo-board",
    "product": "default",
    "variant": "debug",
    "architecture": {"userspace": "aarch64"},
}


def _write_app(path: Path, name: str = "demo") -> Path:
    path.mkdir(parents=True)
    (path / "app.yaml").write_text(
        "app:\n"
        f"  name: {name}\n"
        "  version: 0.1.0\n"
        "  description: 测试 App\n"
        "  type: exec\n"
        "  arch: [aarch64]\n"
        "maintainer:\n"
        "  name: flange\n"
        "  email: flange@localhost\n"
        "build:\n"
        "  system: none\n",
        encoding="utf-8",
    )
    return path


def test_resolve_app_relative_path_uses_caller_cwd(tmp_path: Path):
    app_dir = _write_app(tmp_path / "vendor" / "demo")

    resolved = dev.resolve_app_dir(
        "./demo",
        _CONFIG,
        caller_cwd=tmp_path / "vendor",
        project_root=tmp_path / "project",
    )

    assert resolved == app_dir.resolve()


def test_existing_directory_without_manifest_does_not_fall_back_to_name(
    tmp_path: Path,
):
    caller = tmp_path / "caller"
    (caller / "demo").mkdir(parents=True)

    with pytest.raises(dev.DevelopmentError, match="app.yaml"):
        dev.resolve_app_dir(
            "demo",
            _CONFIG,
            caller_cwd=caller,
            project_root=tmp_path / "project",
        )


def test_action_arguments_are_not_shell_split(tmp_path: Path, monkeypatch):
    source = tmp_path / "outside"
    source.mkdir()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dev.subprocess, "run", fake_run)
    dev._run_action(
        ["./run.sh", "safe;literal"],
        ["--value", "$(touch nope)"],
        source,
        _CONFIG,
        in_container=False,
    )

    assert calls[0][0] == [
        "./run.sh", "safe;literal", "--value", "$(touch nope)",
    ]
    assert calls[0][1]["cwd"] == source
    assert "shell" not in calls[0][1]


def test_external_app_mount_exists_before_container_build(
    tmp_path: Path,
    monkeypatch,
):
    app_dir = _write_app(tmp_path / "external" / "demo")
    calls = []

    def fake_run(self, argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dev.DockerRunner, "run", fake_run)
    dev._build_standard_app(app_dir, _CONFIG)

    argv, kwargs = calls[0]
    assert argv[-4] == str(app_dir.resolve())
    assert argv[-3:] == ["demo-board", "default", "debug"]
    assert kwargs["extra_mounts"]
    assert app_dir.is_relative_to(kwargs["extra_mounts"][0])


def test_package_requires_component_when_multiple_vendors(tmp_path: Path):
    package_dir = tmp_path / "package"
    _write_app(package_dir / "one", "one")
    _write_app(package_dir / "two", "two")
    package = {
        "name": "package",
        "components": [
            {"type": "vendor", "name": "one", "dir": "one"},
            {"type": "vendor", "name": "two", "dir": "two"},
        ],
        "actions": {},
    }

    with pytest.raises(dev.DevelopmentError, match="--component"):
        dev._package_lifecycle("run", package_dir, package, _CONFIG)


def test_package_component_selects_vendor_lifecycle(tmp_path: Path, monkeypatch):
    package_dir = tmp_path / "package"
    one = _write_app(package_dir / "one", "one")
    _write_app(package_dir / "two", "two")
    package = {
        "name": "package",
        "components": [
            {"type": "vendor", "name": "one", "dir": "one"},
            {"type": "vendor", "name": "two", "dir": "two"},
            {"type": "oot-driver", "name": "driver"},
        ],
        "actions": {},
    }
    calls = []
    monkeypatch.setattr(
        dev,
        "_app_lifecycle",
        lambda action, app_dir, config, **options: calls.append(
            (action, app_dir, options)
        ),
    )

    dev._package_lifecycle(
        "run",
        package_dir,
        package,
        _CONFIG,
        component="one",
        serial="device-1",
        action_args=["--demo"],
    )

    assert calls == [(
        "run",
        one,
        {
            "action_args": ["--demo"],
            "serial": "device-1",
            "no_build": False,
            "lines": None,
            "since": None,
            "follow": True,
            "build_mount_root": package_dir,
        },
    )]


def test_package_vendor_build_mounts_complete_package(
    tmp_path: Path,
    monkeypatch,
):
    package_dir = tmp_path / "package"
    app_dir = _write_app(package_dir / "app")
    (package_dir / "shared").mkdir()
    calls = []
    monkeypatch.setattr(dev.DockerRunner, "run", lambda self, argv, **kwargs: (
        calls.append((argv, kwargs))
        or SimpleNamespace(returncode=0)
    ))

    dev._build_standard_app(app_dir, _CONFIG, mount_root=package_dir)

    assert calls[0][1]["extra_mounts"] == [package_dir.resolve()]


def test_package_deploy_builds_but_skips_staging_vendor(
    tmp_path: Path,
    monkeypatch,
):
    package_dir = tmp_path / "package"
    stage_dir = _write_app(package_dir / "stage", "stage")
    runtime_dir = _write_app(package_dir / "runtime", "runtime")
    package = {
        "name": "package",
        "components": [
            {"type": "vendor", "name": "stage", "dir": "stage"},
            {"type": "vendor", "name": "runtime", "dir": "runtime"},
        ],
        "actions": {},
    }
    calls = []
    monkeypatch.setattr(
        dev,
        "load_spec",
        lambda path: SimpleNamespace(
            app=SimpleNamespace(
                type="staging" if path == stage_dir else "exec"
            )
        ),
    )
    monkeypatch.setattr(
        dev,
        "_app_lifecycle",
        lambda action, app_dir, config, **options: calls.append(
            (action, app_dir, options)
        ),
    )

    dev._package_lifecycle("deploy", package_dir, package, _CONFIG)

    assert calls == [
        ("build", stage_dir, {"build_mount_root": package_dir}),
        (
            "deploy",
            runtime_dir,
            {
                "serial": None,
                "no_build": False,
                "build_mount_root": package_dir,
            },
        ),
    ]


def test_package_non_vendor_reports_missing_action(tmp_path: Path):
    package = {
        "name": "driver-only",
        "components": [{"type": "oot-driver", "name": "demo"}],
        "actions": {},
    }

    with pytest.raises(dev.DevelopmentError, match="显式 action"):
        dev._package_lifecycle("deploy", tmp_path, package, _CONFIG)


def test_package_mixed_components_require_action_or_selection(tmp_path: Path):
    package_dir = tmp_path / "package"
    _write_app(package_dir / "app")
    package = {
        "name": "mixed",
        "components": [
            {"type": "vendor", "name": "app", "dir": "app"},
            {"type": "oot-driver", "name": "driver"},
        ],
        "actions": {},
    }

    with pytest.raises(dev.DevelopmentError, match=r"driver \(oot-driver\)"):
        dev._package_lifecycle("build", package_dir, package, _CONFIG)


def test_resource_create_defaults_to_caller_directory(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    assert dev.main(["package", "create", "demo-package"]) == 0
    assert (tmp_path / "demo-package" / "package.py").is_file()
    assert (tmp_path / "demo-package" / "app" / "app.yaml").is_file()


def test_split_action_args_preserves_literal_values():
    command, extra = dev._split_action_args([
        "app", "run", ".", "--", "--name", "a b", "x;y",
    ])

    assert command == ["app", "run", "."]
    assert extra == ["--name", "a b", "x;y"]


def test_standard_run_builds_once_and_deploys_once(tmp_path: Path, monkeypatch):
    app_dir = _write_app(tmp_path / "demo")
    calls = []

    monkeypatch.setattr(
        dev,
        "_build_app",
        lambda *args, **kwargs: calls.append("build"),
    )
    from builder import deploy

    def fake_run(app, build_deb=True, **kwargs):
        calls.append((Path(app), build_deb, kwargs["args"]))
        return "serial"

    monkeypatch.setattr(deploy, "run_app", fake_run)
    dev._app_lifecycle(
        "run",
        app_dir,
        _CONFIG,
        action_args=["--port", "9000"],
    )

    assert calls == [
        "build",
        (app_dir, False, ["--port", "9000"]),
    ]


def test_release_debug_fails_before_build_or_deploy(tmp_path: Path, monkeypatch):
    app_dir = _write_app(tmp_path / "demo")
    monkeypatch.setattr(
        dev,
        "_build_app",
        lambda *args, **kwargs: pytest.fail("不应构建"),
    )
    config = {**_CONFIG, "variant": "release"}

    with pytest.raises(dev.DevelopmentError, match="debug variant"):
        dev._app_lifecycle("debug", app_dir, config)


def test_staging_app_rejects_default_deploy_before_build(
    tmp_path: Path,
    monkeypatch,
):
    app_dir = _write_app(tmp_path / "stage")
    monkeypatch.setattr(
        dev,
        "load_spec",
        lambda _: SimpleNamespace(
            app=SimpleNamespace(type="staging"),
            actions={},
        ),
    )
    monkeypatch.setattr(
        dev,
        "_build_app",
        lambda *args, **kwargs: pytest.fail("不应构建或寻找旧 deb"),
    )

    with pytest.raises(dev.DevelopmentError, match="不产出可部署 deb"):
        dev._app_lifecycle("deploy", app_dir, _CONFIG)


def test_shell_entry_preserves_outside_cwd(tmp_path: Path):
    shadow = tmp_path / "builder"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "dev.py").write_text(
        "raise RuntimeError('不应加载调用者的 builder')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1/envsetup.sh" >/dev/null && cd "$2" && '
            "flange package create shell-demo --build-system none",
            "flange-test",
            str(dev.PROJECT_ROOT),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "shell-demo" / "package.py").is_file()


def test_shell_help_does_not_require_target_or_docker():
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1/envsetup.sh" >/dev/null && '
            '_flange_check_all() { return 93; } && '
            '_flange_check_target() { return 94; } && '
            'flange app build --help >/dev/null && '
            'flange package log --help >/dev/null',
            "flange-test",
            str(dev.PROJECT_ROOT),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


def test_package_cli_runs_explicit_action_with_passthrough(
    tmp_path: Path,
    monkeypatch,
):
    package_dir = tmp_path / "action-package"
    package_dir.mkdir()
    (package_dir / "package.py").write_text(
        "PACKAGE = {"
        "'name': 'action-package', "
        "'components': [], "
        "'actions': {'run': ['./run.sh', '--safe']}"
        "}\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.chdir(package_dir)
    monkeypatch.setattr(dev, "load_current_config", lambda: _CONFIG)
    from builder import deploy

    monkeypatch.setattr(deploy, "select_adb_device", lambda serial: "device-1")
    monkeypatch.setattr(
        dev.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs))
        or SimpleNamespace(returncode=0),
    )

    result = dev.main([
        "package", "run", ".", "--", "--port", "9000;literal",
    ])

    assert result == 0
    assert calls[0][0] == [
        "./run.sh", "--safe", "--port", "9000;literal",
    ]
    assert calls[0][1]["cwd"] == package_dir
    assert calls[0][1]["env"]["FLANGE_ADB_SERIAL"] == "device-1"
