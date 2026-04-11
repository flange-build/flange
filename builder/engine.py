"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
from pathlib import Path
from builder.app import AppBuilder
from builder.docker import DockerRunner, BuildError
from builder.flash import FlashConfigGenerator
from builder.source import SourceManager
from builder.cache import BuildCache
from builder.output import BuildOutput, OutputLevel

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


def _resolve_output_level(config: dict) -> OutputLevel:
    """从 config 解析输出级别。"""
    if config.get("verbose"):
        return OutputLevel.VERBOSE
    if config.get("quiet"):
        return OutputLevel.QUIET
    return OutputLevel.NORMAL


class BuildEngine:
    """构建引擎 — 按依赖图调度组件构建。"""

    def __init__(self, config: dict, project_dir: Path = None):
        self.config = config
        self.project_dir = project_dir or Path.cwd()
        self.cache = BuildCache(config)

        # 统一输出
        level = _resolve_output_level(config)
        self.output = BuildOutput(self.cache.target_dir, level=level)
        self.docker = DockerRunner(self.project_dir, output=self.output)
        self.source = SourceManager(self.project_dir / "sources")
        self._outputs = {}

    def build(self, target: str = "image"):
        self.output.build_start(target, self.config)
        try:
            self._build_components(target)
        except BuildError as e:
            self.output.build_end()
            raise
        except Exception as e:
            self.output.build_end()
            raise

        # image 构建完成后生成 flash-config.json
        if target == "image":
            self._generate_flash_config()

        self.output.build_end()

    def _build_components(self, target: str):
        for component in _topo_sort(DEPENDENCY_GRAPH, target):
            if self.cache.is_up_to_date(component):
                self.output.phase_skip(component)
                continue
            self.output.phase_start(component)
            try:
                if component == "app":
                    outputs = self._build_app()
                else:
                    builder = self._get_builder(component)
                    builder.cache = self.cache
                    builder.output = self.output
                    outputs = builder.build(self.config)
                self._outputs[component] = outputs
                self.cache.store(component)
                self.output.phase_end(component, success=True)
            except (BuildError, Exception) as e:
                self.output.phase_end(component, success=False, error=e)
                raise

    def _build_app(self) -> dict:
        """使用 AppBuilder 构建所有自定义 App，返回 {app_name: deb_path} 映射。"""
        builder = AppBuilder(
            self.docker,
            self.source,
            self.config,
            project_dir=self.project_dir,
        )
        builder.output = self.output
        return builder.build_all()

    def _generate_flash_config(self):
        """image 构建完成后生成 flash-config.json。"""
        target_dir = self.cache.target_dir
        try:
            gen = FlashConfigGenerator()
            gen.generate(self.config, target_dir)
            self.output.status("flash-config.json 已生成")
        except Exception as e:
            self.output.warning(f"flash-config.json 生成失败: {e}")

    def _get_builder(self, component: str):
        platform = self.config["platform"]
        mod = importlib.import_module(f"builder.platforms.{platform}")
        return mod.create_builder(component, self.docker, self.source)
