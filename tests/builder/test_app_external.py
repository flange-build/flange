"""工具仓库来源解析、共享 Git 身份与独立工作区覆盖规则。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.source import SourceManager
from builder.app import AppBuilder


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def _repo_path(root, entry):
    descriptor = {**entry, "url": entry["git"]}
    return root / "sources/repos" / SourceManager.source_identity(descriptor)


def _make_config(
    external_apps: dict | None = None,
    external_app_dirs: list[str] | None = None,
) -> dict:
    """构造最小 FINAL_CONFIG。"""
    config: dict = {
        "board":   "test-board",
        "product": "default",
        "variant": "release",
        "architecture": {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64"},
        "rootfs":  {"custom_packages": []},
        "external_app_dirs": external_app_dirs or [],
    }
    if external_apps is not None:
        config["external_apps"] = external_apps
    return config


def _write_app_yaml(app_dir: Path, name: str) -> None:
    """在 app_dir 写入最小合法 app.yaml。"""
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "app.yaml").write_text(
        f"app:\n"
        f"  name: {name}\n"
        f"  version: 1.0.0\n"
        f"  description: {name} 测试\n"
        f"  type: exec\n"
        f"  arch:\n"
        f"    - aarch64\n"
        f"\n"
        f"maintainer:\n"
        f"  name: tester\n"
        f"  email: tester@localhost\n"
        f"\n"
        f"build:\n"
        f"  system: none\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 第一组：SourceManager.ensure_app 基础分支
# ---------------------------------------------------------------------------

class TestSourceManagerEnsureAppBasics:

    def test_本地components_app_命中时直接返回(self, tmp_path):
        """<project_root>/components/app/<name>/app.yaml 存在时命中返回。"""
        local_app = tmp_path / "components" / "app" / "myapp"
        _write_app_yaml(local_app, "myapp")
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)

        with patch.object(sm, "_clone") as mock_clone:
            result = sm.ensure_app("myapp", _make_config())

        assert result == local_app
        mock_clone.assert_not_called()

    def test_本地目录存在但缺少_app_yaml_时不命中(self, tmp_path):
        """空的 components/app/<name>/ 不被识别为 App，继续向下查找。"""
        (tmp_path / "components" / "app" / "stub").mkdir(parents=True)
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)

        with pytest.raises(ValueError, match="stub"):
            sm.ensure_app("stub", _make_config())

    def test_外部_git_带_tag_时触发克隆(self, tmp_path):
        ext = {
            "zigbee-daemon": {
                "git": "ssh://git@example.com/zigbee.git",
                "tag": "v2.1.0",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        expected = _repo_path(tmp_path, ext["zigbee-daemon"])

        with patch.object(sm, "_clone") as mock_clone:
            result = sm.ensure_app("zigbee-daemon", _make_config(external_apps=ext))

        mock_clone.assert_called_once_with(
            repo="ssh://git@example.com/zigbee.git",
            branch="",
            dest=expected,
            commit="v2.1.0",
            recurse=False,
            is_tag=True,
        )
        assert result == expected

    def test_外部_git_带_branch_时触发克隆(self, tmp_path):
        ext = {
            "ota-agent": {
                "git": "ssh://git@example.com/ota.git",
                "branch": "release/3.0",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        expected = _repo_path(tmp_path, ext["ota-agent"])

        with patch.object(sm, "_clone") as mock_clone:
            result = sm.ensure_app("ota-agent", _make_config(external_apps=ext))

        mock_clone.assert_called_once_with(
            repo="ssh://git@example.com/ota.git",
            branch="release/3.0",
            dest=expected,
            commit="",
            recurse=False,
            is_tag=False,
        )
        assert result == expected

    def test_外部_git_已克隆时同步branch(self, tmp_path):
        ext = {
            "ota-agent": {
                "git": "ssh://git@example.com/ota.git",
                "branch": "release/3.0",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        already_cloned = _repo_path(tmp_path, ext["ota-agent"])
        already_cloned.mkdir(parents=True)

        with patch.object(sm, "_clone") as mock_clone, \
                patch.object(sm, "_fetch_reset_branch") as fetch:
            result = sm.ensure_app("ota-agent", _make_config(external_apps=ext))

        mock_clone.assert_not_called()
        fetch.assert_called_once_with(already_cloned, "release/3.0")
        assert result == already_cloned

    def test_外部_git_tag_和_branch_并存时_tag_优先(self, tmp_path):
        ext = {
            "myapp": {
                "git": "ssh://git@example.com/myapp.git",
                "tag": "v1.0.0",
                "branch": "main",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)

        with patch.object(sm, "_clone") as mock_clone:
            sm.ensure_app("myapp", _make_config(external_apps=ext))

        mock_clone.assert_called_once_with(
            repo="ssh://git@example.com/myapp.git",
            branch="main",
            dest=_repo_path(tmp_path, ext["myapp"]),
            commit="v1.0.0",
            recurse=False,
            is_tag=True,
        )

    def test_外部_git_commit_字段(self, tmp_path):
        ext = {
            "myapp": {
                "git": "ssh://git@example.com/myapp.git",
                "commit": "abc1234",
                "branch": "main",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)

        with patch.object(sm, "_clone") as mock_clone:
            sm.ensure_app("myapp", _make_config(external_apps=ext))

        mock_clone.assert_called_once_with(
            repo="ssh://git@example.com/myapp.git",
            branch="main",
            dest=_repo_path(tmp_path, ext["myapp"]),
            commit="abc1234",
            recurse=False,
            is_tag=False,
        )

    def test_app_未找到时错误信息列出所有层级(self, tmp_path):
        """三层均未命中时，错误信息应包含每层已尝试路径。"""
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        config = _make_config(
            external_apps={"other": {"git": "ssh://x.git"}},
            external_app_dirs=[str(tmp_path / "nowhere-a"), str(tmp_path / "nowhere-b")],
        )

        with pytest.raises(ValueError) as exc_info:
            sm.ensure_app("missing", config)

        msg = str(exc_info.value)
        assert "missing" in msg
        # 层 1：本地路径
        assert "components/app/missing" in msg
        # 层 2：external_apps 未声明此 name
        assert "external_apps['missing']" in msg or "'missing'" in msg
        # 层 3：external_app_dirs 下的两个候选都应被列出
        assert "nowhere-a" in msg
        assert "nowhere-b" in msg


# ---------------------------------------------------------------------------
# 第二组：out-of-tree 新分支
# ---------------------------------------------------------------------------

class TestOutOfTreeApps:

    def test_external_apps_local_path_命中(self, tmp_path):
        """external_apps[<name>].local_path 指向真实目录时直接返回，不触发克隆。"""
        out_of_tree = tmp_path / "vendor" / "wifi"
        _write_app_yaml(out_of_tree, "wifi")
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        config = _make_config(
            external_apps={"wifi": {"local_path": str(out_of_tree)}},
        )

        with patch.object(sm, "_clone") as mock_clone:
            result = sm.ensure_app("wifi", config)

        assert result == out_of_tree
        mock_clone.assert_not_called()

    def test_external_apps_local_path_路径不存在_不回退到搜索路径(self, tmp_path):
        """local_path 无效时严格报错，不能悄悄去 external_app_dirs 找同名。"""
        fallback = tmp_path / "fallback" / "wifi"
        _write_app_yaml(fallback, "wifi")
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        config = _make_config(
            external_apps={"wifi": {"local_path": str(tmp_path / "missing" / "wifi")}},
            external_app_dirs=[str(tmp_path / "fallback")],
        )

        with pytest.raises(ValueError, match="local_path"):
            sm.ensure_app("wifi", config)

    def test_external_app_dirs_顺序命中_首个为主(self, tmp_path):
        """多个搜索目录含同名 App 时，列表中靠前者胜出。"""
        first = tmp_path / "team-apps" / "wifi"
        second = tmp_path / "personal-apps" / "wifi"
        _write_app_yaml(first, "wifi")
        _write_app_yaml(second, "wifi")
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        config = _make_config(
            external_app_dirs=[
                str(tmp_path / "team-apps"),
                str(tmp_path / "personal-apps"),
            ],
        )

        result = sm.ensure_app("wifi", config)
        assert result == first

    def test_三层全部未命中_包含全部已尝试路径(self, tmp_path):
        """完整的未命中场景：local 未建、external_apps 无此键、搜索目录不存在。"""
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        config = _make_config(
            external_app_dirs=[str(tmp_path / "vendor-a"), str(tmp_path / "vendor-b")],
        )

        with pytest.raises(ValueError) as exc_info:
            sm.ensure_app("qux", config)

        msg = str(exc_info.value)
        assert "qux" in msg
        assert "components/app/qux" in msg
        assert "vendor-a" in msg
        assert "vendor-b" in msg


# ---------------------------------------------------------------------------
# 第三组：工作区来源优先级与歧义拒绝。

from tests.builder.app_support import app, builder
from dataclasses import replace
from builder.app_resolver import AppResolver


def test_workspace_registration_overrides_search_roots(tmp_path):
    explicit = app(tmp_path / "registered/hello")
    directory = app(tmp_path / "apps/hello")
    engine = builder(tmp_path, apps={"hello": explicit}, app_dirs=[directory.parent])
    assert engine.resolver.resolve("hello") == explicit


def test_duplicate_search_roots_need_explicit_registration(tmp_path):
    first, second = app(tmp_path / "first/hello"), app(tmp_path / "second/hello")
    engine = builder(tmp_path, app_dirs=[first.parent, second.parent])
    with pytest.raises(ValueError, match="多个工作区来源"):
        engine.resolver.resolve("hello")


def test_explicit_path_and_relative_dependency_keep_caller_context(tmp_path):
    library = app(tmp_path / "external/library")
    main = app(tmp_path / "external/main", deps=["../library"])
    engine = builder(tmp_path)
    roots, ordered = engine.resolver.closure([main])
    assert [item.source_dir for item in ordered] == [library, main]
    assert roots == (ordered[-1].resource_id,)


def test_same_name_different_sources_in_one_closure_are_rejected(tmp_path):
    first, second = app(tmp_path / "first/demo"), app(tmp_path / "second/demo")
    engine = builder(tmp_path)
    with pytest.raises(ValueError, match="同名不同源"):
        engine.resolver.closure([first, second])
