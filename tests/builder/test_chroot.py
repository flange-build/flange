"""Chroot 资源生命周期：部分失败回滚、原配置恢复与异常优先级。"""

import os
from pathlib import Path
import subprocess

import pytest

from builder.chroot import ChrootContext
from builder.docker import BuildError


class RecordingDocker:
    """只记录挂载命令；临时配置写到测试目录，不操作真实挂载。"""

    def __init__(self):
        self.calls = []
        self.failures = {}

    def run_privileged(self, command, **kwargs):
        self.calls.append((command, kwargs))
        failure = self.failures.get((command[0], command[-1]))
        if failure is not None:
            raise failure
        if command[0] == "cp":
            Path(command[-1]).write_text("nameserver 192.0.2.1\n")
        return subprocess.CompletedProcess(command, 0)


def unmounted(docker):
    return [Path(command[-1]) for command, _ in docker.calls if command[0] == "umount"]


def mount_paths(root):
    return [root / path for path in ("proc", "sys", "dev", "dev/pts")]


def original_files(root):
    resolv = root / "etc/resolv.conf"
    resolv.parent.mkdir(parents=True)
    resolv.symlink_to("/run/systemd/resolve/stub-resolv.conf")
    policy = root / "usr/sbin/policy-rc.d"
    policy.parent.mkdir(parents=True)
    policy.write_text("#!/bin/sh\nexit 42\n")
    policy.chmod(0o750)
    return resolv, policy


@pytest.mark.parametrize("failed_index", range(4))
def test_进入期间任一挂载失败都逆序回滚本实例已挂载项(tmp_path, failed_index):
    docker = RecordingDocker()
    paths = mount_paths(tmp_path)
    primary = BuildError("挂载失败")
    docker.failures["mount", str(paths[failed_index])] = primary
    context = ChrootContext(tmp_path, docker)

    with pytest.raises(BuildError) as caught:
        with context:
            pytest.fail("进入失败后不能执行主体")

    assert caught.value is primary
    assert unmounted(docker) == list(reversed(paths[:failed_index]))
    assert context._mounts == []


@pytest.mark.parametrize("failure_at", ["dns-copy", "policy-write", "policy-mode"])
def test_准备文件失败恢复旧配置并卸载全部挂载(tmp_path, monkeypatch, failure_at):
    resolv, policy = original_files(tmp_path)
    docker = RecordingDocker()
    primary = PermissionError("临时配置准备失败")
    if failure_at == "dns-copy":
        docker.failures["cp", str(resolv)] = primary
    else:
        method = "write_text" if failure_at == "policy-write" else "chmod"
        original = getattr(Path, method)

        def fail_policy(path, *args, **kwargs):
            if path == policy:
                raise primary
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, method, fail_policy)

    with pytest.raises(PermissionError) as caught:
        with ChrootContext(tmp_path, docker):
            pytest.fail("准备失败后不能执行主体")

    assert caught.value is primary
    assert os.readlink(resolv) == "/run/systemd/resolve/stub-resolv.conf"
    assert policy.read_text() == "#!/bin/sh\nexit 42\n"
    assert policy.stat().st_mode & 0o777 == 0o750
    assert unmounted(docker) == list(reversed(mount_paths(tmp_path)))


