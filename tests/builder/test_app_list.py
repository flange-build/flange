"""builder.app_list.list_all 单元测试。

覆盖四类场景：
  1. 纯本地 — components/app/* 被识别，无 config 时只扫本地
  2. 本地 + external_apps_local + external_apps_git 三类共存，各自来源标签正确
  3. 同名多来源 — 本地压 external，also_found_in 记录其它来源
  4. external_app_dirs 下枚举多 App（顺序遍历 + 命名）
"""

from __future__ import annotations

from pathlib import Path

from builder.app_list import AppEntry, list_all, format_lines


def _write_app(app_dir: Path, name: str, app_type: str = "exec",
               version: str = "1.0.0", description: str = "") -> None:
    """写一份最小合法 app.yaml。"""
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "app.yaml").write_text(
        f"app:\n"
        f"  name: {name}\n"
        f"  version: {version}\n"
        f"  description: {description or name}\n"
        f"  type: {app_type}\n"
        f"  arch:\n"
        f"    - aarch64\n"
        f"\n"
        f"maintainer:\n"
        f"  name: t\n"
        f"  email: t@localhost\n"
        f"\n"
        f"build:\n"
        f"  system: none\n",
        encoding="utf-8",
    )


class TestListAllLocal:

    def test_仅扫描本地_components_app(self, tmp_path):
        """config=None 时仅扫本地，external_* 字段即使存在也不遍历。"""
        _write_app(tmp_path / "components" / "app" / "adbd", "adbd", version="1.2.3")
        _write_app(tmp_path / "components" / "app" / "wifi", "wifi")

        entries = list_all(project_root=tmp_path, config=None)
        names = [e.name for e in entries]
        assert names == ["adbd", "wifi"]
        for e in entries:
            assert e.source_label == "local"
            assert e.also_found_in == []

        adbd = next(e for e in entries if e.name == "adbd")
        assert adbd.type == "exec"
        assert adbd.version == "1.2.3"

    def test_缺少_app_yaml_的子目录被忽略(self, tmp_path):
        """components/app/<name>/ 存在但无 app.yaml 的目录不进入结果。"""
        (tmp_path / "components" / "app" / "stub").mkdir(parents=True)
        _write_app(tmp_path / "components" / "app" / "real", "real")

        entries = list_all(project_root=tmp_path, config=None)
        assert [e.name for e in entries] == ["real"]


class TestListAllThreeSources:

    def test_三类来源共存(self, tmp_path):
        """本地 + external_apps(local_path) + external_apps(git) + external_app_dirs 全链路。"""
        # 本地
        _write_app(tmp_path / "components" / "app" / "adbd", "adbd")

        # external_apps: local_path
        _write_app(tmp_path / "vendor" / "wifi", "wifi", version="2.0.0")

        # external_apps: git（不存在于磁盘，纯配置）

        # external_app_dirs 下：bt
        _write_app(tmp_path / "teamapps" / "bt", "bt", description="bluetooth")

        config = {
            "external_apps": {
                "wifi": {"local_path": str(tmp_path / "vendor" / "wifi")},
                "zigbee": {"git": "ssh://git@example.com/zigbee.git"},
            },
            "external_app_dirs": [str(tmp_path / "teamapps")],
        }

        entries = list_all(project_root=tmp_path, config=config)
        by_name = {e.name: e for e in entries}

        assert set(by_name.keys()) == {"adbd", "wifi", "zigbee", "bt"}
        assert by_name["adbd"].source_label == "local"
        assert by_name["wifi"].source_label == "external:local"
        assert by_name["wifi"].version == "2.0.0"
        assert by_name["zigbee"].source_label == "external:git"
        assert by_name["bt"].source_label == f"dir:{tmp_path / 'teamapps'}"
        assert by_name["bt"].description == "bluetooth"


class TestSameNameMultiSource:

    def test_本地压_external_apps(self, tmp_path):
        """本地与 external_apps 同名时，本地胜出，external 进入 also_found_in。"""
        _write_app(tmp_path / "components" / "app" / "foo", "foo", version="local-v")
        _write_app(tmp_path / "other" / "foo", "foo", version="external-v")

        config = {
            "external_apps": {
                "foo": {"local_path": str(tmp_path / "other" / "foo")},
            },
            "external_app_dirs": [],
        }
        entries = list_all(project_root=tmp_path, config=config)
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "foo"
        assert e.source_label == "local"
        # 元数据来自主来源（本地）
        assert e.version == "local-v"
        # 次来源记录
        assert len(e.also_found_in) == 1
        assert e.also_found_in[0][0] == "external:local"

    def test_external_apps_压_external_app_dirs(self, tmp_path):
        """external_apps 显式注册压过搜索路径里的同名条目。"""
        _write_app(tmp_path / "explicit" / "bar", "bar")
        _write_app(tmp_path / "search" / "bar", "bar")

        config = {
            "external_apps": {"bar": {"local_path": str(tmp_path / "explicit" / "bar")}},
            "external_app_dirs": [str(tmp_path / "search")],
        }
        entries = list_all(project_root=tmp_path, config=config)
        assert len(entries) == 1
        e = entries[0]
        assert e.source_label == "external:local"
        assert len(e.also_found_in) == 1
        assert e.also_found_in[0][0].startswith("dir:")


class TestExternalAppDirsEnumeration:

    def test_dir_下枚举多个_app(self, tmp_path):
        """同一搜索目录下多个 App 都应被列出。"""
        vendor = tmp_path / "vendor-apps"
        _write_app(vendor / "wifi", "wifi")
        _write_app(vendor / "bt", "bt")
        _write_app(vendor / "nfc", "nfc")
        # 无 app.yaml 的噪声目录
        (vendor / "not-an-app").mkdir()

        config = {
            "external_app_dirs": [str(vendor)],
        }
        entries = list_all(project_root=tmp_path, config=config)
        names = sorted(e.name for e in entries)
        assert names == ["bt", "nfc", "wifi"]
        for e in entries:
            assert e.source_label == f"dir:{vendor}"

    def test_多_dir_时保留首个命中(self, tmp_path):
        """多目录含同名 App：列表前者为主来源，后者进入 also_found_in。"""
        team = tmp_path / "team"
        personal = tmp_path / "personal"
        _write_app(team / "x", "x", version="team-v")
        _write_app(personal / "x", "x", version="personal-v")

        config = {
            "external_app_dirs": [str(team), str(personal)],
        }
        entries = list_all(project_root=tmp_path, config=config)
        assert len(entries) == 1
        e = entries[0]
        assert e.source_label == f"dir:{team}"
        assert e.version == "team-v"
        assert len(e.also_found_in) == 1
        assert e.also_found_in[0][0] == f"dir:{personal}"


class TestFormatLines:

    def test_空列表有占位提示(self):
        out = format_lines([])
        assert len(out) == 1
        assert "未找到" in out[0]

    def test_含_also_found_in_多行(self, tmp_path):
        entry = AppEntry(
            name="foo", type="exec", version="1.0", description="d",
            source_label="local", source_path=Path("/a"),
            also_found_in=[("external:local", Path("/b"))],
        )
        out = format_lines([entry])
        assert len(out) == 2
        assert "[local]" in out[0]
        assert "also found in" in out[1]
        assert "external:local" in out[1]
