"""多层组合、来源边界与工作区隔离的行为测试。"""

import json
from pathlib import Path

import pytest

from builder.config.jsonnet import JsonnetConfigLoader, JsonnetEvaluator
from builder.config.query import get_valid_targets
from builder.layers import LayerError, LayerStack
from builder.source import SourceManager
from builder.workspace import load_workspace, workspace_settings


def put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return file


def layer(root, name, requires=(), providers=""):
    put(
        root,
        "layer.toml",
        f'schema_version = 1\napi_version = 1\nname = "{name}"\n'
        f"requires = {json.dumps(list(requires))}\n{providers}",
    )
    return root


@pytest.fixture
def tree(tmp_path, monkeypatch):
    base = tmp_path / "flange"
    put(base, "docker-compose.yml", "services: {}")
    configs = {
        "rootfs": "{rootfs: {packages: ['base']}}",
        "platform/demo": "{platform:'demo', vendor:'demo', flash_tool:'none', "
        "architecture:{userspace:'aarch64',kernel:'arm64',bootloader:'arm64'}}",
        "platform/demo/chip": "{platform:'demo',soc:'chip'}",
        "board/test": "{board:'test', platform:'demo',soc:'chip', products:['default'],"
        "variants:['release'],kernel:{device_tree:{directory:'demo',name:'test'},config:{CONFIG_CHOICE:'board'}},"
        "recovery:{enabled:false}}",
    }
    for path, source in configs.items():
        put(base, f"components/{path}/config.jsonnet", "// 测试配置。\n" + source)
    monkeypatch.setattr("builder.config.validate.validate_platform", lambda *_: None)
    monkeypatch.setattr(
        "builder.config.validate._run_platform_validation", lambda *_: None
    )
    return base


def test_workspace_target_uses_all_layers(tree, tmp_path):
    vendor = layer(tmp_path / "vendor", "vendor", ["flange"])
    product = layer(tmp_path / "product", "product", ["vendor"])
    put(
        vendor,
        "components/platform/demo/config.jsonnet",
        "{kernel+: {config+: {CONFIG_CHOICE: 'vendor'}}}",
    )
    put(
        product,
        "components/board/test/config.jsonnet",
        "{products+: ['custom'],rootfs+: {packages+: ['custom']}}",
    )
    put(
        product,
        "flange.toml",
        'schema_version=2\ntool_root="../flange"\nlayers=["../vendor", "."]\n',
    )
    context = load_workspace(product, target="test-custom-release", tool_root=tree)
    assert context.target.product == "custom"
    loader = JsonnetConfigLoader(tree, layer_stack=context.layer_stack)
    cfg = loader.evaluate_board("test", "custom", "release")
    assert cfg["rootfs"]["packages"] == ["base", "custom"]
    assert cfg["kernel"]["config"]["CONFIG_CHOICE"] == "board"
    assert "test-custom-release" in get_valid_targets(
        project_root=tree, layer_stack=context.layer_stack
    )
    assert cfg.config_chain[-1].startswith("layer://product/")


@pytest.mark.parametrize("case", ["order", "missing", "duplicate", "path", "cycle"])
def test_rejects_invalid_layers(tree, tmp_path, case):
    one = layer(tmp_path / "one", "one", ["flange"])
    two = layer(tmp_path / "two", "two", ["one"])
    paths = [one, two]
    if case == "order":
        paths.reverse()
    elif case == "missing":
        paths = [two]
    elif case == "duplicate":
        layer(two, "one")
    elif case == "path":
        paths = [one, one]
    else:
        layer(one, "one", ["two"])
    with pytest.raises(LayerError):
        LayerStack.load(tree, paths)


