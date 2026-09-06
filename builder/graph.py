"""可序列化构建计划；执行、缓存和解释共同读取具名输入。"""

from __future__ import annotations

import copy
import subprocess
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from builder.artifacts import ArtifactSpec
from builder.digest import canonical_value, digest_value, hash_path


@dataclass(frozen=True)
class InputSpec:
    name: str
    kind: str
    data: Any = None
    location: Path | None = None
    exclude_names: tuple[str, ...] = ()
    exclude_paths: tuple[Path, ...] = ()

    @classmethod
    def value(cls, name: str, value: Any) -> InputSpec:
        canonical_value(value)
        return cls(name, "value", copy.deepcopy(value))

    @classmethod
    def file(cls, name: str, path: Path) -> InputSpec:
        return cls(name, "file", location=Path(path).absolute())

    @classmethod
    def tree(
        cls,
        name: str,
        path: Path,
        *,
        exclude_names: Collection[str] = (),
        exclude_paths: Collection[Path] = (),
    ) -> InputSpec:
        return cls(
            name,
            "tree",
            location=Path(path).absolute(),
            exclude_names=tuple(exclude_names),
            exclude_paths=tuple(exclude_paths),
        )

    @classmethod
    def git(cls, name: str, path: Path, revision: str) -> InputSpec:
        if not revision:
            raise ValueError(f"源码输入 {name} 缺少已解析 revision")
        return cls(name, "git", data=revision, location=Path(path).absolute())

    def digest(self) -> str:
        if self.kind == "git":
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.location,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            return digest_value({"kind": "git", "value": revision})
        if self.kind == "value":
            return digest_value({"kind": self.kind, "value": self.data})
        if self.location is None:
            raise ValueError(f"输入 {self.name} 缺少路径")
        return hash_path(
            self.location, exclude_names=self.exclude_names, exclude_paths=self.exclude_paths
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "value": canonical_value(self.data),
            "path": str(self.location) if self.location else None,
            "exclude_names": list(self.exclude_names),
            "exclude_paths": [str(path) for path in self.exclude_paths],
        }


@dataclass(frozen=True)
class TaskFingerprint:
    digest: str
    segments: Mapping[str, str]


@dataclass(frozen=True)
class TaskPlan:
    task_id: str
    recipe: str
    inputs: tuple[InputSpec, ...]
    outputs: tuple[ArtifactSpec, ...]
    dependencies: tuple[str, ...] = ()
    enabled: bool = True

    def __post_init__(self):
        if not self.task_id or not self.recipe:
            raise ValueError("任务必须声明 task_id 和 recipe")
        for values, label in ((self.inputs, "输入"), (self.outputs, "产物")):
            if len({item.name for item in values}) != len(values):
                raise ValueError(f"任务 {self.task_id} 存在重复{label}名称")

    def _input(self, name: str) -> InputSpec:
        for value in self.inputs:
            if value.name == name:
                return value
        raise KeyError(f"任务 {self.task_id} 未声明输入: {name}")

    def value(self, name: str) -> Any:
        value = self._input(name)
        if value.kind != "value":
            raise TypeError(f"输入 {name} 不是值")
        return copy.deepcopy(value.data)

    def path(self, name: str) -> Path:
        value = self._input(name)
        if value.location is None:
            raise TypeError(f"输入 {name} 不是路径")
        return value.location

    def fingerprint(
        self, dependency_identities: Mapping[str, str] | None = None
    ) -> TaskFingerprint:
        dependencies = dependency_identities or {}
        missing = set(self.dependencies) - dependencies.keys()
        if missing:
            raise ValueError(f"任务 {self.task_id} 缺少上游产物身份: {', '.join(sorted(missing))}")
        segments = {"recipe": digest_value(self.recipe), "enabled": digest_value(self.enabled)}
        if self.enabled:
            segments.update({f"input:{value.name}": value.digest() for value in self.inputs})
            segments.update({f"dep:{name}": dependencies[name] for name in self.dependencies})
            segments["outputs"] = digest_value(
                [
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "required": item.required,
                        "allow_empty": item.allow_empty,
                    }
                    for item in self.outputs
                ]
            )
        return TaskFingerprint(digest_value(segments), segments)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "recipe": self.recipe,
            "enabled": self.enabled,
            "dependencies": list(self.dependencies),
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [canonical_value(item) for item in self.outputs],
        }


DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "kernel": [],
    "bootloader": [],
    "app": [],
    "device-tree-overlay": ["kernel"],
    "rootfs": ["app", "kernel", "device-tree-overlay"],
    "boot": ["kernel", "device-tree-overlay"],
    "recovery": ["app", "kernel"],
    "amp": ["kernel"],
    "image": ["boot", "bootloader", "rootfs", "recovery", "amp"],
}


def component_enabled(config: Mapping, component: str) -> bool:
    if component in {"recovery", "amp"}:
        return bool((config.get(component) or {}).get("enabled", False))
    return True


def topological_order(graph: Mapping[str, Collection[str]], targets: Collection[str]) -> list[str]:
    """求请求节点的闭包，拒绝缺失节点和带完整路径的环。"""
    completed: set[str] = set()
    visiting: list[str] = []
    order: list[str] = []

    def visit(name: str) -> None:
        if name not in graph:
            raise ValueError(f"未知构建任务: {name}")
        if name in visiting:
            raise ValueError(
                "构建依赖循环: " + " → ".join(visiting[visiting.index(name) :] + [name])
            )
        if name in completed:
            return
        visiting.append(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.pop()
        completed.add(name)
        order.append(name)

    for target in targets:
        visit(target)
    return order
