from builder.config.jsonnet import JsonnetEvaluator
from builder.paths import PROJECT_ROOT


def test_jsonnet_sources_have_chinese_responsibility_comment():
    components = PROJECT_ROOT / "components"
    sources = sorted(components.rglob("*.jsonnet"))
    sources += sorted(components.rglob("*.libsonnet"))

    missing = []
    for path in sources:
        first_line = path.read_text(encoding="utf-8").lstrip().partition("\n")[0]
        has_chinese = any("\u4e00" <= char <= "\u9fff" for char in first_line)
        if not first_line.startswith("//") or not has_chinese:
            missing.append(str(path.relative_to(PROJECT_ROOT)))

    assert sources
    assert missing == []


def test_rootfs_jsonnet_package_set_matches_variant():
    evaluator = JsonnetEvaluator(PROJECT_ROOT)
    path = PROJECT_ROOT / "components/rootfs/config.jsonnet"

    debug = evaluator.evaluate_file(
        path, ext_vars={"product": "default", "variant": "debug"})
    release = evaluator.evaluate_file(
        path, ext_vars={"product": "default", "variant": "release"})

    assert debug.config["rootfs"]["package_set"] == ["base", "debug"]
    assert release.config["rootfs"]["package_set"] == ["base", "release"]


def test_overlay_jsonnet_uses_canonical_source_reference():
    result = JsonnetEvaluator(PROJECT_ROOT).evaluate_file(
        PROJECT_ROOT / "components/device-tree-overlay/config.jsonnet",
        ext_vars={"product": "default", "variant": "release"},
    ).config

    ref = result["device-tree-overlay"]["source"]["name"]
    assert result["sources"][ref] == {
        "url": "https://github.com/radxa-pkg/radxa-overlays.git",
        "commit": "902ba0e8672c8e79db9f5f675fe35f697ff3beb3",
    }
