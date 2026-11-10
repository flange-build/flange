"""目标选择的完整容器环境；低层工具与用户态 SDK 在同一环境内共存。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from builder.layers import stack_for


@dataclass(frozen=True)
class BuildEnvironmentSpec:
    name: str
    image: str
    dockerfile: Path | None = None
    build_context: Path | None = None
    platform: str = "linux/amd64"
    toolchain: str = ""
    # (工具绝对路径, --version 输出须包含的版本文本)。
    required_tools: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not self.name or not self.image:
            raise ValueError("构建环境必须声明 name 与 image")
        if bool(self.dockerfile) != bool(self.build_context):
            raise ValueError("dockerfile 与 build_context 必须一起声明")
        if self.platform not in {"linux/amd64", "linux/arm64"}:
            raise ValueError("构建环境 platform 必须是 linux/amd64 或 linux/arm64")
        for path, version in self.required_tools:
            if not Path(path).is_absolute() or not version:
                raise ValueError("required_tools 必须声明绝对路径与预期版本")


def environment_name(config: dict, context=None) -> str:
    explicit = config.get("build_environment")
    if explicit:
        return explicit
    distro = config.get("distro", "ubuntu")
    module = stack_for(config, context).provider("distro", distro)
    return getattr(
        module, "BUILD_ENVIRONMENT", "ubuntu" if distro == "ubuntu" else distro
    )


def resolve_environment(config: dict, context=None) -> BuildEnvironmentSpec | None:
    """None 表示兼容内建 Ubuntu Compose，不改变旧工作区的 Docker 配方。"""
    name = environment_name(config, context)
    stack = stack_for(config, context)
    module = stack.provider("environment", name)
    if module is None:
        if name == "ubuntu":
            return None
        raise ValueError(f"未注册构建环境：{name}")
    spec = module.create_environment(config, context)
    if not isinstance(spec, BuildEnvironmentSpec) or spec.name != name:
        raise ValueError(f"环境策略 {name} 必须返回同名 BuildEnvironmentSpec")
    if spec.dockerfile is not None:
        stack.reference(spec.dockerfile).path
        stack.reference(spec.build_context).path
    return spec


def environment_inputs(config, context):
    """配方路径来自选中环境，镜像实际身份另由 runner 提供。"""
    from builder.graph import InputSpec

    stack = stack_for(config, context)
    name = environment_name(config, context)
    spec = resolve_environment(config, context)
    inputs = [
        InputSpec.file(f"environment:provider:{ref.identity}", ref.path)
        for ref in stack.provider_inputs("environment", name)
    ]
    if spec is not None:
        inputs.append(
            InputSpec.value(
                "environment:profile",
                {
                    "name": name,
                    "platform": spec.platform,
                    "image": spec.image,
                    "toolchain": spec.toolchain,
                    "required_tools": spec.required_tools,
                },
            )
        )
        if spec.dockerfile is not None:
            inputs.append(InputSpec.file("environment:dockerfile", spec.dockerfile))
        if spec.build_context is not None:
            inputs.append(
                InputSpec.tree(
                    "environment:context",
                    spec.build_context,
                    exclude_names={".git", "__pycache__", ".build"},
                )
            )
    return inputs
