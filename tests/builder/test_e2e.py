"""端到端验证测试（Task 13）

覆盖场景：
13.1 adbd 真实 App 端到端打包验证：
    - 使用真实 app/adbd/ 目录构建 .deb（若目录不存在则跳过）
    - 验证 .deb 文件名格式
    - 验证 control 文件字段（Package / Version / Architecture / Depends）
    - 验证 data.tar.gz 文件列表（完整安装路径）
    - 验证 postinst 脚本包含 chroot 兼容的 systemd enable 逻辑
    - 验证文件权限（/usr/bin/adbd 0o755，/etc/usbdevice.conf 0o644）

13.2 构建引擎 App 集成验证：
    - engine.build("rootfs") 时拓扑排序包含 app → rootfs 顺序
    - engine.build("app") 触发 AppBuilder.build_all() 调用
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from builder.app import AppBuilder
from builder.engine import DEPENDENCY_GRAPH, BuildEngine, _topo_sort


# ---------------------------------------------------------------------------
# 辅助工具：纯 Python ar 归档读取器（复用 test_deb.py 中的实现）
# ---------------------------------------------------------------------------

def _read_ar_members(deb_path: Path) -> Dict[str, bytes]:
    """从 .deb 文件（ar 格式）读取所有成员，返回 {成员名: 数据} 字典。

    只支持标准 POSIX ar 格式，与 .deb 规范一致。
    """
    data = deb_path.read_bytes()
    magic = b"!<arch>\n"
    if not data.startswith(magic):
        raise ValueError(f"不是有效的 ar 归档：{deb_path}")

    members: Dict[str, bytes] = {}
    pos = len(magic)
    while pos < len(data):
        if pos + 60 > len(data):
            break
        # 解析 60 字节成员头
        header = data[pos: pos + 60]
        name = header[0:16].rstrip().decode("ascii")
        size = int(header[48:58].rstrip())
        end_mag = header[58:60]
        assert end_mag == b"\x60\x0a", f"ar 成员头 magic 错误：{end_mag!r}"

        pos += 60
        member_data = data[pos: pos + size]
        members[name] = member_data
        # 成员数据按 2 字节对齐
        pos += size + (size % 2)

    return members


def _read_tar_names(tar_data: bytes) -> list[str]:
    """从 tar.gz 字节读取所有成员名称列表。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        return tf.getnames()


