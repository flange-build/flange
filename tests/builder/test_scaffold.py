"""AppScaffold 脚手架生成器测试 — 覆盖各 type × build-system 组合、
无效组合拒绝、模板变量替换及目录结构校验。"""

from __future__ import annotations

import pytest
from pathlib import Path

from builder.scaffold import AppScaffold, ScaffoldError


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_scaffold(tmp_path: Path) -> AppScaffold:
    """返回以 tmp_path 为项目根目录的 AppScaffold 实例。"""
    return AppScaffold(project_root=tmp_path)


def _create(
    tmp_path: Path,
    name: str,
    app_type: str,
    build_system: str,
    **kwargs,
) -> Path:
    """调用 scaffold.create()，目标目录为 tmp_path 下唯一路径。"""
    target = tmp_path / "out" / name
    s = _make_scaffold(tmp_path)
    return s.create(
        name=name,
        app_type=app_type,
        build_system=build_system,
        target_dir=target,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# app.yaml 通用测试
# ---------------------------------------------------------------------------

class TestAppYaml:
    """所有组合都应生成有效的 app.yaml。"""

    def test_app_yaml_created(self, tmp_path):
        """生成目录中必须包含 app.yaml。"""
        dest = _create(tmp_path, "myapp", "exec", "cmake")
        assert (dest / "app.yaml").exists()

    def test_app_yaml_variables_substituted(self, tmp_path):
        """app.yaml 中的模板变量应被正确替换。"""
        dest = _create(
            tmp_path, "hello", "exec", "cmake",
            version="2.3.4",
            description="测试描述",
        )
        content = (dest / "app.yaml").read_text()
        assert "name: hello" in content
        assert "version: 2.3.4" in content
        assert "测试描述" in content
        assert "type: exec" in content
        assert "system: cmake" in content

    def test_app_yaml_no_template_tokens(self, tmp_path):
        """app.yaml 中不应存在未替换的 $ 占位符。"""
        dest = _create(tmp_path, "myservice", "service", "none",
                       description="a service")
        content = (dest / "app.yaml").read_text()
        # string.Template 使用 safe_substitute，未替换的键会原样保留 $key
        # 我们确保已知变量都被替换
        assert "${name}" not in content
        assert "${version}" not in content
        assert "${type}" not in content
        assert "${build_system}" not in content


# ---------------------------------------------------------------------------
# exec 类型测试
# ---------------------------------------------------------------------------

class TestExecType:
    """exec 类型支持 none / cmake / meson / make / swift。"""

    def test_exec_none_only_app_yaml(self, tmp_path):
        """exec + none 只生成 app.yaml。"""
        dest = _create(tmp_path, "myexec", "exec", "none")
        files = [f.name for f in dest.iterdir()]
        assert files == ["app.yaml"]

    def test_exec_cmake_files(self, tmp_path):
        """exec + cmake 应生成 CMakeLists.txt 和 src/main.c。"""
        dest = _create(tmp_path, "myexec", "exec", "cmake")
        assert (dest / "CMakeLists.txt").exists()
        assert (dest / "src" / "main.c").exists()

    def test_exec_cmake_name_substituted(self, tmp_path):
        """CMakeLists.txt 中应包含正确的项目名。"""
        dest = _create(tmp_path, "myexec", "exec", "cmake")
        content = (dest / "CMakeLists.txt").read_text()
        assert "project(myexec" in content
        assert "add_executable(myexec" in content

    def test_exec_meson_files(self, tmp_path):
        """exec + meson 应生成 meson.build 和 src/main.c。"""
        dest = _create(tmp_path, "myexec", "exec", "meson")
        assert (dest / "meson.build").exists()
        assert (dest / "src" / "main.c").exists()

    def test_exec_meson_name_substituted(self, tmp_path):
        """meson.build 中应包含正确的项目名。"""
        dest = _create(tmp_path, "myexec", "exec", "meson")
        content = (dest / "meson.build").read_text()
        assert "project('myexec'" in content
        assert "executable('myexec'" in content

    def test_exec_make_files(self, tmp_path):
        """exec + make 应生成 Makefile 和 src/main.c。"""
        dest = _create(tmp_path, "myexec", "exec", "make")
        assert (dest / "Makefile").exists()
        assert (dest / "src" / "main.c").exists()

    def test_exec_swift_files(self, tmp_path):
        """exec + swift 应生成 Package.swift 和 Sources/main.swift。"""
        dest = _create(tmp_path, "myexec", "exec", "swift")
        assert (dest / "Package.swift").exists()
        assert (dest / "Sources" / "main.swift").exists()

    def test_exec_swift_name_substituted(self, tmp_path):
        """Package.swift 中应包含正确的包名。"""
        dest = _create(tmp_path, "myexec", "exec", "swift")
        content = (dest / "Package.swift").read_text()
        assert 'name: "myexec"' in content


# ---------------------------------------------------------------------------
# service 类型测试
# ---------------------------------------------------------------------------

class TestServiceType:
    """service 类型支持 none / cmake / meson / make / swift，
    且均应包含 systemd unit 文件和 conf/config.yaml。"""

    def test_service_none_systemd_and_conf(self, tmp_path):
        """service + none 应生成 systemd unit 和 conf/config.yaml。"""
        dest = _create(tmp_path, "mysvc", "service", "none",
                       description="my service desc")
        assert (dest / "systemd" / "mysvc.service").exists()
        assert (dest / "conf" / "config.yaml").exists()

    def test_service_none_systemd_variables(self, tmp_path):
        """systemd unit 文件中应包含正确的服务描述和名称。"""
        dest = _create(tmp_path, "mysvc", "service", "none",
                       description="my service desc")
        unit = (dest / "systemd" / "mysvc.service").read_text()
        assert "Description=my service desc" in unit
        assert "ExecStart=/usr/bin/mysvc" in unit

    def test_service_cmake_has_cmake_and_systemd(self, tmp_path):
        """service + cmake 应同时包含 CMakeLists.txt 和 systemd unit。"""
        dest = _create(tmp_path, "mysvc", "service", "cmake",
                       description="cmake svc")
        assert (dest / "CMakeLists.txt").exists()
        assert (dest / "src" / "main.c").exists()
        assert (dest / "systemd" / "mysvc.service").exists()
        assert (dest / "conf" / "config.yaml").exists()

    def test_service_meson_files(self, tmp_path):
        """service + meson 应包含 meson.build、systemd unit 和 conf。"""
        dest = _create(tmp_path, "mysvc", "service", "meson")
        assert (dest / "meson.build").exists()
        assert (dest / "systemd" / "mysvc.service").exists()
        assert (dest / "conf" / "config.yaml").exists()

    def test_service_make_files(self, tmp_path):
        """service + make 应包含 Makefile、systemd unit 和 conf。"""
        dest = _create(tmp_path, "mysvc", "service", "make")
        assert (dest / "Makefile").exists()
        assert (dest / "systemd" / "mysvc.service").exists()

    def test_service_swift_files(self, tmp_path):
        """service + swift 应包含 Package.swift 和 systemd unit。"""
        dest = _create(tmp_path, "mysvc", "service", "swift")
        assert (dest / "Package.swift").exists()
        assert (dest / "systemd" / "mysvc.service").exists()


# ---------------------------------------------------------------------------
# lib 类型测试
# ---------------------------------------------------------------------------

class TestLibType:
    """lib 类型支持 cmake / meson / make，不支持 none 和 swift。"""

    def test_lib_cmake_files(self, tmp_path):
        """lib + cmake 应生成 CMakeLists.txt、头文件和源文件。"""
        dest = _create(tmp_path, "mylib", "lib", "cmake")
        assert (dest / "CMakeLists.txt").exists()
        assert (dest / "include" / "mylib.h").exists()
        assert (dest / "src" / "mylib.c").exists()

    def test_lib_cmake_shared_library(self, tmp_path):
        """CMakeLists.txt 应使用 SHARED 类型构建库。"""
        dest = _create(tmp_path, "mylib", "lib", "cmake")
        content = (dest / "CMakeLists.txt").read_text()
        assert "SHARED" in content
        assert "add_library(mylib SHARED" in content

    def test_lib_cmake_header_guard(self, tmp_path):
        """头文件应包含基于库名的宏保护符。"""
        dest = _create(tmp_path, "mylib", "lib", "cmake")
        header = (dest / "include" / "mylib.h").read_text()
        assert "MYLIB_H" in header
        assert "#ifndef MYLIB_H" in header

    def test_lib_meson_files(self, tmp_path):
        """lib + meson 应生成 meson.build、头文件和源文件。"""
        dest = _create(tmp_path, "mylib", "lib", "meson")
        assert (dest / "meson.build").exists()
        assert (dest / "include" / "mylib.h").exists()
        assert (dest / "src" / "mylib.c").exists()

    def test_lib_meson_shared_library(self, tmp_path):
        """meson.build 应使用 shared_library 构建库。"""
        dest = _create(tmp_path, "mylib", "lib", "meson")
        content = (dest / "meson.build").read_text()
        assert "shared_library" in content

    def test_lib_make_files(self, tmp_path):
        """lib + make 应生成 Makefile、头文件和源文件。"""
        dest = _create(tmp_path, "mylib", "lib", "make")
        assert (dest / "Makefile").exists()
        assert (dest / "include" / "mylib.h").exists()
        assert (dest / "src" / "mylib.c").exists()

    def test_lib_name_with_hyphen(self, tmp_path):
        """含连字符的库名应正确转换为 C 标识符（下划线）。"""
        dest = _create(tmp_path, "my-lib", "lib", "cmake")
        # 头文件名应保留连字符
        assert (dest / "include" / "my-lib.h").exists()
        header = (dest / "include" / "my-lib.h").read_text()
        # 宏保护符应使用下划线
        assert "MY_LIB_H" in header


# ---------------------------------------------------------------------------
# test 类型测试
# ---------------------------------------------------------------------------

class TestTestType:
    """test 类型仅支持 none 构建系统。"""

    def test_test_none_script(self, tmp_path):
        """test + none 应生成 scripts/test_example.sh。"""
        dest = _create(tmp_path, "mytest", "test", "none",
                       description="测试套件")
        assert (dest / "scripts" / "test_example.sh").exists()

    def test_test_none_script_variables(self, tmp_path):
        """测试脚本中应包含正确的 App 名称。"""
        dest = _create(tmp_path, "mytest", "test", "none",
                       description="测试套件")
        script = (dest / "scripts" / "test_example.sh").read_text()
        assert "mytest" in script


# ---------------------------------------------------------------------------
# amp 类型测试
# ---------------------------------------------------------------------------

class TestAmpType:
    """amp 类型支持 HAL 与 RT-Thread overlay 脚手架。"""

    def test_amp_scons_default_is_c_overlay(self, tmp_path):
        """amp+scons 默认保持纯 C overlay，不隐式启用 Swift。"""
        dest = _create(tmp_path, "myamp", "amp", "scons")
        assert (dest / "applications" / "main.c").exists()
        assert not (dest / "Package.swift").exists()
        assert "swift:" not in (dest / "app.yaml").read_text()

    def test_amp_scons_embedded_swift_files(self, tmp_path):
        """显式 embedded_swift=True 时生成 SwiftPM static library 骨架。"""
        dest = _create(
            tmp_path, "myamp", "amp", "scons",
            embedded_swift=True,
        )

        assert (dest / "Package.swift").exists()
        assert (dest / "Sources" / "AmpLogic" / "AmpLogic.swift").exists()
        assert (dest / "include" / "swift_bridge.h").exists()
        assert (dest / "applications" / "main.c").exists()

        app_yaml = (dest / "app.yaml").read_text()
        assert "system: scons" in app_yaml
        assert "swift:" in app_yaml
        assert "enabled: true" in app_yaml
        assert "product: AmpLogic" in app_yaml

    def test_embedded_swift_only_for_amp_scons(self, tmp_path):
        """embedded_swift 只能配合 amp+scons 使用。"""
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="embedded_swift"):
            s.create(
                "bad", "exec", "swift",
                target_dir=tmp_path / "out" / "bad",
                embedded_swift=True,
            )


