"""带版本的成功产物清单；输入一致且输出内容完整才允许缓存命中。"""

from __future__ import annotations

import json
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from builder.digest import canonical_value, digest_value, hash_path
from builder.locking import atomic_write

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: Path
    kind: str = "file"
    required: bool = True
    allow_empty: bool = True

    def __post_init__(self):
        object.__setattr__(self, "path", Path(self.path).absolute())
        if not self.name or self.kind not in {"file", "tree", "symlink"}:
            raise ValueError(f"无效产物声明: {self.name!r} / {self.kind!r}")


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    kind: str
    sha256: str
    mode: int
    size: int

    @classmethod
    def capture(cls, spec: ArtifactSpec) -> Artifact | None:
        try:
            info = spec.path.lstat()
        except FileNotFoundError:
            if spec.required:
                raise ValueError(f"缺少必需产物 {spec.name}: {spec.path}") from None
            return None
        kind = (
            "symlink"
            if stat.S_ISLNK(info.st_mode)
            else "tree"
            if stat.S_ISDIR(info.st_mode)
            else "file"
            if stat.S_ISREG(info.st_mode)
            else "unsupported"
        )
        if kind != spec.kind:
            raise ValueError(f"产物 {spec.name} 类型应为 {spec.kind}，实际为 {kind}: {spec.path}")
        if not spec.allow_empty:
            empty = not any(spec.path.iterdir()) if kind == "tree" else info.st_size == 0
            if empty:
                raise ValueError(f"产物 {spec.name} 不得为空: {spec.path}")
        return cls(
            spec.name,
            spec.path,
            kind,
            hash_path(spec.path),
            stat.S_IMODE(info.st_mode),
            info.st_size if kind == "file" else 0,
        )

    def validate(self) -> bool:
        try:
            current = self.capture(ArtifactSpec(self.name, self.path, self.kind))
            return current == self
        except (OSError, ValueError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return canonical_value(self)

    @classmethod
    def from_dict(cls, value: dict) -> Artifact:
        return cls(
            name=value["name"],
            path=Path(value["path"]),
            kind=value["kind"],
            sha256=value["sha256"],
            mode=value["mode"],
            size=value["size"],
        )


@dataclass(frozen=True)
class ArtifactManifest:
    task_id: str
    input_digest: str
    artifacts: tuple[Artifact, ...]
    input_segments: Mapping[str, str] = field(default_factory=dict)
    dependencies: Mapping[str, str] = field(default_factory=dict)
    version: int = MANIFEST_VERSION

    @classmethod
    def capture(
        cls,
        task_id: str,
        input_digest: str,
        outputs: Sequence[ArtifactSpec],
        *,
        input_segments: Mapping[str, str] | None = None,
        dependencies: Mapping[str, str] | None = None,
    ) -> ArtifactManifest:
        if len({output.name for output in outputs}) != len(outputs):
            raise ValueError(f"任务 {task_id} 有重复产物名称")
        records = tuple(
            record for output in outputs if (record := Artifact.capture(output)) is not None
        )
        return cls(
            task_id, input_digest, records, dict(input_segments or {}), dict(dependencies or {})
        )

    @property
    def identity(self) -> str:
        # 下游只依赖实际产物身份；构建位置和不影响结果的上游输入不级联。
        return digest_value(
            {
                "version": self.version,
                "task_id": self.task_id,
                "artifacts": [
                    {key: value for key, value in record.to_dict().items() if key != "path"}
                    for record in sorted(self.artifacts, key=lambda item: item.name)
                ],
            }
        )

    def validate(self) -> bool:
        return self.version == MANIFEST_VERSION and all(item.validate() for item in self.artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "task_id": self.task_id,
            "input_digest": self.input_digest,
            "identity": self.identity,
            "input_segments": dict(self.input_segments),
            "dependencies": dict(self.dependencies),
            "artifacts": [item.to_dict() for item in self.artifacts],
        }

    @classmethod
    def from_dict(cls, value: dict) -> ArtifactManifest:
        if value.get("version") != MANIFEST_VERSION:
            raise ValueError("产物清单版本不支持")
        result = cls(
            value["task_id"],
            value["input_digest"],
            tuple(Artifact.from_dict(item) for item in value["artifacts"]),
            dict(value["input_segments"]),
            dict(value["dependencies"]),
        )
        if value.get("identity") != result.identity:
            raise ValueError("产物清单身份校验失败")
        if len({item.name for item in result.artifacts}) != len(result.artifacts):
            raise ValueError("产物清单包含重复名称")
        return result

    @classmethod
    def load(cls, path: Path) -> ArtifactManifest | None:
        try:
            return cls.from_dict(json.loads(Path(path).read_text()))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def write(self, path: Path) -> None:
        if not self.validate():
            raise ValueError(f"任务 {self.task_id} 产物验证失败，拒绝发布成功清单")
        atomic_write(
            path, json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
