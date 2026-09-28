"""disable_root_login 的 sshd drop-in 必须被主配置实际加载。"""

from unittest.mock import MagicMock

import pytest

from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder

INCLUDE = "Include /etc/ssh/sshd_config.d/*.conf"
# Ubuntu 24.04 默认主配置开头即 Include；18.04 只有注释掉的 PermitRootLogin。
NOBLE = f"# header\n\n{INCLUDE}\n\n#PermitRootLogin prohibit-password\n"
BIONIC = "# header\n\n#PermitRootLogin prohibit-password\nUsePAM yes\n"


def _rootfs(tmp_path, main: str | None):
    ssh = tmp_path / "etc/ssh"
    ssh.mkdir(parents=True)
    if main is not None:
        (ssh / "sshd_config").write_text(main)
    return tmp_path


def _builder():
    return RockchipRootfsBuilder(MagicMock(), MagicMock())


def test_existing_include_keeps_main_config_bytes(tmp_path):
    rootfs = _rootfs(tmp_path, NOBLE)

    _builder()._write_sshd_no_root_drop_in(rootfs)

    assert (rootfs / "etc/ssh/sshd_config").read_text() == NOBLE
    _builder()._verify_sshd_no_root(rootfs)


def test_missing_include_is_inserted_before_other_directives(tmp_path):
    rootfs = _rootfs(tmp_path, BIONIC)

    _builder()._write_sshd_no_root_drop_in(rootfs)

    main = (rootfs / "etc/ssh/sshd_config").read_text()
    assert main == f"{INCLUDE}\n{BIONIC}"
    assert "PermitRootLogin no" in (rootfs / "etc/ssh/sshd_config.d/10-flange.conf").read_text()
    _builder()._verify_sshd_no_root(rootfs)


def test_commented_include_does_not_count(tmp_path):
    rootfs = _rootfs(tmp_path, f"#{INCLUDE}\n{BIONIC}")

    _builder()._write_sshd_no_root_drop_in(rootfs)

    assert (rootfs / "etc/ssh/sshd_config").read_text().splitlines()[0] == INCLUDE


def test_without_openssh_only_drop_in_is_written(tmp_path):
    rootfs = _rootfs(tmp_path, None)

    _builder()._write_sshd_no_root_drop_in(rootfs)

    assert not (rootfs / "etc/ssh/sshd_config").exists()
    _builder()._verify_sshd_no_root(rootfs)


def test_verify_rejects_unloaded_drop_in(tmp_path):
    rootfs = _rootfs(tmp_path, BIONIC)
    drop_in = rootfs / "etc/ssh/sshd_config.d/10-flange.conf"
    drop_in.parent.mkdir()
    drop_in.write_text("PermitRootLogin no\n")

    with pytest.raises(RuntimeError, match="未加载 sshd_config.d"):
        _builder()._verify_sshd_no_root(rootfs)