# ---------------------------------------------------------------------------
# 无效组合测试
# ---------------------------------------------------------------------------

class TestInvalidCombinations:
    """非法 type × build-system 组合应抛出 ScaffoldError。"""

    @pytest.mark.parametrize("app_type,build_system", [
        ("lib",  "none"),
        ("lib",  "swift"),
        ("test", "cmake"),
        ("test", "meson"),
        ("test", "make"),
        ("test", "swift"),
    ])
    def test_invalid_combination(self, tmp_path, app_type, build_system):
        """非法组合应抛出 ScaffoldError 并说明原因。"""
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError):
            s.create("myapp", app_type, build_system,
                     target_dir=tmp_path / "out")

    def test_invalid_type(self, tmp_path):
        """未知 App 类型应抛出 ScaffoldError。"""
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="不支持"):
            s.create("myapp", "unknown", "cmake",
                     target_dir=tmp_path / "out")

    def test_empty_name(self, tmp_path):
        """空名称应抛出 ScaffoldError。"""
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="name"):
            s.create("", "exec", "cmake", target_dir=tmp_path / "out")

    def test_name_with_spaces(self, tmp_path):
        """含空格的名称应抛出 ScaffoldError。"""
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="非法字符"):
            s.create("my app", "exec", "cmake", target_dir=tmp_path / "out")

    def test_existing_directory_raises(self, tmp_path):
        """目标目录已存在时应抛出 ScaffoldError。"""
        target = tmp_path / "myapp"
        target.mkdir()
        s = _make_scaffold(tmp_path)
        with pytest.raises(ScaffoldError, match="已存在"):
            s.create("myapp", "exec", "cmake", target_dir=target)


