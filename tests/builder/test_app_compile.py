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

import io
import os
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from builder.app import AppBuilder, _BUILD_SYSTEMS, _CROSS_COMPILE_PREFIX
from builder.app_spec import AppSpec, AppInfo, BuildConfig, MaintainerInfo
from builder.docker import BuildError


# ---------------------------------------------------------------------------
# 测试辅助：构造最小 AppSpec
# ---------------------------------------------------------------------------

def _make_spec(
    name: str = "testapp",
    system: str = "cmake",
    options: dict | None = None,
    deps: list[str] | None = None,
    apt_packages: list[str] | None = None,
    commands: list[list[str]] | None = None,
    app_type: str = "exec",
) -> AppSpec:
    """构造用于测试的最小 AppSpec 对象。

    参数：
        name:     App 名称
        system:   构建系统（cmake/meson/make/swift/custom/none）
        options:  build.options 字典
        deps:     build.deps 列表
        apt_packages: 当前构建容器内安装的 APT 编译依赖
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
            apt_packages=apt_packages or [],
            commands=commands or [],
        ),
    )


def _make_builder(
    tmp_path: Path,
    arch: str = "aarch64",
    variant: str = "release",
) -> AppBuilder:
    """构造使用 tmp_path 作为项目根目录的 AppBuilder。

    DockerRunner 使用 MagicMock，以便捕获 run() 调用参数。
    """
    config = {
        "board":   "rk3566",
        "product": "default",
        "variant": variant,
        "architecture": {"userspace": arch, "kernel": "arm64", "bootloader": "arm64"},
        "rootfs":  {"custom_packages": []},
    }
    docker = MagicMock()
    docker.run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr="",
    )
    source = MagicMock()
    return AppBuilder(docker, source, config, project_dir=tmp_path)


def _deb_data_names(deb_path: Path) -> list[str]:
    """读取 deb 的 data.tar.gz 成员名，不依赖宿主机 dpkg 工具。"""
    data = deb_path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        raise ValueError(f"不是有效的 deb：{deb_path}")

    position = 8
    while position + 60 <= len(data):
        header = data[position:position + 60]
        name = header[:16].rstrip().decode("ascii")
        size = int(header[48:58].rstrip())
        position += 60
        payload = data[position:position + size]
        if name == "data.tar.gz":
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                return archive.getnames()
        position += size + (size % 2)
    raise ValueError(f"deb 缺少 data.tar.gz：{deb_path}")


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
        assert cmds[1] == [
            "cmake", "--build", "build", f"-j{os.cpu_count() or 1}"
        ]

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

    @pytest.mark.parametrize(
        ("variant", "build_type"),
        [("debug", "Debug"), ("release", "Release")],
    )
    def test_cmake构建类型跟随variant(self, tmp_path, variant, build_type):
        builder = _make_builder(tmp_path, variant=variant)
        commands = builder._build_commands(
            _make_spec(system="cmake"), builder._config,
        )

        assert f"-DCMAKE_BUILD_TYPE={build_type}" in commands[0]
        assert "-DCMAKE_INSTALL_PREFIX=/usr" in commands[0]

    def test_cmake显式选项覆盖variant默认值(self, tmp_path):
        builder = _make_builder(tmp_path, variant="debug")
        commands = builder._build_commands(
            _make_spec(
                system="cmake",
                options={"CMAKE_BUILD_TYPE": "RelWithDebInfo"},
            ),
            builder._config,
        )

        assert "-DCMAKE_BUILD_TYPE=RelWithDebInfo" in commands[0]
        assert "-DCMAKE_BUILD_TYPE=Debug" not in commands[0]


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

    @pytest.mark.parametrize("variant", ["debug", "release"])
    def test_meson构建类型跟随variant(self, tmp_path, variant):
        builder = _make_builder(tmp_path, variant=variant)
        commands = builder._build_commands(
            _make_spec(system="meson"), builder._config,
        )

        assert f"--buildtype={variant}" in commands[0]
        assert "--prefix=/usr" in commands[0]


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
        """make 命令应包含解析为实际 CPU 数的并行编译标志。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        cmds = builder._build_commands(spec, builder._config)
        assert f"-j{os.cpu_count() or 1}" in cmds[0]

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

    @pytest.mark.parametrize(
        ("variant", "flags"),
        [("debug", "-Wall -O0 -g"), ("release", "-Wall -O2")],
    )
    def test_make编译标志与sysroot同时保留(self, tmp_path, variant, flags):
        builder = _make_builder(tmp_path, variant=variant)
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        builder._compile(
            app_dir,
            _make_spec(system="make", deps=["libbase"]),
            builder._config,
        )

        build_call = builder._docker.run.call_args_list[0]
        cflags = next(
            arg for arg in build_call.args[0] if arg.startswith("CFLAGS=")
        )
        assert flags in cflags
        assert "sysroot" in cflags
        assert "CFLAGS" not in build_call.kwargs["env"]

    def test_make显式CFLAGS保持命令行优先(self, tmp_path):
        builder = _make_builder(tmp_path, variant="debug")
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        builder._compile(
            app_dir,
            _make_spec(system="make", options={"CFLAGS": "-Os -pipe"}),
            builder._config,
        )

        build_call = builder._docker.run.call_args_list[0]
        assert "CFLAGS=-Os -pipe" in build_call.args[0]
        assert "CFLAGS" not in build_call.kwargs["env"]


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

    @pytest.mark.parametrize("variant", ["debug", "release"])
    def test_swift_configuration跟随variant(self, tmp_path, variant):
        builder = _make_builder(tmp_path, variant=variant)
        command = builder._build_commands(
            _make_spec(system="swift"), builder._config,
        )[0]

        assert command[command.index("-c") + 1] == variant

    def test_swift显式configuration覆盖variant默认值(self, tmp_path):
        builder = _make_builder(tmp_path, variant="debug")
        command = builder._build_commands(
            _make_spec(
                system="swift",
                options={"configuration": "release"},
            ),
            builder._config,
        )[0]

        assert command[command.index("-c") + 1] == "release"


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

    def test_cmake系统调用原生install(self, tmp_path):
        """CMake 应执行 configure、build 和 install。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="cmake")
        app_dir = self._app_dir(tmp_path)
        install_dir = builder._compile(app_dir, spec, builder._config)

        assert builder._docker.run.call_count == 3
        install_call = builder._docker.run.call_args_list[-1]
        assert install_call.args[0] == ["cmake", "--install", "build"]
        assert install_call.kwargs["env"]["DESTDIR"] == str(install_dir)

    def test_make系统调用原生install(self, tmp_path):
        """Make 应在编译后传递同组变量执行 install。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        app_dir = self._app_dir(tmp_path)
        install_dir = builder._compile(app_dir, spec, builder._config)

        assert builder._docker.run.call_count == 3
        probe_call = builder._docker.run.call_args_list[-2]
        assert probe_call.args[0][:3] == ["make", "-n", "install"]
        assert probe_call.kwargs["check"] is False
        assert probe_call.kwargs["capture"] is True
        install_call = builder._docker.run.call_args_list[-1]
        assert install_call.args[0][:2] == ["make", "install"]
        assert install_call.kwargs["env"]["DESTDIR"] == str(install_dir)
        assert install_call.args[0][-1] == f"DESTDIR={install_dir}"

    def test_make无install_target回退约定文件收集(self, tmp_path):
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="make")
        app_dir = self._app_dir(tmp_path)
        executable = app_dir / "bin/testapp"
        executable.parent.mkdir()
        executable.write_bytes(b"\x7fELF")
        builder._docker.run.side_effect = [
            subprocess.CompletedProcess(["make"], 0, "", ""),
            subprocess.CompletedProcess(
                ["make", "-n", "install"],
                2,
                "",
                "make: *** No rule to make target 'install'. Stop.\n",
            ),
        ]

        install_dir = builder._compile(app_dir, spec, builder._config)
        files = builder._collect_package_files(app_dir, spec, install_dir)

        assert install_dir is None
        assert not builder._native_install_dir(spec).exists()
        assert any(
            source == executable and destination == "/usr/bin/testapp"
            for source, destination, _mode in files
        )

    @pytest.mark.parametrize(
        "probe_error",
        [
            "make: *** No rule to make target 'generated.h', "
            "needed by 'install'. Stop.\n",
            "make[1]: *** No rule to make target 'install'. Stop.\n",
        ],
    )
    def test_make_install_target前置错误不回退(self, tmp_path, probe_error):
        builder = _make_builder(tmp_path)
        app_dir = self._app_dir(tmp_path)
        builder._docker.run.side_effect = [
            subprocess.CompletedProcess(["make"], 0, "", ""),
            subprocess.CompletedProcess(
                ["make", "-n", "install"],
                2,
                "",
                probe_error,
            ),
        ]

        with pytest.raises(BuildError, match="Make install target 检查失败"):
            builder._compile(
                app_dir, _make_spec(system="make"), builder._config,
            )

    def test_make_install_target执行失败保持报错(self, tmp_path):
        builder = _make_builder(tmp_path)
        app_dir = self._app_dir(tmp_path)
        builder._docker.run.side_effect = [
            subprocess.CompletedProcess(["make"], 0, "", ""),
            subprocess.CompletedProcess(
                ["make", "-n", "install"], 0, "install command\n", "",
            ),
            BuildError("install failed"),
        ]

        with pytest.raises(BuildError, match="install failed"):
            builder._compile(
                app_dir, _make_spec(system="make"), builder._config,
            )

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
        assert [item.args[0] for item in calls] == custom_cmds
        # 仓库内 App，_compile 不应注入 extra_mounts（None）
        assert all(item.kwargs["cwd"] == str(app_dir) for item in calls)
        assert all(item.kwargs["extra_mounts"] is None for item in calls)

    def test_meson系统调用原生install(self, tmp_path):
        """Meson 应执行 setup、ninja 和 install。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="meson")
        app_dir = self._app_dir(tmp_path)
        install_dir = builder._compile(app_dir, spec, builder._config)

        assert builder._docker.run.call_count == 3
        install_call = builder._docker.run.call_args_list[-1]
        assert install_call.args[0] == ["meson", "install", "-C", "build"]
        assert install_call.kwargs["env"]["DESTDIR"] == str(install_dir)

    def test_swift系统复制已知executable(self, tmp_path):
        """Swift 应把当前 configuration 的 executable 复制到 staging。"""
        builder = _make_builder(tmp_path)
        spec = _make_spec(system="swift")
        app_dir = self._app_dir(tmp_path)
        install_dir = builder._compile(app_dir, spec, builder._config)

        assert builder._docker.run.call_count == 2
        install_call = builder._docker.run.call_args_list[-1]
        assert install_call.args[0] == [
            "install",
            "-Dm755",
            ".build/aarch64-unknown-linux-gnu/release/testapp",
            str(install_dir / "usr/bin/testapp"),
        ]

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

    def test_apt构建依赖在编译前按目标架构安装(self, tmp_path):
        """apt_packages 应先更新索引、安装，再执行 CMake。"""
        builder = _make_builder(tmp_path, arch="armhf")
        spec = _make_spec(
            system="cmake",
            apt_packages=["libasound2-dev:{arch}", "zlib1g-dev"],
        )
        app_dir = self._app_dir(tmp_path)

        builder._compile(app_dir, spec, builder._config)

        calls = builder._docker.run.call_args_list
        assert calls[0].args[0] == ["apt-get", "update"]
        assert calls[1].args[0] == [
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "-o",
            "Dir::Cache::archives=/cache/apt",
            "libasound2-dev:armhf",
            "zlib1g-dev",
        ]
        assert calls[2].args[0][0] == "cmake"

    def test_apt构建依赖把aarch64映射为Debian的arm64(self, tmp_path):
        builder = _make_builder(tmp_path, arch="aarch64")
        spec = _make_spec(
            system="custom",
            commands=[["true"]],
            apt_packages=["libasound2-dev:{arch}"],
        )

        builder._compile(self._app_dir(tmp_path), spec, builder._config)

        assert builder._docker.run.call_args_list[1].args[0][-1] == (
            "libasound2-dev:arm64"
        )

    def test_apt索引与已安装依赖在同次构建中复用(self, tmp_path):
        """同一 AppBuilder 重复遇到相同包时不应再次调用 APT。"""
        builder = _make_builder(tmp_path, arch="armhf")
        spec = _make_spec(
            system="make",
            apt_packages=["libasound2-dev:{arch}"],
        )
        app_dir = self._app_dir(tmp_path)

        builder._compile(app_dir, spec, builder._config)
        builder._compile(app_dir, spec, builder._config)

        commands = [item.args[0] for item in builder._docker.run.call_args_list]
        assert commands.count(["apt-get", "update"]) == 1
        apt_installs = [
            command for command in commands
            if command[:2] == ["apt-get", "install"]
        ]
        assert len(apt_installs) == 1


class TestInstallStagingPackaging:
    """验证原生 install staging 与现有安装映射的合并语义。"""

    def test_显式install映射优先于staging同路径(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        explicit = app_dir / "manual"
        explicit.write_bytes(b"manual")
        install_dir = tmp_path / "install"
        staged = install_dir / "usr/bin/testapp"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"staged")
        extra = install_dir / "usr/share/testapp/data"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"data")

        spec = _make_spec(system="cmake")
        spec.install = {"manual": "/usr/bin/testapp"}
        files = _make_builder(tmp_path)._collect_package_files(
            app_dir, spec, install_dir,
        )
        by_destination = {destination: source for source, destination, _ in files}

        assert by_destination["/usr/bin/testapp"] == explicit
        assert by_destination["/usr/share/testapp/data"] == extra

    def test_lib缓存命中复用install_staging恢复sysroot(self, tmp_path):
        app_dir = tmp_path / "components/app/libfoo"
        app_dir.mkdir(parents=True)
        (app_dir / "app.yaml").write_text(
            """\
