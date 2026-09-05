"""Ubuntu 构建容器的编译依赖，独立于 App 交付包格式。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from builder.deb import _map_arch
from builder.locking import FileLock


class UbuntuBuildDependencies:
    """同一次 App 闭包构建只刷新一次 APT 索引，按需安装编译依赖。"""

    def __init__(self, runner, build_root: Path) -> None:
        self.runner = runner
        self.build_root = build_root
        self.index_updated = False
        self.installed: set[str] = set()

    def install(self, packages: Sequence[str], arch: str) -> None:
        if not packages:
            return
        with FileLock(self.build_root / "locks/apt-cache.lock"):
            requested = [
                package.replace("{arch}", _map_arch(arch)) for package in packages
            ]
            pending = list(
                dict.fromkeys(item for item in requested if item not in self.installed)
            )
            if not pending:
                return
            if not self.index_updated:
                self.runner.run(["apt-get", "update"])
                self.index_updated = True
            self.runner.run(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    "-o",
                    "Dir::Cache::archives=/cache/apt",
                    *pending,
                ]
            )
            self.installed.update(pending)