# ---------------------------------------------------------------------------
# 默认目标目录测试
# ---------------------------------------------------------------------------

class TestDefaultTargetDir:
    """不指定 target_dir 时，目录应在 <project_root>/components/app/<name>/ 下创建。"""

    def test_default_dir_in_app_folder(self, tmp_path):
        """默认目标目录应为 components/app/<name>/。"""
        s = AppScaffold(project_root=tmp_path)
        dest = s.create("myapp", "exec", "none")
        expected = tmp_path / "components" / "app" / "myapp"
        assert dest == expected
        assert dest.exists()

    def test_default_dir_app_yaml_exists(self, tmp_path):
        """默认路径下也应生成 app.yaml。"""
        s = AppScaffold(project_root=tmp_path)
        dest = s.create("myapp", "exec", "none")
        assert (dest / "app.yaml").exists()


# ---------------------------------------------------------------------------
# 清理测试（原子性保证）
# ---------------------------------------------------------------------------

class TestParentDir:
    """--dir / parent_dir 参数覆盖：父目录语义、自动 mkdir、目标冲突、注册指引。"""

    def test_parent_dir_生成到_parent_name(self, tmp_path):
        """parent_dir=<p> 时最终目录为 <p>/<name>/，name 实参决定子目录名。"""
        parent = tmp_path / "vendor-apps"
        parent.mkdir()
        s = AppScaffold(project_root=tmp_path)
        dest = s.create(
            "wifi", "exec", "cmake",
            parent_dir=parent,
        )
        assert dest == parent / "wifi"
        assert (dest / "app.yaml").exists()

    def test_parent_dir_不存在时自动创建(self, tmp_path):
        """父目录不存在时应自动创建（与默认路径行为一致），不报错。"""
        parent = tmp_path / "fresh" / "nested" / "vendor-apps"
        assert not parent.exists()
        s = AppScaffold(project_root=tmp_path)
        dest = s.create("foo", "exec", "none", parent_dir=parent)
        assert dest == parent / "foo"
        assert dest.exists()

    def test_parent_dir_下子目录已存在时报错(self, tmp_path):
        """<parent>/<name>/ 已存在时应拒绝，不覆盖任何内容。"""
        parent = tmp_path / "vendor"
        parent.mkdir()
        (parent / "bar").mkdir()
        s = AppScaffold(project_root=tmp_path)
        with pytest.raises(ScaffoldError, match="已存在"):
            s.create("bar", "exec", "none", parent_dir=parent)

    def test_target_dir_与_parent_dir_互斥(self, tmp_path):
        """两个参数同时传入时应明确报错。"""
        s = AppScaffold(project_root=tmp_path)
        with pytest.raises(ScaffoldError, match="不能同时"):
            s.create(
                "x", "exec", "none",
                target_dir=tmp_path / "out",
                parent_dir=tmp_path / "other",
            )

    def test_out_of_tree_输出提示(self, tmp_path, capsys):
        """生成到 components/app/ 之外时，stdout 应含 [注册指引] 片段。"""
        parent = tmp_path / "workspace" / "my-apps"
        parent.mkdir(parents=True)
        s = AppScaffold(project_root=tmp_path)
        dest = s.create("zigbee", "exec", "none", parent_dir=parent)

        captured = capsys.readouterr().out
        assert "[注册指引]" in captured
        # 两种示例片段都应出现
        assert "external_apps" in captured
        assert "external_app_dirs" in captured
        # 指引中应包含绝对路径
        import os as _os
        assert _os.path.realpath(str(dest)) in captured
        assert _os.path.realpath(str(parent)) in captured

    def test_默认路径不输出提示(self, tmp_path, capsys):
        """生成到 components/app/<name>/ 时，stdout 不应含 [注册指引] 标记。"""
        s = AppScaffold(project_root=tmp_path)
        s.create("foo", "exec", "none")
        captured = capsys.readouterr().out
        # 用完整标记匹配，避免 tmp_path 目录名中若含中文片段被误匹配
        assert "[注册指引]" not in captured


class TestAtomicCleanup:
    """出错时应清理已创建的目录，不留下半成品。"""

    def test_cleanup_on_error(self, tmp_path, monkeypatch):
        """模拟渲染失败时，目标目录应被清理。"""
        from builder import scaffold as sc

        # 让 _render_file 在第二次调用时抛出异常（第一次写 app.yaml 成功）
        call_count = [0]
        original_render = sc.AppScaffold._render_file

        def mock_render(tpl_path, out_path, variables):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("模拟渲染错误")
            original_render(tpl_path, out_path, variables)

        monkeypatch.setattr(sc.AppScaffold, "_render_file", staticmethod(mock_render))

        target = tmp_path / "fail_app"
        with pytest.raises(RuntimeError):
            s = AppScaffold(project_root=tmp_path)
            s.create("fail_app", "exec", "cmake", target_dir=target)
        # 目录应已被清理
        assert not target.exists()
