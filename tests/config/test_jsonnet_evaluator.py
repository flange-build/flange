"""Jsonnet 配置求值边界测试。"""

from pathlib import Path

import pytest

from builder.config.jsonnet import (
    JsonnetConfigError,
    JsonnetConfigLoader,
    JsonnetEvaluator,
    ResolvedConfig,
)


def _config_tree(tmp_path: Path) -> tuple[JsonnetEvaluator, Path]:
    config_dir = tmp_path / "components" / "board" / "demo"
    config_dir.mkdir(parents=True)
    return JsonnetEvaluator(tmp_path), config_dir


def test_evaluate_file_returns_plain_dict_and_dependencies(tmp_path):
    evaluator, config_dir = _config_tree(tmp_path)
    library = config_dir / "values.libsonnet"
    entry = config_dir / "config.jsonnet"
    library.write_text('{ value: std.extVar("product") }')
    entry.write_text('(import "values.libsonnet") + { variant: std.extVar("variant") }')

    result = evaluator.evaluate_file(
        entry, ext_vars={"product": "demo", "variant": "debug"}
    )

    assert result.config == {"value": "demo", "variant": "debug"}
    assert result.dependencies == (entry, library)
    assert result.canonical_json == '{"value":"demo","variant":"debug"}'


def test_evaluate_snippet_preserves_filename_in_error(tmp_path):
    evaluator, _ = _config_tree(tmp_path)

    with pytest.raises(JsonnetConfigError, match=r"broken\.jsonnet:1"):
        evaluator.evaluate_snippet("broken.jsonnet", "{ broken: }")


@pytest.mark.parametrize(
    "import_name",
    ["../../outside.libsonnet", "/tmp/outside.libsonnet"],
)
def test_import_rejects_absolute_and_parent_paths(tmp_path, import_name):
    evaluator, config_dir = _config_tree(tmp_path)
    entry = config_dir / "config.jsonnet"
    entry.write_text(f'import "{import_name}"')

    with pytest.raises(JsonnetConfigError, match="允许根目录"):
        evaluator.evaluate_file(entry)


def test_import_rejects_symlink_escape(tmp_path):
    evaluator, config_dir = _config_tree(tmp_path)
    outside = tmp_path / "outside.libsonnet"
    outside.write_text("{}")
    (config_dir / "escape.libsonnet").symlink_to(outside)
    entry = config_dir / "config.jsonnet"
    entry.write_text('import "escape.libsonnet"')

    with pytest.raises(JsonnetConfigError, match="允许根目录"):
        evaluator.evaluate_file(entry)


def test_import_rejects_non_jsonnet_extension(tmp_path):
    evaluator, config_dir = _config_tree(tmp_path)
    (config_dir / "values.json").write_text("{}")
    entry = config_dir / "config.jsonnet"
    entry.write_text('import "values.json"')

    with pytest.raises(JsonnetConfigError, match="扩展名"):
        evaluator.evaluate_file(entry)


def test_content_hash_tracks_imports_and_target_but_not_unrelated_board(tmp_path):
    evaluator, config_dir = _config_tree(tmp_path)
    library = config_dir / "values.libsonnet"
    entry = config_dir / "config.jsonnet"
    library.write_text("{ value: 1 }")
    entry.write_text('import "values.libsonnet"')

    result = evaluator.evaluate_file(entry)
    baseline = evaluator.content_hash(
        result, board="demo", product="default", variant="release"
    )

    unrelated = tmp_path / "components" / "board" / "other"
    unrelated.mkdir()
    (unrelated / "config.jsonnet").write_text("{ unrelated: true }")
    assert evaluator.content_hash(
        result, board="demo", product="default", variant="release"
    ) == baseline

    library.write_text("{ value: 2 }")
    assert evaluator.content_hash(
        result, board="demo", product="default", variant="release"
    ) != baseline
    assert evaluator.content_hash(
        result, board="demo", product="other", variant="release"
    ) != baseline


def test_components_relative_library_without_preserves_order(tmp_path):
    evaluator, config_dir = _config_tree(tmp_path)
    library_dir = tmp_path / "components" / "config"
    library_dir.mkdir()
    library = library_dir / "lib.libsonnet"
    library.write_text(
        "{ without(values, removed):: "
        "[value for value in values if !std.member(removed, value)] }"
    )
    entry = config_dir / "config.jsonnet"
    entry.write_text(
        'local lib = import "config/lib.libsonnet"; '
        '{ values: lib.without(["a", "b", "a", "c"], ["a"]) }'
    )

    result = evaluator.evaluate_file(entry)

    assert result.config == {"values": ["b", "c"]}
    assert library in result.dependencies


def _skip_platform_validation(monkeypatch) -> None:
    """本组测试用合成平台 `demo` 验证 layer loader 的组合顺序。

    `demo` 没有对应的 `builder/platforms/demo/` 包，所以两处平台相关校验都
    不在本测试范围内：平台扩展校验（找不到模块本就静默跳过）与平台名注册
    校验（`validate_platform`，它保证写错的平台名在配置阶段就报错）。
    """
    monkeypatch.setattr(
        "builder.config.validate._run_platform_validation", lambda *_: None
    )
    monkeypatch.setattr(
        "builder.config.validate.validate_platform", lambda *_: None
    )


