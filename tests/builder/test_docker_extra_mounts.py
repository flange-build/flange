"""DockerRunner.extra_mounts 单元测试。

覆盖三个场景：
- _run_docker 分支：extra_mounts 拼成 `-v <realpath>:<realpath>:rw`
- symlink 路径经 realpath 解析后挂载
- _run_direct 分支（容器内）忽略 extra_mounts
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.docker import DockerRunner


class TestExtraMountsRunDocker:
    """容器外 _run_docker 分支的 extra_mounts 拼接。"""

    @patch("builder.docker._is_inside_container", return_value=False)
    def test_extra_mounts_拼成_v参数(self, mock_container, tmp_path):
        """传入 extra_mounts 时，docker compose run 命令含 -v src:src:rw。"""
        target = tmp_path / "ext-app"
        target.mkdir()

        runner = DockerRunner(project_dir=tmp_path)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run(["echo", "hello"], extra_mounts=[target])

        # 取出实际调用的命令列表
        args, _ = mock_run.call_args
        cmd = args[0]
        real = os.path.realpath(str(target))
        # docker compose run --rm -v <real>:<real>:rw ... build echo hello
        assert "-v" in cmd
        v_index = cmd.index("-v")
        assert cmd[v_index + 1] == f"{real}:{real}:rw"
        assert "build" in cmd
        assert "echo" in cmd and "hello" in cmd

    @patch("builder.docker._is_inside_container", return_value=False)
    def test_无_extra_mounts_时不注入_v(self, mock_container, tmp_path):
        """未传 extra_mounts 时 docker compose run 命令中无 -v。"""
        runner = DockerRunner(project_dir=tmp_path)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run(["echo", "x"])

        args, _ = mock_run.call_args
        cmd = args[0]
        assert "-v" not in cmd

    @patch("builder.docker._is_inside_container", return_value=False)
    def test_多条_extra_mounts_全部注入(self, mock_container, tmp_path):
        """多条 extra_mounts 时，每条都产生一组 -v。"""
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()

        runner = DockerRunner(project_dir=tmp_path)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run(["true"], extra_mounts=[a, b])

        args, _ = mock_run.call_args
        cmd = args[0]
        v_args = [cmd[i + 1] for i, t in enumerate(cmd) if t == "-v"]
        real_a = os.path.realpath(str(a))
        real_b = os.path.realpath(str(b))
        assert f"{real_a}:{real_a}:rw" in v_args
        assert f"{real_b}:{real_b}:rw" in v_args


class TestExtraMountsRealpath:
    """挂载源路径必须经 os.path.realpath 解析。"""

    @patch("builder.docker._is_inside_container", return_value=False)
    def test_symlink_路径经_realpath_解析(self, mock_container, tmp_path):
        """传入的路径含 symlink 时，-v 用的是 deref 后的真实路径。"""
        real_dir = tmp_path / "real" / "foo"
        real_dir.mkdir(parents=True)
        link_dir = tmp_path / "link"
        link_dir.symlink_to(tmp_path / "real")

        # 通过 symlink 访问
        symlinked = link_dir / "foo"

        runner = DockerRunner(project_dir=tmp_path)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run(["true"], extra_mounts=[symlinked])

        args, _ = mock_run.call_args
        cmd = args[0]
        # symlink 一定 deref 到 real_dir
        deref = os.path.realpath(str(symlinked))
        assert deref == os.path.realpath(str(real_dir))
        assert f"{deref}:{deref}:rw" in cmd


class TestExtraMountsRunDirect:
    """容器内 _run_direct 分支必须忽略 extra_mounts。"""

    @patch("builder.docker._is_inside_container", return_value=True)
    def test_run_direct_忽略_extra_mounts(self, mock_container, tmp_path):
        """已在容器内时，extra_mounts 不会被传递到 subprocess.run。"""
        target = tmp_path / "ext"
        target.mkdir()

        runner = DockerRunner(project_dir=tmp_path)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run(["echo", "x"], extra_mounts=[target])

        args, _ = mock_run.call_args
        cmd = args[0]
        # _run_direct 直接 subprocess.run([str(c) for c in cmd])，
        # 命令应当是原 cmd，不含 docker / -v 等参数
        assert "-v" not in cmd
        assert "docker" not in cmd
        assert cmd == ["echo", "x"]
