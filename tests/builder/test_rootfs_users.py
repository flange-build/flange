"""RootfsBuilder 的 Ubuntu Desktop 用户编号契约测试。"""

from unittest.mock import MagicMock

from builder.rootfs import RootfsBuilder


def test_default_user_reserves_ubuntu_desktop_identity_first(tmp_path):
    """default_user 不受声明顺序影响，并固定使用同名 1000:1000。"""
    docker = MagicMock()
    builder = RootfsBuilder(docker, MagicMock())
    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir()

    builder._configure_users(rootfs_dir, {
        "rootfs": {
            "groups": ["i2c"],
            "users": {
                "guest": {},
                "flange": {},
            },
            "default_user": "flange",
        },
    })

    commands = [
        call.args[0][2:]
        for call in docker.run_privileged.call_args_list
        if call.args[0][:2] == ["chroot", str(rootfs_dir)]
    ]
    assert commands == [
        ["groupadd", "-r", "-f", "i2c"],
        ["groupadd", "-g", "1000", "flange"],
        [
            "useradd", "-m", "-u", "1000", "-g", "flange",
            "-s", "/bin/bash", "flange",
        ],
        ["usermod", "-aG", "i2c", "flange"],
        ["useradd", "-m", "-U", "-s", "/bin/bash", "guest"],
        ["usermod", "-aG", "i2c", "guest"],
    ]
