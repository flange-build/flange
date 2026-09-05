"""严格边界回归：错误在消费者运行前失败，输入类型不改变校验语义。"""

import pytest
import yaml

from builder.app_spec import AppSpecError, load_spec
from builder.config.apps import AppSourceConfigError, normalize_app_sources
from builder.config.jsonnet import JsonnetConfigLoader, ResolvedConfig
from builder.config.validate import ConfigError, validate_config
from builder.deb import generate_control
from builder.packages import load_package_manifest_dir
from builder.paths import PROJECT_ROOT


def system_config():
    return {
        "architecture": {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm"},
        "board": "demo",
        "platform": "amlogic",
        "soc": "demo",
        "product": "default",
        "variant": "release",
        "sources": {"kernel": {"url": "https://example.test/kernel.git", "commit": "abc"}},
        "kernel": {"source": {"name": "kernel"}, "device_tree": {"directory": "", "name": "demo"}},
    }


@pytest.mark.parametrize("wrapper", [dict, ResolvedConfig])
@pytest.mark.parametrize(
    "section,value,field",
    [
        ("recovery", {"enabeld": True}, "recovery.enabeld"),
        ("recovery", {"enabled": "false"}, "recovery.enabled"),
        ("amp", {"enabled": False, "memory": {"cpu": True}}, "amp.memory.cpu"),
        ("sources", {"kernel": {"url": 42}}, "sources.kernel.url"),
        (
            "sources",
            {"kernel": {"url": "repo", "recurse_submodules": "false"}},
            "recurse_submodules",
        ),
        ("rootfs", {"packages": "curl"}, "rootfs.packages"),
        ("rootfs", {"users": {"demo": {"sodu": True}}}, "rootfs.users.demo.sodu"),
        ("boot", {"overlays": {"enabled": [False]}}, "boot.overlays.enabled"),
        ("partitions", {"sector_size": True}, "partitions.sector_size"),
        ("packages", [{"name": "demo", "drivers": [1]}], "drivers"),
    ],
)
def test_system_rejects_invalid_fields_for_every_mapping_type(wrapper, section, value, field):
    config = system_config()
    config[section] = value
    with pytest.raises(ConfigError, match=field):
        validate_config(wrapper(config))


def test_authored_shape_precedes_expansion_and_rejects_derived_metadata():
    for payload, field in [
        ({"rootfs": {"packages": "curl"}}, "rootfs.packages"),
        ({"packages_meta": {}}, "packages_meta"),
        ({"boot": {"package_overlay_sources": {}}}, "package_overlay_sources"),
    ]:
        with pytest.raises(ConfigError, match=field):
            JsonnetConfigLoader._validate_authored_shape(payload)


def test_dynamic_map_names_are_not_confused_with_structural_dimensions():
    config = system_config()
    config["sources"]["product"] = {"url": "https://example.test/product.git"}
    validate_config(config)


@pytest.mark.parametrize(
    "value",
    [
        {"git": "repo", "commmit": "abc"},
        {"git": "repo", "branch": 42},
        {"git": "repo", "recurse_submodules": "false"},
        {"local_path": "app", "branch": "main"},
    ],
)
def test_external_source_entrypoint_is_strict(tmp_path, value):
    with pytest.raises(AppSourceConfigError, match="external_apps"):
        normalize_app_sources({"external_apps": {"demo": value}}, tmp_path)


def app_config():
    return {
        "app": {
            "name": "demo",
            "version": "1.0",
            "description": "测试",
            "type": "exec",
            "arch": ["aarch64"],
        },
        "maintainer": {"name": "flange", "email": "flange@example.test"},
    }


def write_app(tmp_path, config):
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "section,value,field",
    [
        ("capabilities", [], "capabilities"),
        ("lib", {"headers_dir": "include"}, "headers_dir"),
        ("build", {"systme": "cmake"}, "systme"),
        ("build", {"system": "cmake", "outputs": ["demo"]}, "outputs"),
        ("build", {"system": "custom", "commands": ["make"]}, "commands"),
        ("build", {"system": "custom", "commands": [["make", 2]]}, "commands"),
        ("build", {"system": "none", "options": {"ignored": "yes"}}, "options"),
        ("build", {"system": "cmake", "commands": [["make"]]}, "commands"),
        ("systemd", {"unit": "demo.service", "auto_start": "false"}, "auto_start"),
        ("runtime", {"executable": "../demo"}, "runtime.executable"),
        ("runtime", {"executable": "/usr/../bin/demo"}, "runtime.executable"),
        ("install", {"demo": "usr/bin/demo"}, "install"),
        ("depends", [12], "depends"),
    ],
)
def test_app_rejects_silent_coercion_and_unconsumed_fields(tmp_path, section, value, field):
    config = app_config()
    config[section] = value
    with pytest.raises(AppSpecError, match=field):
        load_spec(write_app(tmp_path, config))


def test_yaml_duplicate_keys_are_not_last_writer_wins(tmp_path):
    config = yaml.safe_dump(app_config()) + "runtime: {}\nruntime: {}\n"
    (tmp_path / "app.yaml").write_text(config)
    with pytest.raises(AppSpecError, match="重复字段.*runtime"):
        load_spec(tmp_path)


