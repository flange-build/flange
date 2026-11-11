"""发行版/rootfs 策略，保留共用存储、硬件安装和成像编排。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from builder.graph import InputSpec
from builder.layers import stack_for


class DistroBackend(ABC):
    """扩展层提供的发行版接口；所有执行发生在已选 Docker 环境内。

    ``init_system`` 决定 App 服务文件与设备服务操作，``package_format`` 是 App
    未显式声明 ``packaging.format`` 时的默认包格式。
    """

    init_system: str = "systemd"
    package_format: str = "deb"

    @abstractmethod
    def base_plan(self, config, component, context): ...

    @abstractmethod
    def build_base(self, plan, root, *, context, source, docker, status): ...

    @abstractmethod
    def install_apps(self, builder, root, config): ...

    @abstractmethod
    def install_extra(self, builder, root, config): ...

    @abstractmethod
    def customize(self, builder, root, config): ...

    @abstractmethod
    def export_packages(self, builder, root): ...


class AptDistro(DistroBackend):
    """DEB/APT 发行版的公共策略；Ubuntu 默认实现保持既有行为。"""

    def base_plan(self, config, component, context):
        from builder.rootfs_base import base_plan

        return base_plan(config, component, context)

    def build_base(self, plan, root, **kwargs):
        from builder.rootfs_base import build_base

        build_base(plan, root, **kwargs)

    def install_apps(self, builder, root, config):
        builder._install_app_debs(root, config)

    def install_extra(self, builder, root, config):
        builder._install_extra_debs(root, config)
        builder._install_phase2_packages(root, config)

    def customize(self, builder, root, config):
        builder._configure_default_locale(root, config)
        builder._configure_users(root, config)
        builder._install_hostname(root, config)

    def export_packages(self, builder, root):
        builder._export_package_manifest(root)


def get_distro(config, context=None) -> DistroBackend:
    name = config.get("distro", "ubuntu")
    module = stack_for(config, context).provider("distro", name)
    if module is None:
        if name == "ubuntu":
            return AptDistro()
        raise ValueError(f"未注册发行版策略：{name}")
    result = module.create_distro()
    if not isinstance(result, DistroBackend):
        raise ValueError(f"发行版 {name} 必须返回 DistroBackend")
    return result


def base_recipe_inputs(context) -> tuple[InputSpec, ...]:
    """各发行版共用的基础执行、活树存储和快照配方。"""
    filenames = (
        "distro.py", "rootfs_storage.py", "snapshot.py", "chroot.py", "source.py",
        "docker.py", "environment.py", "locking.py",
    )
    return tuple(
        InputSpec.file(f"recipe:{name}", path)
        for name in filenames
        if (path := context.tool_root / "builder" / name).is_file()
    )


def distro_base_plan(config, component, context):
    from builder.build_environment import environment_inputs

    plan = get_distro(config, context).base_plan(config, component, context)
    stack = stack_for(config, context)
    inputs = list(plan.inputs)
    for item in base_recipe_inputs(context):
        if item not in inputs:
            inputs.append(item)
    inputs.extend(
        InputSpec.file(f"distro:{ref.identity}", ref.path)
        for ref in stack.provider_inputs("distro", config.get("distro", "ubuntu"))
    )
    inputs.extend(environment_inputs(config, context))
    return replace(plan, inputs=tuple(inputs))
