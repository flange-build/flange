"""工作区值对象与发现服务：工具、源码、状态和产物各有明确归属。"""

from dataclasses import dataclass, field
import json
from os.path import relpath
from pathlib import Path
import re
import tomllib
from types import MappingProxyType
from typing import Mapping

from builder.paths import PROJECT_ROOT, build_dir, components_dir
from builder.locking import FileLock, atomic_write
from builder.layers import LayerStack, read_layer


class WorkspaceError(ValueError):
    """可通过修改工作区声明或选择目标恢复的错误。"""


@dataclass(frozen=True)
class Target:
    board: str
    product: str
    variant: str

    def __post_init__(self):
        for name in ("board", "product", "variant"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                raise WorkspaceError(f"target.{name} 必须是有效的目标名称，实际为 {value!r}")

    @property
    def key(self) -> str:
        return f"{self.board}-{self.product}-{self.variant}"

    def to_dict(self) -> dict:
        return {"board": self.board, "product": self.product, "variant": self.variant}

    @classmethod
    def parse(cls, value: str, tool_root: Path = PROJECT_ROOT, layer_stack=None):
        from builder.config.query import parse_target

        return cls(**parse_target(value, project_root=tool_root, layer_stack=layer_stack))


@dataclass(frozen=True)
class WorkspaceContext:
    tool_root: Path
    workspace_root: Path
    build_root: Path
    target: Target
    invocation_dir: Path | None = None
    apps: Mapping[str, Path] = field(default_factory=dict)
    app_dirs: tuple[Path, ...] = ()
    layer_stack: LayerStack | None = None
    environment_ids: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self):
        if self.layer_stack is None:
            object.__setattr__(self, "layer_stack", LayerStack.base(self.tool_root))
        for name in ("tool_root", "workspace_root", "build_root"):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())
        object.__setattr__(
            self, "invocation_dir", Path(self.invocation_dir or self.workspace_root).resolve()
        )
        object.__setattr__(
            self,
            "apps",
            MappingProxyType({name: Path(path).resolve() for name, path in self.apps.items()}),
        )
        object.__setattr__(self, "app_dirs", tuple(Path(path).resolve() for path in self.app_dirs))

    @property
    def target_dir(self) -> Path:
        return (
            self.build_root
            / "target"
            / self.target.board
            / self.target.product
            / self.target.variant
        )

    @property
    def sources_dir(self) -> Path:
        return self.build_root / "sources"

    @property
    def state_file(self) -> Path:
        return self.workspace_root / ".flange" / "current_config"

    @property
    def components_root(self) -> Path:
        return components_dir(self.tool_root)

    def to_dict(self) -> dict:
        return {
            "tool_root": str(self.tool_root),
            "workspace_root": str(self.workspace_root),
            "build_root": str(self.build_root),
            "target": self.target.to_dict(),
            "target_dir": str(self.target_dir),
            "apps": {k: str(v) for k, v in self.apps.items()},
            "app_dirs": [str(p) for p in self.app_dirs],
            "layers": self.layer_stack.to_dict(),
        }


