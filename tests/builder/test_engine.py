"""调度、上下文、原子产物发布和取消的集成契约。"""

import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.artifacts import ArtifactSpec
from builder.engine import BuildEngine
from builder.graph import InputSpec, TaskPlan
from builder.workspace import Target, WorkspaceContext


def setup(tmp_path, monkeypatch):
    context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    engine = BuildEngine({'platform': 'rockchip', 'board': 'board', 'product': 'default', 'variant': 'release'}, context=context, output=MagicMock())
    monkeypatch.setattr('builder.engine.DEPENDENCY_GRAPH', {'kernel': [], 'boot': ['kernel']})
    events = []
    engine.source.prepare_cache_inputs = lambda name, config: events.append(('prepare', name))

    def plan(name):
        events.append(('plan', name))
        return TaskPlan(name, f'{name}-v1', (InputSpec.value('config', {}),),
                        (ArtifactSpec(name, context.target_dir / name / f'{name}.img', allow_empty=False),),
                        ('kernel',) if name == 'boot' else ())

    engine._plan_component = plan
    engine._get_artifact_names = lambda: {}

    class Recipe:
        def execute(self, plan):
            assert self.context is context
            events.append(('execute', plan.task_id))
            work = context.build_root / 'work' / plan.task_id
            work.mkdir(parents=True, exist_ok=True)
            file = work / f'{plan.task_id}.img'
            file.write_text(plan.task_id)
            return {plan.task_id: file}

    engine._get_builder = lambda name: Recipe()
    return engine, events


def test_先准备源码后查询计划且第二次跳过执行(tmp_path, monkeypatch):
    engine, events = setup(tmp_path, monkeypatch)
    engine.build('boot')
    assert events == [('prepare', 'kernel'), ('plan', 'kernel'), ('execute', 'kernel'),
                      ('prepare', 'boot'), ('plan', 'boot'), ('execute', 'boot')]
    events.clear()
    engine.build('boot')
    assert not any(event[0] == 'execute' for event in events)
    assert engine.cache.load('kernel').validate()
    assert engine.cache.load('boot').validate()
    engine.output.build_end.assert_called_with(success=True)


def test_损坏依赖产物触发重建下游按实际结果复用(tmp_path, monkeypatch):
    engine, events = setup(tmp_path, monkeypatch)
    engine.build('boot')
    (engine.context.target_dir / 'kernel/kernel.img').write_text('corrupt')
    events.clear()
    engine.build('boot')
    assert ('execute', 'kernel') in events
    assert ('execute', 'boot') not in events


def test_强制构建且原子目录发布删除旧残留(tmp_path, monkeypatch):
    engine, events = setup(tmp_path, monkeypatch)
    engine.build('kernel')
    stale = engine.context.target_dir / 'kernel/stale.img'
    stale.write_text('old')
    engine.build('kernel', force='kernel')
    assert not stale.exists()
    assert sum(event == ('execute', 'kernel') for event in events) == 2


def test_发布的产物目录宿主机可读(tmp_path, monkeypatch):
    """容器内 root 发布的产物要让宿主机刷写进程读得到。"""
    engine, _ = setup(tmp_path, monkeypatch)
    engine.build('kernel')
    mode = stat.S_IMODE((engine.context.target_dir / 'kernel').stat().st_mode)
    assert mode & 0o055 == 0o055, f'产物目录权限 {mode:04o} 宿主机无法读取'


def test_失败或取消不发布成功manifest(tmp_path, monkeypatch):
    engine, events = setup(tmp_path, monkeypatch)

    class Cancel:
        def execute(self, plan):
            raise KeyboardInterrupt()

    engine._get_builder = lambda _: Cancel()
    with pytest.raises(KeyboardInterrupt):
        engine.build('kernel')
    assert engine.cache.load('kernel') is None
    engine.output.build_end.assert_called_with(success=False)
    assert engine.output.phase_end.call_args.kwargs['success'] is False


def test_缺产物不替换上次完整结果(tmp_path, monkeypatch):
    engine, events = setup(tmp_path, monkeypatch)
    engine.build('kernel')
    identity = engine.cache.load('kernel').identity

    class Missing:
        def execute(self, plan):
            return {}

    engine._get_builder = lambda _: Missing()
    with pytest.raises(ValueError, match='缺少必需产物'):
        engine.build('kernel', force='all')
    assert engine.cache.load('kernel').identity == identity
    assert engine.cache.load('kernel').validate()


def test_纯查询不创建目录或输出文件(tmp_path):
    context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    engine = BuildEngine({'platform': 'rockchip', 'board': 'board', 'product': 'default', 'variant': 'release', 'kernel': {
        'device_tree': {'directory': '', 'name': 'board'}}}, context=context)
    assert engine.plan('kernel')[0].task_id == 'kernel'
    assert engine.explain('kernel')[0]['status'] in {'miss', 'blocked'}
    assert engine.output is None
    assert not context.build_root.exists()


def test_产物路径越界不能在暂存区之外写入(tmp_path, monkeypatch):
    engine, _ = setup(tmp_path, monkeypatch)
    source = tmp_path / 'data'
    source.write_text('data')
    engine._get_artifact_names = lambda: {('kernel', 'kernel'): '../outside'}
    with pytest.raises(ValueError, match='产物文件名'):
        engine._collect_artifacts(engine._plan_component('kernel'), {'kernel': source})
    assert not (engine.context.target_dir / 'outside').exists()


def test_配置目标与工作区不一致在执行前拒绝(tmp_path):
    context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'product', 'debug'))
    with pytest.raises(ValueError, match='目标与工作区不一致'):
        BuildEngine({'board': 'board', 'product': 'other', 'variant': 'debug'}, context=context)
    assert not context.build_root.exists()


def test_构造后调用方修改字典不改变已接受配置(tmp_path):
    context = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    config = {'board': 'board', 'product': 'default', 'variant': 'release', 'kernel': {'defconfig': ['base']}}
    engine = BuildEngine(config, context=context)
    config['kernel']['defconfig'].append('mutation')
    assert engine.config['kernel']['defconfig'] == ['base']
