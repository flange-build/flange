"""AppBuilder._compile 与 _build_commands 单元测试（Task 5）。

覆盖场景：
- cmake：命令模板生成、交叉编译参数替换、-D 选项展开、sysroot 注入
- meson：命令模板生成、-D 选项展开
- make：命令模板生成、交叉编译前缀替换、KEY=VALUE 选项展开、sysroot 注入
- swift：命令模板生成、--triple 替换、--key value 选项展开
- custom：直通 spec.build.commands，不经模板展开
- none：_compile 提前返回，不调用 DockerRunner.run
- armhf 架构：交叉编译前缀正确替换
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from builder.app import AppBuilder, _BUILD_SYSTEMS, _CROSS_COMPILE_PREFIX
from builder.app_spec import AppSpec, AppInfo, BuildConfig, MaintainerInfo


# ---------------------------------------------------------------------------
# 测试辅助：构造最小 AppSpec
# ---------------------------------------------------------------------------

def _make_spec(
    name: str = "testapp",
    system: str = "cmake",
    options: dict | None = None,
    deps: list[str] | None = None,
    commands: list[list[str]] | None = None,
    app_type: str = "exec",
) -> AppSpec:
    """构造用于测试的最小 AppSpec 对象。

    参数：
        name:     App 名称
        system:   构建系统（cmake/meson/make/swift/custom/none）
        options:  build.options 字典
        deps:     build.deps 列表
        commands: build.commands 列表（custom 构建系统专用）
        app_type: App 类型

    返回：
        AppSpec 实例
    """
    return AppSpec(
        app=AppInfo(
            name=name,
            version="1.0.0",
            description="测试 App",
            type=app_type,
            arch=["aarch64"],
        ),
        maintainer=MaintainerInfo(name="tester", email="test@localhost"),
        build=BuildConfig(
            system=system,
            options=options or {},
            deps=deps or [],
            commands=commands or [],
        ),
    )


def _make_builder(tmp_path: Path, arch: str = "aarch64") -> AppBuilder:
    """构造使用 tmp_path 作为项目根目录的 AppBuilder。

    DockerRunner 使用 MagicMock，以便捕获 run() 调用参数。
    """
    config = {
        "board":   "rk3566",
        "product": "default",
        "variant": "release",
        "arch":    arch,
        "rootfs":  {"custom_packages": []},
    }
    docker = MagicMock()
    source = MagicMock()
    return AppBuilder(docker, source, config, project_dir=tmp_path)


# ---------------------------------------------------------------------------
# 常量表验证
# ---------------------------------------------------------------------------

class TestBuildSystemsConstants:
    """验证 _BUILD_SYSTEMS 与 _CROSS_COMPILE_PREFIX 常量定义。"""

    def test_构建系统常量包含所有有效系统(self):
        """_BUILD_SYSTEMS 应包含所有 6 个有效构建系统键。"""
        expected = {"none", "cmake", "meson", "make", "swift", "custom"}
        assert set(_BUILD_SYSTEMS.keys()) == expected

    def test_cmake模板有两步(self):
        """cmake 模板应包含 configure 和 build 两步命令。"""
        assert len(_BUILD_SYSTEMS["cmake"]) == 2
        assert _BUILD_SYSTEMS["cmake"][0][0] == "cmake"
        assert _BUILD_SYSTEMS["cmake"][1][0] == "cmake"

    def test_meson模板有两步(self):
        """meson 模板应包含 setup（meson）和 build（ninja）两步。"""
        assert len(_BUILD_SYSTEMS["meson"]) == 2
        assert _BUILD_SYSTEMS["meson"][0][0] == "meson"
        assert _BUILD_SYSTEMS["meson"][1][0] == "ninja"

    def test_make模板有一步(self):
        """make 模板应包含一步 make 命令。"""
        assert len(_BUILD_SYSTEMS["make"]) == 1
        assert _BUILD_SYSTEMS["make"][0][0] == "make"

    def test_swift模板有一步(self):
        """swift 模板应包含一步 swift build 命令。"""
        assert len(_BUILD_SYSTEMS["swift"]) == 1
        assert _BUILD_SYSTEMS["swift"][0][0] == "swift"

    def test_none模板为空列表(self):
        """none 模板为空，预编译包不需要任何命令。"""
        assert _BUILD_SYSTEMS["none"] == []

    def test_custom模板为空列表(self):
        """custom 模板为空，命令由 spec.build.commands 提供。"""
        assert _BUILD_SYSTEMS["custom"] == []

    def test_aarch64交叉前缀(self):
        """aarch64 架构应映射到 aarch64-linux-gnu- 前缀。"""
        assert _CROSS_COMPILE_PREFIX["aarch64"] == "aarch64-linux-gnu-"

    def test_armhf交叉前缀(self):
        """armhf 架构应映射到 arm-linux-gnueabihf- 前缀。"""
        assert _CROSS_COMPILE_PREFIX["armhf"] == "arm-linux-gnueabihf-"


# ---------------------------------------------------------------------------
# cmake 命令生成
# ---------------------------------------------------------------------------

class TestCmakeBuildCommands:
    """测试 cmake 构建系统的命令生成。"""

    def test_基础cmake命令包含两步(self, tmp_path):
        """无选项时，cmake 应生成 configure + build 两步命令。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake")
        cmds = builder._build_commands(spec, builder._config)
        assert len(cmds) == 2

    def test_cmake第一步包含cmake_B_build(self, tmp_path):
        """configure 步骤应包含 cmake -B build。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake")
        cmds = builder._build_commands(spec, builder._config)
        assert "cmake" in cmds[0]
        assert "-B" in cmds[0]
        assert "build" in cmds[0]

    def test_cmake第二步包含build(self, tmp_path):
        """build 步骤应包含 cmake --build build。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake")
        cmds = builder._build_commands(spec, builder._config)
        assert cmds[1] == ["cmake", "--build", "build", "-j$(nproc)"]

    def test_cmake注入aarch64编译器(self, tmp_path):
        """aarch64 架构时，cmake configure 步骤应使用 aarch64-linux-gnu- 编译器。"""
        builder = _make_builder(tmp_path, arch="aarch64")
        spec = _make_spec(system="cmake")
        cmds = builder._build_commands(spec, builder._config)
        configure_cmd = cmds[0]
        assert "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc" in configure_cmd
        assert "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++" in configure_cmd

    def test_cmake注入armhf编译器(self, tmp_path):
        """armhf 架构时，cmake configure 步骤应使用 arm-linux-gnueabihf- 编译器。"""
        builder = _make_builder(tmp_path, arch="armhf")
        spec = _make_spec(system="cmake")
        cmds = builder._build_commands(spec, builder._config)
        configure_cmd = cmds[0]
        assert "-DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc" in configure_cmd
        assert "-DCMAKE_CXX_COMPILER=arm-linux-gnueabihf-g++" in configure_cmd

    def test_cmake选项展开为DKEY_VALUE格式(self, tmp_path):
        """build.options 中的键值对应展开为 -DKEY=VALUE 追加到 configure 步骤。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", options={"ENABLE_FOO": "ON", "LOG_LEVEL": "3"})
        cmds = builder._build_commands(spec, builder._config)
        configure_cmd = cmds[0]
        assert "-DENABLE_FOO=ON" in configure_cmd
        assert "-DLOG_LEVEL=3" in configure_cmd

    def test_cmake选项不影响build步骤(self, tmp_path):
        """build.options 应仅追加到 configure 步骤，不影响 cmake --build 步骤。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", options={"ENABLE_FOO": "ON"})
        cmds = builder._build_commands(spec, builder._config)
        build_cmd = cmds[1]
        assert not any("-DENABLE_FOO" in arg for arg in build_cmd)

    def test_cmake_sysroot注入(self, tmp_path):
        """当 build.deps 非空时，应向 configure 步骤注入 -DCMAKE_SYSROOT=<sysroot>。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", deps=["libfoo"])
        cmds = builder._build_commands(spec, builder._config)
        configure_cmd = cmds[0]
        sysroot_args = [arg for arg in configure_cmd if arg.startswith("-DCMAKE_SYSROOT=")]
        assert len(sysroot_args) == 1
        # 验证 sysroot 路径包含 board/product/variant/sysroot 结构
        sysroot_path = sysroot_args[0].split("=", 1)[1]
        assert "rk3566" in sysroot_path
        assert "default" in sysroot_path
        assert "release" in sysroot_path
        assert sysroot_path.endswith("sysroot")

    def test_cmake无deps不注入sysroot(self, tmp_path):
        """build.deps 为空时，configure 步骤不应包含 -DCMAKE_SYSROOT。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", deps=[])
        cmds = builder._build_commands(spec, builder._config)
        configure_cmd = cmds[0]
        assert not any(arg.startswith("-DCMAKE_SYSROOT=") for arg in configure_cmd)

    def test_cmake模板深拷贝不污染常量(self, tmp_path):
        """多次调用 _build_commands 不应修改 _BUILD_SYSTEMS 常量中的模板。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", options={"FOO": "bar"})
        original_len = len(_BUILD_SYSTEMS["cmake"][0])
        builder._build_commands(spec, builder._config)
        builder._build_commands(spec, builder._config)
        # 反复调用后，全局常量长度不变
        assert len(_BUILD_SYSTEMS["cmake"][0]) == original_len


# ---------------------------------------------------------------------------
# meson 命令生成
# ---------------------------------------------------------------------------

class TestMesonBuildCommands:
    """测试 meson 构建系统的命令生成。"""

    def test_基础meson命令包含两步(self, tmp_path):
        """meson 应生成 setup（meson）+ build（ninja）两步。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson")
        cmds = builder._build_commands(spec, builder._config)
        assert len(cmds) == 2

    def test_meson第一步为setup(self, tmp_path):
        """第一步命令应为 meson setup build。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson")
        cmds = builder._build_commands(spec, builder._config)
        assert cmds[0][0] == "meson"
        assert "setup" in cmds[0]
        assert "build" in cmds[0]

    def test_meson第二步为ninja(self, tmp_path):
        """第二步命令应为 ninja -C build。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson")
        cmds = builder._build_commands(spec, builder._config)
        assert cmds[1] == ["ninja", "-C", "build"]

    def test_meson选项展开为Dkey_value格式(self, tmp_path):
        """build.options 应展开为 -Dkey=value 追加到 setup 步骤。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson", options={"prefix": "/usr", "feature_foo": "enabled"})
        cmds = builder._build_commands(spec, builder._config)
        setup_cmd = cmds[0]
        assert "-Dprefix=/usr" in setup_cmd
        assert "-Dfeature_foo=enabled" in setup_cmd

    def test_meson选项不影响ninja步骤(self, tmp_path):
        """build.options 应仅追加到 setup 步骤，不影响 ninja 步骤。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson", options={"prefix": "/usr"})
        cmds = builder._build_commands(spec, builder._config)
        ninja_cmd = cmds[1]
        assert not any("-Dprefix" in arg for arg in ninja_cmd)


