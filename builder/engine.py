"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
import logging
from pathlib import Path
from builder.app import AppBuilder
from builder.docker import DockerRunner
from builder.source import SourceManager
from builder.cache import BuildCache

log = logging.getLogger("flange")

# 组件依赖图：键为组件名，值为该组件依赖的组件列表。
# app 组件无需依赖其他组件（独立构建）；
# rootfs 依赖 app，确保 .deb 包在 rootfs 构建前已就绪。
DEPENDENCY_GRAPH = {
    "kernel":     [],
    "bootloader": [],
    "app":        [],               # 新增：App 构建无依赖
    "rootfs":     ["app"],          # 修改：rootfs 依赖 app（需要 .deb 文件）
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
            if component == "app":
                # app 组件使用 AppBuilder，接口与平台策略构建器不同
                outputs = self._build_app()
            else:
                builder = self._get_builder(component)
                outputs = builder.build(self.config)
            self._outputs[component] = outputs
            self.cache.store(component)
            log.info(f"  {component}: 完成")

    def _build_app(self) -> dict:
        """使用 AppBuilder 构建所有自定义 App，返回 {app_name: deb_path} 映射。"""
        builder = AppBuilder(
            self.docker,
            self.source,
            self.config,
            project_dir=self.project_dir,
        )
        return builder.build_all()

    def _get_builder(self, component: str):
        platform = self.config["platform"]
        mod = importlib.import_module(f"builder.platforms.{platform}")
        return mod.create_builder(component, self.docker, self.source)
