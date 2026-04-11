"""AppSpec 解析测试 — 覆盖 4 种 App 类型、字段校验、默认值填充、构建系统取值。"""

import tempfile
from pathlib import Path

import pytest

from builder.app_spec import (
    AppSpec,
    AppSpecError,
    BuildConfig,
    LibConfig,
    SystemdConfig,
    load_spec,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _write_yaml(tmpdir: str, content: str) -> Path:
    """在临时目录写入 app.yaml，返回目录 Path。"""
    app_dir = Path(tmpdir)
    (app_dir / "app.yaml").write_text(content, encoding="utf-8")
    return app_dir


# 最小合法 YAML（service 类型）
_MINIMAL_SERVICE = """\
app:
  name: my-service
  version: 1.0.0
  description: 测试服务
  type: service
  arch: [aarch64]

maintainer:
  name: flange
  email: flange@localhost
"""

# 最小合法 YAML（exec 类型）
_MINIMAL_EXEC = """\
app:
  name: my-exec
  version: 2.0.0
  description: 测试可执行文件
  type: exec
  arch:
    - aarch64
    - armhf

maintainer:
  name: tester
  email: test@example.com
"""

# 最小合法 YAML（lib 类型）
_MINIMAL_LIB = """\
app:
  name: libfoo
  version: 0.1.0
  description: 测试链接库
  type: lib
  arch: [aarch64]

maintainer:
  name: flange
  email: flange@localhost
"""

# 最小合法 YAML（test 类型）
_MINIMAL_TEST = """\
app:
  name: my-test
  version: 1.0.0
  description: 测试脚本
  type: test
  arch: [aarch64]

maintainer:
  name: flange
  email: flange@localhost
"""

# 完整字段 YAML（cmake 构建 + systemd + install 等）
_FULL_SERVICE = """\
app:
  name: my-daemon
  version: 1.0.0
  description: 示例守护进程
  type: service
  arch: [aarch64, armhf]

maintainer:
  name: flange
  email: flange@localhost

capabilities:
  - network
  - usb-gadget

build:
  system: cmake
  options:
    CMAKE_BUILD_TYPE: Release
  outputs:
    - bin/my-daemon
  deps:
    - libfoo
  commands: []

install:
  bin/my-daemon: /usr/bin/my-daemon
  conf/config.yaml: /etc/my-daemon/config.yaml

systemd:
  unit: systemd/my-daemon.service
  auto_start: true

depends:
  - libc6
  - libssl3

conffiles:
  - /etc/my-daemon/config.yaml

data_dirs:
  - /var/lib/my-daemon
"""

# lib 类型完整字段
_FULL_LIB = """\
app:
  name: libbar
  version: 2.0.0
  description: 示例动态库
  type: lib
  arch: [aarch64]

maintainer:
  name: flange
  email: flange@localhost

build:
  system: make
  outputs:
    - lib/libbar.so

lib:
  headers_dir: include/bar/
  dev_suffix: "-dev"
"""

# custom 构建系统
_CUSTOM_BUILD = """\
app:
  name: legacy-app
  version: 0.9.0
  description: 使用自定义构建脚本
  type: exec
  arch: [aarch64]

maintainer:
  name: flange
  email: flange@localhost

build:
  system: custom
  commands:
    - ["./configure", "--host=aarch64-linux-gnu"]
    - ["make", "-j4"]
  outputs:
    - bin/legacy-app
"""


# ---------------------------------------------------------------------------
# 测试：4 种 App 类型正常解析
# ---------------------------------------------------------------------------

class TestAppTypes:
    """验证 4 种 App 类型均可正常解析。"""

    def test_service_type_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.app.type == "service"
        assert spec.app.name == "my-service"
        assert spec.app.arch == ["aarch64"]

    def test_exec_type_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_EXEC))
        assert spec.app.type == "exec"
        assert spec.app.name == "my-exec"
        assert spec.app.arch == ["aarch64", "armhf"]

    def test_lib_type_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_LIB))
        assert spec.app.type == "lib"
        assert spec.app.name == "libfoo"

    def test_test_type_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_TEST))
        assert spec.app.type == "test"
        assert spec.app.name == "my-test"


