"""deploy_app 入口路径解析测试。

不触发 docker / adb，验证：
- `_resolve_app_arg` 三种判定规则
- `deploy_app("<path>", build_deb=False, run=False)` 能解析路径并按 spec.app.name 查 .deb
- `deploy_app("<name>", ...)` 纯名称行为不变（走 list_all）
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from builder import deploy


def _write_app(target: Path, name: str) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    (target / "app.yaml").write_text(
        "app:\n"
        f"  name: {name}\n"
        "  version: 1.0.0\n"
        f"  description: {name} 测试\n"
        "  type: exec\n"
        "  arch:\n"
        "    - aarch64\n"
        "\n"
        "maintainer:\n"
        "  name: tester\n"
        "  email: tester@localhost\n"
        "\n"
        "build:\n"
        "  system: none\n",
        encoding="utf-8",
    )
    return target


class TestResolveAppArg:
    """_resolve_app_arg 三种判定。"""

    def test_含斜杠按路径解析(self, tmp_path):
        ext = _write_app(tmp_path / "ext" / "foo", "foo")
        config = SimpleNamespace(board="b", product="p", variant="v")
        result = deploy._resolve_app_arg(str(ext), tmp_path, config)
        assert result == (ext.resolve(), "foo")

    def test_点开头按路径解析(self, tmp_path, monkeypatch):
        ext = _write_app(tmp_path / "demo", "demo")
        monkeypatch.chdir(tmp_path)
        config = SimpleNamespace(board="b", product="p", variant="v")
        result = deploy._resolve_app_arg("./demo", tmp_path, config)
        assert result == (ext.resolve(), "demo")

    def test_纯名称走_list_all(self, tmp_path):
        # 在仓库内 components/app/ 下放一个 App，让 list_all 能发现
        local = _write_app(tmp_path / "components" / "app" / "adbd", "adbd")
        config = SimpleNamespace(board="b", product="p", variant="v")
        # 用 _scan_local 的真实行为；list_all 接受 project_root 与 config
        # config 在 list_all 内会取 external_apps/external_app_dirs，给空 dict
        with patch.object(deploy, "list_all") as mock_list:
            from builder.app_list import AppEntry
            mock_list.return_value = [
                AppEntry(
                    name="adbd",
                    type="exec",
                    version="1.0.0",
                    description="",
                    source_label="local",
                    source_path=local,
                )
            ]
            result = deploy._resolve_app_arg("adbd", tmp_path, config)
        assert result == (local, "adbd")

    def test_路径不存在时退出(self, tmp_path):
        config = SimpleNamespace(board="b", product="p", variant="v")
        with pytest.raises(SystemExit):
            deploy._resolve_app_arg("/tmp/nonexistent-deploy-xyz", tmp_path, config)

    def test_未注册的名称退出(self, tmp_path):
        config = SimpleNamespace(board="b", product="p", variant="v")
        with patch.object(deploy, "list_all", return_value=[]):
            with pytest.raises(SystemExit):
                deploy._resolve_app_arg("unknown-app-name", tmp_path, config)


class TestDeployAppPathEntry:
    """deploy_app 路径入口能正确进到 find_latest_deb 阶段。"""

    def test_path_入口解析后能按_app_name_查_deb(self, tmp_path, monkeypatch, capsys):
        """当 --no-build 模式时，路径解析后应按 spec.app.name 找 .deb。"""
        # 准备外部 App
        ext = _write_app(tmp_path / "ext-mypkg", "mypkg")

        # 准备伪造的 .deb，让 find_latest_deb 能命中
        deb_dir = tmp_path / ".build" / "target" / "test-board" / "default" / "release" / "app"
        deb_dir.mkdir(parents=True)
        deb_file = deb_dir / "mypkg_1.0.0_arm64.deb"
        deb_file.write_bytes(b"fake-deb")

        # cwd 设为 tmp_path 让 find_latest_deb 的相对路径解析正确
        monkeypatch.chdir(tmp_path)

        # mock load_current_config 返回 dict（与真实返回类型一致；find_latest_deb 用下标访问）
        fake_config = {"board": "test-board", "product": "default", "variant": "release"}
        monkeypatch.setattr(deploy, "load_current_config", lambda: fake_config)

        # mock check_adb / get_adb_device 让流程在 adb 之前结束（或 mock 整条 adb）
        monkeypatch.setattr(deploy, "check_adb", lambda: False)

        # 调用 deploy_app，应在 adb 检查阶段 sys.exit
        with pytest.raises(SystemExit):
            deploy.deploy_app(str(ext), build_deb=False, run=False)

        # 验证输出里出现了正确的 deb 文件名（说明 find_latest_deb 命中了）
        out = capsys.readouterr().out
        assert "mypkg_1.0.0_arm64.deb" in out


class TestDeployAppNamePreservedBehavior:
    """deploy_app 纯名称分支行为不变（用 mock 隔离 list_all）。"""

    def test_name_分支走_list_all(self, tmp_path, monkeypatch):
        """纯名称入参时应调用 list_all 查找。"""
        local = _write_app(tmp_path / "components" / "app" / "adbd", "adbd")

        fake_config = {"board": "test-board", "product": "default", "variant": "release"}
        monkeypatch.setattr(deploy, "load_current_config", lambda: fake_config)
        monkeypatch.setattr(deploy, "check_adb", lambda: False)
        monkeypatch.chdir(tmp_path)

        from builder.app_list import AppEntry
        called = {}

        def fake_list_all(project_root, config):
            called["called"] = True
            return [AppEntry(
                name="adbd",
                type="exec",
                version="1.0.0",
                description="",
                source_label="local",
                source_path=local,
            )]

        monkeypatch.setattr(deploy, "list_all", fake_list_all)

        # 没准备 .deb，find_latest_deb 返回 None → 退出
        with pytest.raises(SystemExit):
            deploy.deploy_app("adbd", build_deb=False, run=False)

        assert called.get("called"), "纯名称分支应调用 list_all"
