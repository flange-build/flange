"""计划缓存的成功、失效、损坏和发布边界。"""

from dataclasses import replace
from pathlib import Path

import pytest

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.cache import BuildCache
from builder.graph import InputSpec, TaskPlan
from builder.workspace import Target, WorkspaceContext


def context(tmp_path):
    return WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))


def plan_for(ctx, value=1, *, dependencies=()):
    return TaskPlan('kernel', 'test-kernel-v1', (InputSpec.value('config', {'value': value}),),
                    (ArtifactSpec('image', ctx.target_dir / 'kernel/Image', allow_empty=False),
                     ArtifactSpec('modules', ctx.target_dir / 'kernel/modules', kind='tree')),
                    dependencies)


def materialize(plan):
    for spec in plan.outputs:
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        if spec.kind == 'tree':
            spec.path.mkdir(exist_ok=True)
        else:
            spec.path.write_bytes(b'artifact')


def test_构造查询只读且旧成功标记不命中(tmp_path):
    ctx = context(tmp_path)
    cache = BuildCache(context=ctx)
    plan = plan_for(ctx)
    assert cache.explain(plan)['status'] == 'miss'
    assert not ctx.build_root.exists()
    materialize(plan)
    (ctx.target_dir / 'kernel/.build_hash').write_text(plan.fingerprint().digest)
    assert not cache.is_up_to_date(plan)


def test_成功发布并逐项验证产物(tmp_path):
    ctx = context(tmp_path)
    cache, plan = BuildCache(context=ctx), plan_for(ctx)
    materialize(plan)
    manifest = cache.store(plan, plan.fingerprint(), {})
    assert manifest.validate() and cache.is_up_to_date(plan)
    assert ArtifactManifest.load(cache.manifest_path('kernel')) == manifest
    plan.outputs[1].path.rmdir()
    assert cache.explain(plan)['status'] == 'miss'
    assert 'modules' in ' '.join(cache.explain(plan)['reasons'])


def test_内容权限符号链接变更均拒绝命中(tmp_path):
    ctx = context(tmp_path)
    cache, plan = BuildCache(context=ctx), plan_for(ctx)
    materialize(plan)
    link = plan.outputs[1].path / 'current'
    link.symlink_to('version-a')
    cache.store(plan, plan.fingerprint(), {})
    plan.outputs[0].path.chmod(0o700)
    assert not cache.is_up_to_date(plan)
    cache.store(plan, plan.fingerprint(), {})
    link.unlink()
    link.symlink_to('version-b')
    assert not cache.is_up_to_date(plan)
    cache.store(plan, plan.fingerprint(), {})
    plan.outputs[0].path.write_bytes(b'changed')
    assert not cache.is_up_to_date(plan)


def test_缺少模块或空镜像不能发布(tmp_path):
    ctx = context(tmp_path)
    cache, plan = BuildCache(context=ctx), plan_for(ctx)
    plan.outputs[0].path.parent.mkdir(parents=True)
    plan.outputs[0].path.write_bytes(b'image')
    with pytest.raises(ValueError):
        cache.store(plan, plan.fingerprint(), {})
    plan.outputs[1].path.mkdir()
    plan.outputs[0].path.write_bytes(b'')
    with pytest.raises(ValueError):
        cache.store(plan, plan.fingerprint(), {})
    assert cache.load('kernel') is None


def test_解释列出具名输入变化(tmp_path):
    ctx = context(tmp_path)
    cache, plan = BuildCache(context=ctx), plan_for(ctx)
    materialize(plan)
    cache.store(plan, plan.fingerprint(), {})
    result = cache.explain(plan_for(ctx, 2))
    assert result['changed_inputs'] == ['input:config']


def test_执行期间源码变化拒绝发布(tmp_path):
    ctx = context(tmp_path)
    source = tmp_path / 'source'
    source.write_text('before')
    plan = replace(plan_for(ctx), inputs=(InputSpec.file('source', source),))
    materialize(plan)
    before = plan.fingerprint()
    source.write_text('after')
    cache = BuildCache(context=ctx)
    with pytest.raises(RuntimeError, match='输入发生变化'):
        cache.store(plan, before, {})
    assert cache.load('kernel') is None


def test_损坏manifest与错误路径不能命中(tmp_path):
    ctx = context(tmp_path)
    cache, plan = BuildCache(context=ctx), plan_for(ctx)
    materialize(plan)
    cache.store(plan, plan.fingerprint(), {})
    moved = replace(plan, outputs=(replace(plan.outputs[0], path=tmp_path / 'other'), plan.outputs[1]))
    assert not cache.is_up_to_date(moved)
    cache.manifest_path('kernel').write_text('{partial')
    assert cache.load('kernel') is None


def test_下游依赖产物身份而非上游输入摘要(tmp_path):
    ctx = context(tmp_path)
    cache, upstream = BuildCache(context=ctx), plan_for(ctx)
    materialize(upstream)
    first = cache.store(upstream, upstream.fingerprint(), {})
    downstream = TaskPlan('boot', 'boot-v1', (), (), ('kernel',))
    cache.store(downstream, downstream.fingerprint({'kernel': first.identity}), {'kernel': first})
    changed_inputs = plan_for(ctx, 2)
    second = cache.store(changed_inputs, changed_inputs.fingerprint(), {})
    assert first.input_digest != second.input_digest
    assert first.identity == second.identity
    assert cache.is_up_to_date(downstream, {'kernel': second})
    upstream.outputs[0].path.write_bytes(b'new-kernel')
    third = cache.store(changed_inputs, changed_inputs.fingerprint(), {})
    assert third.identity != second.identity
    result = cache.explain(downstream, {'kernel': third})
    assert result['changed_inputs'] == ['dep:kernel']
