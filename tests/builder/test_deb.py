"""deb 打包核心引擎测试 — 覆盖 control 生成、conffiles、postinst/prerm、
data.tar.gz 文件树结构与权限、端到端 .deb 构建验证。
"""

from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

from builder.app_spec import AppInfo, AppSpec, BuildConfig, MaintainerInfo, SystemdConfig
from builder.deb import (
    DebBuildError,
    DebBuilder,
    _build_control_tar,
    _build_data_tar,
    _generate_conffiles_text,
    _generate_control_text,
    _generate_postinst,
    _generate_prerm,
    _map_arch,
    generate_control,
)


# ---------------------------------------------------------------------------
# 辅助函数 / Fixtures
# ---------------------------------------------------------------------------

def _make_spec(
    *,
    name: str = "test-daemon",
    version: str = "1.0.0",
    app_type: str = "service",
    arch: List[str] = None,
    depends: List[str] = None,
    conffiles: List[str] = None,
    data_dirs: List[str] = None,
    systemd_unit: str = "systemd/test-daemon.service",
    auto_start: bool = True,
    include_systemd: bool = True,
    maintainer_scripts: Dict[str, str] = None,
) -> AppSpec:
    """构造测试用 AppSpec 的辅助函数。"""
    systemd = None
    if include_systemd and app_type == "service":
        systemd = SystemdConfig(unit=systemd_unit, auto_start=auto_start)
    return AppSpec(
        app=AppInfo(
            name=name,
            version=version,
            description="测试用守护进程",
            type=app_type,
            arch=arch or ["aarch64"],
        ),
        maintainer=MaintainerInfo(name="flange", email="flange@localhost"),
        depends=depends or [],
        conffiles=conffiles or [],
        data_dirs=data_dirs or [],
        maintainer_scripts=maintainer_scripts or {},
        systemd=systemd,
        build=BuildConfig(),
    )


def _read_tar_names(data: bytes) -> List[str]:
    """从 tar.gz bytes 读取所有成员名称列表。"""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        return tf.getnames()


def _read_tar_member(data: bytes, name: str) -> bytes:
    """从 tar.gz bytes 中提取指定成员的内容。"""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        member = tf.getmember(name)
        f = tf.extractfile(member)
        return f.read() if f else b""


def _get_tar_info(data: bytes, name: str) -> tarfile.TarInfo:
    """从 tar.gz bytes 中获取指定成员的 TarInfo。"""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        return tf.getmember(name)


# ---------------------------------------------------------------------------
# 测试：架构映射
# ---------------------------------------------------------------------------

class TestArchMapping:
    """验证 config 架构名到 deb 架构名的映射。"""

    def test_aarch64_maps_to_arm64(self):
        assert _map_arch("aarch64") == "arm64"

    def test_armhf_maps_to_armhf(self):
        assert _map_arch("armhf") == "armhf"

    def test_x86_64_maps_to_amd64(self):
        assert _map_arch("x86_64") == "amd64"

    def test_unknown_arch_passthrough(self):
        """未知架构直接透传，不抛异常。"""
        assert _map_arch("mips64") == "mips64"


# ---------------------------------------------------------------------------
# 测试：control 文件生成
# ---------------------------------------------------------------------------

