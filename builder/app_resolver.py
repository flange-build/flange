"""把工作区名称和路径解析为唯一 App 资源及完整依赖闭包。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from builder.app_spec import AppSpec, load_spec
from builder.digest import digest_value
from builder.workspace import WorkspaceContext


@dataclass(frozen=True)
class AppResource:
    resource_id: str
    source_dir: Path
    spec: AppSpec
    dependency_ids: tuple[str, ...]


class AppResolver:
    """所有入口复用相同来源优先级，缺失、歧义和循环在执行前失败。"""

    def __init__(self, context: WorkspaceContext, source, config: dict, *, read_only=False) -> None:
        self.context = context
        self.source = source
        self.config = config
        self.read_only = read_only

    def resolve(self, request: str | Path, *, relative_to: Path | None = None) -> Path:
        raw = str(request)
        candidate = Path(raw).expanduser()
        base = relative_to or self.context.invocation_dir
        candidate = candidate if candidate.is_absolute() else base / candidate
        if "/" in raw or raw.startswith("."):
            return self._require(candidate)
        if raw in self.context.apps:
            return self._require(self.context.apps[raw])
        if candidate.is_dir():
            return self._require(candidate)
        matches = [
            directory / raw
            for directory in self.context.app_dirs
            if (directory / raw / "app.yaml").is_file()
        ]
        unique = list(dict.fromkeys(path.resolve() for path in matches))
        if len(unique) > 1:
            raise ValueError(f"App {raw!r} 有多个工作区来源，请在 [apps] 显式注册：{unique}")
        if unique:
            return unique[0]
        method = self.source.locate_app if self.read_only else self.source.ensure_app
        return self._require(method(raw, self.config))

    @staticmethod
    def _require(path: Path) -> Path:
        resolved = Path(path).resolve()
        if not (resolved / "app.yaml").is_file():
            raise FileNotFoundError(f"App 目录不存在或缺少 app.yaml：{resolved}")
        return resolved

    @staticmethod
    def resource_id(path: Path, name: str) -> str:
        return f"{name}-{digest_value(str(path.resolve()))[:12]}"

    def closure(
        self, requests: Sequence[str | Path]
    ) -> tuple[tuple[str, ...], tuple[AppResource, ...]]:
        resolved: dict[Path, AppResource] = {}
        visiting: list[Path] = []
        ordered: list[AppResource] = []
        names: dict[str, Path] = {}

        def visit(path: Path) -> AppResource:
            if path in visiting:
                chain = visiting[visiting.index(path) :] + [path]
                raise ValueError("App 循环依赖：" + " → ".join(map(str, chain)))
            if path in resolved:
                return resolved[path]
            spec = load_spec(path)
            other = names.get(spec.app.name)
            if other is not None and other != path:
                raise ValueError(
                    f"同一依赖闭包含有同名不同源 App {spec.app.name!r}：{other}、{path}"
                )
            names[spec.app.name] = path
            visiting.append(path)
            dependencies = tuple(
                visit(self.resolve(name, relative_to=path)).resource_id for name in spec.build.deps
            )
            visiting.pop()
            resource = AppResource(self.resource_id(path, spec.app.name), path, spec, dependencies)
            resolved[path] = resource
            ordered.append(resource)
            return resource

        roots = tuple(
            dict.fromkeys(visit(self.resolve(request)).resource_id for request in requests)
        )
        return roots, tuple(ordered)
