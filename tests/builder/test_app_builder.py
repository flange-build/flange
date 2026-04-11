"""AppBuilder 单元测试。

覆盖场景：
- build_one()：使用 prebuilt App（build.system=none）端到端构建流程
- build_all()：多个 App 的批量构建
- _resolve_build_order()：含依赖关系的拓扑排序
- 循环依赖检测（CircularDependencyError）
- _find_app_dir()：正确查找 app/ 目录，缺失时抛出 FileNotFoundError
- _topo_sort_apps()：独立函数的直接测试
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.app import AppBuilder, CircularDependencyError, _topo_sort_apps


# ---------------------------------------------------------------------------
# 测试辅助：构造临时 App 目录
# ---------------------------------------------------------------------------

def _make_app_dir(
    tmp_path: Path,
    name: str,
    version: str = "1.0.0",
    app_type: str = "exec",
    build_system: str = "none",
    build_deps: list[str] | None = None,
    arch: list[str] | None = None,
    bin_files: list[str] | None = None,
) -> Path:
    """在 tmp_path/app/<name>/ 下创建一个最小可用的 App 目录，包含 app.yaml。

    参数：
        tmp_path:    pytest 提供的临时目录
        name:        App 名称
        version:     版本号
        app_type:    App 类型（exec / service / lib / test）
        build_system: 构建系统（none / cmake / meson 等）
        build_deps:  构建依赖列表（App 名称）
        arch:        支持的架构列表
        bin_files:   在 bin/ 子目录下创建的文件名列表（内容为空字节）

    返回：
        App 目录路径（tmp_path/app/<name>/）
    """
    deps = build_deps or []
    archs = arch or ["aarch64"]

    # 逐行组装 YAML，避免 textwrap.dedent 与 f-string 插值冲突导致缩进错误
    lines: list[str] = [
        "app:",
        f"  name: {name}",
        f"  version: {version}",
        f"  description: {name} 测试 App",
        f"  type: {app_type}",
        "  arch:",
    ]
    for a in archs:
        lines.append(f"    - {a}")

    lines += [
        "",
        "maintainer:",
        "  name: tester",
        "  email: tester@localhost",
        "",
        "build:",
        f"  system: {build_system}",
    ]

    if deps:
        lines.append("  deps:")
        for d in deps:
            lines.append(f"    - {d}")

    yaml_content = "\n".join(lines) + "\n"

    app_dir = tmp_path / "app" / name
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "app.yaml").write_text(yaml_content, encoding="utf-8")

    # 在 bin/ 子目录创建占位文件，collect_files 需要真实文件存在
    if bin_files:
        bin_dir = app_dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        for fname in bin_files:
            (bin_dir / fname).write_bytes(b"\x7fELF")  # 伪 ELF 魔数

    return app_dir


def _make_builder(tmp_path: Path, arch: str = "aarch64") -> AppBuilder:
    """构造一个使用 tmp_path 作为项目根目录的 AppBuilder 实例。

    DockerRunner 与 SourceManager 均使用 MagicMock，
    因为 prebuilt App（build.system=none）不需要 Docker 编译。
    """
    config = {
        "board":   "test-board",
        "product": "default",
        "variant": "release",
        "arch":    arch,
        "rootfs":  {"custom_packages": []},
    }
    docker = MagicMock()
    source = MagicMock()
    return AppBuilder(docker, source, config, project_dir=tmp_path)


# ---------------------------------------------------------------------------
# _topo_sort_apps 独立函数测试
# ---------------------------------------------------------------------------

class TestTopoSortApps:
    """测试 _topo_sort_apps 独立函数。"""

    def test_无依赖单节点(self):
        """单个节点，无依赖，直接返回该节点。"""
        result = _topo_sort_apps({"alpha": []})
        assert result == ["alpha"]

    def test_线性依赖链(self):
        """a → b → c，应返回 [c, b, a]（依赖先于被依赖方）。"""
        graph = {"a": ["b"], "b": ["c"], "c": []}
        result = _topo_sort_apps(graph)
        # 校验 c 在 b 前，b 在 a 前
        assert result.index("c") < result.index("b") < result.index("a")

    def test_多根无依赖(self):
        """三个无依赖节点，顺序不固定但应全部出现。"""
        graph = {"x": [], "y": [], "z": []}
        result = _topo_sort_apps(graph)
        assert sorted(result) == ["x", "y", "z"]

    def test_菱形依赖(self):
        """a → {b, c}，b → d，c → d，d 必须最先构建。"""
        graph = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
        result = _topo_sort_apps(graph)
        assert result.index("d") < result.index("b")
        assert result.index("d") < result.index("c")
        assert result.index("b") < result.index("a")
        assert result.index("c") < result.index("a")

    def test_循环依赖两节点(self):
        """a → b，b → a，应抛出 CircularDependencyError。"""
        graph = {"a": ["b"], "b": ["a"]}
        with pytest.raises(CircularDependencyError):
            _topo_sort_apps(graph)

    def test_循环依赖三节点(self):
        """a → b → c → a，应抛出 CircularDependencyError。"""
        graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
        with pytest.raises(CircularDependencyError):
            _topo_sort_apps(graph)

    def test_自依赖(self):
        """a → a 自依赖，应抛出 CircularDependencyError。"""
        graph = {"a": ["a"]}
        with pytest.raises(CircularDependencyError):
            _topo_sort_apps(graph)

    def test_空图(self):
        """空图返回空列表。"""
        result = _topo_sort_apps({})
        assert result == []


# ---------------------------------------------------------------------------
# AppBuilder._find_app_dir 测试
# ---------------------------------------------------------------------------

class TestFindAppDir:
    """测试 _find_app_dir 查找逻辑。"""

    def test_在本地app目录找到(self, tmp_path):
        """App 目录存在时正确返回路径。"""
        _make_app_dir(tmp_path, "myapp")
        builder = _make_builder(tmp_path)
        result = builder._find_app_dir("myapp")
        assert result == tmp_path / "app" / "myapp"
        assert result.is_dir()

    def test_目录不存在时抛出ValueError(self, tmp_path):
        """App 目录不存在且未在 external_apps 声明时，SourceManager 应抛出 ValueError。"""
        builder = _make_builder(tmp_path)
        # 配置 mock source 模拟 ensure_app 找不到 App 的行为
        builder._source.ensure_app.side_effect = ValueError("nonexistent 未找到")
        with pytest.raises(ValueError, match="nonexistent"):
            builder._find_app_dir("nonexistent")


# ---------------------------------------------------------------------------
# AppBuilder._resolve_build_order 测试
# ---------------------------------------------------------------------------

class TestResolveBuildOrder:
    """测试 _resolve_build_order 方法（基于真实 app.yaml 文件）。"""

    def test_无依赖单app(self, tmp_path):
        """单个无依赖 App，返回该 App 名称。"""
        _make_app_dir(tmp_path, "alpha")
        builder = _make_builder(tmp_path)
        result = builder._resolve_build_order(["alpha"])
        assert result == ["alpha"]

    def test_线性依赖(self, tmp_path):
        """appA 依赖 appB，构建顺序应为 [appB, appA]。"""
        _make_app_dir(tmp_path, "appA", build_deps=["appB"])
        _make_app_dir(tmp_path, "appB")
        builder = _make_builder(tmp_path)
        result = builder._resolve_build_order(["appA", "appB"])
        assert result.index("appB") < result.index("appA")

    def test_集合外依赖被忽略(self, tmp_path):
        """appA 依赖 external_lib（不在本次构建集合中），该依赖应被忽略。"""
        _make_app_dir(tmp_path, "appA", build_deps=["external_lib"])
        builder = _make_builder(tmp_path)
        # 只构建 appA，external_lib 不在集合中
        result = builder._resolve_build_order(["appA"])
        assert result == ["appA"]

    def test_多app有序依赖(self, tmp_path):
        """三个 App 的依赖链：appC → appB → appA，应返回正确顺序。"""
        _make_app_dir(tmp_path, "appA")
        _make_app_dir(tmp_path, "appB", build_deps=["appA"])
        _make_app_dir(tmp_path, "appC", build_deps=["appB"])
        builder = _make_builder(tmp_path)
        result = builder._resolve_build_order(["appA", "appB", "appC"])
        assert result.index("appA") < result.index("appB") < result.index("appC")

    def test_循环依赖抛出异常(self, tmp_path):
        """两个 App 互相依赖，应抛出 CircularDependencyError。"""
        _make_app_dir(tmp_path, "appX", build_deps=["appY"])
        _make_app_dir(tmp_path, "appY", build_deps=["appX"])
        builder = _make_builder(tmp_path)
        with pytest.raises(CircularDependencyError):
            builder._resolve_build_order(["appX", "appY"])


# ---------------------------------------------------------------------------
# AppBuilder.build_one 测试
# ---------------------------------------------------------------------------

class TestBuildOne:
    """测试 build_one() 方法。"""

    def test_prebuilt_app_生成deb(self, tmp_path):
        """prebuilt App（build.system=none）应正常生成 .deb 文件。"""
        _make_app_dir(tmp_path, "hello", bin_files=["hello"])
        builder = _make_builder(tmp_path)
        deb_path = builder.build_one("hello")

        # .deb 文件应真实存在
        assert deb_path.exists()
        assert deb_path.suffix == ".deb"
        # 文件名应包含 App 名称和版本
        assert "hello" in deb_path.name
        assert "1.0.0" in deb_path.name

    def test_deb输出到正确目录(self, tmp_path):
        """生成的 .deb 应位于 target/<board>/<product>/<variant>/app/ 下。"""
        _make_app_dir(tmp_path, "mypkg", bin_files=["mypkg"])
        builder = _make_builder(tmp_path)
        deb_path = builder.build_one("mypkg")

        expected_dir = tmp_path / "target" / "test-board" / "default" / "release" / "app"
        assert deb_path.parent == expected_dir

    def test_app目录不存在时抛出ValueError(self, tmp_path):
        """App 目录不存在且未在 external_apps 声明时，应抛出 ValueError。"""
        builder = _make_builder(tmp_path)
        # mock source 模拟 ensure_app 找不到 App 的行为
        builder._source.ensure_app.side_effect = ValueError("does_not_exist 未找到")
        with pytest.raises(ValueError):
            builder.build_one("does_not_exist")

    def test_无文件app生成空deb(self, tmp_path):
        """无任何安装文件的 App 也能生成 .deb（data.tar.gz 内容为空）。"""
        _make_app_dir(tmp_path, "empty_app")  # 不创建 bin_files
        builder = _make_builder(tmp_path)
        deb_path = builder.build_one("empty_app")
        assert deb_path.exists()

    def test_non_none_build_system_跳过编译(self, tmp_path, caplog):
        """build.system != "none" 时，_compile 应记录跳过日志，不实际执行编译。"""
        import logging
        _make_app_dir(tmp_path, "cmake_app", build_system="cmake", bin_files=["cmake_app"])
        builder = _make_builder(tmp_path)
        # Task 5 未实现前，cmake 构建系统应只记录日志并跳过
        with caplog.at_level(logging.INFO, logger="flange"):
            deb_path = builder.build_one("cmake_app")
        assert deb_path.exists()
        # 确认日志中出现跳过提示
        assert any("cmake" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# AppBuilder.build_all 测试
# ---------------------------------------------------------------------------

class TestBuildAll:
    """测试 build_all() 方法。"""

    def test_空custom_packages返回空字典(self, tmp_path):
        """custom_packages 为空时，build_all 应返回空字典。"""
        builder = _make_builder(tmp_path)
        result = builder.build_all()
        assert result == {}

    def test_单app批量构建(self, tmp_path):
        """custom_packages 中只有一个 App 时，返回包含该 App 的字典。"""
        _make_app_dir(tmp_path, "solo", bin_files=["solo"])
        config = {
            "board":   "test-board",
            "product": "default",
            "variant": "release",
            "arch":    "aarch64",
            "rootfs":  {"custom_packages": ["solo"]},
        }
        builder = AppBuilder(MagicMock(), MagicMock(), config, project_dir=tmp_path)
        result = builder.build_all()

        assert "solo" in result
        assert result["solo"].exists()

    def test_多app按依赖顺序构建(self, tmp_path):
        """多个 App 按拓扑排序顺序构建，全部出现在结果字典中。"""
        _make_app_dir(tmp_path, "libbase", bin_files=["libbase.so"])
        _make_app_dir(tmp_path, "daemon", build_deps=["libbase"], bin_files=["daemon"])
        _make_app_dir(tmp_path, "cli",    build_deps=["libbase"], bin_files=["cli"])

        config = {
            "board":   "test-board",
            "product": "default",
            "variant": "release",
            "arch":    "aarch64",
            "rootfs":  {"custom_packages": ["libbase", "daemon", "cli"]},
        }
        builder = AppBuilder(MagicMock(), MagicMock(), config, project_dir=tmp_path)
        result = builder.build_all()

        assert set(result.keys()) == {"libbase", "daemon", "cli"}
        for name, path in result.items():
            assert path.exists(), f"{name} 的 .deb 文件应存在"

    def test_custom_packages中app不存在时抛出错误(self, tmp_path):
        """custom_packages 包含不存在的 App 时，应抛出 ValueError（SourceManager 报告未找到）。"""
        config = {
            "board":   "test-board",
            "product": "default",
            "variant": "release",
            "arch":    "aarch64",
            "rootfs":  {"custom_packages": ["ghost_app"]},
        }
        mock_source = MagicMock()
        mock_source.ensure_app.side_effect = ValueError("ghost_app 未找到")
        builder = AppBuilder(MagicMock(), mock_source, config, project_dir=tmp_path)
        with pytest.raises(ValueError):
            builder.build_all()

    def test_循环依赖在build_all中抛出错误(self, tmp_path):
        """custom_packages 中存在循环依赖时，build_all 应抛出 CircularDependencyError。"""
        _make_app_dir(tmp_path, "nodeA", build_deps=["nodeB"])
        _make_app_dir(tmp_path, "nodeB", build_deps=["nodeA"])

        config = {
            "board":   "test-board",
            "product": "default",
            "variant": "release",
            "arch":    "aarch64",
            "rootfs":  {"custom_packages": ["nodeA", "nodeB"]},
        }
        builder = AppBuilder(MagicMock(), MagicMock(), config, project_dir=tmp_path)
        with pytest.raises(CircularDependencyError):
            builder.build_all()
