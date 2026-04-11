"""App 描述文件解析模块 — 加载并校验 app.yaml，返回强类型 AppSpec 对象。"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# 允许的 App 类型
VALID_APP_TYPES = {"exec", "service", "lib", "test"}

# 允许的构建系统取值
VALID_BUILD_SYSTEMS = {"none", "cmake", "meson", "make", "swift", "custom"}


class AppSpecError(ValueError):
    """app.yaml 解析或校验失败时抛出。"""


@dataclass
class MaintainerInfo:
    """维护者信息。"""
    name: str
    email: str


@dataclass
class BuildConfig:
    """构建配置段（build:）。"""
    # 构建系统，默认 none
    system: str = "none"
    # 传递给构建系统的选项，如 CMake 变量
    options: Dict[str, str] = field(default_factory=dict)
    # 构建产物路径列表（相对于 App 目录）
    outputs: List[str] = field(default_factory=list)
    # App 间构建依赖
    deps: List[str] = field(default_factory=list)
    # custom 构建专用命令列表，每项为字符串列表
    commands: List[List[str]] = field(default_factory=list)


@dataclass
class SystemdConfig:
    """systemd 服务配置段（systemd:），仅 service 类型使用。"""
    # service unit 文件路径（相对于 App 目录）
    unit: str = ""
    # 是否随系统自动启动，默认 false
    auto_start: bool = False


@dataclass
class LibConfig:
    """链接库配置段（lib:），仅 lib 类型使用。"""
    # 头文件目录（相对于 App 目录）
    headers_dir: str = "include/"
    # dev 包后缀，默认 -dev
    dev_suffix: str = "-dev"


@dataclass
class AppInfo:
    """app: 段的基本信息。"""
    name: str
    version: str
    description: str
    # exec / service / lib / test
    type: str
    # 支持的目标架构列表
    arch: List[str] = field(default_factory=list)


@dataclass
class AppSpec:
    """app.yaml 的完整结构化表示。"""
    app: AppInfo
    maintainer: MaintainerInfo
    # 能力声明（可选）
    capabilities: List[str] = field(default_factory=list)
    # 构建配置（可选，缺省值见 BuildConfig）
    build: BuildConfig = field(default_factory=BuildConfig)
    # 安装路径映射：源文件路径 -> 目标路径（可选，覆盖约定默认值）
    install: Dict[str, str] = field(default_factory=dict)
    # systemd 配置（可选，仅 service 类型有意义）
    systemd: Optional[SystemdConfig] = None
    # 运行期 apt 依赖
    depends: List[str] = field(default_factory=list)
    # dpkg conffiles 声明（安装后不被覆盖的配置文件）
    conffiles: List[str] = field(default_factory=list)
    # 运行时数据目录声明
    data_dirs: List[str] = field(default_factory=list)
    # lib 配置（可选，仅 lib 类型有意义）
    lib: Optional[LibConfig] = None


def _parse_app_info(raw: dict) -> AppInfo:
    """解析 app: 段，校验必填字段与类型合法性。"""
    if not isinstance(raw, dict):
        raise AppSpecError("app: 段必须是字典")

    # 校验必填字段
    for key in ("name", "version", "description", "type"):
        if key not in raw:
            raise AppSpecError(f"app.yaml 缺少必填字段：app.{key}")
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise AppSpecError(f"app.{key} 必须是非空字符串")

    # 校验 type 取值
    app_type = raw["type"]
    if app_type not in VALID_APP_TYPES:
        raise AppSpecError(
            f"app.type 取值无效：'{app_type}'，允许值：{sorted(VALID_APP_TYPES)}"
        )

    # 解析 arch（可选，允许字符串或列表）
    raw_arch = raw.get("arch", [])
    if isinstance(raw_arch, str):
        arch = [raw_arch]
    elif isinstance(raw_arch, list):
        arch = [str(a) for a in raw_arch]
    else:
        raise AppSpecError("app.arch 必须是字符串或列表")

    return AppInfo(
        name=raw["name"].strip(),
        version=raw["version"].strip(),
        description=raw["description"].strip(),
        type=app_type,
        arch=arch,
    )


def _parse_maintainer(raw: dict) -> MaintainerInfo:
    """解析 maintainer: 段，校验必填字段。"""
    if not isinstance(raw, dict):
        raise AppSpecError("maintainer: 段必须是字典")
    for key in ("name", "email"):
        if key not in raw:
            raise AppSpecError(f"app.yaml 缺少必填字段：maintainer.{key}")
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise AppSpecError(f"maintainer.{key} 必须是非空字符串")
    return MaintainerInfo(name=raw["name"].strip(), email=raw["email"].strip())


def _parse_build(raw: dict) -> BuildConfig:
    """解析 build: 段，校验 system 取值，填充默认值。"""
    if not isinstance(raw, dict):
        raise AppSpecError("build: 段必须是字典")

    system = raw.get("system", "none")
    if system not in VALID_BUILD_SYSTEMS:
        raise AppSpecError(
            f"build.system 取值无效：'{system}'，允许值：{sorted(VALID_BUILD_SYSTEMS)}"
        )

    # 解析 options
    options = raw.get("options", {})
    if not isinstance(options, dict):
        raise AppSpecError("build.options 必须是字典")
    options = {str(k): str(v) for k, v in options.items()}

    # 解析 outputs
    outputs = raw.get("outputs", [])
    if isinstance(outputs, str):
        outputs = [outputs]
    elif not isinstance(outputs, list):
        raise AppSpecError("build.outputs 必须是列表")
    outputs = [str(o) for o in outputs]

    # 解析 deps
    deps = raw.get("deps", [])
    if isinstance(deps, str):
        deps = [deps]
    elif not isinstance(deps, list):
        raise AppSpecError("build.deps 必须是列表")
    deps = [str(d) for d in deps]

    # 解析 commands（custom 专用）
    commands = raw.get("commands", [])
    if not isinstance(commands, list):
        raise AppSpecError("build.commands 必须是列表")
    parsed_commands = []
    for i, cmd in enumerate(commands):
        if isinstance(cmd, list):
            parsed_commands.append([str(c) for c in cmd])
        elif isinstance(cmd, str):
            # 兼容单字符串写法
            parsed_commands.append([cmd])
        else:
            raise AppSpecError(f"build.commands[{i}] 必须是字符串或列表")

    return BuildConfig(
        system=system,
        options=options,
        outputs=outputs,
        deps=deps,
        commands=parsed_commands,
    )


def _parse_systemd(raw: dict) -> SystemdConfig:
    """解析 systemd: 段，填充默认值。"""
    if not isinstance(raw, dict):
        raise AppSpecError("systemd: 段必须是字典")
    unit = str(raw.get("unit", ""))
    auto_start = bool(raw.get("auto_start", False))
    return SystemdConfig(unit=unit, auto_start=auto_start)


def _parse_lib(raw: dict) -> LibConfig:
    """解析 lib: 段，填充默认值。"""
    if not isinstance(raw, dict):
        raise AppSpecError("lib: 段必须是字典")
    headers_dir = str(raw.get("headers_dir", "include/"))
    dev_suffix = str(raw.get("dev_suffix", "-dev"))
    return LibConfig(headers_dir=headers_dir, dev_suffix=dev_suffix)


def load_spec(app_dir: Path) -> AppSpec:
    """从 app_dir/app.yaml 加载并返回 AppSpec。

    参数：
        app_dir: App 工程目录，必须包含 app.yaml

    返回：
        解析并校验完毕的 AppSpec 对象

    抛出：
        AppSpecError: app.yaml 缺失、格式错误或字段校验失败
        FileNotFoundError: app.yaml 文件不存在
    """
    yaml_path = app_dir / "app.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"app.yaml 不存在：{yaml_path}")

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AppSpecError(f"app.yaml YAML 解析失败：{exc}") from exc

    if not isinstance(raw, dict):
        raise AppSpecError("app.yaml 顶层必须是字典")

    # 解析必填顶层段
    if "app" not in raw:
        raise AppSpecError("app.yaml 缺少必填段：app")
    if "maintainer" not in raw:
        raise AppSpecError("app.yaml 缺少必填段：maintainer")

    app_info = _parse_app_info(raw["app"])
    maintainer = _parse_maintainer(raw["maintainer"])

    # 解析可选段：capabilities
    raw_caps = raw.get("capabilities", [])
    if isinstance(raw_caps, str):
        capabilities = [raw_caps]
    elif isinstance(raw_caps, list):
        capabilities = [str(c) for c in raw_caps]
    else:
        raise AppSpecError("capabilities 必须是字符串或列表")

    # 解析可选段：build
    build = _parse_build(raw["build"]) if "build" in raw else BuildConfig()

    # 解析可选段：install（文件映射）
    raw_install = raw.get("install", {})
    if not isinstance(raw_install, dict):
        raise AppSpecError("install: 段必须是字典")
    install = {str(k): str(v) for k, v in raw_install.items()}

    # 解析可选段：systemd
    systemd: Optional[SystemdConfig] = None
    if "systemd" in raw:
        systemd = _parse_systemd(raw["systemd"])

    # 解析可选段：depends / conffiles / data_dirs
    def _parse_str_list(key: str) -> List[str]:
        val = raw.get(key, [])
        if isinstance(val, str):
            return [val]
        if isinstance(val, list):
            return [str(v) for v in val]
        raise AppSpecError(f"{key} 必须是字符串或列表")

    depends = _parse_str_list("depends")
    conffiles = _parse_str_list("conffiles")
    data_dirs = _parse_str_list("data_dirs")

    # 解析可选段：lib
    lib: Optional[LibConfig] = None
    if "lib" in raw:
        lib = _parse_lib(raw["lib"])

    return AppSpec(
        app=app_info,
        maintainer=maintainer,
        capabilities=capabilities,
        build=build,
        install=install,
        systemd=systemd,
        depends=depends,
        conffiles=conffiles,
        data_dirs=data_dirs,
        lib=lib,
    )