class TestControlTextGeneration:
    """验证 _generate_control_text 生成的 control 文件内容。"""

    def test_required_fields_present(self):
        """control 文件必须包含所有必填字段。"""
        text = _generate_control_text(
            name="my-pkg",
            version="1.2.3",
            arch="arm64",
            maintainer="flange <flange@localhost>",
            description="测试包",
            depends=[],
        )
        assert "Package: my-pkg" in text
        assert "Version: 1.2.3" in text
        assert "Architecture: arm64" in text
        assert "Maintainer: flange <flange@localhost>" in text
        assert "Description: 测试包" in text

    def test_depends_field_generated(self):
        """有依赖项时生成 Depends 字段，多项用逗号分隔。"""
        text = _generate_control_text(
            name="pkg",
            version="1.0",
            arch="arm64",
            maintainer="test <t@t.com>",
            description="desc",
            depends=["libc6", "libssl3"],
        )
        assert "Depends: libc6, libssl3" in text

    def test_empty_depends_no_field(self):
        """没有依赖项时不生成 Depends 字段。"""
        text = _generate_control_text(
            name="pkg",
            version="1.0",
            arch="arm64",
            maintainer="test <t@t.com>",
            description="desc",
            depends=[],
        )
        assert "Depends:" not in text

    def test_single_depends(self):
        """单个依赖项正常生成。"""
        text = _generate_control_text(
            name="pkg",
            version="1.0",
            arch="arm64",
            maintainer="test <t@t.com>",
            description="desc",
            depends=["libc6"],
        )
        assert "Depends: libc6" in text

    def test_control_ends_with_newline(self):
        """control 文件以换行符结尾。"""
        text = _generate_control_text(
            name="pkg",
            version="1.0",
            arch="arm64",
            maintainer="test <t@t.com>",
            description="desc",
            depends=[],
        )
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# 测试：conffiles 生成
# ---------------------------------------------------------------------------

class TestConffilesGeneration:
    """验证 _generate_conffiles_text 的正确性。"""

    def test_conffiles_content_correct(self):
        """conffiles 包含所有有效路径。"""
        text = _generate_conffiles_text(["/etc/foo/config.yaml", "/etc/bar.conf"])
        assert "/etc/foo/config.yaml" in text
        assert "/etc/bar.conf" in text

    def test_no_trailing_empty_lines(self):
        """conffiles 不得以空行结尾（dpkg 将空行视为无效路径）。"""
        text = _generate_conffiles_text(["/etc/foo.conf"])
        # 最后一个有效字符必须是换行（文件路径后），但不能有多余空行
        lines = text.splitlines()
        # 过滤空行后不应有空字符串
        assert all(line.strip() for line in lines)

    def test_empty_lines_in_input_filtered(self):
        """输入中的空白行被过滤，不出现在输出中。"""
        text = _generate_conffiles_text(["", "/etc/foo.conf", "  ", "/etc/bar.conf"])
        lines = [l for l in text.splitlines() if l]
        assert lines == ["/etc/foo.conf", "/etc/bar.conf"]

    def test_empty_conffiles_returns_empty_string(self):
        """无 conffiles 时返回空字符串。"""
        text = _generate_conffiles_text([])
        assert text == ""

    def test_all_empty_conffiles_returns_empty_string(self):
        """全部为空行时返回空字符串。"""
        text = _generate_conffiles_text(["", "  ", "\t"])
        assert text == ""

    def test_conffiles_ends_with_newline(self):
        """非空 conffiles 以换行符结尾。"""
        text = _generate_conffiles_text(["/etc/foo.conf"])
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# 测试：postinst 脚本
# ---------------------------------------------------------------------------