def _read_tar_member(tar_data: bytes, name: str) -> bytes:
    """从 tar.gz 字节中提取指定成员的内容。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        member = tf.getmember(name)
        f = tf.extractfile(member)
        return f.read() if f else b""


def _get_tar_info(tar_data: bytes, name: str) -> tarfile.TarInfo:
    """从 tar.gz 字节中获取指定成员的 TarInfo（含权限等元数据）。"""
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tf:
        return tf.getmember(name)


# ---------------------------------------------------------------------------
# 辅助：项目根目录 / adbd 目录探测
# ---------------------------------------------------------------------------

# 本测试文件位于 tests/builder/，项目根为上两级目录
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ADBD_DIR = _PROJECT_ROOT / "app" / "adbd"

# adbd 目录缺失时跳过所有 13.1 测试（兼容 CI 精简环境）
_ADBD_EXISTS = _ADBD_DIR.is_dir() and (_ADBD_DIR / "app.yaml").is_file()
_SKIP_IF_NO_ADBD = pytest.mark.skipif(
    not _ADBD_EXISTS,
    reason=f"adbd App 目录不存在：{_ADBD_DIR}，跳过端到端测试",
)


# ---------------------------------------------------------------------------
# 辅助：构建 adbd .deb（供多个测试用例复用）
# ---------------------------------------------------------------------------

def _build_adbd_deb(output_dir: Path) -> Path:
    """使用真实 app/adbd/ 构建 adbd .deb 到指定目录，返回 .deb 路径。

    DockerRunner 与 SourceManager 均使用 MagicMock——adbd 为预编译 App
    （build.system=none），不需要 Docker 编译步骤。
    """
    config = {
        "board":   "radxa-zero3w",
        "product": "default",
        "variant": "release",
        "arch":    "aarch64",
        "rootfs":  {"custom_packages": ["adbd"]},
    }
    builder = AppBuilder(
        docker=MagicMock(),
        source=MagicMock(),
        config=config,
        project_dir=_PROJECT_ROOT,
    )
    # 将输出目录临时重写为 tmp_path 下的子目录，不污染 target/
    builder._output_dir = output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    return builder.build_one("adbd")


# ---------------------------------------------------------------------------
# Task 13.1：adbd 端到端打包验证
# ---------------------------------------------------------------------------

@_SKIP_IF_NO_ADBD
class TestAdbdEndToEnd:
    """13.1 — 使用真实 app/adbd/ 构建 .deb 并验证内容。

    测试通过 AppBuilder.build_one("adbd") 产出 adbd_1.0.0_arm64.deb，
    随后解包验证 control 字段、data.tar.gz 文件树和 postinst 脚本。
    """

    @pytest.fixture(scope="class")
    def deb_path(self, tmp_path_factory):
        """Class-scoped fixture：只构建一次 .deb，所有测试复用。"""
        out = tmp_path_factory.mktemp("adbd_deb")
        return _build_adbd_deb(out)

    @pytest.fixture(scope="class")
    def ar_members(self, deb_path):
        """解析 .deb ar 成员，供内容验证复用。"""
        return _read_ar_members(deb_path)

    @pytest.fixture(scope="class")
    def control_text(self, ar_members):
        """提取 control 文件文本内容。"""
        tar_data = ar_members["control.tar.gz"]
        return _read_tar_member(tar_data, "./control").decode("utf-8")

    @pytest.fixture(scope="class")
    def data_names(self, ar_members):
        """提取 data.tar.gz 中所有成员名称列表。"""
        return _read_tar_names(ar_members["data.tar.gz"])

    @pytest.fixture(scope="class")
    def postinst_text(self, ar_members):
        """提取 postinst 脚本内容。"""
        tar_data = ar_members["control.tar.gz"]
        return _read_tar_member(tar_data, "./postinst").decode("utf-8")

    # -------------------------------------------------------------------
    # .deb 文件存在性与文件名格式
    # -------------------------------------------------------------------

    def test_deb文件存在(self, deb_path):
        """.deb 文件应真实存在于临时目录中。"""
        assert deb_path.exists(), f".deb 文件不存在：{deb_path}"
        assert deb_path.is_file()

    def test_deb文件名格式(self, deb_path):
        """文件名应为 adbd_1.0.0_arm64.deb（Package_Version_Arch.deb）。"""
        assert deb_path.name == "adbd_1.0.0_arm64.deb", (
            f"文件名格式不符：{deb_path.name}"
        )

    def test_deb_ar_magic(self, deb_path):
        """.deb 文件以标准 ar magic 开头（!<arch>\\n）。"""
        raw = deb_path.read_bytes()
        assert raw[:8] == b"!<arch>\n"

    def test_deb包含三个ar成员(self, ar_members):
        """ar 归档必须包含 debian-binary、control.tar.gz、data.tar.gz。"""
        assert "debian-binary" in ar_members
        assert "control.tar.gz" in ar_members
        assert "data.tar.gz" in ar_members

    def test_debian_binary内容(self, ar_members):
        """debian-binary 内容必须是 "2.0\\n"。"""
        assert ar_members["debian-binary"] == b"2.0\n"

    # -------------------------------------------------------------------
    # control 文件字段验证
    # -------------------------------------------------------------------

    def test_control_Package字段(self, control_text):
        """control 文件必须包含正确的 Package 字段。"""
        assert "Package: adbd" in control_text

    def test_control_Version字段(self, control_text):
        """control 文件必须包含正确的 Version 字段。"""
        assert "Version: 1.0.0" in control_text

    def test_control_Architecture字段(self, control_text):
        """aarch64 目标架构应映射为 arm64 写入 control。"""
        assert "Architecture: arm64" in control_text

    def test_control_Depends字段(self, control_text):
        """adbd app.yaml 中声明了 libc6 依赖，control 必须包含 Depends 字段。"""
        assert "Depends: libc6" in control_text

    def test_control_Maintainer字段(self, control_text):
        """control 文件必须包含 Maintainer 字段。"""
        assert "Maintainer:" in control_text

    def test_control_Description字段(self, control_text):
        """control 文件必须包含 Description 字段。"""
        assert "Description:" in control_text

    # -------------------------------------------------------------------
    # data.tar.gz 文件树验证
    # -------------------------------------------------------------------

    def test_data包含adbd二进制(self, data_names):
        """data.tar.gz 应包含 ./usr/bin/adbd（来自 bin/adbd-arm64，架构后缀剥离）。"""
        assert "./usr/bin/adbd" in data_names, (
            f"./usr/bin/adbd 不在 data.tar.gz 中，现有文件：{data_names}"
        )

    def test_data包含usbdevice_conf(self, data_names):
        """data.tar.gz 应包含 ./etc/usbdevice.conf（来自 install 段显式映射）。"""
        assert "./etc/usbdevice.conf" in data_names, (
            f"./etc/usbdevice.conf 不在 data.tar.gz 中，现有文件：{data_names}"
        )

    def test_data包含usbdevice_script(self, data_names):
        """data.tar.gz 应包含 ./usr/sbin/usbdevice（来自 install 段显式映射）。"""
        assert "./usr/sbin/usbdevice" in data_names, (
            f"./usr/sbin/usbdevice 不在 data.tar.gz 中，现有文件：{data_names}"
        )

    def test_data包含systemd_service(self, data_names):
        """data.tar.gz 应包含 usbdevice.service（来自 systemd/ 约定目录）。"""
        assert "./lib/systemd/system/usbdevice.service" in data_names, (
            f"./lib/systemd/system/usbdevice.service 不在 data.tar.gz 中，"
            f"现有文件：{data_names}"
        )

    def test_data包含udev_rules(self, data_names):
        """data.tar.gz 应包含 61-usbdevice.rules（install 段显式映射到 /etc/udev/rules.d/）。

        注意：app.yaml 的 install 段将 udev/61-usbdevice.rules 显式映射到
        /etc/udev/rules.d/，覆盖了约定目录 /lib/udev/rules.d/ 的默认路径。
        """
        assert "./etc/udev/rules.d/61-usbdevice.rules" in data_names, (
            f"./etc/udev/rules.d/61-usbdevice.rules 不在 data.tar.gz 中，"
            f"现有文件：{data_names}"
        )

    # -------------------------------------------------------------------
    # 文件权限验证
    # -------------------------------------------------------------------

    def test_adbd二进制权限为0o755(self, ar_members):
        """/usr/bin/adbd 在 data.tar.gz 中权限应为 0o755（可执行）。"""
        info = _get_tar_info(ar_members["data.tar.gz"], "./usr/bin/adbd")
        assert info.mode == 0o755, (
            f"/usr/bin/adbd 权限错误：{oct(info.mode)}，期望 0o755"
        )

    def test_conf文件权限为0o644(self, ar_members):
        """/etc/usbdevice.conf 在 data.tar.gz 中权限应为 0o644（只读配置）。"""
        info = _get_tar_info(ar_members["data.tar.gz"], "./etc/usbdevice.conf")
        assert info.mode == 0o644, (
            f"/etc/usbdevice.conf 权限错误：{oct(info.mode)}，期望 0o644"
        )

    # -------------------------------------------------------------------
    # postinst 脚本内容验证
    # -------------------------------------------------------------------

    def test_postinst存在(self, ar_members):
        """control.tar.gz 内应包含 ./postinst 脚本。"""
        names = _read_tar_names(ar_members["control.tar.gz"])
        assert "./postinst" in names

    def test_postinst有bash_shebang(self, postinst_text):
        """postinst 必须以 #!/bin/bash 开头。"""
        assert postinst_text.startswith("#!/bin/bash")

    def test_postinst有set_e(self, postinst_text):
        """postinst 必须包含 set -e（错误即终止）。"""
        assert "set -e" in postinst_text

    def test_postinst含chroot检测(self, postinst_text):
        """postinst 必须包含 chroot 兼容检测（[ -d /run/systemd/system ]）。"""
        assert "[ -d /run/systemd/system ]" in postinst_text

    def test_postinst含systemctl_enable(self, postinst_text):
        """postinst 运行中系统分支必须调用 systemctl enable usbdevice.service。"""
        assert "systemctl enable usbdevice.service" in postinst_text

    def test_postinst含chroot软链接逻辑(self, postinst_text):
        """postinst chroot 分支必须手动创建 .wants 软链接。"""
        assert "ln -sf" in postinst_text
        assert ".wants" in postinst_text

    def test_postinst权限可执行(self, ar_members):
        """postinst 在 control.tar.gz 中权限应有可执行位。"""
        info = _get_tar_info(ar_members["control.tar.gz"], "./postinst")
        assert info.mode & 0o111 != 0, (
            f"postinst 权限错误：{oct(info.mode)}，期望含可执行位"
        )

    # -------------------------------------------------------------------
    # conffiles 验证
    # -------------------------------------------------------------------

    def test_conffiles存在(self, ar_members):
        """control.tar.gz 内应包含 ./conffiles（adbd 有配置文件）。"""
        names = _read_tar_names(ar_members["control.tar.gz"])
        assert "./conffiles" in names

    def test_conffiles包含etc_usbdevice_conf(self, ar_members):
        """/etc/usbdevice.conf 应出现在 conffiles 中（app.yaml 中已声明）。"""
        tar_data = ar_members["control.tar.gz"]
        conffiles_text = _read_tar_member(tar_data, "./conffiles").decode("utf-8")
        assert "/etc/usbdevice.conf" in conffiles_text


