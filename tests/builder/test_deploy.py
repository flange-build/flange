"""App 部署、运行、日志与调试的宿主机侧回归测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from builder import deploy


def _config(variant: str = "debug") -> dict:
    return {
        "board": "demo-board",
        "product": "default",
        "variant": variant,
        "architecture": {"userspace": "aarch64"},
    }


def _write_app(
    target: Path,
    *,
    name: str = "demo",
    app_type: str = "exec",
    unit: str | None = None,
    deb_outputs: list[str] | None = None,
) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    lines = [
        "app:",
        f"  name: {name}",
        "  version: 1.0.0",
        "  description: 部署测试",
        f"  type: {app_type}",
        "  arch:",
        "    - aarch64",
        "maintainer:",
        "  name: tester",
        "  email: tester@localhost",
        "build:",
        f"  system: {'custom' if deb_outputs else 'none'}",
    ]
    if deb_outputs:
        lines.append("  deb_outputs:")
        lines.extend(f"    - {filename}" for filename in deb_outputs)
    lines.extend(["install:", f"  bin/{name}: /usr/bin/{name}"])
    if unit is not None:
        lines.extend(["systemd:", f"  unit: {unit}"])
    (target / "app.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _write_deb(project_root: Path, config: dict, name: str = "demo") -> Path:
    target = (
        project_root
        / ".build"
        / "target"
        / config["board"]
        / config["product"]
        / config["variant"]
        / "app"
        / f"{name}_1.0.0_arm64.deb"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"deb")
    return target


def _completed(argv: list[str], stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


class TestResolveApp:
    def test_relative_path_uses_explicit_caller_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        caller = tmp_path / "caller"
        app_dir = _write_app(caller / "demo")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        resolved = deploy._resolve_app_arg(
            "./demo",
            tmp_path / "project",
            _config(),
            caller_cwd=caller,
        )

        assert resolved == (app_dir.resolve(), "demo")

    def test_name_lookup_is_anchored_to_project_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_root = tmp_path / "project"
        app_dir = _write_app(project_root / "components" / "app" / "demo")
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(outside)

        resolved = deploy._resolve_app_arg(
            "demo",
            project_root,
            _config(),
            caller_cwd=outside,
        )

        assert resolved == (app_dir.resolve(), "demo")

    @pytest.mark.parametrize("target", ["./missing", "/missing/flange-app"])
    def test_missing_path_is_an_exception(self, tmp_path: Path, target: str) -> None:
        with pytest.raises(deploy.DeployError, match="缺失 app.yaml"):
            deploy._resolve_app_arg(target, tmp_path, _config(), tmp_path)

    def test_unknown_name_is_an_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(deploy, "list_all", lambda *_: [])

        with pytest.raises(deploy.DeployError, match="找不到"):
            deploy._resolve_app_arg("missing", tmp_path, _config(), tmp_path)

    def test_existing_bare_directory_without_manifest_does_not_use_registry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        caller = tmp_path / "caller"
        (caller / "demo").mkdir(parents=True)
        monkeypatch.setattr(
            deploy,
            "list_all",
            lambda *_: pytest.fail("已存在目录不能回退到 registry"),
        )

        with pytest.raises(deploy.DeployError, match="缺失 app.yaml"):
            deploy._resolve_app_arg("demo", tmp_path / "project", _config(), caller)


def test_find_latest_deb_is_anchored_to_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    expected = _write_deb(project_root, _config())
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    assert deploy.find_latest_deb("demo", _config(), project_root) == expected


def test_find_latest_deb_treats_app_name_as_literal(tmp_path: Path) -> None:
    unrelated = _write_deb(tmp_path, _config(), "unrelated")

    assert unrelated.is_file()
    assert deploy.find_latest_deb("*", _config(), tmp_path) is None


def test_deploy_output_match_uses_exact_name_version_and_arch(
    tmp_path: Path,
) -> None:
    app_dir = _write_app(tmp_path / "app", name="foo")
    _write_deb(tmp_path, _config(), "foo_bar")

    assert deploy.find_latest_debs(
        deploy.load_spec(app_dir),
        _config(),
        tmp_path,
    ) == []


def test_vendor_declared_debs_keep_manifest_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    names = ["dependency_1.0_arm64.deb", "feature_1.0_arm64.deb"]
    app_dir = _write_app(
        tmp_path / "vendor",
        app_type="vendor",
        deb_outputs=names,
    )
    output_dir = (
        project_root
        / ".build"
        / "target"
        / "demo-board"
        / "default"
        / "debug"
        / "app"
    )
    output_dir.mkdir(parents=True)
    for name in reversed(names):
        (output_dir / name).write_bytes(b"deb")
    spec = deploy.load_spec(app_dir)

    assert deploy.find_latest_debs(spec, _config(), project_root) == [
        output_dir / name for name in names
    ]


def test_vendor_declared_debs_fail_when_any_output_is_missing(
    tmp_path: Path,
) -> None:
    app_dir = _write_app(
        tmp_path / "vendor",
        app_type="vendor",
        deb_outputs=["present_1.0.0_arm64.deb", "missing_1.0_arm64.deb"],
    )
    _write_deb(tmp_path, _config(), "present")

    with pytest.raises(deploy.DeployError, match="missing_1.0_arm64.deb"):
        deploy.find_latest_debs(deploy.load_spec(app_dir), _config(), tmp_path)


def test_lib_deploy_selects_runtime_deb_only(tmp_path: Path) -> None:
    app_dir = _write_app(tmp_path / "library", app_type="lib")
    runtime = _write_deb(tmp_path, _config(), "libdemo")
    _write_deb(tmp_path, _config(), "libdemo-dev")

    assert deploy.find_latest_debs(
        deploy.load_spec(app_dir),
        _config(),
        tmp_path,
    ) == [runtime]


class TestDeviceSelection:
    def test_auto_selects_the_only_ready_device(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            deploy,
            "list_adb_devices",
            lambda: {"offline-one": "offline", "ready-one": "device"},
        )

        assert deploy.select_adb_device() == "ready-one"

    @pytest.mark.parametrize(
        ("devices", "message"),
        [
            ({}, "未发现"),
            ({"one": "device", "two": "device"}, "--serial"),
        ],
    )
    def test_zero_or_multiple_devices_are_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devices: dict[str, str],
        message: str,
    ) -> None:
        monkeypatch.setattr(deploy, "list_adb_devices", lambda: devices)

        with pytest.raises(deploy.DeployError, match=message) as exc_info:
            deploy.select_adb_device()
        if len(devices) > 1:
            assert all(serial in str(exc_info.value) for serial in devices)

    def test_explicit_serial_must_be_online(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            deploy,
            "list_adb_devices",
            lambda: {"offline-one": "offline", "ready-one": "device"},
        )

        assert deploy.select_adb_device("ready-one") == "ready-one"
        with pytest.raises(deploy.DeployError, match="offline"):
            deploy.select_adb_device("offline-one")

    def test_ambiguous_devices_fail_before_deploy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo")
        monkeypatch.setattr(
            deploy,
            "list_adb_devices",
            lambda: {"one": "device", "two": "device"},
        )
        monkeypatch.setattr(
            deploy,
            "_prepare_debs",
            lambda *_: pytest.fail("设备存在歧义时不应构建或部署"),
        )

        with pytest.raises(deploy.DeployError, match="one.*two"):
            deploy.deploy_app(
                str(app_dir),
                config=_config(),
                project_root=tmp_path,
            )


def test_deploy_uses_project_output_and_selected_serial_outside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    app_dir = _write_app(tmp_path / "external" / "demo")
    deb_path = _write_deb(project_root, _config())
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    deployed: list[tuple[list[Path], str]] = []
    monkeypatch.setattr(deploy, "select_adb_device", lambda serial: serial)
    monkeypatch.setattr(
        deploy,
        "_deploy_debs",
        lambda paths, serial: deployed.append((paths, serial)),
    )

    selected = deploy.deploy_app(
        str(app_dir),
        build_deb=False,
        serial="SERIAL-1",
        config=_config(),
        project_root=project_root,
        caller_cwd=outside,
    )

    assert selected == "SERIAL-1"
    assert deployed == [([deb_path], "SERIAL-1")]


def test_build_routes_through_dev_module_with_external_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    app_dir = _write_app(tmp_path / "outside" / "demo")
    calls: list[tuple[list[str], Path | None]] = []
    monkeypatch.setattr(deploy, "oot_volume_arguments", lambda _: [])

    def fake_run(
        argv: list[str],
        *,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        calls.append((argv, cwd))
        return _completed(argv)

    monkeypatch.setattr(deploy, "_run_checked", fake_run)

    deploy._build_app(app_dir, _config(), project_root)

    argv, cwd = calls[0]
    assert cwd == project_root.resolve()
    assert ["--volume", f"{app_dir.resolve()}:{app_dir.resolve()}:rw"] == argv[4:6]
    assert argv[-8:] == [
        "python3",
        "-m",
        "builder.dev",
        "_build-app",
        str(app_dir.resolve()),
        "demo-board",
        "default",
        "debug",
    ]
    assert "-c" not in argv


def test_deb_install_and_cleanup_keep_serial_as_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deb_paths = [tmp_path / "dependency.deb", tmp_path / "feature.deb"]
    for path in deb_paths:
        path.write_bytes(b"deb")
    checked: list[list[str]] = []
    cleanup: list[tuple[list[str], dict]] = []

    def fake_checked(argv: list[str], **_: object) -> subprocess.CompletedProcess:
        checked.append(argv)
        return _completed(argv)

    def fake_cleanup(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        cleanup.append((argv, kwargs))
        return _completed(argv)

    monkeypatch.setattr(deploy, "_run_checked", fake_checked)
    monkeypatch.setattr(deploy.subprocess, "run", fake_cleanup)

    deploy._deploy_debs(deb_paths, "SERIAL-1")

    assert checked == [
        [
            "adb", "-s", "SERIAL-1", "push", str(deb_paths[0]),
            "/tmp/dependency.deb",
        ],
        [
            "adb", "-s", "SERIAL-1", "push", str(deb_paths[1]),
            "/tmp/feature.deb",
        ],
        [
            "adb", "-s", "SERIAL-1", "shell",
            "dpkg -i /tmp/dependency.deb /tmp/feature.deb",
        ],
    ]
    assert [item[0] for item in cleanup] == [
        [
            "adb", "-s", "SERIAL-1", "shell",
            "rm -f /tmp/dependency.deb",
        ],
        [
            "adb", "-s", "SERIAL-1", "shell",
            "rm -f /tmp/feature.deb",
        ],
    ]
    assert all("shell" not in kwargs for _, kwargs in cleanup)


def _isolate_deploy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, list[list[str]]]:
    deb_path = tmp_path / "demo.deb"
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "select_adb_device", lambda serial: serial or "ONLY")
    monkeypatch.setattr(deploy, "_prepare_debs", lambda *_: [deb_path])
    monkeypatch.setattr(deploy, "_deploy_debs", lambda *_: None)

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        return _completed(argv)

    monkeypatch.setattr(deploy, "_run_checked", fake_run)
    return deb_path, calls


class TestRun:
    def test_exec_quotes_arguments_for_device_shell(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo")
        _, calls = _isolate_deploy(monkeypatch, tmp_path)

        selected = deploy.run_app(
            str(app_dir),
            build_deb=False,
            serial="SERIAL-1",
            args=["--name", "a b", "x;y"],
            config=_config(),
            project_root=tmp_path,
        )

        assert selected == "SERIAL-1"
        assert calls == [[
            "adb", "-s", "SERIAL-1", "shell",
            "/usr/bin/demo --name 'a b' 'x;y'",
        ]]

    def test_service_reloads_restarts_and_shows_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(
            tmp_path / "demo",
            app_type="service",
            unit="systemd/demo-worker.service",
        )
        _, calls = _isolate_deploy(monkeypatch, tmp_path)

        deploy.run_app(
            str(app_dir),
            build_deb=False,
            serial="SERIAL-1",
            config=_config(),
            project_root=tmp_path,
        )

        assert calls == [
            [
                "adb", "-s", "SERIAL-1", "shell",
                "systemctl daemon-reload",
            ],
            [
                "adb", "-s", "SERIAL-1", "shell",
                "systemctl restart demo-worker.service",
            ],
            [
                "adb", "-s", "SERIAL-1", "shell",
                "systemctl status demo-worker.service --no-pager",
            ],
        ]

    def test_service_rejects_extra_arguments_before_device_selection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo", app_type="service")
        monkeypatch.setattr(
            deploy,
            "select_adb_device",
            lambda _: pytest.fail("不应选择设备"),
        )

        with pytest.raises(ValueError, match="不接受额外 argv"):
            deploy.run_app(
                str(app_dir),
                args=["--unexpected"],
                config=_config(),
                project_root=tmp_path,
            )

    def test_non_runnable_type_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo", app_type="lib")
        monkeypatch.setattr(
            deploy,
            "select_adb_device",
            lambda _: pytest.fail("不应选择设备"),
        )

        with pytest.raises(ValueError, match="无法推断"):
            deploy.run_app(
                str(app_dir),
                config=_config(),
                project_root=tmp_path,
            )


def test_service_log_uses_journalctl_and_follows_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_dir = _write_app(
        tmp_path / "demo",
        app_type="service",
        unit="systemd/demo-worker.service",
    )
    _, calls = _isolate_deploy(monkeypatch, tmp_path)

    deploy.log_app(
        str(app_dir),
        serial="SERIAL-1",
        config=_config(),
        project_root=tmp_path,
    )

    assert calls == [[
        "adb", "-s", "SERIAL-1", "shell",
        "journalctl -u demo-worker.service --no-pager -f",
    ]]


def test_service_log_options_remain_separate_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_dir = _write_app(tmp_path / "demo", app_type="service")
    _, calls = _isolate_deploy(monkeypatch, tmp_path)

    deploy.log_app(
        str(app_dir),
        serial="SERIAL-1",
        lines=20,
        since="1 hour ago; echo unsafe",
        follow=False,
        config=_config(),
        project_root=tmp_path,
    )

    assert calls == [[
        "adb", "-s", "SERIAL-1", "shell",
        "journalctl -u demo.service --no-pager -n 20 --since "
        "'1 hour ago; echo unsafe'",
    ]]


class TestDebug:
    def test_release_variant_is_rejected_before_device_selection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo")
        monkeypatch.setattr(
            deploy,
            "select_adb_device",
            lambda _: pytest.fail("不应选择设备"),
        )

        with pytest.raises(ValueError, match="debug variant"):
            deploy.debug_app(
                str(app_dir),
                config=_config("release"),
                project_root=tmp_path,
            )

    def test_exec_uses_target_gdb_and_forwards_arguments(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo")
        _, calls = _isolate_deploy(monkeypatch, tmp_path)

        deploy.debug_app(
            str(app_dir),
            serial="SERIAL-1",
            args=["--mode", "a b"],
            config=_config(),
            project_root=tmp_path,
        )

        assert calls == [[
            "adb", "-s", "SERIAL-1", "shell", "-t",
            "gdb --args /usr/bin/demo --mode 'a b'",
        ]]

    def test_service_reads_main_pid_then_attaches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(
            tmp_path / "demo",
            app_type="service",
            unit="systemd/demo-worker.service",
        )
        calls: list[list[str]] = []
        monkeypatch.setattr(deploy, "select_adb_device", lambda _: "SERIAL-1")

        def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess:
            calls.append(argv)
            stdout = "321\n" if argv[-1].startswith("systemctl show ") else ""
            return _completed(argv, stdout)

        monkeypatch.setattr(deploy, "_run_checked", fake_run)

        deploy.debug_app(
            str(app_dir),
            config=_config(),
            project_root=tmp_path,
        )

        assert calls == [
            [
                "adb", "-s", "SERIAL-1", "shell",
                "systemctl show demo-worker.service --property MainPID --value",
            ],
            ["adb", "-s", "SERIAL-1", "shell", "-t", "gdb -p 321"],
        ]

    def test_service_without_main_pid_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app_dir = _write_app(tmp_path / "demo", app_type="service")
        monkeypatch.setattr(deploy, "select_adb_device", lambda _: "SERIAL-1")
        monkeypatch.setattr(
            deploy,
            "_run_checked",
            lambda argv, **_: _completed(argv, "0\n"),
        )

        with pytest.raises(deploy.DeployError, match="MainPID"):
            deploy.debug_app(
                str(app_dir),
                config=_config(),
                project_root=tmp_path,
            )


def test_legacy_module_main_uses_shared_run_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, str | None]] = []

    def fake_run(app: str, build_deb: bool, *, serial: str | None) -> str:
        calls.append((app, build_deb, serial))
        return serial or "ONLY"

    monkeypatch.setattr(deploy, "run_app", fake_run)

    assert deploy.main(["demo", "--run", "--no-build", "--serial", "SERIAL-1"]) == 0
    assert calls == [("demo", False, "SERIAL-1")]
