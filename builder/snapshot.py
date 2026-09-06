"""跨目标共享的 base 快照：完整校验、原子发布与容量治理。"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.locking import FileLock

DEFAULT_KEEP = 6
KEEP_ENV = "FLANGE_SNAPSHOT_KEEP"
SNAPSHOT_SUFFIX = ".tar.zst"
ZSTD_COMPRESSOR = "zstd -3 -T0"
# GNU tar 默认不保存扩展属性，解包时还会忽略非 user 命名空间。
# 显式保留 Linux capability、ACL 与数字所有权，使缓存恢复与首次构建等价。
TAR_METADATA_OPTIONS = ("--numeric-owner", "--xattrs", "--xattrs-include=*", "--acls")


def resolve_keep() -> int:
    try:
        return max(int(os.environ.get(KEEP_ENV, str(DEFAULT_KEEP))), 0)
    except ValueError:
        return DEFAULT_KEEP


class SnapshotStore:
    """快照仅在 tar 与成功 manifest 均完整时可复用。"""

    def __init__(self, directory: Path, prefix: str, docker, status=None):
        self.directory = Path(directory)
        self.prefix = prefix
        self.docker = docker
        self._status = status or (lambda _message: None)

    def path_for(self, content_hash: str) -> Path:
        return self.directory / f"{self.prefix}{content_hash}{SNAPSHOT_SUFFIX}"

    def resolve(self, content_hash: str) -> Path:
        return self.path_for(content_hash)

    @staticmethod
    def _manifest_path(path: Path) -> Path:
        return path.with_name(path.name + ".manifest.json")

    @staticmethod
    def _lock(path: Path) -> FileLock:
        return FileLock(path.parent / ".locks" / f"{path.name}.lock")

    def _valid(self, path: Path) -> bool:
        manifest = ArtifactManifest.load(self._manifest_path(path))
        return bool(
            manifest
            and manifest.task_id == "rootfs:base-snapshot"
            and manifest.input_digest == path.name
            and len(manifest.artifacts) == 1
            and manifest.artifacts[0].path == path.absolute()
            and manifest.validate()
        )

    def restore(self, path: Path, dest: Path) -> bool:
        """损坏或解压失败按未命中处理，并移除部分解压内容。"""
        with self._lock(path):
            if not self._valid(path):
                return False
            try:
                self.docker.run_privileged(["tar", "tf", str(path)], capture=True)
                self.docker.run_privileged(
                    ["tar", *TAR_METADATA_OPTIONS, "-xf", str(path), "-C", str(dest)]
                )
            except Exception:
                path.rename(path.with_name(path.name + ".corrupt"))
                self._manifest_path(path).unlink(missing_ok=True)
                shutil.rmtree(dest)
                dest.mkdir(parents=True)
                self._status("base 快照损坏，已隔离并重新构建")
                return False
            try:
                os.utime(path, None)
            except OSError:
                pass
            return True

    def save(self, source_dir: Path, path: Path) -> None:
        """先写独立临时 tar 并完整读取校验，最后才公布成功记录。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(path):
            if self._valid(path):
                return
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            os.close(fd)
            temporary = Path(name)
            try:
                self._status(f"保存 base 快照到 {path.name}")
                self.docker.run_privileged(
                    [
                        "tar",
                        *TAR_METADATA_OPTIONS,
                        "-I",
                        ZSTD_COMPRESSOR,
                        "-cf",
                        str(temporary),
                        "-C",
                        str(source_dir),
                        ".",
                    ]
                )
                self.docker.run_privileged(["tar", "tf", str(temporary)], capture=True)
                if not temporary.stat().st_size:
                    raise ValueError("tar 未产生有效快照")
                temporary.replace(path)
                manifest = ArtifactManifest.capture(
                    "rootfs:base-snapshot",
                    path.name,
                    (ArtifactSpec("archive", path, allow_empty=False),),
                )
                manifest.write(self._manifest_path(path))
            finally:
                temporary.unlink(missing_ok=True)
        self.prune(protect=path)

    def _all_snapshots(self) -> list[Path]:
        return [
            path
            for path in self.directory.glob(f"{self.prefix}*{SNAPSHOT_SUFFIX}")
            if path.is_file()
        ]

    def prune(self, protect: Path | None = None) -> list[Path]:
        keep = resolve_keep()
        if not keep or not self.directory.is_dir():
            return []
        removed = []
        with FileLock(self.directory / ".locks/prune.lock"):
            candidates = sorted(
                self._all_snapshots(), key=lambda path: path.stat().st_mtime, reverse=True
            )
            for path in candidates[keep:]:
                if protect and path.absolute() == protect.absolute():
                    continue
                with self._lock(path):
                    try:
                        path.unlink()
                        self._manifest_path(path).unlink(missing_ok=True)
                        removed.append(path)
                    except FileNotFoundError:
                        pass
        return removed
