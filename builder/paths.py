"""仓库分层路径锚点。

按 repo-layout 规格的三层分法暴露：
  - PROJECT_ROOT:    仓库根（绝对路径）
  - COMPONENTS_ROOT: 仓库内容层（PROJECT_ROOT / "components"）
  - BUILD_ROOT:      运行时产物层（PROJECT_ROOT / ".build"）

以及按给定 project_root 计算同名子目录的两个辅助函数，供测试注入替代根时使用。
"""

from pathlib import Path

COMPONENTS_DIRNAME = "components"
BUILD_DIRNAME = ".build"

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
COMPONENTS_ROOT: Path = PROJECT_ROOT / COMPONENTS_DIRNAME
BUILD_ROOT: Path = PROJECT_ROOT / BUILD_DIRNAME


def components_dir(project_root: Path) -> Path:
    return Path(project_root) / COMPONENTS_DIRNAME


def build_dir(project_root: Path) -> Path:
    return Path(project_root) / BUILD_DIRNAME
