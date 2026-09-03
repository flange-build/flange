"""硬件特性包（components/packages）机制测试。

覆盖：清单加载与校验、board opt-in 解析、按类型展开到既有配置结构、
按需编译筛选；并验证 dtb_overlay 四源并集 / 撞名 / default 子集校验。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.config.jsonnet import ResolvedConfig
from builder.dtb_overlay import (
    all_declared_overlays,
    package_overlays,
    runtime_overlays,
)
from builder.packages import (
    _parse_opt_in,
    expand_hardware_packages,
    load_package_manifest,
    load_package_manifest_dir,
    resolve_package_dir,
)


def _write_package(root: Path, name: str, package_py: str,
                   files: dict[str, str] | None = None) -> None:
    """在临时项目根下创建 components/packages/<name>/ 包。"""
    pkg_dir = root / "components" / "packages" / name
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.py").write_text(package_py, encoding="utf-8")
    for rel, content in (files or {}).items():
        f = pkg_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")


_MEIZU_LIKE = """
PACKAGE = {
    "name": "demo-panel",
    "components": [
        {"type": "oot-driver", "name": "touch", "dir": "driver/touch",
         "ko_pattern": ["touch.ko"]},
        {"type": "oot-driver", "name": "bl", "dir": "driver/bl",
         "ko_pattern": ["bl.ko"]},
        {"type": "devicetree", "name": "panel",
         "overlays": {"my-board": "device-tree/my-board-demo.dtso"}},
    ],
}
"""

_VENDOR_PACKAGE = """
PACKAGE = {
    "name": "demo-firmware",
    "components": [
        {"type": "vendor", "name": "demo-firmware",
         "dir": "."},
    ],
}
"""

_VENDOR_APP = """
app:
  name: demo-firmware
  version: 1.0.0
  description: 测试固件
  type: vendor
  arch: [aarch64]
maintainer:
  name: flange
  email: flange@localhost
"""


@pytest.fixture
def demo_root(tmp_path: Path) -> Path:
    _write_package(tmp_path, "demo-panel", _MEIZU_LIKE, files={
        "driver/touch/touch.c": "/* touch */\n",
        "driver/touch/Makefile": "obj-m += touch.o\n",
        "driver/bl/bl.c": "/* bl */\n",
        "driver/bl/Makefile": "obj-m += bl.o\n",
        "device-tree/my-board-demo.dtso": "/dts-v1/;\n/plugin/;\n",
    })
    return tmp_path


# ---- 清单加载与校验 ----

def test_load_valid_manifest(demo_root: Path):
    pkg = load_package_manifest("demo-panel", demo_root)
    assert pkg["name"] == "demo-panel"
    assert len(pkg["components"]) == 3


def test_old_firmware_component_type_is_invalid(tmp_path: Path):
    _write_package(tmp_path, "bad", """
PACKAGE = {"name": "bad", "components": [{"type": "firmware", "name": "x"}]}
""")
    with pytest.raises(ValueError, match="type 非法.*firmware"):
        load_package_manifest("bad", tmp_path)


def test_name_dir_mismatch(tmp_path: Path):
    _write_package(tmp_path, "foo", """
PACKAGE = {"name": "bar", "components": []}
""")
    with pytest.raises(ValueError, match="name.*不一致"):
        load_package_manifest("foo", tmp_path)


def test_package_name_must_be_kebab_case(tmp_path: Path):
    _write_package(tmp_path, "bad_name", """
PACKAGE = {"name": "bad_name", "components": []}
""")
    with pytest.raises(ValueError, match="kebab-case"):
        load_package_manifest("bad_name", tmp_path)


def test_missing_package(tmp_path: Path):
    with pytest.raises(ValueError, match="不存在"):
        load_package_manifest("nope", tmp_path)


def test_oot_driver_requires_ko_pattern(tmp_path: Path):
    _write_package(tmp_path, "p", """