# ---------------------------------------------------------------------------
# make 命令生成
# ---------------------------------------------------------------------------

class TestMakeBuildCommands:
    """测试 make 构建系统的命令生成。"""

    def test_基础make命令包含一步(self, tmp_path):
        """make 应生成单步命令。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert len(cmds) == 1
        assert cmds[0][0] == "make"

    def test_make包含并行编译标志(self, tmp_path):
        """make 命令应包含 -j$(nproc) 并行编译标志。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert "-j$(nproc)" in cmds[0]

    def test_make包含ARCH参数(self, tmp_path):
        """make 命令应包含 ARCH=arm64。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert "ARCH=arm64" in cmds[0]

    def test_make注入aarch64交叉编译前缀(self, tmp_path):
        """aarch64 架构时，CROSS_COMPILE 应为 aarch64-linux-gnu-。"""
        builder = _make_builder(tmp_path, arch="aarch64")
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert "CROSS_COMPILE=aarch64-linux-gnu-" in cmds[0]

    def test_make注入armhf交叉编译前缀(self, tmp_path):
        """armhf 架构时，CROSS_COMPILE 应为 arm-linux-gnueabihf-。"""
        builder = _make_builder(tmp_path, arch="armhf")
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert "CROSS_COMPILE=arm-linux-gnueabihf-" in cmds[0]

    def test_make选项展开为KEY_VALUE格式(self, tmp_path):
        """build.options 应展开为 KEY=VALUE 追加到 make 命令。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make", options={"V": "1", "DEBUG": "y"})
        cmds = builder._build_commands(spec, builder._config)
        assert "V=1" in cmds[0]
        assert "DEBUG=y" in cmds[0]

    def test_make_sysroot注入CFLAGS_LDFLAGS(self, tmp_path):
        """当 build.deps 非空时，make 命令应包含 CFLAGS 和 LDFLAGS sysroot 参数。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make", deps=["libbase"])
        cmds = builder._build_commands(spec, builder._config)
        make_cmd = cmds[0]
        cflags_args = [arg for arg in make_cmd if arg.startswith("CFLAGS=")]
        ldflags_args = [arg for arg in make_cmd if arg.startswith("LDFLAGS=")]
        assert len(cflags_args) == 1
        assert len(ldflags_args) == 1
        assert "sysroot" in cflags_args[0]
        assert "sysroot" in ldflags_args[0]


# ---------------------------------------------------------------------------
# swift 命令生成
# ---------------------------------------------------------------------------

class TestSwiftBuildCommands:
    """测试 swift 构建系统的命令生成。"""

    def test_基础swift命令包含一步(self, tmp_path):
        """swift 应生成单步命令。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="swift")
        cmds = builder._build_commands(spec, builder._config)
        assert len(cmds) == 1
        assert cmds[0][0] == "swift"

    def test_swift包含build_release(self, tmp_path):
        """swift 命令应包含 build -c release。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="swift")
        cmds = builder._build_commands(spec, builder._config)
        cmd = cmds[0]
        assert "build" in cmd
        assert "-c" in cmd
        assert "release" in cmd

    def test_swift注入aarch64三元组(self, tmp_path):
        """aarch64 架构时，--triple 后应跟 aarch64-unknown-linux-gnu。"""
        builder = _make_builder(tmp_path, arch="aarch64")
        spec = _make_spec(system="swift")
        cmds = builder._build_commands(spec, builder._config)
        cmd = cmds[0]
        assert "--triple" in cmd
        triple_idx = cmd.index("--triple")
        assert cmd[triple_idx + 1] == "aarch64-unknown-linux-gnu"

    def test_swift注入armhf三元组(self, tmp_path):
        """armhf 架构时，--triple 后应跟 armv7-unknown-linux-gnueabihf。"""
        builder = _make_builder(tmp_path, arch="armhf")
        spec = _make_spec(system="swift")
        cmds = builder._build_commands(spec, builder._config)
        cmd = cmds[0]
        triple_idx = cmd.index("--triple")
        assert cmd[triple_idx + 1] == "armv7-unknown-linux-gnueabihf"

    def test_swift选项展开为双横线格式(self, tmp_path):
        """build.options 应展开为 --key value 追加到 swift 命令。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="swift", options={"jobs": "4", "verbose": ""})
        cmds = builder._build_commands(spec, builder._config)
        cmd = cmds[0]
        assert "--jobs" in cmd
        # jobs 有值，紧跟 "4"
        jobs_idx = cmd.index("--jobs")
        assert cmd[jobs_idx + 1] == "4"
        # verbose 无值，只追加 --verbose
        assert "--verbose" in cmd