app:
  name: foo
  version: 1.0.0
  description: 测试库
  type: lib
  arch: [aarch64]
maintainer:
  name: tester
  email: test@localhost
build:
  system: cmake
""",
            encoding="utf-8",
        )
        install_dir = (
            tmp_path
            / ".build/work/apps/foo/aarch64"
            / "rk3566/default/release/install"
        )
        header = install_dir / "usr/include/foo/foo.h"
        header.parent.mkdir(parents=True)
        header.write_text("#pragma once\n", encoding="utf-8")
        library = install_dir / "usr/lib/libfoo.so.1"
        library.parent.mkdir(parents=True)
        library.write_bytes(b"\x7fELF staged library")

        builder = _make_builder(tmp_path)
        builder.cache = MagicMock()
        builder.cache.is_app_up_to_date.return_value = True
        builder.cache._registered_app_source_dir.return_value = app_dir

        assert builder._reuse_app("foo") is True
        sysroot = (
            tmp_path
            / ".build/target/rk3566/default/release/sysroot/usr"
        )
        assert (sysroot / "include/foo/foo.h").read_text(
            encoding="utf-8",
        ) == "#pragma once\n"
        assert (sysroot / "lib/libfoo.so.1").read_bytes() == (
            b"\x7fELF staged library"
        )

    def test_native_install_staging_is_target_specific(self, tmp_path):
        spec = _make_spec(name="foo", system="cmake", app_type="lib")
        release = _make_builder(tmp_path, variant="release")
        debug = _make_builder(tmp_path, variant="debug")

        assert release._native_install_dir(spec) != debug._native_install_dir(spec)

    def test_lib_pkg_config_enters_dev_deb_and_sysroot(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        install_dir = tmp_path / "install"
        metadata = install_dir / "usr/lib/pkgconfig/foo.pc"
        metadata.parent.mkdir(parents=True)
        metadata.write_text("Name: foo\nVersion: 1.0.0\n", encoding="utf-8")
        library = install_dir / "usr/lib/libfoo.so.1"
        library.write_bytes(b"\x7fELF")
        spec = _make_spec(name="foo", system="meson", app_type="lib")
        builder = _make_builder(tmp_path)

        outputs = builder._build_lib(app_dir, spec, install_dir)

        assert "./usr/lib/pkgconfig/foo.pc" in _deb_data_names(outputs["dev"])
        sysroot_pc = (
            tmp_path
            / ".build/target/rk3566/default/release/sysroot"
            / "usr/lib/pkgconfig/foo.pc"
        )
        assert sysroot_pc.read_text(encoding="utf-8").startswith("Name: foo")

    def test_默认cmake_scaffold_deb包含executable(self, tmp_path):
        from builder.scaffold import AppScaffold
        from builder.source import SourceManager

        class CmakeInstallDocker:
            """模拟 CMake 执行 install 规则后写入 DESTDIR。"""

            def run(self, cmd, *, env=None, **_kwargs):
                if cmd == ["cmake", "--install", "build"]:
                    cmake = Path(_kwargs["cwd"]) / "CMakeLists.txt"
                    assert "install(TARGETS hello DESTINATION bin)" in (
                        cmake.read_text(encoding="utf-8")
                    )
                    executable = Path(env["DESTDIR"]) / "usr/bin/hello"
                    executable.parent.mkdir(parents=True)
                    executable.write_bytes(b"\x7fELF scaffold")
                    executable.chmod(0o755)

        AppScaffold(project_root=tmp_path).create(
            "hello", "exec", "cmake",
        )
        config = {
            "board": "test-board",
            "product": "default",
            "variant": "release",
            "architecture": {
                "userspace": "aarch64",
                "kernel": "arm64",
                "bootloader": "arm64",
            },
            "rootfs": {"custom_packages": []},
        }
        source = SourceManager(project_root=tmp_path)
        builder = AppBuilder(
            CmakeInstallDocker(), source, config, project_dir=tmp_path,
        )

        deb_path = builder.build_one("hello")

        assert "./usr/bin/hello" in _deb_data_names(deb_path)