PACKAGE = {"name": "p", "components": [
    {"type": "oot-driver", "name": "x", "dir": "driver/x"}]}
""")
    with pytest.raises(ValueError, match="ko_pattern"):
        load_package_manifest("p", tmp_path)


def test_vendor_requires_name_and_dir(tmp_path: Path):
    _write_package(tmp_path, "p", """
PACKAGE = {"name": "p", "components": [
    {"type": "vendor", "name": "demo"}]}
""")
    with pytest.raises(ValueError, match="vendor component.*name 与 dir"):
        load_package_manifest("p", tmp_path)


def test_component_variants_requires_nonempty_string_list(tmp_path: Path):
    _write_package(tmp_path, "p", """
PACKAGE = {"name": "p", "components": [
    {"type": "vendor", "name": "demo", "dir": ".", "variants": []}]}
""")
    with pytest.raises(ValueError, match="variants 必须是非空字符串列表"):
        load_package_manifest("p", tmp_path)


def test_load_manifest_dir_accepts_actions_and_ignores_jsonnet(tmp_path: Path):
    pkg_dir = tmp_path / "external-demo"
    pkg_dir.mkdir()
    (pkg_dir / "package.py").write_text(
        "PACKAGE = {\n"
        "    'name': 'external-demo',\n"
        "    'components': [],\n"
        "    'actions': {\n"
        "        'build': ['./build.sh', '--release'],\n"
        "        'log': ['./log.sh', '--follow'],\n"
        "    },\n"
        "}\n",
        encoding="utf-8",
    )
    # ad-hoc 清单加载不得尝试解析或合并同目录的配置。
    (pkg_dir / "config.jsonnet").write_text("这不是合法 Jsonnet", encoding="utf-8")

    manifest = load_package_manifest_dir(pkg_dir)

    assert manifest["actions"] == {
        "build": ["./build.sh", "--release"],
        "log": ["./log.sh", "--follow"],
    }


@pytest.mark.parametrize(
    "actions",
    [
        {"publish": ["./publish.sh"]},
        {"run": "./run.sh"},
        {"run": []},
        {"run": ["./run.sh", 1]},
        {"run": ["./run.sh", ""]},
        None,
    ],
)
def test_package_actions_reject_invalid_argv(tmp_path: Path, actions):
    _write_package(
        tmp_path,
        "invalid-actions",
        "PACKAGE = {"
        "'name': 'invalid-actions', "
        "'components': [], "
        f"'actions': {actions!r}"
        "}\n",
    )

    with pytest.raises(ValueError, match="actions"):
        load_package_manifest("invalid-actions", tmp_path)


def test_package_without_actions_defaults_to_empty_mapping(demo_root: Path):
    manifest = load_package_manifest("demo-panel", demo_root)

    assert manifest["actions"] == {}


class TestResolvePackageDir:
    """Package 名称、路径与调用者 cwd 的解析。"""

    def test_name_resolves_from_project_packages(self, tmp_path: Path):
        _write_package(
            tmp_path,
            "named-package",
            "PACKAGE = {'name': 'named-package', 'components': []}\n",
        )
        caller_cwd = tmp_path / "elsewhere"
        caller_cwd.mkdir()

        resolved = resolve_package_dir(
            "named-package",
            project_root=tmp_path,
            caller_cwd=caller_cwd,
        )

        assert resolved == (
            tmp_path / "components" / "packages" / "named-package"
        ).resolve()

    def test_relative_path_uses_caller_cwd(self, tmp_path: Path):
        project_root = tmp_path / "project"
        caller_cwd = tmp_path / "vendor"
        pkg_dir = caller_cwd / "nested" / "external-package"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.py").write_text(
            "PACKAGE = {'name': 'external-package', 'components': []}\n",
            encoding="utf-8",
        )

        resolved = resolve_package_dir(
            "./nested/external-package",
            project_root=project_root,
            caller_cwd=caller_cwd,
        )

        assert resolved == pkg_dir.resolve()

    def test_omitted_target_uses_caller_cwd(self, tmp_path: Path):
        caller_cwd = tmp_path / "current-package"
        caller_cwd.mkdir()
        (caller_cwd / "package.py").write_text(
            "PACKAGE = {'name': 'current-package', 'components': []}\n",
            encoding="utf-8",
        )

        assert resolve_package_dir(
            None,
            project_root=tmp_path / "project",
            caller_cwd=caller_cwd,
        ) == caller_cwd.resolve()

    def test_existing_relative_directory_takes_precedence(self, tmp_path: Path):
        caller_cwd = tmp_path / "vendor"
        pkg_dir = caller_cwd / "demo"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.py").write_text(
            "PACKAGE = {'name': 'demo', 'components': []}\n",
            encoding="utf-8",
        )

        assert resolve_package_dir(
            "demo",
            project_root=tmp_path / "project",
            caller_cwd=caller_cwd,
        ) == pkg_dir.resolve()

    def test_path_without_manifest_is_rejected(self, tmp_path: Path):
        invalid = tmp_path / "invalid"
        invalid.mkdir()

        with pytest.raises(FileNotFoundError, match="package.py"):
            resolve_package_dir(
                str(invalid),
                project_root=tmp_path / "project",
                caller_cwd=tmp_path,
            )


# ---- opt-in 解析 ----

def test_parse_opt_in_string():
    assert _parse_opt_in("foo") == ("foo", None)


def test_parse_opt_in_dict_with_drivers():
    assert _parse_opt_in({"name": "foo", "drivers": ["a", "b"]}) == (
        "foo", {"a", "b"})


def test_parse_opt_in_dict_without_drivers():
    assert _parse_opt_in({"name": "foo"}) == ("foo", None)


def test_parse_opt_in_missing_name():
    with pytest.raises(ValueError, match="缺少 name"):
        _parse_opt_in({"drivers": ["a"]})


# ---- 展开：oot-driver ----

def test_expand_string_takes_all_drivers(demo_root: Path):
    cfg = {"board": "my-board", "packages": ["demo-panel"]}
    expand_hardware_packages(cfg, project_root=demo_root)
    labels = [m["label"] for m in cfg["kernel"]["oot_modules"]]
    assert any("touch" in l for l in labels)
    assert any("/bl " in l for l in labels)


def test_expand_on_demand_subset(demo_root: Path):
    cfg = {"board": "my-board",
           "packages": [{"name": "demo-panel", "drivers": ["touch"]}]}
    expand_hardware_packages(cfg, project_root=demo_root)
    labels = [m["label"] for m in cfg["kernel"]["oot_modules"]]
    assert any("touch" in l for l in labels)
    assert not any("/bl " in l for l in labels)  # bl 未选中，不编译


def test_expand_oot_make_args_absolute(demo_root: Path):
    cfg = {"board": "my-board",
           "packages": [{"name": "demo-panel", "drivers": ["touch"]}]}
    expand_hardware_packages(cfg, project_root=demo_root)
    mod = cfg["kernel"]["oot_modules"][0]
    assert Path(mod["dir"]).is_absolute()
    assert "ARCH={arch}" in mod["make_args"]
    assert "KSRC={kernel_src_abs}" in mod["make_args"]
    assert any(a.startswith("M=/") for a in mod["make_args"])
    assert mod["ko_pattern"][0].endswith("/touch.ko")


def test_expand_nonexistent_driver_errors(demo_root: Path):
    cfg = {"board": "my-board",
           "packages": [{"name": "demo-panel", "drivers": ["ghost"]}]}
    with pytest.raises(ValueError, match="不存在的 driver.*ghost"):
        expand_hardware_packages(cfg, project_root=demo_root)


# ---- 展开：devicetree ----

def test_expand_devicetree_overlay(demo_root: Path):
    cfg = {"board": "my-board", "packages": ["demo-panel"]}
    expand_hardware_packages(cfg, project_root=demo_root)
    assert "my-board-demo.dtbo" in cfg["boot"]["overlays"]["package"]
    src = cfg["boot"]["package_overlay_sources"]["my-board-demo.dtbo"]
    assert src.endswith("device-tree/my-board-demo.dtso")
    assert Path(src).is_absolute()


def test_canonical_qualcomm_package_overlay_is_build_time(demo_root: Path):
    cfg = ResolvedConfig({
        "board": "my-board",
        "platform": "qualcommqcs6490",
        "packages": ["demo-panel"],
        "kernel": {"device_tree": {"directory": "qcom", "name": "demo"}},
        "boot": {"overlays": {}},
    })

    expand_hardware_packages(cfg, project_root=demo_root)

    assert cfg["boot"]["overlays"]["package"] == ["my-board-demo.dtbo"]
    assert cfg["kernel"]["device_tree"]["build_overlays"] == [
        "my-board-demo.dtbo",
    ]


def test_expand_devicetree_skipped_for_other_board(demo_root: Path):
    cfg = {"board": "other-board", "packages": ["demo-panel"]}
    expand_hardware_packages(cfg, project_root=demo_root)
    # 该包未对 other-board 提供 overlay → package_overlays 不含它
    assert not cfg.get("boot", {}).get("overlays", {}).get("package")


def test_expand_records_cache_meta(demo_root: Path):
    cfg = {"board": "my-board", "packages": ["demo-panel"]}
    expand_hardware_packages(cfg, project_root=demo_root)
    meta = cfg["packages_meta"]
    assert "components/packages/demo-panel/driver/touch" in meta["kernel_src_paths"]
    assert any("my-board-demo.dtso" in p for p in meta["overlay_src_paths"])


def test_no_packages_is_noop(demo_root: Path):
    cfg = {"board": "my-board"}
    out = expand_hardware_packages(cfg, project_root=demo_root)
    assert out is cfg
    assert "kernel" not in cfg or not cfg.get("kernel", {}).get("oot_modules")


def test_expand_vendor_into_custom_deb(tmp_path: Path):
    _write_package(
        tmp_path,
        "demo-firmware",
        _VENDOR_PACKAGE,
        files={"app.yaml": _VENDOR_APP},
    )
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    expand_hardware_packages(cfg, project_root=tmp_path)
    assert cfg["rootfs"]["custom_packages"] == ["demo-firmware"]
    assert cfg["external_apps"]["demo-firmware"] == {
        "local_path": str(
            (tmp_path / "components/packages/demo-firmware").resolve()
        )
    }


def test_expand_vendor_requires_app_yaml(tmp_path: Path):
    _write_package(tmp_path, "demo-firmware", _VENDOR_PACKAGE)
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    with pytest.raises(FileNotFoundError, match="缺少 app.yaml"):
        expand_hardware_packages(cfg, project_root=tmp_path)


def test_expand_vendor_filters_variant(tmp_path: Path):
    _write_package(
        tmp_path,
        "demo-firmware",
        """