# ---------------------------------------------------------------------------
# Task 13.2：构建引擎 App 集成测试
# ---------------------------------------------------------------------------

class TestEngineAppIntegration:
    """13.2 — 验证构建引擎依赖图拓扑排序与 App 组件集成逻辑。

    不需要 Docker 也不需要 adbd 真实目录，所有重依赖均通过 Mock 隔离。
    """

    # -------------------------------------------------------------------
    # 依赖图结构验证
    # -------------------------------------------------------------------

    def test_app节点在依赖图中存在(self):
        """DEPENDENCY_GRAPH 必须包含 app 节点。"""
        assert "app" in DEPENDENCY_GRAPH

    def test_rootfs依赖app(self):
        """rootfs 必须依赖 app，确保 .deb 在 rootfs 构建前完成。"""
        assert "app" in DEPENDENCY_GRAPH["rootfs"]

    def test_app无前置依赖(self):
        """app 节点本身无依赖（预编译 App 无需依赖其他组件）。"""
        assert DEPENDENCY_GRAPH["app"] == []

    # -------------------------------------------------------------------
    # 拓扑排序：rootfs 构建路径
    # -------------------------------------------------------------------

    def test_构建rootfs时app在rootfs之前(self):
        """_topo_sort(rootfs) 中 app 的索引必须小于 rootfs 的索引。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "rootfs")
        assert "app" in order
        assert "rootfs" in order
        assert order.index("app") < order.index("rootfs"), (
            f"期望 app 在 rootfs 之前，实际顺序：{order}"
        )

    def test_构建rootfs时不含无关组件(self):
        """构建 rootfs 路径不应包含 kernel、bootloader、image 等无关组件。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "rootfs")
        for irrelevant in ("kernel", "bootloader", "boot", "image"):
            assert irrelevant not in order, (
                f"{irrelevant} 不应出现在 rootfs 构建路径中，实际顺序：{order}"
            )

    # -------------------------------------------------------------------
    # 拓扑排序：image 构建路径
    # -------------------------------------------------------------------

    def test_构建image时app在rootfs之前(self):
        """_topo_sort(image) 中 app 的索引必须小于 rootfs 的索引。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert order.index("app") < order.index("rootfs"), (
            f"期望 app 在 rootfs 之前，实际顺序：{order}"
        )

    def test_构建image时包含所有必要组件(self):
        """image 构建路径应包含 app、rootfs、kernel、bootloader 等所有必要组件。"""
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        for component in ("app", "rootfs", "boot", "kernel", "bootloader", "image"):
            assert component in order, (
                f"{component} 应出现在 image 构建顺序中，实际：{order}"
            )

    # -------------------------------------------------------------------
    # BuildEngine.build("app") 调用 AppBuilder.build_all()
    # -------------------------------------------------------------------

    def _make_config(self) -> dict:
        """构造最小可用的构建配置。"""
        return {
            "board":    "test-board",
            "product":  "default",
            "variant":  "release",
            "arch":     "aarch64",
            "platform": "rockchip",
            "soc":      "rk3566",
            "rootfs":   {"custom_packages": []},
        }

    def test_build_app调用AppBuilder_build_all(self, tmp_path):
        """engine.build('app') 应实例化 AppBuilder 并调用 build_all()。"""
        config = self._make_config()

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
        ):
            # 缓存始终认为需要重建
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"
            mock_cache_instance.target_dir = tmp_path / "target"

            # AppBuilder.build_all 返回空字典（无 App 需要构建）
            mock_builder = MockAppBuilder.return_value
            mock_builder.build_all.return_value = {}

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("app")

            # 验证 AppBuilder 被实例化
            assert MockAppBuilder.called, "AppBuilder 应被实例化"
            # 验证 build_all 被调用一次
            mock_builder.build_all.assert_called_once()

    def test_build_app结果存入outputs(self, tmp_path):
        """build_all 的返回值应存入 engine._outputs['app']。"""
        config = self._make_config()
        fake_deb = tmp_path / "adbd_1.0.0_arm64.deb"
        fake_deb.touch()

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
        ):
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"
            mock_cache_instance.target_dir = tmp_path / "target"

            mock_builder = MockAppBuilder.return_value
            mock_builder.build_all.return_value = {"adbd": fake_deb}

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("app")

            assert engine._outputs.get("app") == {"adbd": fake_deb}, (
                f"engine._outputs['app'] 应为 {{'adbd': {fake_deb}}}，"
                f"实际：{engine._outputs.get('app')}"
            )

    def test_build_rootfs时AppBuilder被调用(self, tmp_path):
        """engine.build('rootfs') 通过依赖图先构建 app，AppBuilder 应被调用。"""
        config = self._make_config()

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"
            mock_cache_instance.target_dir = tmp_path / "target"

            mock_builder = MockAppBuilder.return_value
            mock_builder.build_all.return_value = {}

            # 模拟 rootfs 平台构建器
            mock_mod = MagicMock()
            mock_mod.create_builder.return_value.build.return_value = {}
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("rootfs")

            # AppBuilder 应在 rootfs 构建前被调用
            mock_builder.build_all.assert_called_once(), (
                "构建 rootfs 时 AppBuilder.build_all 应被调用一次"
            )

    def test_build_rootfs时app先于rootfs执行(self, tmp_path):
        """engine.build('rootfs') 中 app 组件的 build_all 应在 rootfs 构建器之前调用。"""
        config = self._make_config()
        call_order: list[str] = []

        with (
            patch("builder.engine.DockerRunner"),
            patch("builder.engine.SourceManager"),
            patch("builder.engine.BuildCache") as MockCache,
            patch("builder.engine.AppBuilder") as MockAppBuilder,
            patch("builder.engine.importlib") as mock_importlib,
        ):
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.is_up_to_date.return_value = False
            mock_cache_instance.compute_hash.return_value = "abc123"
            mock_cache_instance.target_dir = tmp_path / "target"

            # 记录 build_all 调用顺序
            mock_builder = MockAppBuilder.return_value
            def _track_app_build():
                call_order.append("app")
                return {}
            mock_builder.build_all.side_effect = _track_app_build

            # 记录 rootfs 构建器调用顺序
            mock_rootfs_builder = MagicMock()
            def _track_rootfs_build(cfg):
                call_order.append("rootfs")
                return {}
            mock_rootfs_builder.build.side_effect = _track_rootfs_build

            mock_mod = MagicMock()
            mock_mod.create_builder.return_value = mock_rootfs_builder
            mock_importlib.import_module.return_value = mock_mod

            engine = BuildEngine(config, project_dir=tmp_path)
            engine.build("rootfs")

            # 验证 app 先于 rootfs 执行
            assert "app" in call_order, "app 组件应被构建"
            assert "rootfs" in call_order, "rootfs 组件应被构建"
            assert call_order.index("app") < call_order.index("rootfs"), (
                f"app 应在 rootfs 之前执行，实际顺序：{call_order}"
            )