def test_import_ownership_and_cross_layer_helper(tree, tmp_path):
    upper = layer(tmp_path / "upper", "upper")
    base_lib = put(tree, "components/config/shared.libsonnet", "{value:'base'}")
    put(upper, "components/config/shared.libsonnet", "{value:'upper'}")
    entry = put(
        upper,
        "components/board/test/config.jsonnet",
        """
local p = import 'flange/layer.libsonnet';
local own = import 'config/shared.libsonnet';
local lower = import 'layer://flange/components/config/shared.libsonnet';
{own:own.value,lower:lower.value,path:p.path('assets/source')}
""",
    )
    stack = LayerStack.load(tree, [upper])
    result = JsonnetEvaluator(tree, layer_stack=stack).evaluate_file(entry)
    assert result.config == {
        "own": "upper",
        "lower": "base",
        "path": "layer://upper/assets/source",
    }
    assert stack.resolve_values(result.config)["path"] == str(upper / "assets/source")
    assert base_lib in result.dependencies
    with pytest.raises(LayerError):
        stack.uri("layer://upper/../secret")
    with pytest.raises(LayerError):
        stack.uri("layer://missing/components/config/a.libsonnet")


def test_patch_replacement_preserves_position(tree, tmp_path):
    upper = layer(tmp_path / "upper", "upper")
    directory = "components/platform/demo/patches/kernel"
    put(tree, f"{directory}/01.patch", "old")
    put(tree, f"{directory}/02.patch", "second")
    replacement = put(upper, f"{directory}/01.patch", "new")
    addition = put(upper, f"{directory}/00.patch", "addition")
    stack = LayerStack.load(tree, [upper])
    assert [r.path for r in stack.files(directory, "*.patch")] == [
        replacement,
        tree / directory / "02.patch",
        addition,
    ]


def test_selected_package_does_not_inherit_lower_files(tree, tmp_path):
    upper = layer(tmp_path / "upper", "upper")
    put(
        tree,
        "components/packages/sample/package.py",
        "PACKAGE={'name':'sample','components':[]}",
    )
    put(
        tree,
        "components/packages/sample/config.jsonnet",
        "{rootfs+: {packages+: ['lower']}}",
    )
    put(
        upper,
        "components/packages/sample/package.py",
        "PACKAGE={'name':'sample','components':[]}",
    )
    put(upper, "components/board/test/config.jsonnet", "{packages:['sample']}")
    cfg = JsonnetConfigLoader(
        tree, layer_stack=LayerStack.load(tree, [upper])
    ).evaluate_board("test", "default", "release")
    assert cfg["rootfs"]["packages"] == ["base"]


def test_provider_namespaces_and_relative_imports(tree, tmp_path):
    roots = []
    for name in ("one", "two"):
        root = tmp_path / name
        put(root, "strategies/entry.py", "from .helper import VALUE\n")
        put(root, "strategies/helper.py", f"VALUE={name!r}\n")
        roots.append(
            layer(
                root, name, providers='[providers.platform]\ndemo="strategies/entry.py"'
            )
        )
    stacks = [LayerStack.load(tree, [root]) for root in roots]
    assert [s.provider("platform", "demo").VALUE for s in stacks] == ["one", "two"]
    assert not list(tmp_path.rglob("__pycache__"))
    assert len(stacks[0].provider_inputs("platform", "demo")) == 2


def test_legacy_workspace_has_only_base(tree):
    settings = workspace_settings(tree, tool_root=tree)
    assert [item.name for item in settings["layer_stack"].layers] == ["flange"]


def test_non_ubuntu_baseline_is_independent(tree, tmp_path):
    upper = layer(tmp_path / "debian", "debian")
    put(
        upper,
        "components/distro/debian/config.jsonnet",
        "{rootfs:{packages:['debian-only']}}",
    )
    put(upper, "components/board/test/config.jsonnet", "{distro:'debian'}")
    cfg = JsonnetConfigLoader(
        tree, layer_stack=LayerStack.load(tree, [upper])
    ).evaluate_board("test", "default", "release")
    assert cfg["rootfs"]["packages"] == ["debian-only"]
    assert all("components/rootfs/" not in path for path in cfg.config_chain)


