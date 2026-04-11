"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
import logging
from pathlib import Path
from builder.docker import DockerRunner
from builder.source import SourceManager
from builder.cache import BuildCache

log = logging.getLogger("flange")

DEPENDENCY_GRAPH = {
    "kernel":     [],
    "bootloader": [],
    "rootfs":     [],
    "boot":       ["kernel"],
    "image":      ["boot", "bootloader", "rootfs"],
}


def _topo_sort(graph: dict, target: str) -> list:
    """拓扑排序，返回构建顺序。"""
    visited = set()
    order = []
    def visit(node):
        if node in visited:
            return
        visited.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        order.append(node)
    visit(target)
    return order


class BuildEngine:
    """构建引擎 — 按依赖图调度组件构建。"""

    def __init__(self, config: dict, project_dir: Path = None):
        self.config = config
        self.project_dir = project_dir or Path.cwd()
        self.docker = DockerRunner(self.project_dir)
        self.source = SourceManager(self.project_dir / "sources")
        self.cache = BuildCache(config)
        self._outputs = {}

    def build(self, target: str = "image"):
        for component in _topo_sort(DEPENDENCY_GRAPH, target):
            if self.cache.is_up_to_date(component):
                log.info(f"  {component}: 无变更，跳过")
                continue
            log.info(f"  {component}: 开始构建...")
            builder = self._get_builder(component)
            outputs = builder.build(self.config)
            self._outputs[component] = outputs
            self.cache.store(component)
            log.info(f"  {component}: 完成")

    def _get_builder(self, component: str):
        platform = self.config["platform"]
        mod = importlib.import_module(f"builder.platforms.{platform}")
        return mod.create_builder(component, self.docker, self.source)
