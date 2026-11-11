"""rootfs 包暂存：保留完整文件名，同名产物以独立子目录隔离。"""

from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
import shutil

from builder.packaging.model import PackageArtifact


@contextmanager
def stage_packages(
    packages: Sequence[PackageArtifact], root: Path, directory: str,
) -> Iterator[tuple[str, ...]]:
    """返回 chroot 内包路径；安装结束或失败时清理本次暂存文件。"""
    staging = root / "tmp" / directory
    staging.mkdir(parents=True, exist_ok=False)
    counts = Counter(package.path.name for package in packages)
    paths: list[str] = []
    primary_error: BaseException | None = None
    try:
        for index, package in enumerate(packages):
            relative = Path(package.path.name)
            if counts[package.path.name] > 1:
                relative = Path(str(index)) / relative
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(package.path, target)
            paths.append(f"/tmp/{directory}/{relative.as_posix()}")
        yield tuple(paths)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            shutil.rmtree(staging)
        except OSError as error:
            if primary_error is None:
                raise
            primary_error.add_note(f"包暂存目录清理失败：{staging}：{error}")
