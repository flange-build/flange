"""与包格式无关的交付配置和产物记录。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROLES = frozenset({"runtime", "development"})


@dataclass(frozen=True)
class PackageOutput:
    """规划阶段的精确文件名和消费角色，不从命名推断用途。"""

    file: str
    role: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._~:-]*", self.file):
            raise ValueError(f"包输出必须是安全的精确文件名：{self.file!r}")
        if self.role not in PACKAGE_ROLES:
            raise ValueError(f"包角色必须为 runtime 或 development：{self.role!r}")


@dataclass
class PackagingConfig:
    """输出留空时由格式后端从安装树打包，否则导入完整外部包。"""

    format: str = "deb"
    outputs: list[PackageOutput] = field(default_factory=list)


@dataclass(frozen=True)
class PackageArtifact:
    """报告中的具名包；内容身份由同一资源的 ArtifactManifest 负责。"""

    path: Path
    format: str
    role: str

    def __post_init__(self) -> None:
        PackageOutput(self.path.name, self.role)
        if not self.format:
            raise ValueError("包格式不能为空")

    def metadata(self) -> dict[str, str]:
        return {"file": self.path.name, "format": self.format, "role": self.role}

    def to_dict(self) -> dict[str, str]:
        return {"path": str(self.path), "format": self.format, "role": self.role}

    @classmethod
    def from_dict(cls, value: dict) -> PackageArtifact:
        if set(value) != {"path", "format", "role"}:
            raise ValueError("包记录字段不完整或含未知字段")
        return cls(Path(value["path"]), value["format"], value["role"])
