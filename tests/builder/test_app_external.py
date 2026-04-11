"""仓库外 App 支持测试（Task 7）。

覆盖场景：
- SourceManager.ensure_app()：仓库内 App 查找（本地 app/ 目录存在）
- SourceManager.ensure_app()：外部 App 带 tag → 克隆到 sources/apps/<name>
- SourceManager.ensure_app()：外部 App 带 branch → 克隆
- SourceManager.ensure_app()：外部 App 已克隆 → 跳过克隆
- SourceManager.ensure_app()：App 未在任何地方找到 → 抛出 ValueError
- AppBuilder._find_app_dir()：本地 App 直接返回（不调用 SourceManager）
- AppBuilder._find_app_dir()：本地不存在时委托 SourceManager.ensure_app()
- AppBuilder._find_app_dir()：SourceManager 报告 App 未找到 → 传播 ValueError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from builder.source import SourceManager
from builder.app import AppBuilder


# ---------------------------------------------------------------------------
# 测试辅助：构建最小配置字典
# ---------------------------------------------------------------------------

def _make_config(external_apps: dict | None = None) -> dict:
    """构造包含 external_apps 的最小 FINAL_CONFIG 字典。"""
    config: dict = {
        "board":   "test-board",
        "product": "default",
        "variant": "release",
        "arch":    "aarch64",
        "rootfs":  {"custom_packages": []},
    }
    if external_apps:
        config["external_apps"] = external_apps
    return config


def _make_app_yaml(app_dir: Path, name: str) -> None:
    """在指定目录创建最小 app.yaml，便于 AppBuilder 加载规格。"""
    app_dir.mkdir(parents=True, exist_ok=True)
    yaml = (
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
        f"  system: none\n"
    )
    (app_dir / "app.yaml").write_text(yaml, encoding="utf-8")


# ---------------------------------------------------------------------------
# SourceManager.ensure_app 直接测试
# ---------------------------------------------------------------------------

class TestSourceManagerEnsureApp:
    """直接测试 SourceManager.ensure_app 各分支路径。"""

    def test_本地app目录存在时直接返回(self, tmp_path):
        """本地 app/<name>/ 目录存在时，应直接返回该路径，不触发克隆。"""
        # 在当前工作目录下创建 app/myapp/，ensure_app 使用相对路径查找
        local_app = tmp_path / "app" / "myapp"
        local_app.mkdir(parents=True)

        sm = SourceManager(sources_dir=tmp_path / "sources")

        with patch.object(sm, "_clone") as mock_clone:
            # 切换到 tmp_path 作为工作目录，使相对路径 "app/myapp" 可解析
            with patch("pathlib.Path.exists", side_effect=lambda s=None: _path_exists_local(s, local_app)):
                pass  # 不使用此 patch，改用 monkeypatch cwd

        # 使用真实文件系统（local_app 已创建），直接以 tmp_path 为 cwd
        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                result = sm.ensure_app("myapp", _make_config())
        finally:
            os.chdir(orig_cwd)

        assert result == Path("app/myapp")
        mock_clone.assert_not_called()

    def test_外部app带tag时触发克隆(self, tmp_path):
        """external_apps 中声明了 tag 的 App，应以 tag 作为 commit 参数克隆。"""
        ext_config = {
            "zigbee-daemon": {
                "git": "ssh://git@gitlab.example.com/apps/zigbee.git",
                "tag": "v2.1.0",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")
        expected_dest = tmp_path / "sources" / "apps" / "zigbee-daemon"

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)  # 确保本地 app/zigbee-daemon 不存在
            with patch.object(sm, "_clone") as mock_clone:
                result = sm.ensure_app("zigbee-daemon", config)
        finally:
            os.chdir(orig_cwd)

        mock_clone.assert_called_once_with(
            repo="ssh://git@gitlab.example.com/apps/zigbee.git",
            branch="",
            dest=expected_dest,
            commit="v2.1.0",
        )
        assert result == expected_dest

    def test_外部app带branch时触发克隆(self, tmp_path):
        """external_apps 中声明了 branch 的 App，应以 branch 参数克隆。"""
        ext_config = {
            "ota-agent": {
                "git": "ssh://git@gitlab.example.com/apps/ota.git",
                "branch": "release/3.0",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")
        expected_dest = tmp_path / "sources" / "apps" / "ota-agent"

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                result = sm.ensure_app("ota-agent", config)
        finally:
            os.chdir(orig_cwd)

        mock_clone.assert_called_once_with(
            repo="ssh://git@gitlab.example.com/apps/ota.git",
            branch="release/3.0",
            dest=expected_dest,
            commit="",
        )
        assert result == expected_dest

    def test_外部app已克隆则跳过克隆(self, tmp_path):
        """sources/apps/<name>/ 目录已存在时，应跳过克隆直接返回路径。"""
        ext_config = {
            "ota-agent": {
                "git": "ssh://git@gitlab.example.com/apps/ota.git",
                "branch": "release/3.0",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")

        # 提前创建目录，模拟已克隆
        already_cloned = tmp_path / "sources" / "apps" / "ota-agent"
        already_cloned.mkdir(parents=True)

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                result = sm.ensure_app("ota-agent", config)
        finally:
            os.chdir(orig_cwd)

        mock_clone.assert_not_called()
        assert result == already_cloned

    def test_app未找到时抛出ValueError(self, tmp_path):
        """本地不存在且未在 external_apps 声明的 App，应抛出 ValueError 且包含 App 名称。"""
        config = _make_config()  # 无 external_apps
        sm = SourceManager(sources_dir=tmp_path / "sources")

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(ValueError, match="missing-app"):
                sm.ensure_app("missing-app", config)
        finally:
            os.chdir(orig_cwd)

    def test_external_apps为空字典时抛出ValueError(self, tmp_path):
        """external_apps 存在但不包含目标 App 时，应抛出 ValueError。"""
        config = _make_config(external_apps={"other-app": {"git": "ssh://x.git"}})
        sm = SourceManager(sources_dir=tmp_path / "sources")

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(ValueError, match="not-declared"):
                sm.ensure_app("not-declared", config)
        finally:
            os.chdir(orig_cwd)

    def test_外部app带tag和branch时tag优先作为commit(self, tmp_path):
        """同时设置 tag 和 branch 时，tag 应优先作为 commit 参数。"""
        ext_config = {
            "myapp": {
                "git": "ssh://git@gitlab.example.com/apps/myapp.git",
                "tag": "v1.0.0",
                "branch": "main",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")
        expected_dest = tmp_path / "sources" / "apps" / "myapp"

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                sm.ensure_app("myapp", config)
        finally:
            os.chdir(orig_cwd)

        # tag 优先于 commit，branch 也应传递
        mock_clone.assert_called_once_with(
            repo="ssh://git@gitlab.example.com/apps/myapp.git",
            branch="main",
            dest=expected_dest,
            commit="v1.0.0",
        )

    def test_外部app带commit字段(self, tmp_path):
        """external_apps 中声明 commit（无 tag）时，commit 作为 checkout 哈希。"""
        ext_config = {
            "myapp": {
                "git": "ssh://git@gitlab.example.com/apps/myapp.git",
                "commit": "abc1234",
                "branch": "main",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")
        expected_dest = tmp_path / "sources" / "apps" / "myapp"

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                sm.ensure_app("myapp", config)
        finally:
            os.chdir(orig_cwd)

        mock_clone.assert_called_once_with(
            repo="ssh://git@gitlab.example.com/apps/myapp.git",
            branch="main",
            dest=expected_dest,
            commit="abc1234",
        )


# ---------------------------------------------------------------------------
# AppBuilder._find_app_dir 集成测试（含外部仓库路径）
# ---------------------------------------------------------------------------

class TestAppBuilderFindAppDirExternal:
    """测试 AppBuilder._find_app_dir 与 SourceManager 的集成。"""

    def _make_builder_with_source(
        self,
        tmp_path: Path,
        source: SourceManager | MagicMock | None = None,
        external_apps: dict | None = None,
    ) -> AppBuilder:
        """构造 AppBuilder，source 可传入真实或 mock 的 SourceManager。"""
        config = _make_config(external_apps=external_apps)
        docker = MagicMock()
        if source is None:
            source = MagicMock()
        return AppBuilder(docker, source, config, project_dir=tmp_path)

    def test_本地app存在时不调用SourceManager(self, tmp_path):
        """本地 app/<name>/ 存在时，_find_app_dir 应直接返回，不调用 SourceManager。"""
        app_dir = tmp_path / "app" / "localapp"
        _make_app_yaml(app_dir, "localapp")

        mock_source = MagicMock()
        builder = self._make_builder_with_source(tmp_path, source=mock_source)

        result = builder._find_app_dir("localapp")

        assert result == app_dir
        mock_source.ensure_app.assert_not_called()

    def test_本地不存在时委托SourceManager(self, tmp_path):
        """本地 app/<name>/ 不存在时，应调用 SourceManager.ensure_app()。"""
        expected_path = tmp_path / "sources" / "apps" / "ext-app"
        expected_path.mkdir(parents=True)

        mock_source = MagicMock()
        mock_source.ensure_app.return_value = expected_path

        builder = self._make_builder_with_source(tmp_path, source=mock_source)
        result = builder._find_app_dir("ext-app")

        assert result == expected_path
        mock_source.ensure_app.assert_called_once_with("ext-app", builder._config)

    def test_SourceManager报错时传播ValueError(self, tmp_path):
        """SourceManager.ensure_app() 抛出 ValueError 时，_find_app_dir 应向上传播。"""
        mock_source = MagicMock()
        mock_source.ensure_app.side_effect = ValueError("ext-app 未找到")

        builder = self._make_builder_with_source(tmp_path, source=mock_source)

        with pytest.raises(ValueError, match="ext-app"):
            builder._find_app_dir("ext-app")

    def test_source为None时抛出FileNotFoundError(self, tmp_path):
        """source=None 时，本地不存在应抛出 FileNotFoundError（兜底保护）。"""
        config = _make_config()
        docker = MagicMock()
        # 显式传入 source=None，不经过 _make_builder_with_source 的 mock 替换逻辑
        builder = AppBuilder(docker, None, config, project_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match="no-such-app"):
            builder._find_app_dir("no-such-app")

    def test_外部app完整流程端到端(self, tmp_path):
        """使用真实 SourceManager（mock _clone），验证外部 App 端到端路径。"""
        ext_config = {
            "remote-agent": {
                "git": "ssh://git@gitlab.example.com/apps/remote-agent.git",
                "tag": "v3.0.0",
            }
        }
        config = _make_config(external_apps=ext_config)
        sm = SourceManager(sources_dir=tmp_path / "sources")
        docker = MagicMock()
        builder = AppBuilder(docker, sm, config, project_dir=tmp_path)

        expected_dest = tmp_path / "sources" / "apps" / "remote-agent"

        import os
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch.object(sm, "_clone") as mock_clone:
                # _clone 被调用时创建目标目录，模拟克隆成功
                def fake_clone(repo, branch, dest, commit=""):
                    dest.mkdir(parents=True, exist_ok=True)
                mock_clone.side_effect = fake_clone

                result = builder._find_app_dir("remote-agent")
        finally:
            os.chdir(orig_cwd)

        assert result == expected_dest
        mock_clone.assert_called_once_with(
            repo="ssh://git@gitlab.example.com/apps/remote-agent.git",
            branch="",
            dest=expected_dest,
            commit="v3.0.0",
        )