@pytest.mark.parametrize("app_type", ["exec", "test"])
def test_custom_runtime_path_and_test_action_survive_parsing(tmp_path, app_type):
    config = app_config()
    config["app"]["type"] = app_type
    config["runtime"] = {"executable": "/opt/demo/bin/demo"}
    config["actions"] = {"test": ["./verify.sh", "literal;argument"]}
    spec = load_spec(write_app(tmp_path, config))
    assert spec.runtime.executable == "/opt/demo/bin/demo"
    assert spec.actions["test"] == ["./verify.sh", "literal;argument"]


@pytest.mark.parametrize("auto_start", [False, True])
def test_service_auto_start_controls_generated_install_script(tmp_path, auto_start):
    config = app_config()
    config["app"]["type"] = "service"
    config["systemd"] = {"unit": "demo.service", "auto_start": auto_start}
    config["data_dirs"] = ["/var/lib/demo"]
    spec = load_spec(write_app(tmp_path, config))
    script = generate_control(spec, "aarch64")["postinst"]
    assert ("systemctl enable demo.service" in script) is auto_start
    assert ("ln -sf" in script) is auto_start
    assert "systemctl daemon-reload" in script
    assert "mkdir -p /var/lib/demo" in script


@pytest.mark.parametrize(
    "component,field",
    [
        (
            {"name": "driver", "type": "oot-driver", "dir": "driver", "ko_pattern": "*.ko"},
            "ko_pattern",
        ),
        ({"name": "app", "type": "vendor", "dir": "../outside"}, "dir"),
        ({"name": "app", "type": "vendor", "dir": ".", "options": {}}, "options"),
        ({"name": "overlay", "type": "devicetree", "overlays": {"board": False}}, "overlays.board"),
    ],
)
def test_package_discriminated_schema(tmp_path, component, field):
    package = tmp_path / "demo"
    package.mkdir()
    (package / "package.py").write_text(
        f"PACKAGE = {dict(name='demo', components=[component])!r}\n"
    )
    with pytest.raises(ValueError, match=field):
        load_package_manifest_dir(package)


def test_package_rejects_symlink_escape(tmp_path):
    package = tmp_path / "demo"
    package.mkdir()
    (package / "outside").symlink_to(tmp_path, target_is_directory=True)
    component = {"name": "app", "type": "vendor", "dir": "outside"}
    (package / "package.py").write_text(
        f"PACKAGE = {dict(name='demo', components=[component])!r}\n"
    )
    with pytest.raises(ValueError, match="符号链接越出"):
        load_package_manifest_dir(package)


def test_all_repository_app_and_package_manifests_are_strict():
    manifests = sorted((PROJECT_ROOT / "components").rglob("app.yaml"))
    assert manifests
    for manifest in manifests:
        load_spec(manifest.parent)
    for manifest in sorted((PROJECT_ROOT / "components/packages").glob("*/package.py")):
        load_package_manifest_dir(manifest.parent)


def test_ci_uses_scoped_pinned_openspec_and_canonical_target_parser(tmp_path, monkeypatch):
    ci = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text()
    assert "@fission-ai/openspec@1.2.0 validate --all --strict" in ci
    workflow = yaml.safe_load((PROJECT_ROOT / ".github/workflows/build.yml").read_text())
    step = next(item for item in workflow["jobs"]["build"]["steps"] if item.get("id") == "target")
    assert "from builder.config.query import parse_target" in step["run"]
    assert "${{ inputs.target }}" not in step["run"]
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("FLANGE_CI_TARGET", "orangepi-cm4-amp-rtt-release")
    python_source = "\n".join(step["run"].splitlines()[1:-1])
    exec(compile(python_source, "workflow-target.py", "exec"), {})
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields == {
        "board": "orangepi-cm4",
        "product": "amp-rtt",
        "variant": "release",
        "outdir": ".build/target/orangepi-cm4/amp-rtt/release",
    }


def test_recovery_phase1_fields_survive_strict_config_and_drive_plan(tmp_path):
    from builder.rootfs_base import base_plan
    from tests.builder.context import component_context

    config = system_config()
    config["recovery"] = {
        "install_recommends": True,
        "extra_apt_sources": [
            {
                "name": "vendor",
                "source": "deb https://example.test noble main",
                "key": {"url": "https://example.test/key", "sha256": "a" * 64},
            }
        ],
    }
    validate_config(config)
    apt = base_plan(config, "recovery", component_context(tmp_path, config)).value("apt")
    assert apt["install_recommends"] is True
    assert apt["extra_sources"] == config["recovery"]["extra_apt_sources"]


@pytest.mark.parametrize(
    "change,field",
    [
        ({"install_recommends": "false"}, "install_recommends"),
        ({"extra_apt_sources": "vendor"}, "extra_apt_sources"),
        (
            {
                "extra_apt_sources": [
                    {
                        "name": "../escape",
                        "source": "deb url noble main",
                        "key": {"url": "key", "sha256": "a" * 64},
                    }
                ]
            },
            "name",
        ),
        (
            {
                "extra_apt_sources": [
                    {
                        "name": "vendor",
                        "source": "deb url noble main",
                        "key": {"url": "key", "sha256": "invalid"},
                    }
                ]
            },
            "sha256",
        ),
    ],
)
def test_recovery_phase1_fields_reject_invalid_types_and_downloads(change, field):
    config = system_config()
    config["recovery"] = change
    with pytest.raises(ConfigError, match=field):
        validate_config(config)
