"""仓库外 App 支持测试。

覆盖 SourceManager.ensure_app() 三层查找与 AppBuilder._find_app_dir 集成：

第一组 — 基础分支：
  - 本地 components/app/<name>/app.yaml 命中
  - external_apps.git：带 tag / branch / commit
  - external_apps.git：已克隆则跳过
  - external_apps 未声明 → 抛 ValueError
  - 未找到时错误信息枚举所有层级

第二组 — out-of-tree 新分支（本变更新增）：
  - external_apps.local_path 命中
  - external_apps.local_path 路径不存在 → 抛 ValueError（不回退到搜索路径）
  - external_app_dirs 顺序命中（首个命中即终止）
  - 三层全部未命中

第三组 — AppBuilder._find_app_dir 集成：
  - 委托 SourceManager.ensure_app()（不再做两段式本地/外部切换）
  - SourceManager 抛 ValueError 时向上传播
  - source=None 兜底分支
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.source import SourceManager
from builder.app import AppBuilder


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

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
        expected = tmp_path / "sources" / "apps" / "zigbee-daemon"

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
        expected = tmp_path / "sources" / "apps" / "ota-agent"

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
        already_cloned = tmp_path / "sources" / "apps" / "ota-agent"
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
            dest=tmp_path / "sources" / "apps" / "myapp",
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
            dest=tmp_path / "sources" / "apps" / "myapp",
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
# 第三组：AppBuilder._find_app_dir 集成
# ---------------------------------------------------------------------------

class TestAppBuilderFindAppDir:

    def _make_builder(self, tmp_path: Path, source=None, **config_kwargs) -> AppBuilder:
        config = _make_config(**config_kwargs)
        docker = MagicMock()
        return AppBuilder(docker, source, config, project_dir=tmp_path)

    def test_委托给_SourceManager_ensure_app(self, tmp_path):
        """新版 _find_app_dir 总是调用 source.ensure_app，无本地兜底逻辑。"""
        expected_path = tmp_path / "somewhere" / "ext-app"
        expected_path.mkdir(parents=True)
        mock_source = MagicMock()
        mock_source.ensure_app.return_value = expected_path

        builder = self._make_builder(tmp_path, source=mock_source)
        result = builder._find_app_dir("ext-app")

        assert result == expected_path
        mock_source.ensure_app.assert_called_once_with("ext-app", builder._config)

    def test_SourceManager_抛出_ValueError_时传播(self, tmp_path):
        mock_source = MagicMock()
        mock_source.ensure_app.side_effect = ValueError("ext-app 未找到")
        builder = self._make_builder(tmp_path, source=mock_source)

        with pytest.raises(ValueError, match="ext-app"):
            builder._find_app_dir("ext-app")

    def test_source_为_None_时退化为仅查本地(self, tmp_path):
        """source=None 时，仅支持本地 components/app/ 查找作为兜底。"""
        # 本地存在
        local_app = tmp_path / "components" / "app" / "foo"
        _write_app_yaml(local_app, "foo")
        builder = self._make_builder(tmp_path, source=None)
        assert builder._find_app_dir("foo") == local_app

        # 本地不存在
        with pytest.raises(FileNotFoundError, match="bar"):
            builder._find_app_dir("bar")

    def test_真实_SourceManager_端到端_git_流程(self, tmp_path):
        """使用真实 SourceManager（mock _clone），验证 AppBuilder → ensure_app → git 流程。"""
        ext = {
            "remote-agent": {
                "git": "ssh://git@example.com/remote-agent.git",
                "tag": "v3.0.0",
            }
        }
        sm = SourceManager(sources_dir=tmp_path / "sources", project_root=tmp_path)
        builder = self._make_builder(tmp_path, source=sm, external_apps=ext)
        expected_dest = tmp_path / "sources" / "apps" / "remote-agent"

        with patch.object(sm, "_clone") as mock_clone:
            def fake_clone(repo, branch, dest, commit="", **_kwargs):
                dest.mkdir(parents=True, exist_ok=True)
            mock_clone.side_effect = fake_clone

            result = builder._find_app_dir("remote-agent")

        assert result == expected_dest
        mock_clone.assert_called_once_with(
            repo="ssh://git@example.com/remote-agent.git",
            branch="",
            dest=expected_dest,
            commit="v3.0.0",
            recurse=False,
            is_tag=True,
        )
