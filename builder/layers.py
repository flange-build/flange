"""有序本地扩展层、资源归属和受信任策略的统一解析边界。"""

from __future__ import annotations

import hashlib
import importlib.util
import importlib.abc
import importlib.machinery
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

from builder.paths import PROJECT_ROOT, components_dir

_NAME = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*\Z")
PROVIDER_KINDS = {
    "platform",
    "distro",
    "environment",
    "toolchain",
    "packaging",
    "flash",
    "flash_plan",
}


class LayerError(ValueError):
    """层声明或资源解析不合法。"""


def _name(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise LayerError(f"{field_name} 必须是小写英文、数字及连字符组成的名称")
    return value


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or any(c in value for c in "\0\r\n")
    ):
        raise LayerError(f"层资源必须是层内相对路径，不能越界：{value!r}")
    return Path(*path.parts)


@dataclass(frozen=True)
class ProviderRef:
    kind: str
    name: str
    entry: str


@dataclass(frozen=True)
class Layer:
    name: str
    root: Path
    requires: tuple[str, ...] = ()
    providers: tuple[ProviderRef, ...] = ()

    @property
    def components(self) -> Path:
        return components_dir(self.root)

    def path(self, relative: str, *, symlink_node: bool = False) -> Path:
        path = self.root / _relative(relative)
        checked = (
            path.parent.resolve()
            if symlink_node and path.is_symlink()
            else path.resolve()
        )
        if not checked.is_relative_to(self.root):
            raise LayerError(f"层 {self.name} 资源经符号链接越界：{relative}")
        return path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "root": str(self.root),
            "requires": list(self.requires),
            "providers": [
                {"kind": p.kind, "name": p.name, "entry": p.entry}
                for p in self.providers
            ],
        }


@dataclass(frozen=True)
class ResourceRef:
    layer: Layer
    relative_path: str
    symlink_node: bool = False

    @property
    def path(self) -> Path:
        return self.layer.path(self.relative_path, symlink_node=self.symlink_node)

    @property
    def identity(self) -> str:
        return f"layer://{self.layer.name}/{self.relative_path}"

    def to_dict(self) -> dict:
        return {"source": self.identity, "path": str(self.path)}


