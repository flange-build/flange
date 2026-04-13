"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
import shutil
from pathlib import Path
from builder.app import AppBuilder
from builder.docker import DockerRunner, BuildError
from builder.flash import FlashConfigGenerator
from builder.source import SourceManager
from builder.cache import BuildCache, DEPENDENCY_GRAPH
from builder.output import BuildOutput, OutputLevel


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
                self._collect_artifacts(component, outputs)
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

    # (组件, collect key) → target 目录下的文件名/目录名。
    # 未在表中的 key 保持源文件原始文件名。
    _ARTIFACT_NAMES = {
        ("kernel",     "dtbos"):      "overlay",   # DTB overlay 目录
        ("kernel",     "modules"):    "modules",   # 内核模块 staging 目录
        ("bootloader", "bootloader"): "u-boot.itb",
        ("bootloader", "idbloader"):  "idbloader.img",
        ("bootloader", "miniloader"): "miniloader.bin",
        ("boot",       "boot"):       "boot.img",
        ("rootfs",     "rootfs"):     "rootfs.img",
        ("image",      "image"):      "raw.img",
    }

    def _collect_artifacts(self, component: str, outputs: dict):
        """将构建产物复制到 target 目录，供刷写使用。

        文件产物用 shutil.copy2，目录产物用 shutil.copytree（先删旧目录）。
        """
        if not outputs:
            return
        component_dir = self.cache.target_dir / component
        component_dir.mkdir(parents=True, exist_ok=True)
        for key, src_path in outputs.items():
            if src_path is None:
                continue
            src = Path(src_path)
            if not src.exists():
                continue
            filename = self._ARTIFACT_NAMES.get((component, key), src.name)
            dest = component_dir / filename
            if src.resolve() == dest.resolve():
                continue
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest, symlinks=True)
            else:
                shutil.copy2(src, dest)
        self.output.status("产物收集")

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