class TestPostinstGeneration:
    """验证 _generate_postinst 的内容正确性。"""

    def test_postinst_shebang(self):
        """postinst 必须有 bash shebang。"""
        script = _generate_postinst("my-daemon.service", [], auto_start=True)
        assert script.startswith("#!/bin/bash")

    def test_postinst_set_e(self):
        """postinst 必须包含 set -e。"""
        script = _generate_postinst("my-daemon.service", [], auto_start=True)
        assert "set -e" in script

    def test_chroot_detection_present(self):
        """postinst 必须包含 chroot 检测逻辑（/run/systemd/system 判断）。"""
        script = _generate_postinst("my-daemon.service", [], auto_start=True)
        assert "[ -d /run/systemd/system ]" in script

    def test_systemctl_enable_in_live_branch(self):
        """运行中系统分支必须调用 systemctl enable。"""
        script = _generate_postinst("my-daemon.service", [], auto_start=True)
        assert "systemctl enable my-daemon.service" in script
        assert "systemctl daemon-reload" in script

    def test_chroot_symlink_in_chroot_branch(self):
        """chroot 分支必须手动创建 .wants 软链接。"""
        script = _generate_postinst("my-daemon.service", [], auto_start=True)
        assert "ln -sf" in script
        assert ".wants" in script

    def test_data_dirs_mkdir_commands_generated(self):
        """有 data_dirs 时生成 mkdir -p 命令。"""
        script = _generate_postinst("my.service", ["/var/lib/my-app", "/var/log/my-app"])
        assert "mkdir -p /var/lib/my-app" in script
        assert "mkdir -p /var/log/my-app" in script

    def test_no_data_dirs_no_data_mkdir(self):
        """无 data_dirs 时，数据目录部分只有注释，
        不生成用户数据目录的 mkdir 命令。"""
        script = _generate_postinst("my.service", [])
        # chroot 分支中有 mkdir -p /etc/systemd/system/$target.wants，是正常的
        # 但不应有用户数据目录的 mkdir 命令（/var/ 或 /etc/ 下的具体路径）
        assert "# 无需创建数据目录" in script

    def test_service_name_in_script(self):
        """service 文件名正确出现在脚本中。"""
        script = _generate_postinst("usbdevice.service", [], auto_start=True)
        assert "usbdevice.service" in script

    def test_service_name_with_shell_metachar_raises(self):
        """service_name 含 shell 元字符时抛出 DebBuildError。"""
        with pytest.raises(DebBuildError):
            _generate_postinst("my-daemon.service; rm -rf /", [])

    def test_service_name_with_dollar_raises(self):
        """service_name 含 $ 时抛出 DebBuildError（防止变量展开注入）。"""
        with pytest.raises(DebBuildError):
            _generate_postinst("$malicious.service", [])

    def test_data_dir_with_shell_metachar_raises(self):
        """data_dirs 条目含 shell 元字符时抛出 DebBuildError。"""
        with pytest.raises(DebBuildError):
            _generate_postinst("my.service", ["/var/lib/app; rm -rf /"])

    def test_data_dir_with_backtick_raises(self):
        """data_dirs 条目含反引号时抛出 DebBuildError（防止命令替换注入）。"""
        with pytest.raises(DebBuildError):
            _generate_postinst("my.service", ["/var/lib/`id`"])


# ---------------------------------------------------------------------------
# 测试：prerm 脚本
# ---------------------------------------------------------------------------

class TestPrermGeneration:
    """验证 _generate_prerm 的内容正确性。"""

    def test_prerm_shebang(self):
        """prerm 必须有 bash shebang。"""
        script = _generate_prerm("my-daemon.service")
        assert script.startswith("#!/bin/bash")

    def test_prerm_set_e(self):
        """prerm 必须包含 set -e。"""
        script = _generate_prerm("my-daemon.service")
        assert "set -e" in script

    def test_prerm_chroot_detection(self):
        """prerm 必须包含 chroot 检测逻辑。"""
        script = _generate_prerm("my-daemon.service")
        assert "[ -d /run/systemd/system ]" in script

    def test_prerm_stop_command(self):
        """prerm 必须调用 systemctl stop。"""
        script = _generate_prerm("my-daemon.service")
        assert "systemctl stop my-daemon.service" in script

    def test_prerm_disable_command(self):
        """prerm 必须调用 systemctl disable。"""
        script = _generate_prerm("my-daemon.service")
        assert "systemctl disable my-daemon.service" in script

    def test_prerm_stop_with_error_suppress(self):
        """prerm 的 stop/disable 命令失败时不应中止（|| true）。"""
        script = _generate_prerm("my-daemon.service")
        assert "|| true" in script

    def test_service_name_with_shell_metachar_raises(self):
        """service_name 含 shell 元字符时抛出 DebBuildError。"""
        with pytest.raises(DebBuildError):
            _generate_prerm("my-daemon.service; rm -rf /")

    def test_service_name_with_dollar_raises(self):
        """service_name 含 $ 时抛出 DebBuildError（防止变量展开注入）。"""
        with pytest.raises(DebBuildError):
            _generate_prerm("$(evil)")