def read_layer(root: Path) -> Layer:
    root = root.expanduser().resolve()
    try:
        data = tomllib.loads((root / "layer.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LayerError(f"无法读取层清单 {root / 'layer.toml'}：{exc}") from exc
    unknown = set(data) - {
        "schema_version",
        "api_version",
        "name",
        "requires",
        "providers",
    }
    if unknown:
        raise LayerError(f"layer.toml 未知字段：{', '.join(sorted(unknown))}")
    for key in ("schema_version", "api_version"):
        if type(data.get(key)) is not int or data[key] != 1:
            raise LayerError(f"{root}/layer.toml 的 {key} 必须为整数 1")
    name = _name(data.get("name"), "layer.name")
    requires = data.get("requires", [])
    if not isinstance(requires, list):
        raise LayerError("layer.requires 必须是层名称数组")
    required = tuple(_name(item, "layer.requires") for item in requires)
    if len(set(required)) != len(required):
        raise LayerError(f"层 {name} 重复声明依赖")
    providers = data.get("providers", {})
    if not isinstance(providers, dict) or set(providers) - PROVIDER_KINDS:
        raise LayerError(
            f"providers 必须是策略种类映射，支持：{', '.join(sorted(PROVIDER_KINDS))}"
        )
    entries = []
    for kind, mapping in providers.items():
        if not isinstance(mapping, dict):
            raise LayerError(f"providers.{kind} 必须是名称到 Python 入口的映射")
        for provider_name, entry in mapping.items():
            _name(provider_name, f"providers.{kind}")
            if not isinstance(entry, str):
                raise LayerError(
                    f"providers.{kind}.{provider_name} 必须是 Python 文件路径"
                )
            relative = _relative(entry)
            if relative.suffix != ".py":
                raise LayerError(f"策略入口必须是 .py 文件：{entry}")
            entries.append(ProviderRef(kind, provider_name, entry))
    layer = Layer(name, root, required, tuple(entries))
    for provider in entries:
        if not layer.path(provider.entry).is_file():
            raise LayerError(f"策略入口不存在：{name}/{provider.entry}")
    return layer


class _LayerSourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # 不读取已有 pyc；相同 mtime/size 的 helper 修改也必须立即生效。
        return compile(self.get_data(self.path), self.path, "exec", dont_inherit=True)


class _LayerModuleFinder(importlib.abc.MetaPathFinder):
    roots: dict[str, Path] = {}

    def find_spec(self, fullname, path=None, target=None):
        prefix, separator, relative = fullname.partition(".")
        if not separator or prefix not in self.roots:
            return None
        root = self.roots[prefix]
        candidate = root.joinpath(*relative.split("."))
        package = candidate.is_dir()
        source = candidate / "__init__.py" if package else candidate.with_suffix(".py")
        if not source.resolve().is_relative_to(root.resolve()):
            raise LayerError(f"策略辅助模块越界：{source}")
        if source.is_file():
            return importlib.util.spec_from_file_location(
                fullname,
                source,
                loader=_LayerSourceLoader(fullname, str(source)),
                submodule_search_locations=[str(candidate)] if package else None,
            )
        if package:
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = [str(candidate)]
            return spec
        return None


_LAYER_FINDER = _LayerModuleFinder()
sys.meta_path.insert(0, _LAYER_FINDER)


@dataclass(frozen=True)
class LayerStack:
    layers: tuple[Layer, ...]
    _modules: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.layers or self.layers[0].name != "flange":
            raise LayerError("flange 基础层必须是第一层")
        seen: set[str] = set()
        roots: set[Path] = set()
        for layer in self.layers:
            if layer.name in seen or layer.root in roots:
                raise LayerError(f"重复层名称或路径：{layer.name} ({layer.root})")
            for dependency in layer.requires:
                if dependency not in seen:
                    raise LayerError(
                        f"层 {layer.name} 依赖 {dependency}：依赖缺失、存在循环或未位于下层；请修正 layers 顺序"
                    )
            seen.add(layer.name)
            roots.add(layer.root)

    def __deepcopy__(self, memo):
        # 层声明不可变；缓存模块不应被 deepcopy 或序列化。
        return self

    @classmethod
    def base(cls, root: Path = PROJECT_ROOT) -> LayerStack:
        return cls((Layer("flange", Path(root).resolve()),))

    @classmethod
    def load(cls, root: Path, paths: list[Path]) -> LayerStack:
        return cls(
            (Layer("flange", Path(root).resolve()), *(read_layer(p) for p in paths))
        )

    def layer(self, name: str) -> Layer:
        for layer in self.layers:
            if layer.name == name:
                return layer
        raise LayerError(f"未启用扩展层：{name}")

    def reference(self, path: Path) -> ResourceRef:
        path = Path(path).absolute()
        # 嵌套存放层时优先使用最长所属根，而不是错误归到工作区层。
        for layer in sorted(
            self.layers, key=lambda item: len(item.root.parts), reverse=True
        ):
            if path.is_relative_to(layer.root):
                ref = ResourceRef(layer, path.relative_to(layer.root).as_posix())
                ref.path
                return ref
        raise LayerError(f"资源不属于启用层：{path}")

    def uri(self, value: str) -> ResourceRef:
        if not value.startswith("layer://"):
            raise LayerError(f"不是层资源引用：{value}")
        name, separator, relative = value[8:].partition("/")
        if not separator:
            raise LayerError(f"层资源引用缺少路径：{value}")
        ref = ResourceRef(self.layer(name), _relative(relative).as_posix())
        ref.path
        return ref

    def resolve_values(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("layer://"):
            return str(self.uri(value).path)
        if isinstance(value, dict):
            return {key: self.resolve_values(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve_values(item) for item in value]
        return value

    def all(self, relative: str) -> tuple[ResourceRef, ...]:
        relative = _relative(relative).as_posix()
        return tuple(
            ResourceRef(layer, relative)
            for layer in self.layers
            if layer.path(relative).exists()
        )

    def selected(self, relative: str) -> ResourceRef | None:
        refs = self.all(relative)
        return refs[-1] if refs else None

    def names(self, directory: str, marker: str) -> list[str]:
        names: set[str] = set()
        for ref in self.all(directory):
            if ref.path.is_dir():
                names.update(
                    child.name
                    for child in ref.path.iterdir()
                    if child.is_dir() and (child / marker).is_file()
                )
        return sorted(names)

    def files(self, directory: str, pattern: str = "*") -> tuple[ResourceRef, ...]:
        """低到高新增，重名原位替换；字典的插入序就是执行序。"""
        chosen: dict[str, ResourceRef] = {}
        for directory_ref in self.all(directory):
            for path in sorted(directory_ref.path.glob(pattern)):
                if path.is_file() or path.is_symlink():
                    key = path.relative_to(directory_ref.path).as_posix()
                    chosen[key] = ResourceRef(
                        directory_ref.layer, f"{directory_ref.relative_path}/{key}"
                    )
        return tuple(chosen.values())

    def provider_ref(self, kind: str, name: str) -> ResourceRef | None:
        for layer in reversed(self.layers):
            for provider in layer.providers:
                if (provider.kind, provider.name) == (kind, name):
                    return ResourceRef(layer, provider.entry)
        return None

    def provider(self, kind: str, name: str) -> ModuleType | None:
        ref = self.provider_ref(kind, name)
        if ref is None:
            return None
        key = (kind, name)
        signature = hashlib.sha256(
            b"".join(
                resource.identity.encode() + resource.path.read_bytes()
                for resource in self.provider_inputs(kind, name)
            )
        ).hexdigest()
        cached = self._modules.get(key)
        if cached is None or cached[0] != signature:
            # 整个策略目录提供相对 import 边界，不向 sys.path 注入层根。
            token = hashlib.sha256(
                f"{id(self)}:{ref.path}:{signature}".encode()
            ).hexdigest()[:24]
            module_name = f"_flange_layer_{token}"
            _LAYER_FINDER.roots[module_name] = ref.path.parent
            spec = importlib.util.spec_from_file_location(
                module_name, ref.path, submodule_search_locations=[str(ref.path.parent)]
            )
            if spec is None or spec.loader is None:
                raise LayerError(f"无法加载策略：{ref.identity}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                # 避免外部层写 __pycache__，并避免相同 mtime/size 的旧 pyc。
                previous = sys.dont_write_bytecode
                sys.dont_write_bytecode = True
                exec(
                    compile(ref.path.read_bytes(), str(ref.path), "exec"),
                    module.__dict__,
                )
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            finally:
                sys.dont_write_bytecode = previous
            self._modules[key] = (signature, module)
        return self._modules[key][1]

    def provider_inputs(self, kind: str, name: str) -> tuple[ResourceRef, ...]:
        ref = self.provider_ref(kind, name)
        if ref is None:
            return ()
        return tuple(
            self.reference(path)
            for path in sorted(ref.path.parent.rglob("*.py"))
            if "__pycache__" not in path.parts
        )

    def check_providers(self) -> None:
        """只检查胜出策略的公开入口；被覆盖实现无需导入。"""
        required = {
            "platform": ("create_builder",),
            "distro": ("create_distro",),
            "environment": ("create_environment",),
            "toolchain": ("create_toolchain",),
            "packaging": ("create_backend",),
            "flash_plan": ("create_plan",),
            "flash": ("create_strategy",),
        }
        for kind, name in sorted(
            {(p.kind, p.name) for layer in self.layers for p in layer.providers}
        ):
            module = self.provider(kind, name)
            for method in required[kind]:
                if not callable(getattr(module, method, None)):
                    raise LayerError(f"策略 {kind}:{name} 缺少工厂 {method}")
            if kind == "platform" and not isinstance(
                getattr(module, "ARTIFACT_NAMES", None), dict
            ):
                raise LayerError(f"平台 {name} 缺少 ARTIFACT_NAMES")

    def to_dict(self) -> list[dict]:
        return [
            dict(layer.to_dict(), order=index)
            for index, layer in enumerate(self.layers)
        ]


def stack_for(config=None, context=None, project_root=None) -> LayerStack:
    stack = getattr(context, "layer_stack", None) or getattr(
        config, "layer_stack", None
    )
    return stack if stack is not None else LayerStack.base(project_root or PROJECT_ROOT)