def test_external_app_whole_override(tree, tmp_path):
    upper = layer(tmp_path / "upper", "upper")
    put(tree, "components/app/demo/app.yaml", "app: {}")
    put(upper, "components/app/demo/README.md", "上层缺少描述文件")
    from builder.config.jsonnet import ResolvedConfig

    cfg = ResolvedConfig({})
    cfg.layer_stack = LayerStack.load(tree, [upper])
    source = SourceManager(project_root=tree)
    with pytest.raises((ValueError, FileNotFoundError), match="app.yaml"):
        source.locate_app("demo", cfg)
    from builder.app_list import list_all
    assert list_all(tree, cfg)[0].source_path == upper / "components/app/demo"


def test_overlay_type_replacement_and_hidden_inputs(tree, tmp_path):
    from builder.layer_resources import copy_overlay, overlay_entries, overlay_resources
    from builder.digest import hash_path

    lower = put(tree, "components/board/test/overlay/etc/value", "lower")
    upper = layer(tmp_path / "upper", "upper")
    replacement = put(upper, "components/board/test/overlay/etc/value", "upper")
    link = upper / "components/board/test/overlay/run"
    link.symlink_to("/run/runtime")
    stack = LayerStack.load(tree, [upper])
    config = {"board": "test", "platform": "demo"}
    entries = overlay_entries(stack, config, "rootfs")
    assert entries["etc/value"].path == replacement
    before = {path: hash_path(ref.path) for path, ref in entries.items()}
    lower.write_text("无效的下层变更")
    assert before == {
        path: hash_path(ref.path)
        for path, ref in overlay_entries(stack, config, "rootfs").items()
    }
    dest = tmp_path / "output"
    put(dest, "etc", "此前是文件")
    for ref in overlay_resources(stack, config, "rootfs"):
        copy_overlay(ref.path, dest)
    assert (dest / "etc/value").read_text() == "upper"
    assert (dest / "run").readlink() == Path("/run/runtime")
    assert link.is_symlink()


def test_layer_file_symlink_cannot_escape(tree, tmp_path):
    outside = put(tmp_path, "outside", "保密")
    (tree / "link").symlink_to(outside)
    with pytest.raises(LayerError, match="越界"):
        LayerStack.base(tree).uri("layer://flange/link")


def test_external_strategy_helpers_and_patch_order_are_inputs(tree, tmp_path):
    from builder.component_plan import create_component_plan
    from builder.workspace import resolve_config

    upper = layer(
        tmp_path / "upper",
        "upper",
        providers='[providers.platform]\ndemo="strategy/provider.py"',
    )
    put(
        upper,
        "strategy/provider.py",
        """from builder.base import ComponentBuilder
from .helper import VALUE
ARTIFACT_NAMES = {}
class Builder(ComponentBuilder):
    def configure(self, src, config): pass
    def compile(self, src, config): pass
    def collect(self, src, config): return {}
def create_builder(component, docker, source):
    return Builder(docker, source)
""",
    )
    helper = put(upper, "strategy/helper.py", "VALUE=1\n")
    low = put(tree, "components/platform/demo/patches/kernel/01.patch", "lower")
    high = put(upper, "components/platform/demo/patches/kernel/01.patch", "upper")
    put(
        upper,
        "flange.toml",
        f'schema_version=2\ntool_root={json.dumps(str(tree))}\nlayers=["."]\n',
    )
    context = load_workspace(upper, target="test-default-release")
    cfg = resolve_config(context)
    source = SourceManager(context=context)
    plan = create_component_plan("kernel", cfg, context, source)
    before = plan.fingerprint()
    low.write_text("下层被覆盖内容")
    put(upper, "components/board/irrelevant/file", "无关输入")
    assert plan.fingerprint() == before
    high.write_text("生效补丁变化")
    assert plan.fingerprint() != before
    changed = plan.fingerprint()
    helper.write_text("VALUE=2\n")
    assert plan.fingerprint() != changed
    assert plan.value("patch:sequence") == [
        "layer://upper/components/platform/demo/patches/kernel/01.patch"
    ]


