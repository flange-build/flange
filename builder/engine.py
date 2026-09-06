"""计划驱动的构建调度；渲染由输出层负责。"""

from __future__ import annotations

import copy
from builder.platforms.spec import load_for as load_platform
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from builder.app import AppBuilder
from builder.artifacts import Artifact, ArtifactSpec
from builder.cache import BuildCache
from builder.component_plan import create_component_plan
from builder.config.apps import gather_custom_packages
from builder.docker import DockerRunner, BuildError
from builder.flash import FlashConfigGenerator
from builder.graph import (
    DEPENDENCY_GRAPH,
    InputSpec,
    TaskPlan,
    component_enabled,
    topological_order,
)
from builder.locking import FileLock
from builder.output import BuildOutput, OutputLevel
from builder.source import SourceManager
from builder.workspace import WorkspaceContext


def _topo_sort(graph: dict, target: str) -> list:
    return topological_order(graph, [target])


def _copy_sparse(src: Path, dest: Path) -> None:
    """GNU cp 保留稀疏镜像；非 GNU 宿主用于测试时回退普通复制。"""
    try:
        subprocess.run(
            ["cp", "--sparse=auto", "--preserve=mode,timestamps", str(src), str(dest)],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        shutil.copy2(src, dest)


class BuildEngine:
    """WorkspaceContext 定位资源，TaskPlan 决定执行，manifest 决定复用。"""

    def __init__(
        self,
        config: dict,
        *,
        context: WorkspaceContext,
        output=None,
        output_level: OutputLevel = OutputLevel.NORMAL,
    ):
        identity = {
            "board": config.get("board"),
            "product": config.get("product"),
            "variant": config.get("variant"),
        }
        if identity != context.target.to_dict():
            raise ValueError(
                f"构建配置目标与工作区不一致: {identity} != {context.target.to_dict()}"
            )
        from builder.config.jsonnet import ResolvedConfig

        self.config = ResolvedConfig(copy.deepcopy(config))
        self.config.layer_stack = context.layer_stack
        self.context = context
        self.project_dir = context.tool_root
        self.cache = BuildCache(context=context)
        self.output = output
        self.output_level = output_level
        self.docker = DockerRunner(context=context, output=output)
        self.source = SourceManager(context=context)
        self._outputs = {}
        self._app_report = None

    def _app_builder(self):
        builder = AppBuilder(self.docker, self.source, self.config, context=self.context)
        builder.output = self.output
        return builder

    def _plan_component(self, component: str) -> TaskPlan:
        plan = create_component_plan(component, self.config, self.context, self.source)
        if component != "app":
            return plan
        inputs = list(plan.inputs)
        try:
            app_plans = self._app_builder().plan(gather_custom_packages(self.config))
        except (ValueError, FileNotFoundError) as exc:
            inputs.append(InputSpec.value("apps:unresolved", {"unresolved": str(exc)}))
        else:
            for node in app_plans:
                inputs.append(InputSpec.value(f"app:{node.task_id}:recipe", node.recipe))
                inputs.extend(
                    replace(value, name=f"app:{node.task_id}:{value.name}") for value in node.inputs
                )
        return replace(
            plan,
            inputs=tuple(inputs),
            outputs=(
                ArtifactSpec(
                    "report", self.context.target_dir / "apps/build-report.json", allow_empty=False
                ),
            ),
        )

    def plan(self, target: str = "image") -> tuple[TaskPlan, ...]:
        """只读计划：未准备源码以 unresolved 输入表示，绝不隐式 fetch。"""
        return tuple(self._plan_component(name) for name in _topo_sort(DEPENDENCY_GRAPH, target))

    def explain(self, target: str = "image") -> list[dict]:
        results = []
        states = {}
        for plan in self.plan(target):
            result = self.cache.explain(plan)
            unresolved = [
                value.name
                for value in plan.inputs
                if value.kind == "value"
                and isinstance(value.data, dict)
                and ("unresolved" in value.data or "missing" in value.data)
            ]
            if plan.enabled and unresolved:
                result.update(status="blocked", reasons=["输入尚未准备: " + ", ".join(unresolved)])
            pending = [name for name in plan.dependencies if states.get(name) != "hit"]
            if plan.enabled and pending:
                result.update(status="blocked", reasons=["等待上游任务: " + ", ".join(pending)])
            states[plan.task_id] = result["status"]
            results.append(result)
        return results

    def build(self, target: str = "image", force=None):
        """同目标串行发布，不同目标使用独立 worktree 与输出目录。"""
        success = False
        with FileLock(self.context.build_root / "locks" / f"{self.context.target.key}.lock"):
            if self.output is None:
                self.output = BuildOutput(self.context.target_dir, level=self.output_level)
            self.docker.output = self.output
            self.source.output = self.output
            try:
                self.output.build_start(target, self.config)
                self._build_components(target, force)
                success = True
            finally:
                self.output.build_end(success=success)

    def _build_components(self, target: str, force=None):
        order = _topo_sort(DEPENDENCY_GRAPH, target)
        self.output.plan([name for name in order if component_enabled(self.config, name)])
        manifests = {}
        for component in order:
            if not component_enabled(self.config, component):
                self.output.phase_skip(component, reason="disabled")
                continue
            forced = force in {"all", component}
            # 源同步也是该阶段的一部分，异常/取消必须记录失败。
            self.output.phase_start(component)
            try:
                if component == "app":
                    self._app_report = self._app_builder().build_all(force=forced)
                    plan = self._plan_component(component)
                    before = plan.fingerprint()
                    outputs = []
                    for result in self._app_report.ordered:
                        for record in result.manifest.artifacts:
                            outputs.append(
                                ArtifactSpec(
                                    f"{result.resource_id}:{record.name}",
                                    record.path,
                                    kind=record.kind,
                                )
                            )
                    manifests[component] = self.cache.store(
                        plan, before, manifests, extra_outputs=outputs
                    )
                else:
                    with self.output.step("检查源码与缓存"):
                        self.source.prepare_cache_inputs(component, self.config)
                        plan = self._plan_component(component)
                        dependencies = self.cache.dependency_identities(plan, manifests)
                        before = plan.fingerprint(dependencies)
                        cached = not forced and self.cache.is_up_to_date(plan, manifests)
                    if cached:
                        manifests[component] = self.cache.load(component)
                        self.output.phase_skip(component)
                        continue
                    builder = self._get_builder(component)
                    builder.context, builder.cache, builder.output = (
                        self.context,
                        self.cache,
                        self.output,
                    )
                    builder.app_report = self._app_report
                    outputs = builder.execute(plan)
                    self._outputs[component] = outputs
                    extras = self._collect_artifacts(plan, outputs)
                    if component == "image":
                        FlashConfigGenerator().generate(
                            self.config,
                            self.context.target_dir,
                            context=self.context,
                            source=self.source,
                        )
                    manifests[component] = self.cache.store(
                        plan, before, manifests, extra_outputs=extras
                    )
                self.output.phase_end(component, success=True)
            except BaseException as exc:
                self.output.phase_end(component, success=False, error=exc)
                raise

    def _component_disabled(self, component: str) -> bool:
        return not component_enabled(self.config, component)

    def _get_artifact_names(self) -> dict:
        module = load_platform(self.config)
        return getattr(module, "ARTIFACT_NAMES", {})

    def _collect_artifacts(self, plan: TaskPlan, outputs: dict) -> tuple[ArtifactSpec, ...]:
        """在独立目录收集并验证完整输出，再一次替换组件目录。"""
        component = plan.task_id
        destination = self.context.target_dir / component
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{component}-", dir=destination.parent))
        backup = destination.with_name(f".{component}-previous")
        extra = []
        try:
            names = self._get_artifact_names()
            published_names = set()
            for key, source in outputs.items():
                if source is None:
                    continue
                source = Path(source)
                if not source.exists() and not source.is_symlink():
                    raise BuildError(f"{component} 声明的产物不存在: {source}")
                filename = names.get((component, key), source.name)
                if Path(filename).name != filename or filename in {".", "..", ""}:
                    raise ValueError(f"非法产物文件名: {filename!r}")
                if filename in published_names:
                    raise ValueError(f"重复产物文件名: {filename!r}")
                published_names.add(filename)
                target = staging / filename
                if source.is_symlink():
                    target.symlink_to(source.readlink())
                    kind = "symlink"
                elif source.is_dir():
                    shutil.copytree(source, target, symlinks=True)
                    kind = "tree"
                else:
                    _copy_sparse(source, target)
                    kind = "file"
                extra.append(ArtifactSpec(str(key), destination / filename, kind=kind))
            for spec in plan.outputs:
                if spec.path.is_relative_to(destination):
                    Artifact.capture(
                        replace(spec, path=staging / spec.path.relative_to(destination))
                    )
            if backup.exists():
                shutil.rmtree(backup)
            if destination.exists():
                destination.rename(backup)
            try:
                staging.rename(destination)
            except BaseException:
                if backup.exists():
                    backup.rename(destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            self.output.status("产物已发布")
            return tuple(extra)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _get_builder(self, component: str):
        if component == "device-tree-overlay":
            from builder.overlays import OverlaysBuilder

            return OverlaysBuilder(self.docker, self.source)
        module = load_platform(self.config)
        return module.create_builder(component, self.docker, self.source)
