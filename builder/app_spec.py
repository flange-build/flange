"""App 描述文件解析模块 — 加载并校验 app.yaml，返回强类型 AppSpec 对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

import yaml


# 允许的 App 类型。amp = 协处理器固件工程（裸机 HAL / RT-Thread 之上的用户
# 应用），产物是固件而非装进 rootfs 的 deb，走独立构建路径（见 app.py
# build_one 的 amp 分叉与 platforms/rockchip/amp.py 的应用槽位 staging）。
VALID_APP_TYPES = {"exec", "service", "lib", "test", "amp"}

# 允许的构建系统取值。amp = 经 SDK（HAL Makefile / RT-Thread scons）+ mkimage
# 打 FIT，由 amp 组件驱动，不复用 _BUILD_SYSTEMS 的 host 交叉编译模板。
VALID_BUILD_SYSTEMS = {"none", "cmake", "meson", "make", "swift", "custom", "amp", "scons"}

# build.apt_packages 仅接受 Debian 包名和可选架构限定符。允许 {arch}
# 占位符在构建时替换成当前目标架构，拒绝以 '-' 开头的 APT 选项注入。
APT_PACKAGE_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9+.-]*(?::(?:\{arch\}|[a-z0-9][a-z0-9-]*))?$"
)


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
    # 当前构建容器内安装的 APT 编译依赖，支持 :{arch} 架构占位符
    apt_packages: List[str] = field(default_factory=list)
    # custom 构建专用命令列表，每项为字符串列表
    commands: List[List[str]] = field(default_factory=list)
    # Embedded Swift 配置；仅 app.type=amp + build.system=scons 可用
    swift: Optional["SwiftBuildConfig"] = None


@dataclass
class SwiftBuildConfig:
    """Embedded Swift / SwiftPM 构建配置段（build.swift:）。"""
    # 是否启用 SwiftPM 构建
    enabled: bool = False
    # Swift package 路径（相对于 App 根目录）
    package_path: str = "."
    # SwiftPM static library product 名称
    product: str = ""
    # C ABI bridge 头文件路径（相对于 App 根目录，可选）
    c_header: str = ""
    # SwiftPM baremetal target triple；默认由 RK3568 A55 AArch32 使用
    target_triple: str = "armv7-none-none-eabi"
    # 追加到 swift build 后的原始参数
    extra_flags: List[str] = field(default_factory=list)


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

    # 校验 arch 非空
    if not arch:
        raise AppSpecError("app.arch 不能为空")

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


def _parse_str_list_value(value, field: str) -> List[str]:
    """把字符串或字符串列表解析成 List[str]。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise AppSpecError(f"{field} 必须是字符串或列表")


def _validate_relative_path(value, field: str, *, allow_empty: bool = False) -> str:
    """校验相对 App 根目录的路径，禁止绝对路径和 `..` 逃逸。"""
    if not isinstance(value, str):
        raise AppSpecError(f"{field} 必须是字符串")
    path = value.strip()
    if not path:
        if allow_empty:
            return ""
        raise AppSpecError(f"{field} 不能为空")

    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise AppSpecError(f"{field} 必须是相对 app 根目录且不得包含 '..'")
    return path


def _parse_swift_build(raw, app_info: AppInfo, system: str) -> Optional[SwiftBuildConfig]:
    """解析 build.swift 子段。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise AppSpecError("build.swift 必须是字典")
    if app_info.type != "amp" or system != "scons":
        raise AppSpecError("build.swift 仅允许用于 app.type=amp 且 build.system=scons")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AppSpecError("build.swift.enabled 必须是布尔值")

    package_path = _validate_relative_path(
        raw.get("package_path", "."),
        "build.swift.package_path",
    )
    product = str(raw.get("product", "")).strip()
    if enabled and not product:
        raise AppSpecError("build.swift.product 在 enabled=true 时必须是非空字符串")

    c_header = _validate_relative_path(
        raw.get("c_header", ""),
        "build.swift.c_header",
        allow_empty=True,
    )
    target_triple = str(raw.get("target_triple", "armv7-none-none-eabi")).strip()
    if enabled and not target_triple:
        raise AppSpecError("build.swift.target_triple 在 enabled=true 时必须是非空字符串")

    return SwiftBuildConfig(
        enabled=enabled,
        package_path=package_path,
        product=product,
        c_header=c_header,
        target_triple=target_triple,
        extra_flags=_parse_str_list_value(
            raw.get("extra_flags", []),
            "build.swift.extra_flags",
        ),
    )


def _parse_build(raw: dict, app_info: AppInfo) -> BuildConfig:
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

    outputs = _parse_str_list_value(raw.get("outputs", []), "build.outputs")
    deps = _parse_str_list_value(raw.get("deps", []), "build.deps")
    apt_packages = _parse_str_list_value(
        raw.get("apt_packages", []),
        "build.apt_packages",
    )
    for package in apt_packages:
        if not APT_PACKAGE_PATTERN.fullmatch(package):
            raise AppSpecError(
                "build.apt_packages 包名无效："
                f"'{package}'，仅允许 Debian 包名及可选的 :{{arch}} 架构限定符"
            )

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
        apt_packages=apt_packages,
        commands=parsed_commands,
        swift=_parse_swift_build(raw.get("swift"), app_info, system),
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
    build = _parse_build(raw["build"], app_info) if "build" in raw else BuildConfig()

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
        return _parse_str_list_value(raw.get(key, []), key)

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