# ---------------------------------------------------------------------------
# 测试：完整字段解析
# ---------------------------------------------------------------------------

class TestFullFieldParsing:
    """验证所有字段均可正确解析。"""

    def test_full_service_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _FULL_SERVICE))

        # app 段
        assert spec.app.name == "my-daemon"
        assert spec.app.version == "1.0.0"
        assert spec.app.description == "示例守护进程"
        assert spec.app.type == "service"
        assert spec.app.arch == ["aarch64", "armhf"]

        # maintainer 段
        assert spec.maintainer.name == "flange"
        assert spec.maintainer.email == "flange@localhost"

        # capabilities
        assert "network" in spec.capabilities
        assert "usb-gadget" in spec.capabilities

        # build 段
        assert spec.build.system == "cmake"
        assert spec.build.options == {"CMAKE_BUILD_TYPE": "Release"}
        assert spec.build.outputs == ["bin/my-daemon"]
        assert spec.build.deps == ["libfoo"]

        # install 映射
        assert spec.install["bin/my-daemon"] == "/usr/bin/my-daemon"
        assert spec.install["conf/config.yaml"] == "/etc/my-daemon/config.yaml"

        # systemd 段
        assert spec.systemd is not None
        assert spec.systemd.unit == "systemd/my-daemon.service"
        assert spec.systemd.auto_start is True

        # depends / conffiles / data_dirs
        assert "libc6" in spec.depends
        assert "/etc/my-daemon/config.yaml" in spec.conffiles
        assert "/var/lib/my-daemon" in spec.data_dirs

    def test_full_lib_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _FULL_LIB))
        assert spec.app.type == "lib"
        assert spec.build.system == "make"
        assert spec.lib is not None
        assert spec.lib.headers_dir == "include/bar/"
        assert spec.lib.dev_suffix == "-dev"

    def test_custom_build_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _CUSTOM_BUILD))
        assert spec.build.system == "custom"
        assert spec.build.commands[0] == ["./configure", "--host=aarch64-linux-gnu"]
        assert spec.build.commands[1] == ["make", "-j4"]


# ---------------------------------------------------------------------------
# 测试：默认值填充
# ---------------------------------------------------------------------------