# ---------------------------------------------------------------------------
# 测试：generate_control（从 AppSpec 生成所有控制文件）
# ---------------------------------------------------------------------------

class TestGenerateControl:
    """验证 generate_control 从 AppSpec 生成完整控制文件集合。"""

    def test_control_key_always_present(self):
        """control 文件必须始终存在。"""
        spec = _make_spec()
        result = generate_control(spec, "aarch64")
        assert "control" in result

    def test_arch_mapped_in_control(self):
        """control 文件中架构名使用 deb 格式（aarch64 → arm64）。"""
        spec = _make_spec(arch=["aarch64"])
        result = generate_control(spec, "aarch64")
        assert "Architecture: arm64" in result["control"]

    def test_maintainer_format(self):
        """control 文件中 Maintainer 格式为 "Name <email>"。"""
        spec = _make_spec()
        result = generate_control(spec, "aarch64")
        assert "Maintainer: flange <flange@localhost>" in result["control"]

    def test_depends_in_control(self):
        """有 depends 时 control 文件包含 Depends 字段。"""
        spec = _make_spec(depends=["libc6", "libssl3"])
        result = generate_control(spec, "aarch64")
        assert "Depends: libc6, libssl3" in result["control"]

    def test_conffiles_generated_when_present(self):
        """有 conffiles 时生成 conffiles 文件。"""
        spec = _make_spec(conffiles=["/etc/test/config.yaml"])
        result = generate_control(spec, "aarch64")
        assert "conffiles" in result
        assert "/etc/test/config.yaml" in result["conffiles"]

    def test_conffiles_absent_when_empty(self):
        """无 conffiles 时不生成 conffiles 文件。"""
        spec = _make_spec(conffiles=[])
        result = generate_control(spec, "aarch64")
        assert "conffiles" not in result

    def test_postinst_prerm_for_service_with_systemd(self):
        """service 类型且有 systemd 配置时生成 postinst 和 prerm。"""
        spec = _make_spec(app_type="service", include_systemd=True)
        result = generate_control(spec, "aarch64")
        assert "postinst" in result
        assert "prerm" in result

    def test_no_postinst_prerm_for_exec_type(self):
        """exec 类型不生成 postinst 和 prerm。"""
        spec = _make_spec(app_type="exec", include_systemd=False)
        result = generate_control(spec, "aarch64")
        assert "postinst" not in result
        assert "prerm" not in result

    def test_no_postinst_prerm_without_systemd(self):
        """service 类型但无 systemd 配置时不生成 postinst 和 prerm。"""
        spec = _make_spec(app_type="service", include_systemd=False)
        result = generate_control(spec, "aarch64")
        assert "postinst" not in result
        assert "prerm" not in result

    def test_service_name_from_unit_path(self):
        """从 systemd.unit 路径提取 service 文件名（去除目录前缀）。"""
        spec = _make_spec(systemd_unit="systemd/usbdevice.service")
        result = generate_control(spec, "aarch64")
        assert "usbdevice.service" in result["postinst"]
        assert "usbdevice.service" in result["prerm"]

    def test_data_dirs_in_postinst(self):
        """data_dirs 中的目录出现在 postinst mkdir 命令中。"""
        spec = _make_spec(data_dirs=["/var/lib/test-daemon"])
        result = generate_control(spec, "aarch64")
        assert "mkdir -p /var/lib/test-daemon" in result["postinst"]

    def test_vendor_maintainer_scripts_are_mapped(self):
        scripts = {
            "postinst": "#!/bin/sh\nset -xe\n",
            "triggers": "activate-noawait ldconfig\n",
        }
        spec = _make_spec(
            app_type="vendor",
            include_systemd=False,
            maintainer_scripts=scripts,
        )

        result = generate_control(spec, "aarch64")

        assert result["postinst"] == scripts["postinst"]
        assert result["triggers"] == scripts["triggers"]


