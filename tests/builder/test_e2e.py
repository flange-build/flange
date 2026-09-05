"""端到端验证测试（Task 13）

覆盖场景：
13.1 adbd 真实 App 端到端打包验证：
    - 使用真实 components/app/adbd/ 目录构建 .deb（若目录不存在则跳过）
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
from builder.config.registry import resolve_config
from builder.engine import DEPENDENCY_GRAPH, BuildEngine, _topo_sort
from builder.source import SourceManager
from builder.workspace import WorkspaceContext, Target


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
_ADBD_DIR = _PROJECT_ROOT / "components" / "app" / "adbd"

# adbd 目录缺失时跳过所有 13.1 测试（兼容 CI 精简环境）
_ADBD_EXISTS = _ADBD_DIR.is_dir() and (_ADBD_DIR / "app.yaml").is_file()
_SKIP_IF_NO_ADBD = pytest.mark.skipif(
    not _ADBD_EXISTS,
    reason=f"adbd App 目录不存在：{_ADBD_DIR}，跳过端到端测试",
)


def test_q8b_firmware_package_builds_flange_deb(tmp_path: Path):
    """package 固件应由 flange 重打 deb，并保留目标路径与原始内容。"""
    config = resolve_config("radxa-dragon-q8b", "default", "release")
    source = SourceManager(
        sources_dir=tmp_path / "sources",
        project_root=_PROJECT_ROOT,
    )
    builder = AppBuilder(
        docker=MagicMock(),
        source=source,
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    deb_path = builder.build_one("firmware-qcom-audioreach").root().runtime_debs[0]

    assert deb_path.name == "firmware-qcom-audioreach_1.0.4-2_arm64.deb"
    members = _read_ar_members(deb_path)
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: firmware-qcom-audioreach" in control
    assert "Depends:" not in control
    firmware_member = (
        "./lib/firmware/qcom/sc8280xp/"
        "SC8280XP-Radxa-Dragon-Q8B-tplg.bin"
    )
    assert firmware_member in _read_tar_names(members["data.tar.gz"])
    source_blob = (
        _PROJECT_ROOT / "components/packages/firmware-qcom-audioreach/"
        "firmware/qcom/sc8280xp/SC8280XP-Radxa-Dragon-Q8B-tplg.bin"
    )
    assert _read_tar_member(
        members["data.tar.gz"], firmware_member
    ) == source_blob.read_bytes()


def test_q8b_fastrpc_packages_follow_radxa_boundaries(tmp_path: Path):
    """FastRPC 参考 payload 应按 Radxa 包边界重打为 flange deb。"""
    config = resolve_config("radxa-dragon-q8b", "default", "release")
    source = SourceManager(
        sources_dir=tmp_path / "sources",
        project_root=_PROJECT_ROOT,
    )
    builder = AppBuilder(
        docker=MagicMock(),
        source=source,
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    packages = {item.name: item.runtime_debs[0] for item in builder.build_all().ordered if item.runtime_debs}

    assert {
        "radxa-firmware-sc8280xp",
        "libadsprpc1",
        "libadsp-default-listener1",
        "libcdsprpc1",
        "libcdsp-default-listener1",
        "fastrpc",
    }.issubset(packages)
    assert packages["fastrpc"].name == "fastrpc_1.0.7-1flange1_arm64.deb"
    assert packages["libcdsprpc1"].name == (
        "libcdsprpc1_1.0.7-1flange1_arm64.deb"
    )
    assert packages["radxa-firmware-sc8280xp"].name == (
        "radxa-firmware-sc8280xp_0.2.41-1flange1_arm64.deb"
    )

    members = _read_ar_members(packages["fastrpc"])
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: fastrpc" in control
    assert "libadsp-default-listener1 (>= 1.0.7)" in control
    assert "libcdsprpc1 (>= 1.0.7)" in control
    assert "radxa-firmware-sc8280xp (= 0.2.41-1flange1)" in control
    control_tar = members["control.tar.gz"]
    control_names = _read_tar_names(control_tar)
    for name in ("postinst", "prerm", "postrm"):
        assert f"./{name}" in control_names
    assert "./triggers" not in control_names
    scripts = "\n".join(
        _read_tar_member(control_tar, f"./{name}").decode("utf-8")
        for name in ("postinst", "prerm", "postrm")
    )
    assert "adsprpcd.service" in scripts
    assert "cdsprpcd.service" in scripts
    assert "deb-systemd-helper" not in scripts
    for excluded in ("sdsprpcd.service", "gdsp0rpcd.service",
                     "gdsp1rpcd.service", "cdsp1rpcd.service"):
        assert excluded not in scripts
    for name in ("postinst", "prerm", "postrm"):
        assert _get_tar_info(control_tar, f"./{name}").mode == 0o755
    data = members["data.tar.gz"]
    names = _read_tar_names(data)
    assert "./usr/sbin/cdsprpcd" in names
    assert "./lib/systemd/system/fastrpc.service" in names
    assert "./usr/libexec/fastrpc/setup-dsp.sh" in names
    assert "./usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0" not in names
    assert (
        "./usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp/"
        "cdsp/fastrpc_shell_3"
    ) not in names

    library_payloads = {
        "libadsprpc1": "libadsprpc.so.1.0.0",
        "libadsp-default-listener1": "libadsp_default_listener.so.1.0.0",
        "libcdsprpc1": "libcdsprpc.so.1.0.0",
        "libcdsp-default-listener1": "libcdsp_default_listener.so.1.0.0",
    }
    for package, library in library_payloads.items():
        library_members = _read_ar_members(packages[package])
        library_names = _read_tar_names(library_members["data.tar.gz"])
        assert f"./usr/lib/aarch64-linux-gnu/{library}" in library_names
        triggers = _read_tar_member(
            library_members["control.tar.gz"], "./triggers"
        ).decode("utf-8")
        assert triggers.endswith("activate-noawait ldconfig\n")

    dsp_members = _read_ar_members(packages["radxa-firmware-sc8280xp"])
    dsp_data = dsp_members["data.tar.gz"]
    dsp_names = _read_tar_names(dsp_data)
    assert (
        "./usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp/"
        "cdsp/fastrpc_shell_3"
    ) in dsp_names
    dsp_link = _get_tar_info(dsp_data, "./usr/lib/dsp")
    assert dsp_link.issym()
    assert dsp_link.linkname == (
        "/usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp")


def test_q8b_fastrpc_test_uses_official_package_name(tmp_path: Path):
    """debug 验证工具应生成官方 `fastrpc-test` 包名。"""
    config = resolve_config("radxa-dragon-q8b", "default", "debug")
    builder = AppBuilder(
        docker=MagicMock(),
        source=SourceManager(
            sources_dir=tmp_path / "sources",
            project_root=_PROJECT_ROOT,
        ),
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, tmp_path, tmp_path / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )

    deb_path = builder.build_one("fastrpc-test").root().runtime_debs[0]

    assert deb_path.name == "fastrpc-test_1.0.7-1flange1_arm64.deb"
    members = _read_ar_members(deb_path)
    control = _read_tar_member(
        members["control.tar.gz"], "./control"
    ).decode("utf-8")
    assert "Package: fastrpc-test" in control
    assert "libcdsprpc1 (>= 1.0.7)" in control
    names = _read_tar_names(members["data.tar.gz"])
    assert "./usr/bin/fastrpc_test" in names
    assert "./usr/share/fastrpc_test/v68/libcalculator_skel.so" in names
    assert not any("/v75/" in name for name in names)


# ---------------------------------------------------------------------------
# 辅助：构建 adbd .deb（供多个测试用例复用）
# ---------------------------------------------------------------------------

def _build_adbd_deb(output_dir: Path) -> Path:
    """使用真实 components/app/adbd/ 构建 adbd .deb，返回 .deb 路径。

    DockerRunner 与 SourceManager 均使用 MagicMock——adbd 为预编译 App
    （build.system=none），不需要 Docker 编译步骤。
    """
    config = {
        "board":   "radxa-zero3w",
        "product": "default",
        "variant": "release",
        "architecture": {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64"},
        "rootfs":  {"custom_packages": ["adbd"]},
    }
    builder = AppBuilder(
        docker=MagicMock(),
        source=SourceManager(project_root=_PROJECT_ROOT, sources_dir=output_dir / "sources"),
        config=config,
        context=WorkspaceContext(_PROJECT_ROOT, output_dir, output_dir / "build",
                                 Target(config["board"], config["product"], config["variant"])),
    )
    # 显式工作区把全部产物限制在测试临时目录。
    output_dir.mkdir(parents=True, exist_ok=True)
    return builder.build_one("adbd").root().runtime_debs[0]


# ---------------------------------------------------------------------------
# Task 13.1：adbd 端到端打包验证
# ---------------------------------------------------------------------------

@_SKIP_IF_NO_ADBD
class TestAdbdEndToEnd:
    """13.1 — 使用真实 components/app/adbd/ 构建 .deb 并验证内容。

    测试通过 AppBuilder.build_one("adbd") 产出 adbd_1.0.0_arm64.deb，
    随后解包验证 control 字段、data.tar.gz 文件树和 postinst 脚本。
    """

    @pytest.fixture(scope="class")
    @classmethod
    def deb_path(cls, tmp_path_factory):
        """Class-scoped fixture：只构建一次 .deb，所有测试复用。"""
        out = tmp_path_factory.mktemp("adbd_deb")
        return _build_adbd_deb(out)

    @pytest.fixture(scope="class")
    @classmethod
    def ar_members(cls, deb_path):
        """解析 .deb ar 成员，供内容验证复用。"""
        return _read_ar_members(deb_path)

    @pytest.fixture(scope="class")
    @classmethod
    def control_text(cls, ar_members):
        """提取 control 文件文本内容。"""
        tar_data = ar_members["control.tar.gz"]
        return _read_tar_member(tar_data, "./control").decode("utf-8")

    @pytest.fixture(scope="class")
    @classmethod
    def data_names(cls, ar_members):
        """提取 data.tar.gz 中所有成员名称列表。"""
        return _read_tar_names(ar_members["data.tar.gz"])

    @pytest.fixture(scope="class")
    @classmethod
    def postinst_text(cls, ar_members):
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
    """真实空 App 报告也经过引擎成功清单，不能用旧 dict 伪造成功。"""

    def test_app报告与引擎manifest联通(self, tmp_path):
        from builder.workspace import WorkspaceContext, Target
        from builder.artifacts import ArtifactManifest
        context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build',
                                   Target('board', 'default', 'release'))
        config = {'board': 'board', 'product': 'default', 'variant': 'release', 'platform': 'rockchip',
                  'architecture': {'userspace': 'aarch64', 'kernel': 'arm64', 'bootloader': 'arm64'},
                  'rootfs': {'custom_packages': []}}
        engine = BuildEngine(config, context=context, output=MagicMock())
        engine.build('app')
        report_path = context.target_dir / 'apps/build-report.json'
        assert report_path.is_file()
        manifest = ArtifactManifest.load(context.target_dir / 'app/manifest.json')
        assert manifest and manifest.validate()
        assert manifest.artifacts[0].path == report_path
        assert engine._app_report.runtime_debs == ()
        identity = manifest.identity
        engine.build('app')
        assert ArtifactManifest.load(context.target_dir / 'app/manifest.json').identity == identity
