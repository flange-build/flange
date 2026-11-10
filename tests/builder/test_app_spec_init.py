"""AppSpec 的 init 系统服务段与包格式声明。"""

from pathlib import Path

import pytest

from builder.app_spec import AppSpecError, load_spec

_HEADER = """\
app:
  name: demo
  version: 1.0.0
  description: 测试服务
  type: service
  arch: [armhf]
maintainer:
  name: flange
  email: flange@localhost
"""


def _spec(tmp_path: Path, body: str):
    (tmp_path / "app.yaml").write_text(_HEADER + body, encoding="utf-8")
    return load_spec(tmp_path)


def test_openrc_only_service_is_valid(tmp_path):
    spec = _spec(tmp_path, "openrc:\n  script: openrc/demo\n  auto_start: true\n")

    assert spec.systemd is None
    assert spec.openrc.script == "openrc/demo"
    assert spec.openrc.auto_start is True
    assert spec.openrc.runlevel == "default"


def test_service_may_declare_both_init_systems(tmp_path):
    spec = _spec(
        tmp_path,
        "systemd:\n  unit: systemd/demo.service\nopenrc:\n  script: openrc/demo\n",
    )

    assert spec.systemd.unit == "systemd/demo.service"
    assert spec.openrc.script == "openrc/demo"


def test_service_without_any_init_file_is_rejected(tmp_path):
    with pytest.raises(AppSpecError, match="systemd.unit 或 openrc.script"):
        _spec(tmp_path, "")


def test_openrc_requires_service_type(tmp_path):
    (tmp_path / "app.yaml").write_text(
        _HEADER.replace("type: service", "type: exec") + "openrc:\n  script: openrc/demo\n",
        encoding="utf-8",
    )
    with pytest.raises(AppSpecError, match="openrc 仅允许 app.type=service"):
        load_spec(tmp_path)


def test_openrc_runlevel_is_validated(tmp_path):
    with pytest.raises(AppSpecError, match="runlevel"):
        _spec(tmp_path, "openrc:\n  script: openrc/demo\n  runlevel: ../x\n")


def test_packaging_format_declaration_is_tracked(tmp_path):
    implicit = _spec(tmp_path, "systemd:\n  unit: systemd/demo.service\n")
    assert implicit.packaging.format == "deb"
    assert implicit.packaging.format_declared is False

    explicit = _spec(
        tmp_path, "systemd:\n  unit: systemd/demo.service\npackaging:\n  format: deb\n"
    )
    assert explicit.packaging.format_declared is True


def test_format_specific_depends(tmp_path):
    spec = _spec(
        tmp_path,
        "openrc:\n  script: openrc/demo\n"
        "depends: [libc6]\n"
        "packaging:\n  depends:\n    apk: [musl, python3]\n",
    )

    assert spec.depends == ["libc6"]
    assert spec.packaging.depends == {"apk": ["musl", "python3"]}
