"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
import shutil
import subprocess
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


def _copy_sparse(src: Path, dest: Path) -> None:
    """复制文件产物，保留空洞。

    ``mke2fs -d`` 造出的 rootfs.img 与 image 的 raw.img 都高度稀疏（实测 4GiB
    声明只占 2.2MiB），而 ``shutil.copy2`` 不做空洞检测、会把整个声明尺寸实写
    成零，一次产物收集就要多写数 GiB。

    用 GNU cp 的默认 ``--sparse=auto``：读到全零块时 seek 而不写，实测在
    Docker Desktop 的 bind mount 上能把稀疏完整带到宿主机。**不要**改成
    ``--sparse=always`` —— 它写完后还要 punch hole，而 virtiofs 不支持，会以
    "error deallocating" 失败（实测）。没有 GNU cp 时回退 copy2 保证正确性。
    """
    try:
        subprocess.run(
            ["cp", "--sparse=auto", "--preserve=mode,timestamps",
             str(src), str(dest)],
            check=True, capture_output=True,
        )
        return
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        shutil.copy2(src, dest)


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
        self.cache = BuildCache(config, project_root=self.project_dir)

        # 统一输出
        level = _resolve_output_level(config)
        self.output = BuildOutput(self.cache.target_dir, level=level)
        self.docker = DockerRunner(self.project_dir, output=self.output)
        self.source = SourceManager(
            sources_dir=self.project_dir / ".build" / "sources",
            project_root=self.project_dir,
        )
        self._outputs = {}

    def build(self, target: str = "image", force=None):
        """force：强制重建（绕过缓存校验）。None=正常缓存；组件名=只强制该组件；
        "all"=强制所有组件。由 `flange build -f` 传入——不再由宿主用户删 root 拥有的
        .build_hash（删不动），改在引擎跳过 is_up_to_date，构建后照常 store 覆盖 hash。"""
        self.output.build_start(target, self.config)
        try:
            self._build_components(target, force)
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

    def _build_components(self, target: str, force=None):
        order = _topo_sort(DEPENDENCY_GRAPH, target)
        # 拓扑序在进入循环前就已知，交给输出层用于显示 [i/N] 与总进度
        self.output.plan([c for c in order if not self._component_disabled(c)])
        for component in order:
            if self._component_disabled(component):
                # 静默跳过；image 等下游会感知到 recovery 缺产物从而跳过
                # 对应分区的 dd / flash-config 注入。
                self.output.phase_skip(component, reason="disabled")
                continue
            forced = force == "all" or force == component
            if not forced:
                self.source.prepare_cache_inputs(component, self.config)
                if self.cache.is_up_to_date(component):
                    self.output.phase_skip(component)
                    continue
            self.output.phase_start(component)
            try:
                if component == "app":
                    outputs = self._build_app(force=forced)
                else:
                    builder = self._get_builder(component)
                    builder.cache = self.cache
                    builder.output = self.output
                    outputs = builder.build(self.config)
                self._outputs[component] = outputs
                self._collect_artifacts(component, outputs)
                if not self.cache._required_artifacts_present(component):
                    required = ", ".join(
                        self.cache._required_artifacts(component))
                    raise BuildError(
                        f"{component} 构建完成但缺少必需产物: {required}")
                self.cache.store(component)
                self.output.phase_end(component, success=True)
            except Exception as e:
                self.output.phase_end(component, success=False, error=e)
                raise

    def _component_disabled(self, component: str) -> bool:
        """组件是否被 config 显式关闭。

        recovery 与 amp 受配置开关控制：当 ``config.<comp>.enabled is False``
        时不进入构建图执行，也不为其收集产物。
        """
        if component == "recovery":
            return not (self.config.get("recovery") or {}).get("enabled", False)
        # amp 协处理器固件按 config.amp.enabled 门控（默认关）：未启用时静默跳过，
        # 下游 image/flash 因 amp.img 缺失自动跳过 amp 分区。
        if component == "amp":
            return not (self.config.get("amp") or {}).get("enabled", False)
        return False

    def _build_app(self, force: bool = False) -> dict:
        """使用 AppBuilder 构建所有自定义 App，返回 {app_name: deb_path} 映射。

        注入 cache 后 AppBuilder 会做 per-App 增量：组件级哈希失效只表示
        "App 集合里有东西变了"，具体重建哪些由 build_all 逐个判定。
        """
        builder = AppBuilder(
            self.docker,
            self.source,
            self.config,
            project_dir=self.project_dir,
        )
        builder.output = self.output
        builder.cache = self.cache
        return builder.build_all(force=bool(force))

    def _get_artifact_names(self) -> dict:
        """从当前平台模块获取产物名映射。

        各平台 __init__.py 导出 ARTIFACT_NAMES 常量；
        未在表中的 key 保持源文件原始文件名。
        """
        platform = self.config["platform"]
        mod = importlib.import_module(f"builder.platforms.{platform}")
        return getattr(mod, "ARTIFACT_NAMES", {})

    def _collect_artifacts(self, component: str, outputs: dict):
        """将构建产物复制到 target 目录，供刷写使用。

        文件产物用稀疏拷贝（见 _copy_sparse），目录产物用 shutil.copytree
        （先删旧目录）。
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
                raise BuildError(f"{component} 声明的构建产物不存在: {src}")
            filename = self._get_artifact_names().get((component, key), src.name)
            dest = component_dir / filename
            if src.resolve() == dest.resolve():
                continue
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest, symlinks=True)
            else:
                _copy_sparse(src, dest)
        self.output.status("产物收集")

    def _generate_flash_config(self):
        """image 构建完成后生成 flash-config.json。"""
        target_dir = self.cache.target_dir
        try:
            gen = FlashConfigGenerator()
            gen.generate(self.config, target_dir)
            self.output.status("flash-config.json 已生成")
        except Exception as e:
            raise BuildError(f"flash-config.json 生成失败: {e}") from e

    def _get_builder(self, component: str):
        # device-tree-overlay 组件 vendor 无关，直接路由到统一 builder，
        # 不进入 platform.create_builder 分派；vendor 通过 config["vendor"]
        # 在 builder 内部解析。
        if component == "device-tree-overlay":
            from builder.overlays import OverlaysBuilder
            return OverlaysBuilder(self.docker, self.source)
        platform = self.config["platform"]
        mod = importlib.import_module(f"builder.platforms.{platform}")
        return mod.create_builder(component, self.docker, self.source)
