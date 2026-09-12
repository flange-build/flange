"""只读命令（plan / why）转发进容器执行的单元测试。

源码仓库由容器内的 root clone 出来，归 root:root；git 的 safe.directory 保护按
owner uid 判定仓库可信与否（与权限位无关），宿主机上以普通用户跑 `git rev-parse`
一律 exit 128。build 早就整个转发进容器执行，只读命令没有，于是成了唯一在宿主机
侧读这些仓库的路径。把它们也转发进容器，宿主机只负责渲染。

覆盖命令构造、结果解包、错误传播，以及"已在容器内不再嵌套转发"。
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from builder.commands import _readonly_via_container
from tests.builder.context import component_context


def _completed(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(stdout=json.dumps(payload, ensure_ascii=False), stderr="", returncode=0)


@pytest.fixture
def context(tmp_path: Path):
    return component_context(tmp_path)


class Test只读命令转发:
    def test_命令构造带上工作区与目标和json(self, context):
        """容器内那一侧必须拿到同样的工作区与目标，否则算出的是另一个配置。"""
        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {"schema_version": 1, "command": "plan", "ok": True, "data": {"tasks": []}}
            )
            _readonly_via_container(context, "plan", "kernel")
        cmd = runner_cls.return_value.run.call_args[0][0]
        assert cmd[:3] == ["python3", "-m", "builder"]
        assert "--workspace" in cmd and str(context.workspace_root) in cmd
        assert "--target" in cmd and context.target.key in cmd
        assert "plan" in cmd and "kernel" in cmd
        assert "--json" in cmd, f"必须让容器侧输出结构化结果，实际 {cmd}"

    def test_component为空时不追加位置参数(self, context):
        """flange why 不带组件时要解释整个计划闭包，不能传个空串进去。"""
        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {"schema_version": 1, "command": "why", "ok": True, "data": []}
            )
            _readonly_via_container(context, "why", None)
        cmd = runner_cls.return_value.run.call_args[0][0]
        assert "" not in cmd, f"空组件不该进命令行，实际 {cmd}"

    def test_解包出data(self, context):
        """宿主机只渲染，数据必须原样取自容器侧的 data 字段。"""
        expected = {"tasks": [{"task_id": "kernel"}]}
        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {"schema_version": 1, "command": "plan", "ok": True, "data": expected}
            )
            assert _readonly_via_container(context, "plan", None) == expected

    def test_只读不申请特权(self, context):
        """plan / why 不写任何东西，没有理由拿 privileged。"""
        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {"schema_version": 1, "command": "plan", "ok": True, "data": {}}
            )
            _readonly_via_container(context, "plan", None)
        assert runner_cls.return_value.run.call_args.kwargs.get("privileged", False) is False

    def test_容器侧报错要带原因抛出(self, context):
        """容器里失败却在宿主机静默成空计划，是最难查的那种故障。"""
        from builder.docker import BuildError

        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {
                    "schema_version": 1,
                    "command": "plan",
                    "ok": False,
                    "error": {"kind": "operation", "message": "源码尚未准备"},
                }
            )
            with pytest.raises(BuildError, match="源码尚未准备"):
                _readonly_via_container(context, "plan", None)

    def test_输出不是JSON时报错可诊断(self, context):
        """镜像缺失等情况下 compose 会往 stdout 吐非 JSON，不能抛 JSONDecodeError。"""
        from builder.docker import BuildError

        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = SimpleNamespace(
                stdout="Cannot connect to the Docker daemon", stderr="", returncode=0
            )
            with pytest.raises(BuildError, match="Docker daemon"):
                _readonly_via_container(context, "plan", None)

    def test_不创建构建目录(self, context):
        """契约：干净工作区查询计划不得落下目录、锁、日志或下载内容。

        转发进容器后，容器挂载逻辑会 mkdir 构建根——只读命令必须显式关掉它，
        否则一次 plan 就在干净工作区留下 .build。
        """
        with patch("builder.docker.DockerRunner") as runner_cls:
            runner_cls.return_value.run.return_value = _completed(
                {"schema_version": 1, "command": "plan", "ok": True, "data": {}}
            )
            _readonly_via_container(context, "plan", None)
        kwargs = runner_cls.return_value.run.call_args.kwargs
        assert kwargs.get("ensure_build_root") is False, (
            f"只读命令不得创建构建根，实际 {kwargs}"
        )
        assert not context.build_root.exists()
