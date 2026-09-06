"""计划驱动的缓存：输入身份匹配且全部产物通过校验才可复用。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.graph import DEPENDENCY_GRAPH, TaskFingerprint, TaskPlan
from builder.workspace import WorkspaceContext


class BuildCache:
    """只读构造；缓存发布是显式操作，不接受旧式成功标记。"""

    def __init__(self, *, context: WorkspaceContext):
        self.context = context
        self.target_dir = context.target_dir

    def manifest_path(self, task_id: str) -> Path:
        if task_id not in DEPENDENCY_GRAPH:
            raise ValueError(f"系统缓存不认识任务 {task_id!r}")
        return self.target_dir / task_id / "manifest.json"

    def load(self, task_id: str) -> ArtifactManifest | None:
        return ArtifactManifest.load(self.manifest_path(task_id))

    @staticmethod
    def dependency_identities(
        plan: TaskPlan, manifests: Mapping[str, ArtifactManifest]
    ) -> dict[str, str]:
        identities = {}
        for name in plan.dependencies:
            manifest = manifests.get(name)
            if manifest is None or not manifest.validate():
                raise ValueError(f"任务 {plan.task_id} 的上游 {name} 缺少有效产物 manifest")
            identities[name] = manifest.identity
        return identities

    def explain(
        self, plan: TaskPlan, manifests: Mapping[str, ArtifactManifest] | None = None
    ) -> dict:
        """返回结构化原因；不写文件、不准备源码、不持有锁。"""
        result = {"task_id": plan.task_id, "status": "miss", "reasons": [], "changed_inputs": []}
        if not plan.enabled:
            return {**result, "status": "disabled", "reasons": ["配置已关闭"]}
        upstream = (
            manifests
            if manifests is not None
            else {name: self.load(name) for name in plan.dependencies}
        )
        try:
            identities = self.dependency_identities(plan, upstream)
            fingerprint = plan.fingerprint(identities)
        except (ValueError, OSError) as exc:
            return {**result, "status": "blocked", "reasons": [str(exc)]}
        result["input_digest"] = fingerprint.digest
        manifest = self.load(plan.task_id)
        if manifest is None:
            result["reasons"].append("缺少有效成功 manifest")
            return result
        if manifest.task_id != plan.task_id:
            result["reasons"].append("manifest 任务身份不匹配")
        if manifest.input_digest != fingerprint.digest:
            changed = sorted(
                name
                for name in set(manifest.input_segments) | set(fingerprint.segments)
                if manifest.input_segments.get(name) != fingerprint.segments.get(name)
            )
            result["changed_inputs"] = changed
            result["reasons"].append("声明输入或上游产物已变更")
        records = {record.name: record for record in manifest.artifacts}
        for output in plan.outputs:
            record = records.get(output.name)
            if record is None:
                if output.required:
                    result["reasons"].append(f"manifest 缺少必需产物: {output.name}")
                continue
            if record.path != output.path or record.kind != output.kind:
                result["reasons"].append(f"产物路径或类型不匹配: {output.name}")
        for record in manifest.artifacts:
            if not record.validate():
                result["reasons"].append(f"产物缺失或内容/权限已变更: {record.name}")
        if not result["reasons"]:
            result["status"] = "hit"
            result["artifact_identity"] = manifest.identity
        return result

    def is_up_to_date(
        self, plan: TaskPlan, manifests: Mapping[str, ArtifactManifest] | None = None
    ) -> bool:
        return self.explain(plan, manifests)["status"] == "hit"

    def store(
        self,
        plan: TaskPlan,
        before: TaskFingerprint,
        manifests: Mapping[str, ArtifactManifest],
        *,
        extra_outputs: Sequence[ArtifactSpec] = (),
    ) -> ArtifactManifest:
        """构建前后身份一致才发布；取消或失败均不会创建成功记录。"""
        identities = self.dependency_identities(plan, manifests)
        after = plan.fingerprint(identities)
        if after.digest != before.digest:
            raise RuntimeError(f"任务 {plan.task_id} 执行期间输入发生变化，拒绝发布缓存")
        declared = {output.name: output for output in plan.outputs}
        for output in extra_outputs:
            if output.name not in declared:
                declared[output.name] = output
        manifest = ArtifactManifest.capture(
            plan.task_id,
            after.digest,
            tuple(declared.values()),
            input_segments=after.segments,
            dependencies=identities,
        )
        manifest.write(self.manifest_path(plan.task_id))
        return manifest
