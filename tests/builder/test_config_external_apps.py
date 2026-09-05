"""builder.config.apps.normalize_app_sources 单元测试。

覆盖六类场景：
  1. 合法 local_path
  2. 合法 git
  3. local_path 与 git 同时存在 → 报错
  4. 两者都缺失 → 报错
  5. ``~`` 展开
  6. 相对路径相对 project_root 解析
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from builder.config.apps import AppSourceConfigError, normalize_app_sources


def _base_config() -> dict:
    return {
        "board": "test-board",
        "product": "default",
        "variant": "release",
    }


class TestNormalizeAppSources:
    def test_external_app_dirs_缺失时补空列表(self, tmp_path):
        """配置未声明 external_app_dirs 时，归一化后仍出现空列表字段。"""
        config = _base_config()
        result = normalize_app_sources(config, project_root=tmp_path)
        assert result["external_app_dirs"] == []

    def test_合法_local_path_解析为绝对路径(self, tmp_path):
        """local_path 为相对路径时，解析结果是相对 project_root 的绝对路径。"""
        app_root = tmp_path / "vendor" / "foo"
        app_root.mkdir(parents=True)
        config = _base_config()
        config["external_apps"] = {
            "foo": {"local_path": "vendor/foo"},
        }
        result = normalize_app_sources(config, project_root=tmp_path)
        entry = result["external_apps"]["foo"]
        assert entry["local_path"] == str(app_root.resolve())
        # 原字段以外不应被注入 git 字段
        assert "git" not in entry

    def test_合法_git_字段透传(self, tmp_path):
        """git 条目的各字段保持不变透传下去。"""
        config = _base_config()
        config["external_apps"] = {
            "zigbee": {
                "git": "ssh://git@example.com/zigbee.git",
                "tag": "v1.2.3",
                "branch": "main",
            },
        }
        result = normalize_app_sources(config, project_root=tmp_path)
        entry = result["external_apps"]["zigbee"]
        assert entry["git"] == "ssh://git@example.com/zigbee.git"
        assert entry["tag"] == "v1.2.3"
        assert entry["branch"] == "main"
        assert "local_path" not in entry

    def test_local_path_与_git_互斥(self, tmp_path):
        """两个字段同时出现必须报错。"""
        config = _base_config()
        config["external_apps"] = {
            "x": {"local_path": "/opt/x", "git": "ssh://git@example.com/x.git"},
        }
        with pytest.raises(AppSourceConfigError, match="不允许同时声明"):
            normalize_app_sources(config, project_root=tmp_path)

    def test_local_path_与_git_都缺失时报错(self, tmp_path):
        """条目为空字典也必须报错，错误信息包含键名。"""
        config = _base_config()
        config["external_apps"] = {
            "x": {},
        }
        with pytest.raises(AppSourceConfigError, match="'x'"):
            normalize_app_sources(config, project_root=tmp_path)

    def test_local_path_支持_tilde_展开(self, tmp_path, monkeypatch):
        """local_path 中的 ``~`` 应被展开到 HOME。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        config = _base_config()
        config["external_apps"] = {
            "foo": {"local_path": "~/workspace/foo"},
        }
        result = normalize_app_sources(config, project_root=tmp_path)
        expected = str((tmp_path / "workspace" / "foo").resolve())
        assert result["external_apps"]["foo"]["local_path"] == expected

    def test_external_app_dirs_相对路径相对_project_root(self, tmp_path):
        """external_app_dirs 中的相对路径锚点是 project_root。"""
        (tmp_path / "vendor-apps").mkdir()
        config = _base_config()
        config["external_app_dirs"] = ["vendor-apps"]
        result = normalize_app_sources(config, project_root=tmp_path)
        expected = str((tmp_path / "vendor-apps").resolve())
        assert result["external_app_dirs"] == [expected]

    def test_external_app_dirs_tilde_展开(self, tmp_path, monkeypatch):
        """external_app_dirs 各项也支持 ``~`` 展开。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        config = _base_config()
        config["external_app_dirs"] = ["~/apps-a", "~/apps-b"]
        result = normalize_app_sources(config, project_root=tmp_path)
        assert result["external_app_dirs"] == [
            str((tmp_path / "apps-a").resolve()),
            str((tmp_path / "apps-b").resolve()),
        ]

    def test_external_apps_非字典时报错(self, tmp_path):
        """external_apps 顶层类型错误的明确报错。"""
        config = _base_config()
        config["external_apps"] = ["not a dict"]
        with pytest.raises(AppSourceConfigError, match="必须是键值映射"):
            normalize_app_sources(config, project_root=tmp_path)

    def test_external_app_dirs_非列表时报错(self, tmp_path):
        """external_app_dirs 顶层类型错误的明确报错。"""
        config = _base_config()
        config["external_app_dirs"] = "not a list"
        with pytest.raises(AppSourceConfigError, match="必须是列表"):
            normalize_app_sources(config, project_root=tmp_path)

    def test_local_path_为空字符串时报错(self, tmp_path):
        """local_path 为空字符串必须拒绝，不能静默当成 project_root。"""
        config = _base_config()
        config["external_apps"] = {"x": {"local_path": "   "}}
        with pytest.raises(AppSourceConfigError, match="local_path"):
            normalize_app_sources(config, project_root=tmp_path)

    def test_输入不被就地修改(self, tmp_path):
        """归一化必须返回新 dict，不能污染调用方的 config。"""
        config = _base_config()
        config["external_app_dirs"] = ["relative"]
        config["external_apps"] = {"x": {"local_path": "vendor/x"}}
        before = repr(config)
        normalize_app_sources(config, project_root=tmp_path)
        assert repr(config) == before