def _layered_config_tree(tmp_path: Path) -> None:
    files = {
        "rootfs/config.jsonnet": "{ rootfs: { packages: ['base'] } }",
        "device-tree-overlay/config.jsonnet": (
            "{ sources+: { overlays: { url: 'https://example/overlays.git' } } }"
        ),
        "platform/demo/config.jsonnet": (
            "{ platform: 'demo', vendor: 'demo', flash_tool: 'none', "
            "architecture: {userspace: 'aarch64', kernel: 'arm64', "
            "bootloader: 'arm64'}, rootfs+: { packages+: ['platform'] } }"
        ),
        "platform/demo/chip/config.jsonnet": (
            "{ platform: 'demo', soc: 'chip', "
            "kernel: {config: {CONFIG_CHIP_FACT: 'y'}, "
            "device_tree: {directory: 'demo'}} }"
        ),
        "board/demo-board/config.jsonnet": (
            "{ board: 'demo-board', platform: 'demo', soc: 'chip', "
            "products: ['same', 'other'], variants: ['same', 'release'], "
            "kernel+: {device_tree+: {name: 'demo'}}, "
            "rootfs+: { packages+: "
            "if std.extVar('product') == 'same' then ['product'] else [] }, "
            "boot: {kernel_args: if std.extVar('product') == 'same' "
            "then 'product' else 'other'}, recovery: {enabled: false} }"
        ),
    }
    for relative, content in files.items():
        path = tmp_path / "components" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_layer_loader_composes_in_fixed_order_and_separates_dimensions(
    tmp_path, monkeypatch
):
    _layered_config_tree(tmp_path)
    _skip_platform_validation(monkeypatch)
    loader = JsonnetConfigLoader(tmp_path)

    config = loader.evaluate_board("demo-board", "same", "release")

    assert isinstance(config, ResolvedConfig)
    assert config["rootfs"]["packages"] == [
        "base", "platform", "product",
    ]
    assert config["boot"]["kernel_args"] == "product"
    assert config["kernel"]["config"]["CONFIG_CHIP_FACT"] == "y"
    assert config["product"] == "same"
    assert config["variant"] == "release"
    assert config["sources"]["overlays"]["url"].endswith("overlays.git")
    assert len(config.jsonnet_dependencies) == 5
    assert config.jsonnet_hash


def test_layer_loader_appends_selected_package_config_once(
    tmp_path, monkeypatch
):
    _layered_config_tree(tmp_path)
    board_path = tmp_path / "components/board/demo-board/config.jsonnet"
    board_path.write_text(
        board_path.read_text().replace(
            "products: ['same', 'other'],",
            "products: ['same', 'other'], packages: ['desktop'],",
        )
    )
    package_dir = tmp_path / "components/packages/desktop"
    package_dir.mkdir(parents=True)
    (package_dir / "package.py").write_text(
        "PACKAGE = {'name': 'desktop', 'components': []}\n"
    )
    (package_dir / "config.jsonnet").write_text(
        "// 测试 package 配置：验证后置 overlay 与非递归选择。\n"
        "{ rootfs+: { packages+: ['desktop'] }, packages+: ['nested'] }\n"
    )
    _skip_platform_validation(monkeypatch)

    config = JsonnetConfigLoader(tmp_path).evaluate_board(
        "demo-board", "same", "release"
    )

    assert config["rootfs"]["packages"] == [
        "base", "platform", "product", "desktop",
    ]
    assert config["packages"] == ["desktop"]
    assert package_dir / "config.jsonnet" in config.jsonnet_dependencies


def test_layer_loader_rejects_identity_mismatch(tmp_path):
    _layered_config_tree(tmp_path)
    board_path = tmp_path / "components" / "board" / "demo-board" / "config.jsonnet"
    board_path.write_text("{ board: 'wrong', platform: 'demo', soc: 'chip' }")

    with pytest.raises(JsonnetConfigError, match="身份与目录不一致"):
        JsonnetConfigLoader(tmp_path).board_identity("demo-board")


@pytest.mark.parametrize(
    "soc_override",
    [
        "rootfs+: { packages+: ['policy'] }",
        "storage: { type: 'emmc' }",
        "kernel+: { device_tree+: { name: 'single-board' } }",
        "amp: { enabled: true }",
    ],
)
def test_layer_loader_rejects_board_policy_in_soc(tmp_path, soc_override):
    _layered_config_tree(tmp_path)
    soc_path = (
        tmp_path / "components" / "platform" / "demo" / "chip" /
        "config.jsonnet"
    )
    soc_path.write_text(
        "{ platform: 'demo', soc: 'chip', " + soc_override + " }"
    )

    with pytest.raises(JsonnetConfigError, match="SoC overlay 不得"):
        JsonnetConfigLoader(tmp_path).evaluate_board(
            "demo-board", "same", "release"
        )