def test_external_toolchain_sdk_flags_and_abi_inputs(tree, tmp_path):
    from builder.config.jsonnet import ResolvedConfig
    from builder.toolchain import Toolchain, userland_identity
    from builder.workspace import WorkspaceContext, Target

    upper = layer(
        tmp_path / "sdk",
        "sdk",
        providers='[providers.toolchain]\nsdk="strategy/provider.py"',
    )
    sdk = upper / "components/sdk"
    header = put(sdk, "usr/include/test.h", "one")
    put(
        upper,
        "strategy/provider.py",
        f"""from builder.toolchain import Toolchain
def create_toolchain(config, context):
    return Toolchain("aarch64", "aarch64-linux-gnu", "aarch64", "aarch64", profile="sdk", target_sysroot={str(sdk)!r}, sdk_identity="v1", sdk_source="directory")
""",
    )
    stack = LayerStack.load(tree, [upper])
    context = WorkspaceContext(
        tree,
        upper,
        upper / ".build",
        Target("test", "default", "release"),
        upper,
        layer_stack=stack,
    )
    cfg = ResolvedConfig(
        {"userland_toolchain": "sdk", "architecture": {"userspace": "aarch64"}}
    )
    cfg.layer_stack = stack
    before = userland_identity(cfg, context)
    header.write_text("two")
    assert userland_identity(cfg, context) != before
    toolchain = Toolchain(
        "aarch64", "aarch64-linux-gnu", "aarch64", "aarch64", target_sysroot=str(sdk)
    )
    env = toolchain.environment(sdk)
    assert env["PKG_CONFIG_PATH"] == ""
    assert env["PKG_CONFIG_SYSROOT_DIR"] == str(sdk)
    toolchain.cmake_file(tmp_path / "toolchain.cmake", sdk)
    text = (tmp_path / "toolchain.cmake").read_text()
    assert 'CMAKE_FIND_ROOT_PATH_MODE_LIBRARY "ONLY"' in text
    toolchain.meson_file(tmp_path / "cross.ini", sdk)
    assert "sys_root" in (tmp_path / "cross.ini").read_text()


def test_local_base_archive_is_verified(tree, tmp_path):
    from builder.digest import file_sha256

    source = SourceManager(project_root=tree)
    archive = put(tmp_path, "archive.tar", "归档")
    result = source.ensure_download(
        "rootfs", "base", {"url": archive.as_uri(), "sha256": file_sha256(archive)}
    )
    assert result.read_text() == "归档"
    with pytest.raises(RuntimeError, match="sha256"):
        source.ensure_download(
            "rootfs", "base", {"url": archive.as_uri(), "sha256": "0" * 64}
        )


def test_provider_helper_reload_ignores_existing_bytecode(tree, tmp_path):
    import os
    import py_compile

    upper = layer(
        tmp_path / "upper",
        "upper",
        providers='[providers.platform]\ndemo="strategy/provider.py"',
    )
    put(upper, "strategy/provider.py", "from .helper import VALUE\n")
    helper = put(upper, "strategy/helper.py", "VALUE=1\n")
    py_compile.compile(str(helper))
    timestamp = helper.stat().st_mtime_ns
    stack = LayerStack.load(tree, [upper])
    assert stack.provider("platform", "demo").VALUE == 1
    helper.write_text("VALUE=2\n")
    os.utime(helper, ns=(timestamp, timestamp))
    assert stack.provider("platform", "demo").VALUE == 2


def test_flash_provider_identity_rejects_switch(tree, tmp_path):
    from builder.flash.execute import FlashExecutor
    from builder.flash.model import FlashConfig, FlashError

    upper = layer(
        tmp_path / "upper",
        "upper",
        providers='[providers.flash]\ndemo="strategy/provider.py"',
    )
    put(
        upper,
        "strategy/provider.py",
        """from builder.flash.strategy import FlashStrategy
class Fake(FlashStrategy):
    def partition_image_map(self, config): return {}
    def find_tool(self, root): return root / '模拟工具'
    def detect_device(self, tool): return None
    def pre_flash(self, *args): pass
    def reboot(self, *args): pass
    def write_partition(self, *args): raise AssertionError('禁止实机写入')
def create_strategy(): return Fake()
""",
    )
    stack = LayerStack.load(tree, [upper])
    output = tmp_path / "target"
    cfg = FlashConfig(
        "demo",
        "none",
        "test",
        "default",
        "release",
        provider=stack.provider_ref("flash", "demo").identity,
    )
    cfg.to_json(output / "flash-config.json")
    executor = FlashExecutor(output, tree, layer_stack=stack)
    assert executor.strategy.partition_image_map({}) == {}
    with pytest.raises(FlashError, match="身份"):
        FlashExecutor(output, tree, layer_stack=LayerStack.base(tree))