# ---------------------------------------------------------------------------
# 测试：control.tar.gz 结构
# ---------------------------------------------------------------------------

class TestControlTarBuild:
    """验证 _build_control_tar 的输出结构。"""

    def test_control_member_present(self):
        """control.tar.gz 必须包含 ./control。"""
        tar_data = _build_control_tar({"control": "Package: foo\n"})
        names = _read_tar_names(tar_data)
        assert "./control" in names

    def test_all_control_files_present(self):
        """所有传入的控制文件均出现在 tar 中。"""
        files = {
            "control": "Package: foo\n",
            "conffiles": "/etc/foo.conf\n",
            "postinst": "#!/bin/bash\n",
            "prerm": "#!/bin/bash\n",
        }
        tar_data = _build_control_tar(files)
        names = _read_tar_names(tar_data)
        for fname in files:
            assert f"./{fname}" in names

    def test_control_file_content_preserved(self):
        """control 文件内容在 tar 中完整保留。"""
        content = "Package: myapp\nVersion: 1.0.0\n"
        tar_data = _build_control_tar({"control": content})
        extracted = _read_tar_member(tar_data, "./control")
        assert extracted.decode("utf-8") == content

    def test_postinst_has_executable_mode(self):
        """postinst 在 tar 中的权限应为可执行（755）。"""
        tar_data = _build_control_tar({
            "control": "Package: foo\n",
            "postinst": "#!/bin/bash\nset -e\n",
        })
        info = _get_tar_info(tar_data, "./postinst")
        # 检查可执行位
        assert info.mode & 0o111 != 0, f"postinst mode {oct(info.mode)} 无可执行位"

    def test_prerm_has_executable_mode(self):
        """prerm 在 tar 中的权限应为可执行（755）。"""
        tar_data = _build_control_tar({
            "control": "Package: foo\n",
            "prerm": "#!/bin/bash\nset -e\n",
        })
        info = _get_tar_info(tar_data, "./prerm")
        assert info.mode & 0o111 != 0, f"prerm mode {oct(info.mode)} 无可执行位"

    def test_control_has_non_executable_mode(self):
        """control 文件权限应为 644（不可执行）。"""
        tar_data = _build_control_tar({"control": "Package: foo\n"})
        info = _get_tar_info(tar_data, "./control")
        assert info.mode == 0o644


# ---------------------------------------------------------------------------
# 测试：data.tar.gz 文件树结构与权限
# ---------------------------------------------------------------------------

