"""APT 缓存与互斥使用同一组实际源目录，跨工作区及容器共享。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from builder.locking import FileLock
from builder.paths import build_dir


@dataclass(frozen=True)
class AptCache:
    """路径使用 bind mount 的源目录，不使用容器内别名推断身份。"""

    archives: Path
    lists: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "archives", Path(self.archives).resolve())
        if self.lists is not None:
            object.__setattr__(self, "lists", Path(self.lists).resolve())

    @classmethod
    def for_tool(cls, tool_root: Path) -> AptCache:
        """与 docker-compose.yml 中两个共享缓存的源路径保持一致。"""
        cache = build_dir(tool_root) / "cache"
        return cls(cache / "apt", cache / "apt-lists")

    @property
    def options(self) -> list[str]:
        """显式绑定 APT 读写目录，命令与锁不能各自猜路径。"""
        options = ["-o", f"Dir::Cache::archives={self.archives}"]
        if self.lists is not None:
            options.extend(["-o", f"Dir::State::lists={self.lists}"])
        return options

    @contextmanager
    def locked(self):
        """在已有目标/资源锁内获取；只覆盖 APT 事务，不覆盖后续编译。"""
        directories = {self.archives}
        if self.lists is not None:
            directories.add(self.lists)
        with ExitStack() as stack:
            for directory in sorted(directories):
                directory.mkdir(parents=True, exist_ok=True)
                # 锁位于缓存外侧，APT clean 不会删除或替换它。
                lock = directory.with_name(f".{directory.name}.flange.lock")
                stack.enter_context(FileLock(lock))
            yield
