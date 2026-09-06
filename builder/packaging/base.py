"""包格式策略接口；通用构建只负责调用顺序和原子发布。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from builder.packaging.model import PackageOutput

if TYPE_CHECKING:
    from builder.app_spec import AppSpec

InstalledFile = tuple[Path, str, int]


class PackageBackend(ABC):
    """规划、生成/导入和设备安装属于同一格式契约。"""

    format: str

    @abstractmethod
    def validate_output(self, output: PackageOutput) -> None:
        """验证该格式的输出文件名。"""

    @abstractmethod
    def plan(self, spec: AppSpec, arch: str) -> tuple[PackageOutput, ...]:
        """不执行构建，返回全部交付物及角色。"""

    @abstractmethod
    def build(
        self, spec: AppSpec, arch: str, files: Sequence[InstalledFile], output: Path
    ) -> None:
        """从已验证安装清单生成默认包。"""

    @abstractmethod
    def import_outputs(
        self,
        outputs: Sequence[PackageOutput],
        arch: str,
        output: Path,
        install: Path,
        runner,
    ) -> set[str]:
        """验证完整外部包并合并安装树，返回 runtime 包内的目标文件路径。"""

    @abstractmethod
    def architecture(self, arch: str) -> str:
        """转换为包管理器使用的架构名。"""

    @abstractmethod
    def architecture_command(self) -> list[str]:
        """返回只读查询设备架构的命令。"""

    @abstractmethod
    def install_command(self, paths: Sequence[str]) -> list[str]:
        """返回一次安装所选包的命令。"""

    @abstractmethod
    def recipe_paths(self) -> tuple[Path, ...]:
        """影响格式行为的额外配方文件。"""