class TestDataTarBuild:
    """验证 _build_data_tar 的输出结构与文件权限。"""

    def test_long_paths_and_links_use_dpkg_supported_headers(self, tmp_path):
        """工具链长路径及长链接必须原样保留，且不生成 dpkg 拒绝的 PAX 头。"""
        src = tmp_path / "payload"
        src.write_bytes(b"toolchain")
        destination = "/usr/share/" + "/".join(["a" * 80] * 4) + "/payload"
        link = tmp_path / "link"
        link.symlink_to(destination)
        archive = _build_data_tar([
            (src, destination, 0o755), (link, "/usr/bin/toolchain-link", 0o777),
        ])
        raw = gzip.decompress(archive)
        types = []
        offset = 0
        while raw[offset:offset + 512].strip(b"\0"):
            header = raw[offset:offset + 512]
            types.append(header[156:157])
            size = int(header[124:136].strip(b"\0 ") or b"0", 8)
            offset += 512 + ((size + 511) // 512) * 512
        assert not {b"x", b"g"}.intersection(types)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            payload = tf.getmember("." + destination)
            assert payload.mode == 0o755
            assert tf.extractfile(payload).read() == b"toolchain"
            assert tf.getmember("./usr/bin/toolchain-link").linkname == destination

    def test_file_present_in_tar(self, tmp_path):
        """安装文件出现在 data.tar.gz 中。"""
        src = tmp_path / "my-daemon"
        src.write_bytes(b"\x7fELF")

        tar_data = _build_data_tar([(src, "/usr/bin/my-daemon", 0o755)])
        names = _read_tar_names(tar_data)
        assert "./usr/bin/my-daemon" in names

    def test_file_content_preserved(self, tmp_path):
        """安装文件内容在 data.tar.gz 中完整保留。"""
        content = b"binary content \x00\x01\x02"
        src = tmp_path / "testbin"
        src.write_bytes(content)

        tar_data = _build_data_tar([(src, "/usr/bin/testbin", 0o755)])
        extracted = _read_tar_member(tar_data, "./usr/bin/testbin")
        assert extracted == content

    def test_file_mode_preserved(self, tmp_path):
        """安装文件权限在 data.tar.gz 中正确保留。"""
        src = tmp_path / "config.yaml"
        src.write_text("key: value\n")

        tar_data = _build_data_tar([(src, "/etc/myapp/config.yaml", 0o644)])
        info = _get_tar_info(tar_data, "./etc/myapp/config.yaml")
        assert info.mode == 0o644

    def test_executable_mode_preserved(self, tmp_path):
        """可执行文件权限 755 被正确保留。"""
        src = tmp_path / "mybin"
        src.write_bytes(b"\x7fELF")

        tar_data = _build_data_tar([(src, "/usr/bin/mybin", 0o755)])
        info = _get_tar_info(tar_data, "./usr/bin/mybin")
        assert info.mode == 0o755

    def test_parent_dirs_added(self, tmp_path):
        """安装路径的所有父目录被自动添加到 data.tar.gz。"""
        src = tmp_path / "foo"
        src.write_bytes(b"data")

        tar_data = _build_data_tar([(src, "/usr/bin/foo", 0o755)])
        names = _read_tar_names(tar_data)
        # tarfile 模块会去掉目录名尾部的斜杠
        # 用 ./usr 或 ./usr/ 均可表示同一目录
        assert "./usr" in names or "./usr/" in names
        assert "./usr/bin" in names or "./usr/bin/" in names

    def test_multiple_files(self, tmp_path):
        """多个安装文件均出现在 data.tar.gz 中。"""
        files = []
        for i in range(3):
            src = tmp_path / f"file{i}"
            src.write_bytes(f"content{i}".encode())
            files.append((src, f"/usr/lib/myapp/file{i}", 0o644))

        tar_data = _build_data_tar(files)
        names = _read_tar_names(tar_data)
        for i in range(3):
            assert f"./usr/lib/myapp/file{i}" in names

    def test_duplicate_parent_dirs_not_added_twice(self, tmp_path):
        """共享父目录不被重复添加。"""
        for i in range(2):
            (tmp_path / f"file{i}").write_bytes(b"x")

        files = [
            (tmp_path / "file0", "/usr/bin/file0", 0o755),
            (tmp_path / "file1", "/usr/bin/file1", 0o755),
        ]
        tar_data = _build_data_tar(files)
        names = _read_tar_names(tar_data)
        # ./usr/bin 只应出现一次（tarfile 可能带或不带尾部斜杠）
        count = names.count("./usr/bin") + names.count("./usr/bin/")
        assert count == 1, f"./usr/bin 在 tar 中出现了 {count} 次（应为 1 次）"

    def test_missing_src_raises_error(self, tmp_path):
        """源文件不存在时抛出 DebBuildError。"""
        non_existent = tmp_path / "ghost"
        with pytest.raises(DebBuildError, match="不存在"):
            _build_data_tar([(non_existent, "/usr/bin/ghost", 0o755)])


# ---------------------------------------------------------------------------
# 端到端测试：构建 .deb → 纯 Python 验证结构 → 解压验证内容
# ---------------------------------------------------------------------------

def _read_ar_members(deb_path: Path) -> Dict[str, bytes]:
    """纯 Python ar 归档读取器，返回 {成员名: 数据} 字典。

    支持标准 POSIX ar 格式（.deb 所用格式），不支持 GNU ar 扩展名。
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
        header = data[pos : pos + 60]
        name    = header[0:16].rstrip().decode("ascii")
        size    = int(header[48:58].rstrip())
        end_mag = header[58:60]
        assert end_mag == b"\x60\x0a", f"ar 成员头 magic 错误：{end_mag!r}"

        pos += 60
        member_data = data[pos : pos + size]
        members[name] = member_data
        # 成员数据按 2 字节对齐
        pos += size + (size % 2)

    return members


class TestEndToEnd:
    """端到端测试：构建完整 .deb 包并用纯 Python 验证其结构与内容。"""

    def _build_minimal_deb(self, tmp_path: Path) -> tuple[Path, Path]:
        """构建最小可用 .deb，返回 (deb_path, src_file)。"""
        # 准备源文件
        src_file = tmp_path / "src" / "my-daemon"
        src_file.parent.mkdir(parents=True)
        src_file.write_bytes(b"\x7fELF test binary")

        conf_file = tmp_path / "src" / "config.yaml"
        conf_file.write_text("key: value\n")

        # 控制文件
        control_fields = {
            "control": (
                "Package: my-daemon\n"
                "Version: 1.0.0\n"
                "Architecture: arm64\n"
                "Maintainer: flange <flange@localhost>\n"
                "Description: 测试守护进程\n"
            ),
            "conffiles": "/etc/my-daemon/config.yaml\n",
            "postinst": "#!/bin/bash\nset -e\necho 安装完成\n",
            "prerm": "#!/bin/bash\nset -e\necho 卸载中\n",
        }

        files = [
            (src_file, "/usr/bin/my-daemon", 0o755),
            (conf_file, "/etc/my-daemon/config.yaml", 0o644),
        ]

        output_dir = tmp_path / "dist"
        builder = DebBuilder()
        deb_path = builder.build_deb(
            name="my-daemon",
            version="1.0.0",
            arch="aarch64",
            control_fields=control_fields,
            files=files,
            output_dir=output_dir,
        )
        return deb_path, src_file

    def test_deb_file_created(self, tmp_path):
        """build_deb 返回的路径存在且是文件。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        assert deb_path.exists()
        assert deb_path.is_file()

    def test_deb_filename_format(self, tmp_path):
        """输出文件名格式为 {name}_{version}_{deb_arch}.deb。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        assert deb_path.name == "my-daemon_1.0.0_arm64.deb"

    @pytest.mark.parametrize(
        ("name", "version"),
        [("../escape", "1.0"), ("safe", "../1.0")],
    )
    def test_unsafe_output_identity_rejected(self, tmp_path, name, version):
        with pytest.raises(DebBuildError, match="不安全"):
            DebBuilder().build_deb(
                name=name,
                version=version,
                arch="aarch64",
                control_fields={},
                files=[],
                output_dir=tmp_path / "dist",
            )
        assert not (tmp_path / "dist").exists()

    def test_deb_ar_magic(self, tmp_path):
        """.deb 文件以标准 ar magic 开头。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        raw = deb_path.read_bytes()
        assert raw[:8] == b"!<arch>\n"

    def test_deb_ar_structure(self, tmp_path):
        """ar 归档成员必须包含 debian-binary、control.tar.gz、data.tar.gz。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        assert "debian-binary" in members
        assert "control.tar.gz" in members
        assert "data.tar.gz" in members

    def test_debian_binary_content(self, tmp_path):
        """debian-binary 内容必须是 "2.0\\n"。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        assert members["debian-binary"] == b"2.0\n"

    def test_control_tar_contains_control(self, tmp_path):
        """control.tar.gz 内包含 ./control 文件。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        names = _read_tar_names(members["control.tar.gz"])
        assert "./control" in names

    def test_control_tar_contains_postinst_prerm(self, tmp_path):
        """control.tar.gz 内包含 ./postinst 和 ./prerm。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        names = _read_tar_names(members["control.tar.gz"])
        assert "./postinst" in names
        assert "./prerm" in names

    def test_data_tar_contains_installed_files(self, tmp_path):
        """data.tar.gz 内包含 ./usr/bin/my-daemon 和 ./etc/my-daemon/config.yaml。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        names = _read_tar_names(members["data.tar.gz"])
        assert "./usr/bin/my-daemon" in names
        assert "./etc/my-daemon/config.yaml" in names

    def test_data_tar_binary_content_correct(self, tmp_path):
        """data.tar.gz 中的二进制文件内容与源文件一致。"""
        deb_path, src_file = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        extracted = _read_tar_member(members["data.tar.gz"], "./usr/bin/my-daemon")
        assert extracted == src_file.read_bytes()

    def test_data_tar_file_mode_755(self, tmp_path):
        """data.tar.gz 中可执行文件权限为 755。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        info = _get_tar_info(members["data.tar.gz"], "./usr/bin/my-daemon")
        assert info.mode == 0o755

    def test_data_tar_file_mode_644(self, tmp_path):
        """data.tar.gz 中配置文件权限为 644。"""
        deb_path, _ = self._build_minimal_deb(tmp_path)
        members = _read_ar_members(deb_path)
        info = _get_tar_info(members["data.tar.gz"], "./etc/my-daemon/config.yaml")
        assert info.mode == 0o644

    def test_build_from_spec(self, tmp_path):
        """build_from_spec 便捷方法从 AppSpec 直接构建 .deb。"""
        spec = _make_spec(
            name="spec-daemon",
            version="2.0.0",
            depends=["libc6"],
            conffiles=["/etc/spec-daemon/config.yaml"],
            data_dirs=["/var/lib/spec-daemon"],
        )

        src_file = tmp_path / "spec-daemon"
        src_file.write_bytes(b"\x7fELF binary")

        files = [(src_file, "/usr/bin/spec-daemon", 0o755)]
        output_dir = tmp_path / "out"

        builder = DebBuilder()
        deb_path = builder.build_from_spec(spec, "aarch64", files, output_dir)

        assert deb_path.exists()
        assert deb_path.name == "spec-daemon_2.0.0_arm64.deb"

        # 验证 ar 结构
        members = _read_ar_members(deb_path)
        assert "debian-binary" in members
        assert "control.tar.gz" in members
        assert "data.tar.gz" in members

    def test_build_from_spec_postinst_contains_data_dir(self, tmp_path):
        """build_from_spec 生成的 .deb 中 postinst 包含 data_dirs mkdir 命令。"""
        spec = _make_spec(
            name="data-daemon",
            version="1.0.0",
            data_dirs=["/var/lib/data-daemon"],
        )

        src_file = tmp_path / "data-daemon"
        src_file.write_bytes(b"binary")
        files = [(src_file, "/usr/bin/data-daemon", 0o755)]

        builder = DebBuilder()
        deb_path = builder.build_from_spec(spec, "aarch64", files, tmp_path / "out")

        # 提取 control.tar.gz 并验证 postinst
        members = _read_ar_members(deb_path)
        postinst_content = _read_tar_member(
            members["control.tar.gz"], "./postinst"
        ).decode("utf-8")
        assert "mkdir -p /var/lib/data-daemon" in postinst_content

    def test_output_dir_created_if_not_exists(self, tmp_path):
        """output_dir 不存在时自动创建。"""
        src_file = tmp_path / "bin"
        src_file.write_bytes(b"x")

        output_dir = tmp_path / "non" / "existent" / "dir"
        assert not output_dir.exists()

        builder = DebBuilder()
        deb_path = builder.build_deb(
            name="pkg",
            version="1.0",
            arch="aarch64",
            control_fields={"control": (
                "Package: pkg\nVersion: 1.0\nArchitecture: arm64\n"
                "Maintainer: t <t@t>\nDescription: t\n"
            )},
            files=[(src_file, "/usr/bin/pkg", 0o755)],
            output_dir=output_dir,
        )
        assert deb_path.exists()