# ---------------------------------------------------------------------------
# custom 命令直通
# ---------------------------------------------------------------------------

class TestCustomBuildCommands:
    """测试 custom 构建系统的命令直通行为。"""

    def test_custom直通spec_commands(self, tmp_path):
        """custom 系统应将 spec.build.commands 原样返回。"""
        custom_cmds = [
            ["./autogen.sh"],
            ["./configure", "--prefix=/usr"],
            ["make", "-j4"],
        ]
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="custom", commands=custom_cmds)
        cmds = builder._build_commands(spec, builder._config)
        assert cmds == custom_cmds

    def test_custom空commands返回空列表(self, tmp_path):
        """custom 系统且 spec.build.commands 为空时，应返回空列表。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="custom", commands=[])
        cmds = builder._build_commands(spec, builder._config)
        assert cmds == []

    def test_custom命令深拷贝不污染spec(self, tmp_path):
        """_build_commands 返回的命令列表是深拷贝，修改返回值不影响 spec.build.commands。"""
        custom_cmds = [["make", "-j4"]]
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="custom", commands=custom_cmds)
        cmds = builder._build_commands(spec, builder._config)
        # 修改返回的命令
        cmds[0].append("EXTRA_FLAG")
        # spec.build.commands 不应受影响
        assert spec.build.commands[0] == ["make", "-j4"]

    def test_custom不展开options(self, tmp_path):
        """custom 系统不处理 build.options，选项不会追加到命令中。"""
        custom_cmds = [["my-build-tool"]]
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="custom", commands=custom_cmds, options={"FOO": "bar"})
        cmds = builder._build_commands(spec, builder._config)
        # 仅返回原始命令，不含展开后的选项
        assert cmds == [["my-build-tool"]]


# ---------------------------------------------------------------------------
# _compile 执行流测试（验证 DockerRunner 调用）
# ---------------------------------------------------------------------------

class TestCompileExecution:
    """测试 _compile 方法的执行行为（通过 mock DockerRunner 捕获命令调用）。"""

    def _app_dir(self, tmp_path: Path, name: str = "myapp") -> Path:
        """创建最小 App 目录结构（含 app.yaml）供测试使用。"""
        app_dir = tmp_path / "app" / name
        app_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = (
            "app:\n"
            f"  name: {name}\n"
            "  version: 1.0.0\n"
            "  description: test\n"
            "  type: exec\n"
            "  arch: [aarch64]\n"
            "maintainer:\n"
            "  name: tester\n"
            "  email: t@t.com\n"
        )
        (app_dir / "app.yaml").write_text(yaml_content, encoding="utf-8")
        return app_dir

    def test_none系统不调用docker_run(self, tmp_path):
        """build.system=none 时，_compile 应提前返回，不调用 DockerRunner.run。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="none")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        # docker.run 不应被调用
        builder._docker.run.assert_not_called()

    def test_cmake系统调用两次docker_run(self, tmp_path):
        """cmake 构建系统应调用 DockerRunner.run 两次（configure + build）。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        assert builder._docker.run.call_count == 2

    def test_make系统调用一次docker_run(self, tmp_path):
        """make 构建系统应调用 DockerRunner.run 一次。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        assert builder._docker.run.call_count == 1

    def test_compile传递正确cwd(self, tmp_path):
        """docker.run 调用时，cwd 参数应为 app_dir 的字符串路径。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        # 验证每次 run 调用都传递了正确的 cwd
        for c in builder._docker.run.call_args_list:
            assert c.kwargs.get("cwd") == str(app_dir)

    def test_custom系统按spec_commands逐步调用docker(self, tmp_path):
        """custom 系统应按 spec.build.commands 顺序逐步调用 docker.run。"""
        custom_cmds = [
            ["./autogen.sh"],
            ["./configure", "--prefix=/usr"],
            ["make"],
        ]
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="custom", commands=custom_cmds)
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)

        assert builder._docker.run.call_count == 3
        calls = builder._docker.run.call_args_list
        assert calls[0] == call(["./autogen.sh"], cwd=str(app_dir))
        assert calls[1] == call(["./configure", "--prefix=/usr"], cwd=str(app_dir))
        assert calls[2] == call(["make"], cwd=str(app_dir))

    def test_meson系统调用两次docker_run(self, tmp_path):
        """meson 构建系统应调用 DockerRunner.run 两次（setup + ninja）。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        assert builder._docker.run.call_count == 2

    def test_swift系统调用一次docker_run(self, tmp_path):
        """swift 构建系统应调用 DockerRunner.run 一次。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="swift")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        assert builder._docker.run.call_count == 1

    def test_cmake第一次调用包含编译器标志(self, tmp_path):
        """cmake 的第一次 docker.run 调用（configure）应包含 CMAKE_C_COMPILER 标志。"""
        builder = _make_builder(tmp_path, arch="aarch64")
        spec = _make_spec(system="cmake")
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        first_call_cmd = builder._docker.run.call_args_list[0].args[0]
        assert any("CMAKE_C_COMPILER" in arg for arg in first_call_cmd)

    def test_cmake选项正确传递给docker(self, tmp_path):
        """cmake 带 options 时，docker.run 的 configure 步骤应包含展开后的 -D 参数。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake", options={"BUILD_TESTS": "OFF"})
        app_dir = self._app_dir(tmp_path)
        builder._compile(app_dir, spec, builder._config)
        first_call_cmd = builder._docker.run.call_args_list[0].args[0]
        assert "-DBUILD_TESTS=OFF" in first_call_cmd