@pytest.mark.parametrize("kind", ["absent", "regular", "symlink"])
def test_正常退出恢复文件的缺失内容权限所有权及链接状态(tmp_path, kind):
    docker = RecordingDocker()
    paths = [tmp_path / "etc/resolv.conf", tmp_path / "usr/sbin/policy-rc.d"]
    identities = {}
    for path in paths:
        path.parent.mkdir(parents=True)
        if kind == "regular":
            path.write_text("原配置\n")
            path.chmod(0o640)
        elif kind == "symlink":
            path.symlink_to("../original-missing-file")
        if kind != "absent":
            state = path.lstat()
            identities[path] = (state.st_ino, state.st_mode, state.st_uid, state.st_gid)

    with ChrootContext(tmp_path, docker):
        assert paths[0].read_text() == "nameserver 192.0.2.1\n"
        assert paths[1].read_text() == "#!/bin/sh\nexit 101\n"
        assert not any(path.is_symlink() for path in paths)

    for path in paths:
        if kind == "absent":
            assert not path.exists() and not path.is_symlink()
        else:
            state = path.lstat()
            assert (state.st_ino, state.st_mode, state.st_uid, state.st_gid) == identities[path]
            if kind == "regular":
                assert path.read_text() == "原配置\n"
            else:
                assert os.readlink(path) == "../original-missing-file"
    assert unmounted(docker) == list(reversed(mount_paths(tmp_path)))
    assert not list(tmp_path.rglob(".*.flange-*"))


def test_恢复配置失败也尝试其他恢复和全部逆序卸载(tmp_path, monkeypatch):
    resolv, policy = original_files(tmp_path)
    docker = RecordingDocker()
    context = ChrootContext(tmp_path, docker)
    original = context._restore_file
    cleanup = PermissionError("policy 恢复失败")

    def restore(path, backup):
        if path == policy:
            raise cleanup
        original(path, backup)

    monkeypatch.setattr(context, "_restore_file", restore)
    with pytest.raises(PermissionError) as caught:
        with context:
            pass

    assert caught.value is cleanup
    assert os.readlink(resolv) == "/run/systemd/resolve/stub-resolv.conf"
    assert unmounted(docker) == list(reversed(mount_paths(tmp_path)))
    assert context._mounts == []


def test_正常退出卸载失败必须报错且继续尝试其他挂载(tmp_path):
    docker = RecordingDocker()
    busy = BuildError("device is busy")
    docker.failures["umount", str(tmp_path / "dev/pts")] = busy
    context = ChrootContext(tmp_path, docker)
    with pytest.raises(BuildError) as caught:
        with context:
            pass

    assert caught.value is busy
    assert unmounted(docker) == list(reversed(mount_paths(tmp_path)))
    assert context._mounts == [tmp_path / "dev/pts"]
    for command, kwargs in docker.calls:
        if command[0] == "umount":
            assert "-l" not in command
            assert kwargs.get("check", True)


def test_清理失败保留原构建异常实例与冻结诊断(tmp_path, monkeypatch):
    resolv, policy = original_files(tmp_path)
    docker = RecordingDocker()
    docker.failures["umount", str(tmp_path / "dev/pts")] = BuildError("device is busy")
    context = ChrootContext(tmp_path, docker)
    restore = context._restore_file
    primary = BuildError("APT 安装失败")
    diagnostic = object()
    primary._flange_command_diagnostic = diagnostic

    def fail_policy(path, backup):
        if path == policy:
            raise PermissionError("policy 恢复失败")
        restore(path, backup)

    monkeypatch.setattr(context, "_restore_file", fail_policy)
    with pytest.raises(BuildError) as caught:
        with context:
            raise primary

    assert caught.value is primary
    assert caught.value._flange_command_diagnostic is diagnostic
    assert len(primary.__notes__) == 2
    assert "policy 恢复失败" in primary.__notes__[0]
    assert "device is busy" in primary.__notes__[1]
    assert os.readlink(resolv) == "/run/systemd/resolve/stub-resolv.conf"
    assert unmounted(docker) == list(reversed(mount_paths(tmp_path)))


def test_进入失败且回滚也失败时仍保留进入异常(tmp_path):
    docker = RecordingDocker()
    primary = BuildError("dev 挂载失败")
    docker.failures["mount", str(tmp_path / "dev")] = primary
    docker.failures["umount", str(tmp_path / "sys")] = BuildError("sys 卸载失败")
    with pytest.raises(BuildError) as caught:
        with ChrootContext(tmp_path, docker):
            pass

    assert caught.value is primary
    assert unmounted(docker) == [tmp_path / "sys", tmp_path / "proc"]
    assert "sys 卸载失败" in primary.__notes__[0]