def test_extensions_require_provider_closed_schema(tree, tmp_path):
    from builder.config.validate import validate_config
    from builder.config.jsonnet import ResolvedConfig

    upper = layer(
        tmp_path / "upper",
        "upper",
        providers='[providers.platform]\ndemo="strategy/provider.py"',
    )
    put(
        upper,
        "strategy/provider.py",
        """from builder.config.schema import Object, STRING
EXTENSION_SCHEMA = Object({'mode': STRING}, ('mode',))
""",
    )
    cfg = ResolvedConfig(
        {
            "architecture": {
                "userspace": "aarch64",
                "kernel": "arm64",
                "bootloader": "arm64",
            },
            "extensions": {"platform:demo": {"typo": "value"}},
        }
    )
    cfg.layer_stack = LayerStack.load(tree, [upper])
    with pytest.raises(ValueError, match="typo|mode"):
        validate_config(cfg)


def test_environment_marker_mismatch_rejected(tree, tmp_path, monkeypatch):
    from builder.docker import DockerRunner, BuildError

    monkeypatch.setattr("builder.docker._is_inside_container", lambda: True)
    monkeypatch.setenv("FLANGE_ENVIRONMENT_PROVIDER", "different")
    monkeypatch.setenv("FLANGE_BUILD_ENVIRONMENT", "sha256:wrong")
    with pytest.raises(BuildError, match="不一致"):
        DockerRunner(project_dir=tree)


def test_external_packaging_provider_overrides_builtin(tree, tmp_path):
    from builder.packaging import get_backend
    upper = layer(tmp_path / "upper", "upper", providers='[providers.packaging]\ndeb="strategy/provider.py"')
    put(upper, "strategy/provider.py", '''from builder.packaging.deb import DebPackageBackend
class Custom(DebPackageBackend):
    marker = '外部策略'
def create_backend(): return Custom()
''')
    assert get_backend("deb", LayerStack.load(tree, [upper])).marker == "外部策略"
    assert not hasattr(get_backend("deb", LayerStack.base(tree)), "marker")


def test_old_app_report_requires_rebuild(tmp_path):
    from builder.app_model import AppBuildReport
    report = put(tmp_path, "report.json", '{"schema_version": 2}')
    with pytest.raises(ValueError):
        AppBuildReport.load(report)


def test_environment_dockerfile_outside_context_is_an_input(tree, tmp_path):
    from builder.build_environment import environment_inputs
    from builder.config.jsonnet import ResolvedConfig
    upper = layer(tmp_path / "upper", "upper", providers='[providers.environment]\ncustom="strategy/provider.py"')
    dockerfile = put(upper, "Dockerfile", "FROM scratch\n")
    (upper / "context").mkdir()
    put(upper, "strategy/provider.py", f'''from pathlib import Path
from builder.build_environment import BuildEnvironmentSpec
def create_environment(config, context):
    return BuildEnvironmentSpec('custom', 'custom:latest', Path({str(dockerfile)!r}), Path({str(upper / 'context')!r}))
''')
    cfg = ResolvedConfig({"build_environment": "custom"})
    cfg.layer_stack = LayerStack.load(tree, [upper])
    inputs = environment_inputs(cfg, None)
    selected = next(item for item in inputs if item.name == "environment:dockerfile")
    before = selected.digest()
    dockerfile.write_text("FROM debian:trixie-slim\n")
    assert selected.digest() != before
