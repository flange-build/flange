"""App 构建结果与跨构建、部署边界的准确报告。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from builder.artifacts import ArtifactManifest
from builder.digest import digest_value


@dataclass(frozen=True)
class AppBuildResult:
    """一个资源的成功产物及其来源，不依赖目录扫描推断。"""

    resource_id: str
    name: str
    source_dir: Path
    dependency_ids: tuple[str, ...]
    manifest_path: Path
    manifest: ArtifactManifest
    runtime_debs: tuple[Path, ...]
    install_dir: Path
    executable: str = ""
    service_unit: str = ""
    app_type: str = ""
    reused: bool = False
    compile_source_dir: str = ""
    debug_source_dir: str = ""

    @property
    def identity(self) -> str:
        return self.manifest.identity

    def validate(self) -> bool:
        if not self.manifest.validate():
            return False
        try:
            records = {item.name: item for item in self.manifest.artifacts}
            metadata = json.loads(records["resource"].path.read_text())
            return (
                metadata["name"] == self.name
                and metadata["resource_id"] == self.resource_id
                and Path(metadata["source_dir"]) == self.source_dir
                and tuple(metadata["dependency_ids"]) == self.dependency_ids
                and metadata["executable"] == self.executable
                and metadata["service_unit"] == self.service_unit
                and metadata["app_type"] == self.app_type
                and metadata["compile_source_dir"] == self.compile_source_dir
                and metadata["debug_source_dir"] == self.debug_source_dir
                and (
                    not self.debug_source_dir
                    or Path(self.debug_source_dir) == records["debug-source"].path
                )
                and self.install_dir == records["install"].path
                and tuple(metadata["runtime_debs"])
                == tuple(path.name for path in self.runtime_debs)
                and all(path == records[path.name].path for path in self.runtime_debs)
            )
        except (OSError, ValueError, KeyError):
            return False


@dataclass(frozen=True)
class AppBuildReport:
    """请求根与按依赖顺序排列的完整构建结果。"""

    roots: tuple[str, ...]
    ordered: tuple[AppBuildResult, ...]
    target: dict[str, str]
    architecture: str

    @property
    def identity(self) -> str:
        return digest_value(
            {
                "roots": self.roots,
                "target": self.target,
                "architecture": self.architecture,
                "artifacts": {item.resource_id: item.identity for item in self.ordered},
            }
        )

    @property
    def runtime_debs(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(path for result in self.ordered for path in result.runtime_debs))

    def root(self) -> AppBuildResult:
        if len(self.roots) != 1:
            raise ValueError("该操作要求一个明确的 App 请求根")
        return next(item for item in self.ordered if item.resource_id == self.roots[0])

    def runtime_debs_for(self, names: Sequence[str]) -> tuple[Path, ...]:
        by_id = {item.resource_id: item for item in self.ordered}
        wanted: set[str] = set()

        def visit(resource_id: str) -> None:
            if resource_id in wanted:
                return
            wanted.add(resource_id)
            for dependency in by_id[resource_id].dependency_ids:
                visit(dependency)

        for name in names:
            matches = [item for item in self.ordered if item.name == name]
            if len(matches) != 1:
                raise ValueError(f"报告中的 App 名称不存在或不唯一：{name}")
            visit(matches[0].resource_id)
        return tuple(
            dict.fromkeys(
                path
                for item in self.ordered
                if item.resource_id in wanted
                for path in item.runtime_debs
            )
        )

    def validate(self) -> bool:
        seen = set()
        for item in self.ordered:
            if (
                item.resource_id in seen
                or any(key not in seen for key in item.dependency_ids)
                or not item.validate()
            ):
                return False
            try:
                resource = next(
                    artifact for artifact in item.manifest.artifacts if artifact.name == "resource"
                )
                metadata = json.loads(resource.path.read_text())
                if (
                    metadata["target"] != self.target
                    or metadata["architecture"] != self.architecture
                ):
                    return False
            except (OSError, ValueError, KeyError, StopIteration):
                return False
            seen.add(item.resource_id)
        return set(self.roots).issubset(seen) and (bool(self.roots) or not self.ordered)

    def write(self, path: Path) -> None:
        path = Path(path)
        value = {
            "schema_version": 1,
            "roots": self.roots,
            "target": self.target,
            "architecture": self.architecture,
            "identity": self.identity,
            "ordered": [
                {
                    "resource_id": item.resource_id,
                    "name": item.name,
                    "source_dir": str(item.source_dir),
                    "dependency_ids": item.dependency_ids,
                    "manifest_path": str(item.manifest_path),
                    "manifest_identity": item.identity,
                    "runtime_debs": [str(deb) for deb in item.runtime_debs],
                    "install_dir": str(item.install_dir),
                    "executable": item.executable,
                    "service_unit": item.service_unit,
                    "app_type": item.app_type,
                    "reused": item.reused,
                    "compile_source_dir": item.compile_source_dir,
                    "debug_source_dir": item.debug_source_dir,
                }
                for item in self.ordered
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> AppBuildReport:
        value = json.loads(Path(path).read_text())
        if value.get("schema_version") != 1:
            raise ValueError(f"不支持的 App 报告版本：{path}")
        results = []
        for entry in value["ordered"]:
            manifest_path = Path(entry["manifest_path"])
            manifest = ArtifactManifest.load(manifest_path)
            if manifest is None or manifest.identity != entry["manifest_identity"]:
                raise ValueError(f"App 清单已变化或不存在：{manifest_path}")
            result = AppBuildResult(
                resource_id=entry["resource_id"],
                name=entry["name"],
                source_dir=Path(entry["source_dir"]),
                dependency_ids=tuple(entry["dependency_ids"]),
                manifest_path=manifest_path,
                manifest=manifest,
                runtime_debs=tuple(Path(item) for item in entry["runtime_debs"]),
                install_dir=Path(entry["install_dir"]),
                executable=entry["executable"],
                service_unit=entry["service_unit"],
                app_type=entry["app_type"],
                reused=entry["reused"],
                compile_source_dir=entry["compile_source_dir"],
                debug_source_dir=entry["debug_source_dir"],
            )
            recorded = {artifact.path.resolve() for artifact in manifest.artifacts}
            if any(deb.resolve() not in recorded for deb in result.runtime_debs):
                raise ValueError("App 报告引用了清单之外的 deb")
            results.append(result)
        report = cls(tuple(value["roots"]), tuple(results), value["target"], value["architecture"])
        if report.identity != value["identity"] or not report.validate():
            raise ValueError(f"App 报告或实际产物校验失败：{path}")
        return report
