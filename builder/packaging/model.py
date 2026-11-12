"""与包格式无关的交付配置和产物记录。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

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
class IsolatedRuntime:
    """自带加载器与依赖库的私有运行时；不改变目标系统的默认 ABI。"""

    root: str
    loader: str

    def __post_init__(self) -> None:
        root = PurePosixPath(self.root)
        loader = PurePosixPath(self.loader)
        if (
            not self.root.startswith("/opt/") or len(root.parts) < 3
            or str(root) != self.root or ".." in root.parts
        ):
            raise ValueError("isolated_runtime.root 必须是 /opt 下的规范绝对路径")
        if (
            loader.is_absolute() or str(loader) != self.loader
            or not loader.parts or ".." in loader.parts or self.loader == "."
        ):
            raise ValueError("isolated_runtime.loader 必须是运行时内的规范相对路径")


@dataclass
class PackagingConfig:
    """输出留空时由格式后端从安装树打包，否则导入完整外部包。"""

    format: str = "deb"
    outputs: list[PackageOutput] = field(default_factory=list)
    # False 表示未固定格式；解析时采用目标默认值，直接构造时由 AppBuilder 补齐。
    format_declared: bool = False
    # 按包格式声明的运行依赖（如 {"apk": ["musl"]}）；顶层 depends 仍是 DEB 语义。
    depends: dict[str, list[str]] = field(default_factory=dict)
    isolated_runtime: IsolatedRuntime | None = None


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