PACKAGE = {
    "name": "demo-firmware",
    "components": [
        {"type": "vendor", "name": "runtime", "dir": "runtime"},
        {"type": "vendor", "name": "debug-test", "dir": "test",
         "variants": ["debug"]},
    ],
}
""",
        files={
            "runtime/app.yaml": _VENDOR_APP.replace(
                "demo-firmware", "runtime"),
            "test/app.yaml": _VENDOR_APP.replace(
                "demo-firmware", "debug-test"),
        },
    )

    release = {
        "board": "my-board", "variant": "release",
        "packages": ["demo-firmware"],
    }
    expand_hardware_packages(release, project_root=tmp_path)
    assert release["rootfs"]["custom_packages"] == ["runtime"]

    debug = {
        "board": "my-board", "variant": "debug",
        "packages": ["demo-firmware"],
    }
    expand_hardware_packages(debug, project_root=tmp_path)
    assert debug["rootfs"]["custom_packages"] == [
        "runtime", "debug-test"]


def test_nonexistent_package_errors(demo_root: Path):
    cfg = {"board": "my-board", "packages": ["ghost-pkg"]}
    with pytest.raises(ValueError, match="不存在.*ghost-pkg"):
        expand_hardware_packages(cfg, project_root=demo_root)


# ---- dtb_overlay 四源集成 ----

def test_package_overlays_in_union():
    cfg = {"boot": {"overlays": {
        "intree": ["a.dtbo"], "package": ["p.dtbo"],
    }}}
    assert package_overlays(cfg) == ["p.dtbo"]
    assert all_declared_overlays(cfg) == ["a.dtbo", "p.dtbo"]


def test_package_overlay_collision_fails():
    cfg = {"boot": {"overlays": {
        "board": ["x.dtbo"], "package": ["x.dtbo"],
    }}}
    with pytest.raises(ValueError, match="overlays.package.*重名"):
        all_declared_overlays(cfg)


def test_runtime_overlays_accepts_package_source():
    cfg = {"boot": {"overlays": {
        "package": ["p.dtbo"], "enabled": ["p.dtbo"],
    }}}
    assert runtime_overlays(cfg) == ["p.dtbo"]


def test_runtime_overlays_missing_lists_package_candidates():
    cfg = {"boot": {"overlays": {
        "package": ["p.dtbo"], "enabled": ["missing.dtbo"],
    }}}
    with pytest.raises(ValueError, match="package="):
        runtime_overlays(cfg)


# ---- vendor component 的额外哈希输入（inputs） ----

_VENDOR_WITH_INPUTS = """
PACKAGE = {
    "name": "demo-firmware",
    "components": [
        {"type": "vendor", "name": "demo-firmware", "dir": "build",
         "inputs": ["patches"]},
    ],
}
"""


def test_vendor_inputs_登记为app附加哈希输入(tmp_path: Path):
    """位于 App 目录之外、却参与构建的包内容必须显式登记进缓存输入。"""
    _write_package(
        tmp_path,
        "demo-firmware",
        _VENDOR_WITH_INPUTS,
        files={
            "build/app.yaml": _VENDOR_APP,
            "patches/0001-fix.patch": "--- a\n+++ b\n",
        },
    )
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    expand_hardware_packages(cfg, project_root=tmp_path)

    assert cfg["packages_meta"]["app_src_paths"] == {
        "demo-firmware": ["components/packages/demo-firmware/patches"],
    }


def test_vendor_inputs_缺省时不登记(tmp_path: Path):
    _write_package(
        tmp_path, "demo-firmware", _VENDOR_PACKAGE,
        files={"app.yaml": _VENDOR_APP},
    )
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    expand_hardware_packages(cfg, project_root=tmp_path)

    assert cfg["packages_meta"]["app_src_paths"] == {}


def test_vendor_inputs_路径不存在时报错(tmp_path: Path):
    _write_package(
        tmp_path, "demo-firmware", _VENDOR_WITH_INPUTS,
        files={"build/app.yaml": _VENDOR_APP},
    )
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    with pytest.raises(FileNotFoundError, match="inputs 不存在"):
        expand_hardware_packages(cfg, project_root=tmp_path)


def test_vendor_inputs_必须是字符串列表(tmp_path: Path):
    _write_package(tmp_path, "demo-firmware", """
PACKAGE = {"name": "demo-firmware", "components": [
    {"type": "vendor", "name": "demo-firmware", "dir": "build",
     "inputs": "patches"}]}
""", files={"build/app.yaml": _VENDOR_APP})
    cfg = {"board": "my-board", "packages": ["demo-firmware"]}
    with pytest.raises(ValueError, match="inputs 必须是非空字符串列表"):
        expand_hardware_packages(cfg, project_root=tmp_path)
