"""Ubuntu 构建容器的编译依赖，独立于 App 交付包格式。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from builder.apt import AptCache
from builder.deb import _map_arch


class UbuntuBuildDependencies:
    """同一次 App 闭包构建只刷新一次 APT 索引，按需安装编译依赖。"""

    def __init__(self, runner, tool_root: Path) -> None:
        self.runner = runner
        self.cache = AptCache.for_tool(tool_root)
        self.index_updated = False
        self.installed: set[str] = set()

    def install(self, packages: Sequence[str], arch: str) -> None:
        if not packages:
            return
        with self.cache.locked():
            requested = [
                package.replace("{arch}", _map_arch(arch)) for package in packages
            ]
            pending = list(
                dict.fromkeys(item for item in requested if item not in self.installed)
            )
            if not pending:
                return
            if not self.index_updated:
                self.runner.run(["apt-get", "update", *self.cache.options])
                self.index_updated = True
            self.runner.run(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    *self.cache.options,
                    *pending,
                ]
            )
            self.installed.update(pending)


class SdkBuildDependencies:
    """SDK 已固定目标依赖；不允许隐式向 Ubuntu 容器安装不同发行版依赖。"""

    def install(self, packages, arch):
        if packages:
            raise ValueError("此 SDK 未提供构建依赖适配器；请预置所需依赖或实现 create_dependencies")


def resolve_build_dependencies(config, context, runner):
    from builder.build_environment import resolve_environment
    from builder.layers import stack_for

    environment = resolve_environment(config, context)
    name = config.get("userland_toolchain") or (environment.toolchain if environment else "")
    module = stack_for(config, context).provider("toolchain", name) if name else None
    if module is not None:
        factory = getattr(module, "create_dependencies", None)
        return factory(config, context, runner) if factory else SdkBuildDependencies()
    return UbuntuBuildDependencies(runner, context.tool_root)
