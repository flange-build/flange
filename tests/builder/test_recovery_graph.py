"""recovery 组件在构建图与缓存中的位置测试。

覆盖 Recovery 引导的构建依赖与组件过滤：
- image 构建顺序包含 recovery 且位于 image 之前
- recovery 必须在 kernel / app 就绪后执行，关闭后跳过执行
"""

from __future__ import annotations

import pytest

from builder.graph import DEPENDENCY_GRAPH, component_enabled, topological_order
from builder.engine import _topo_sort


# ── 依赖图与拓扑排序 ────────────────────────────────────────────────


class TestRecoveryDependencyGraph:


    def test_topo_sort_image_includes_recovery_before_image(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert "recovery" in order
        assert order.index("recovery") < order.index("image")

    def test_topo_sort_image_orders_recovery_after_kernel_and_app(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "image")
        assert order.index("kernel") < order.index("recovery")
        assert order.index("app") < order.index("recovery")

    def test_topo_sort_recovery_does_not_pull_image(self):
        order = _topo_sort(DEPENDENCY_GRAPH, "recovery")
        assert "image" not in order
        assert "recovery" in order
        assert "kernel" in order
        assert "app" in order

    def test_disabled_recovery仍在图中但不参与执行(self):
        assert not component_enabled({'recovery': {'enabled': False}}, 'recovery')


def test_未知任务与依赖环给明确错误():
    with pytest.raises(ValueError, match='未知构建任务'):
        topological_order(DEPENDENCY_GRAPH, ['missing'])
    with pytest.raises(ValueError, match='a → b → a'):
        topological_order({'a': ['b'], 'b': ['a']}, ['a'])
