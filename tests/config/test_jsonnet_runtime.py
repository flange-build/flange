"""Jsonnet 运行时基线测试。"""

import json

import _jsonnet
import pytest


def test_jsonnet_binding_needs_no_cli_and_preserves_error_location(monkeypatch):
    monkeypatch.setenv("PATH", "")

    result = json.loads(_jsonnet.evaluate_snippet(
        "smoke.jsonnet",
        '{ ok: true, value: std.extVar("value") }',
        ext_vars={"value": "works"},
    ))
    assert result == {"ok": True, "value": "works"}

    with pytest.raises(RuntimeError, match=r"broken\.jsonnet:1"):
        _jsonnet.evaluate_snippet("broken.jsonnet", "{ broken: }")