class TestDefaultValues:
    """验证可选字段的默认值填充正确。"""

    def test_build_system_defaults_to_none(self):
        """未指定 build 段时，build.system 默认为 none。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.build.system == "none"

    def test_build_options_defaults_to_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.build.options == {}

    def test_build_outputs_defaults_to_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.build.outputs == []

    def test_capabilities_defaults_to_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.capabilities == []

    def test_install_defaults_to_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.install == {}

    def test_systemd_defaults_to_none(self):
        """未指定 systemd 段时，systemd 为 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.systemd is None

    def test_auto_start_defaults_to_false(self):
        """systemd 段存在但未指定 auto_start 时，默认为 False。"""
        yaml_content = _MINIMAL_SERVICE + "\nsystemd:\n  unit: systemd/my.service\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, yaml_content))
        assert spec.systemd is not None
        assert spec.systemd.auto_start is False

    def test_lib_defaults_to_none_for_non_lib_type(self):
        """非 lib 类型不指定 lib 段时，lib 为 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.lib is None

    def test_lib_config_default_values(self):
        """lib 段存在但字段为空时，填充默认值。"""
        yaml_content = _MINIMAL_LIB + "\nlib: {}\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, yaml_content))
        assert spec.lib is not None
        assert spec.lib.headers_dir == "include/"
        assert spec.lib.dev_suffix == "-dev"

    def test_depends_defaults_to_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.depends == []

    def test_conffiles_defaults_to_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.conffiles == []

    def test_data_dirs_defaults_to_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, _MINIMAL_SERVICE))
        assert spec.data_dirs == []


# ---------------------------------------------------------------------------
# 测试：缺失必填字段时报错
# ---------------------------------------------------------------------------

class TestRequiredFieldValidation:
    """验证缺失必填字段时抛出 AppSpecError。"""

    def test_missing_app_section(self):
        yaml_content = "maintainer:\n  name: flange\n  email: a@b.com\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_maintainer_section(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n"
            "  description: desc\n  type: exec\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="maintainer"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_app_name(self):
        yaml_content = (
            "app:\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app.name"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_app_version(self):
        yaml_content = (
            "app:\n  name: foo\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app.version"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_app_description(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app.description"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_app_type(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app.type"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_maintainer_name(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="maintainer.name"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_missing_maintainer_email(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="maintainer.email"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_app_yaml_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                load_spec(Path(tmpdir))

    def test_invalid_yaml_syntax(self):
        yaml_content = "app:\n  name: foo\n  broken: [unclosed"
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="YAML 解析失败"):
                load_spec(_write_yaml(tmpdir, yaml_content))


# ---------------------------------------------------------------------------
# 测试：app.type 非法值报错
# ---------------------------------------------------------------------------

class TestAppTypeValidation:
    """验证 app.type 非法值时抛出 AppSpecError。"""

    def test_invalid_type_rejected(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: daemon\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="app.type"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    @pytest.mark.parametrize("app_type", ["exec", "service", "lib", "test"])
    def test_all_valid_types_accepted(self, app_type):
        yaml_content = (
            f"app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: {app_type}\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, yaml_content))
        assert spec.app.type == app_type


# ---------------------------------------------------------------------------
# 测试：build.system 各取值验证
# ---------------------------------------------------------------------------

class TestBuildSystemValues:
    """验证 build.system 所有合法取值均被接受，非法值被拒绝。"""

    @pytest.mark.parametrize("system", ["none", "cmake", "meson", "make", "swift", "custom"])
    def test_valid_build_system(self, system):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
            f"build:\n  system: {system}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, yaml_content))
        assert spec.build.system == system

    def test_invalid_build_system_rejected(self):
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
            "build:\n  system: autotools\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AppSpecError, match="build.system"):
                load_spec(_write_yaml(tmpdir, yaml_content))

    def test_build_system_none_is_default(self):
        """未指定 build.system 时默认为 none。"""
        yaml_content = (
            "app:\n  name: foo\n  version: 1.0.0\n  description: desc\n  type: exec\n"
            "maintainer:\n  name: flange\n  email: a@b.com\n"
            "build:\n  outputs: [bin/foo]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = load_spec(_write_yaml(tmpdir, yaml_content))
        assert spec.build.system == "none"


# ---------------------------------------------------------------------------
# 测试：真实 adbd app.yaml 解析
# ---------------------------------------------------------------------------

class TestAdbdAppYaml:
    """验证 app/adbd/app.yaml 可被正确解析（集成测试）。"""

    def test_adbd_spec_loads(self):
        # 从真实路径加载（相对于项目根目录）
        project_root = Path(__file__).parent.parent.parent
        adbd_dir = project_root / "app" / "adbd"
        if not (adbd_dir / "app.yaml").exists():
            pytest.skip("app/adbd/app.yaml 不存在，跳过集成测试")

        spec = load_spec(adbd_dir)
        assert spec.app.name == "adbd"
        assert spec.app.type == "service"
        assert "aarch64" in spec.app.arch
        assert spec.maintainer.email == "flange@localhost"

    def test_adbd_has_install_section(self):
        """adbd app.yaml 应包含 install 安装映射。"""
        project_root = Path(__file__).parent.parent.parent
        adbd_dir = project_root / "app" / "adbd"
        if not (adbd_dir / "app.yaml").exists():
            pytest.skip("app/adbd/app.yaml 不存在，跳过集成测试")

        spec = load_spec(adbd_dir)
        assert spec.install, "adbd 应定义 install 映射"

    def test_adbd_has_systemd_section(self):
        """adbd app.yaml 应包含 systemd 配置。"""
        project_root = Path(__file__).parent.parent.parent
        adbd_dir = project_root / "app" / "adbd"
        if not (adbd_dir / "app.yaml").exists():
            pytest.skip("app/adbd/app.yaml 不存在，跳过集成测试")

        spec = load_spec(adbd_dir)
        assert spec.systemd is not None
        assert spec.systemd.auto_start is True