def _fields(value: object, allowed: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise WorkspaceError(f"{location} 必须是表")
    unknown = set(value) - allowed
    if unknown:
        raise WorkspaceError(f"{location} 包含未知字段：{', '.join(sorted(unknown))}；请修正字段名")
    return value


def _path(value: object, root: Path, location: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceError(f"{location} 必须是非空路径字符串")
    return (root / Path(value).expanduser()).resolve()


def discover_workspace(start: Path | None = None, *, tool_root: Path = PROJECT_ROOT) -> Path:
    """祖先声明优先；工具仓库自身也可作为无声明工作区。"""
    start = Path(start or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent
    for directory in (start, *start.parents):
        if (directory / "flange.toml").is_file():
            return directory
        if directory == Path(tool_root).resolve():
            return directory
    raise WorkspaceError(
        "当前目录不属于 flange 工作区。请先运行 flange init . --tool-root /path/to/flange"
    )


def workspace_settings(root: Path, *, tool_root: Path = PROJECT_ROOT) -> dict:
    """严格读取声明，路径只相对声明所在目录解释一次。"""
    root = Path(root).resolve()
    manifest = root / "flange.toml"
    if manifest.is_file():
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise WorkspaceError(f"无法读取 {manifest}：{exc}") from exc
        _fields(
            data,
            {"schema_version", "tool_root", "build_dir", "app_dirs", "apps", "target", "layers"},
            "flange.toml",
        )
        if type(data.get("schema_version")) is not int or data["schema_version"] not in (1, 2):
            raise WorkspaceError("flange.toml 的 schema_version 必须是整数 1 或 2")
    else:
        if root != Path(tool_root).resolve():
            raise WorkspaceError(f"{root} 缺少 flange.toml；请运行 flange init {root}")
        data = {}
    resolved_tool = _path(data.get("tool_root", str(tool_root)), root, "tool_root")
    if (
        not components_dir(resolved_tool).is_dir()
        or not (resolved_tool / "docker-compose.yml").is_file()
    ):
        raise WorkspaceError(f"tool_root 不是完整的 flange 工具仓库：{resolved_tool}")
    raw_layers = data.get("layers", [])
    if "layers" in data and data.get("schema_version") != 2:
        raise WorkspaceError("layers 需要 flange.toml schema_version = 2")
    if not isinstance(raw_layers, list):
        raise WorkspaceError("layers 必须是本地路径数组")
    layer_stack = LayerStack.load(resolved_tool, [
        _path(value, root, f"layers[{index}]") for index, value in enumerate(raw_layers)
    ])
    output = _path(data.get("build_dir", str(build_dir(root))), root, "build_dir")
    if (
        output == root
        or output in root.parents
        or output == resolved_tool
        or output in resolved_tool.parents
    ):
        raise WorkspaceError("build_dir 必须是独立的产物目录，不能覆盖工作区或工具根")
    if any(output == layer.root or output in layer.root.parents for layer in layer_stack.layers):
        raise WorkspaceError("build_dir 不能覆盖任一扩展层根目录")
    app_dirs = data.get("app_dirs", [])
    if not isinstance(app_dirs, list):
        raise WorkspaceError("app_dirs 必须是路径字符串数组")
    apps = data.get("apps", {})
    if not isinstance(apps, dict):
        raise WorkspaceError("apps 必须是名称到路径的表")
    target = data.get("target")
    if target is not None:
        _fields(target, {"board", "product", "variant"}, "target")
        try:
            target = Target(**target)
        except TypeError as exc:
            raise WorkspaceError("target 必须完整声明 board、product、variant") from exc
    return {
        "tool_root": resolved_tool,
        "layer_stack": layer_stack,
        "workspace_root": root,
        "build_root": output,
        "target": target,
        "apps": {name: _path(path, root, f"apps.{name}") for name, path in apps.items()},
        "app_dirs": tuple(
            _path(path, root, f"app_dirs[{index}]") for index, path in enumerate(app_dirs)
        ),
    }


def selected_target(root: Path, default: Target | None = None) -> Target | None:
    state_file = root / ".flange" / "current_config"
    if not state_file.exists():
        return default
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        _fields(state, {"board", "product", "variant"}, str(state_file))
        return Target(**state)
    except (OSError, ValueError, TypeError) as exc:
        raise WorkspaceError(
            f"目标状态无效：{state_file}；运行 flange target select <target> 重新选择。{exc}"
        ) from exc


def load_workspace(
    start: Path | None = None, *, target: str | Target | None = None, tool_root: Path = PROJECT_ROOT
) -> WorkspaceContext:
    invocation = Path(start or Path.cwd()).resolve()
    root = discover_workspace(invocation, tool_root=tool_root)
    values = workspace_settings(root, tool_root=tool_root)
    chosen = Target.parse(target, values["tool_root"], values["layer_stack"]) if isinstance(target, str) else target
    chosen = chosen or selected_target(root, values["target"])
    if chosen is None:
        raise WorkspaceError(
            "尚未选择目标。运行 flange target list 查看目标，再运行 flange target select <target>"
        )
    values["target"] = chosen
    return WorkspaceContext(**values, invocation_dir=invocation)


def save_target(root: Path, target: Target) -> None:
    atomic_write(
        Path(root) / ".flange" / "current_config",
        json.dumps(target.to_dict(), ensure_ascii=False, indent=2) + "\n",
    )


def _array_end(text: str, start: int) -> int:
    """返回 TOML 数组闭合括号之后的位置；跳过字符串与注释。"""
    depth = 0
    index = start
    quote = ""
    while index < len(text):
        char = text[index]
        if quote:
            if len(quote) == 3:
                if text[index : index + 3] == quote:
                    quote = ""
                    index += 3
                    continue
            elif char == "\\" and quote == '"':
                index += 2
                continue
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char * 3 if text[index : index + 3] == char * 3 else char
            index += len(quote)
            continue
        elif char == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise WorkspaceError("flange.toml 的 layers 数组未闭合")


def _with_layers(text: str, layers: list[str]) -> str:
    """只改写顶层 schema_version 与 layers，保留其余声明和注释。"""
    header = re.search(r"(?m)^[ \t]*\[", text)
    boundary = header.start() if header else len(text)
    prefix, suffix = text[:boundary], text[boundary:]
    prefix = re.sub(
        r"(?m)^([ \t]*schema_version\s*=\s*)1([ \t]*(?:#.*)?)$",
        r"\g<1>2\g<2>",
        prefix,
        count=1,
    )
    value = "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in layers) + "]"
    assignment = re.search(r"(?m)^([ \t]*)layers\s*=\s*", prefix)
    if assignment:
        opening = prefix.find("[", assignment.end())
        if opening < 0:
            raise WorkspaceError("flange.toml 的 layers 必须是路径数组")
        end = _array_end(prefix, opening)
        prefix = (
            prefix[: assignment.start()]
            + f"{assignment.group(1)}layers = {value}"
            + prefix[end:]
        )
    else:
        anchor = re.search(r"(?m)^[ \t]*schema_version\s*=.*$", prefix)
        if anchor is None:
            raise WorkspaceError("flange.toml 缺少顶层 schema_version，无法添加扩展层")
        prefix = (
            prefix[: anchor.end()] + f"\nlayers = {value}" + prefix[anchor.end() :]
        )
    return prefix + suffix


def add_layer(root: Path, path: Path, *, tool_root: Path = PROJECT_ROOT) -> dict:
    """把已有本地层追加为最高层；不创建、下载或重排层。"""
    root = Path(root).resolve()
    manifest = root / "flange.toml"
    if not manifest.is_file():
        raise WorkspaceError(
            f"{root} 缺少 flange.toml；请先运行 flange init 创建产品工作区再添加扩展层"
        )
    with FileLock(root / ".flange" / "workspace.lock"):
        settings = workspace_settings(root, tool_root=tool_root)
        candidate = read_layer(Path(path))
        existing = list(settings["layer_stack"].layers[1:])
        if any(item.root == candidate.root for item in existing):
            raise WorkspaceError(f"层已启用：{candidate.name} ({candidate.root})")
        stack = LayerStack.load(
            settings["tool_root"], [item.root for item in existing] + [candidate.root]
        )
        output = settings["build_root"]
        if output == candidate.root or output in candidate.root.parents:
            raise WorkspaceError("build_dir 不能覆盖任一扩展层根目录")
        text = manifest.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        stored = Path(relpath(candidate.root, root)).as_posix()
        layers = [*data.get("layers", []), stored]
        updated = _with_layers(text, layers)
        expected = {**data, "schema_version": 2, "layers": layers}
        if tomllib.loads(updated) != expected:
            raise WorkspaceError(
                f"无法安全更新 {manifest}；请手动把 {stored!r} 追加到 layers 并保持 schema_version = 2"
            )
        atomic_write(manifest, updated)
        return {
            "layer": dict(candidate.to_dict(), order=len(stack.layers) - 1),
            "manifest": str(manifest),
            "layers": stack.to_dict(),
        }


def resolve_config(context: WorkspaceContext) -> dict:
    from builder.config.registry import resolve_config as resolve
    from builder.config.validate import validate_config

    config = resolve(
        context.target.board,
        context.target.product,
        context.target.variant,
        project_root=context.tool_root,
        layer_stack=context.layer_stack,
    )
    validate_config(config)
    return config


def init_workspace(
    root: Path, *, tool_root: Path = PROJECT_ROOT, target: str | None = None
) -> Path:
    root, tool_root = Path(root).resolve(), Path(tool_root).resolve()
    manifest = root / "flange.toml"
    if manifest.exists():
        raise WorkspaceError(f"工作区已存在：{manifest}")
    if not components_dir(tool_root).is_dir() or not (tool_root / "docker-compose.yml").is_file():
        raise WorkspaceError(f"tool_root 不是完整的 flange 工具仓库：{tool_root}")
    chosen = Target.parse(target, tool_root) if target else None
    lines = [
        "# flange 工作区；相对路径以此文件所在目录为基准。",
        "schema_version = 1",
        f"tool_root = {json.dumps(str(tool_root), ensure_ascii=False)}",
        'build_dir = ".build"',
        'app_dirs = ["apps"]',
        "",
        "[apps]",
        "",
    ]
    if chosen:
        lines += ["[target]", *(f"{k} = {json.dumps(v)}" for k, v in chosen.to_dict().items()), ""]
    root.mkdir(parents=True, exist_ok=True)
    # 排他创建，两个初始化进程不能互相覆盖配置。
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return manifest
