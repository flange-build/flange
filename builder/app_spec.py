"""App 描述文件解析模块 — 加载并校验 app.yaml，返回强类型 AppSpec 对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

import yaml

from builder.actions import validate_actions
from builder.config.schema import BOOLEAN, STRING, STRINGS, TEXT, ListOf, Map, Object, SchemaError


# 允许的 App 类型。amp = 协处理器固件工程（裸机 HAL / RT-Thread 之上的用户
# 应用），产物是固件而非装进 rootfs 的 deb，由系统 amp 组件驱动
# platforms/rockchip/amp.py 中的应用槽位 staging。
# staging = 只产出供下游 App 消费的交叉编译产物树（DESTDIR 安装树），不打
# deb、不进 rootfs。用于把一条长编译链拆成可独立增量的单元：链上的中间环节
# （如 GStreamer core/base 之于 Rockchip 插件）本身不交付任何包，只提供下游
# configure 所需的头文件与库。
SUPPORTED_APP_ARCHITECTURES = ("aarch64", "armhf")

VALID_APP_TYPES = {
    "exec",
    "service",
    "lib",
    "test",
    "vendor",
    "amp",
    "staging",
}

# 允许的构建系统取值。amp = 经 SDK（HAL Makefile / RT-Thread scons）+ mkimage
# 打 FIT，由 amp 组件驱动，不复用 _BUILD_SYSTEMS 的 host 交叉编译模板。
VALID_BUILD_SYSTEMS = {"none", "cmake", "meson", "make", "swift", "custom", "amp", "scons"}

# vendor App 可映射进 deb control.tar.gz 的维护脚本与触发器。
VALID_MAINTAINER_SCRIPT_NAMES = {
    "preinst",
    "postinst",
    "prerm",
    "postrm",
    "triggers",
}

# build.apt_packages 仅接受 Debian 包名和可选架构限定符。允许 {arch}
# 占位符在构建时替换成当前目标架构，拒绝以 '-' 开头的 APT 选项注入。
APT_PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.-]*(?::(?:\{arch\}|[a-z0-9][a-z0-9-]*))?$")
APP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]*$")
APP_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.:~_-]*$")


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
    # custom vendor App 直接生成的完整 deb 文件名
    deb_outputs: List[str] = field(default_factory=list)
    # 供下游 App 消费的产物树，相对 FLANGE_APP_WORK_DIR。声明后进入该 App 的
    # 产物清单：缓存命中要求它仍然存在，否则下游会拿不到头文件而编译失败。
    staging: str = ""
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

    # dev 包后缀，默认 -dev
    dev_suffix: str = "-dev"


@dataclass
class RuntimeConfig:
    """exec/test 的目标运行路径；空值使用 /usr/bin/<app.name>。"""

    executable: str = ""


@dataclass
class AppInfo:
    """app: 段的基本信息。"""

    name: str
    version: str
    description: str
    # exec / service / lib / test / vendor / amp
    type: str
    # 支持的目标架构列表
    arch: List[str] = field(default_factory=list)


@dataclass
class AppSpec:
    """app.yaml 的完整结构化表示。"""

    app: AppInfo
    maintainer: MaintainerInfo
    # 可执行程序运行契约；由部署与调试入口消费。
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
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
    # vendor deb 维护脚本名 -> 文件内容
    maintainer_scripts: Dict[str, str] = field(default_factory=dict)
    # lib 配置（可选，仅 lib 类型有意义）
    lib: Optional[LibConfig] = None
    # 显式生命周期 action：action 名 -> 不经 shell 展开的 argv
    actions: Dict[str, List[str]] = field(default_factory=dict)


APP_INFO_SCHEMA = Object(
    dict.fromkeys(("name", "version", "description", "type"), STRING) | {"arch": STRINGS},
    ("name", "version", "description", "type", "arch"),
)
MAINTAINER_SCHEMA = Object({"name": STRING, "email": STRING}, ("name", "email"))
SYSTEMD_SCHEMA = Object({"unit": STRING, "auto_start": BOOLEAN}, ("unit",))
LIB_SCHEMA = Object({"dev_suffix": STRING})
SWIFT_SCHEMA = Object(
    {
        "enabled": BOOLEAN,
        "package_path": STRING,
        "product": TEXT,
        "c_header": TEXT,
        "target_triple": STRING,
        "extra_flags": STRINGS,
    }
)
BUILD_SCHEMA = Object(
    {
        "system": STRING,
        "options": Map(TEXT),
        "deb_outputs": STRINGS,
        "staging": TEXT,
        "deps": STRINGS,
        "apt_packages": STRINGS,
        "commands": ListOf(STRINGS),
        "swift": SWIFT_SCHEMA,
    }
)
APP_SCHEMA = Object(
    {
        "app": APP_INFO_SCHEMA,
        "maintainer": MAINTAINER_SCHEMA,
        "build": BUILD_SCHEMA,
        "install": Map(STRING),
        "systemd": SYSTEMD_SCHEMA,
        "depends": STRINGS,
        "conffiles": STRINGS,
        "data_dirs": STRINGS,
        "maintainer_scripts": Map(STRING),
        "lib": LIB_SCHEMA,
        "actions": Map(STRINGS),
        "runtime": Object({"executable": TEXT}),
    },
    ("app", "maintainer"),
)


def _check(schema, value, path: str) -> None:
    try:
        schema.check(value, path)
    except SchemaError as exc:
        raise AppSpecError(str(exc)) from exc


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝重复键，避免后一个字段静默覆盖维护者看到的前一个字段。"""

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise AppSpecError(f"app.yaml 第 {key_node.start_mark.line + 1} 行的键必须是字符串")
            if key in mapping:
                raise AppSpecError(f"app.yaml 第 {key_node.start_mark.line + 1} 行重复字段：{key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _validate_target_path(value: str, field: str) -> str:
    """目标设备路径与宿主源码路径是不同域，禁止归一化掩盖错误。"""
    _check(STRING, value, field)
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) != value.rstrip("/")
        or value == "/"
        or any(c in value for c in "\0\r\n")
    ):
        raise AppSpecError(f"{field} 必须是规范的目标绝对路径，不能含 '..'、换行或根目录")
    return value


def _parse_app_info(raw: dict) -> AppInfo:
    """解析 app: 段，校验必填字段与类型合法性。"""
    if not isinstance(raw, dict):
        raise AppSpecError("app: 段必须是字典")

    _check(APP_INFO_SCHEMA, raw, "app")
    # 校验必填字段
    for key in ("name", "version", "description", "type"):
        if key not in raw:
            raise AppSpecError(f"app.yaml 缺少必填字段：app.{key}")
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise AppSpecError(f"app.{key} 必须是非空字符串")

    name = raw["name"]
    version = raw["version"]
    if not APP_NAME_PATTERN.fullmatch(name):
        raise AppSpecError(
            "app.name 只能包含字母、数字、加号、点、下划线和连字符，且必须以字母或数字开头"
        )
    if not APP_VERSION_PATTERN.fullmatch(version):
        raise AppSpecError(
            "app.version 只能包含字母、数字、加号、点、冒号、波浪号、"
            "下划线和连字符，且必须以字母或数字开头"
        )

    # 校验 type 取值
    app_type = raw["type"]
    if app_type not in VALID_APP_TYPES:
        raise AppSpecError(f"app.type 取值无效：'{app_type}'，允许值：{sorted(VALID_APP_TYPES)}")

    arch = _parse_str_list_value(raw.get("arch", []), "app.arch")
    if any(item not in SUPPORTED_APP_ARCHITECTURES for item in arch):
        raise AppSpecError("app.arch 只允许 aarch64 或 armhf，请声明实际支持的目标架构")
    if len(set(arch)) != len(arch):
        raise AppSpecError("app.arch 不得重复")

    # 校验 arch 非空
    if not arch:
        raise AppSpecError("app.arch 不能为空")

    return AppInfo(
        name=name,
        version=version,
        description=raw["description"].strip(),
        type=app_type,
        arch=arch,
    )


def _parse_maintainer(raw: dict) -> MaintainerInfo:
    """解析 maintainer: 段，校验必填字段。"""
    if not isinstance(raw, dict):
        raise AppSpecError("maintainer: 段必须是字典")
    _check(MAINTAINER_SCHEMA, raw, "maintainer")
    for key in ("name", "email"):
        if key not in raw:
            raise AppSpecError(f"app.yaml 缺少必填字段：maintainer.{key}")
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise AppSpecError(f"maintainer.{key} 必须是非空字符串")
    return MaintainerInfo(name=raw["name"].strip(), email=raw["email"].strip())


def _parse_maintainer_scripts(
    raw: dict,
    app_dir: Path,
    app_info: AppInfo,
) -> Dict[str, str]:
    """读取 vendor deb 维护脚本，拒绝 App 目录外的路径。"""
    if not isinstance(raw, dict):
        raise AppSpecError("maintainer_scripts: 段必须是字典")
    if raw and app_info.type != "vendor":
        raise AppSpecError("maintainer_scripts 仅允许用于 app.type=vendor")

    app_root = app_dir.resolve()
    scripts: Dict[str, str] = {}
    for name, value in raw.items():
        if name not in VALID_MAINTAINER_SCRIPT_NAMES:
            raise AppSpecError(
                f"maintainer_scripts 名称无效：{name!r}；允许值："
                f"{sorted(VALID_MAINTAINER_SCRIPT_NAMES)}"
            )
        relative = _validate_relative_path(
            value,
            f"maintainer_scripts.{name}",
        )
        script_path = (app_dir / relative).resolve()
        try:
            script_path.relative_to(app_root)
        except ValueError as exc:
            raise AppSpecError(f"maintainer_scripts.{name} 必须位于 App 目录内") from exc
        if not script_path.is_file():
            raise AppSpecError(f"maintainer_scripts.{name} 文件不存在：{script_path}")
        try:
            content = script_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise AppSpecError(f"maintainer_scripts.{name} 必须是 UTF-8 文本") from exc
        if name != "triggers" and not content.startswith("#!"):
            raise AppSpecError(f"maintainer_scripts.{name} 必须以 shebang 开头")
        scripts[name] = content
    return scripts


def _parse_str_list_value(value, field: str) -> List[str]:
    """解析严格字符串列表，不把错误的标量隐式转换。"""
    _check(STRINGS, value, field)
    return list(value)


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
    if pure.is_absolute() or ".." in pure.parts or any(c in path for c in "\0\r\n"):
        raise AppSpecError(f"{field} 必须是相对 app 根目录且不得包含 '..'")
    return path


def _parse_swift_build(raw, app_info: AppInfo, system: str) -> Optional[SwiftBuildConfig]:
    """解析 build.swift 子段。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise AppSpecError("build.swift 必须是字典")
    _check(SWIFT_SCHEMA, raw, "build.swift")
    if app_info.type != "amp" or system != "scons":
        raise AppSpecError("build.swift 仅允许用于 app.type=amp 且 build.system=scons")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AppSpecError("build.swift.enabled 必须是布尔值")

    package_path = _validate_relative_path(
        raw.get("package_path", "."),
        "build.swift.package_path",
    )
    product = raw.get("product", "").strip()
    if enabled and not product:
        raise AppSpecError("build.swift.product 在 enabled=true 时必须是非空字符串")

    c_header = _validate_relative_path(
        raw.get("c_header", ""),
        "build.swift.c_header",
        allow_empty=True,
    )
    target_triple = raw.get("target_triple", "armv7-none-none-eabi").strip()
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

    _check(BUILD_SCHEMA, raw, "build")
    system = raw.get("system", "none")
    if system not in VALID_BUILD_SYSTEMS:
        raise AppSpecError(
            f"build.system 取值无效：'{system}'，允许值：{sorted(VALID_BUILD_SYSTEMS)}"
        )

    if system in {"amp", "scons"} and app_info.type != "amp":
        raise AppSpecError("build.system=amp/scons 仅允许 app.type=amp")
    # 解析 options
    options = raw.get("options", {})
    if not isinstance(options, dict):
        raise AppSpecError("build.options 必须是字典")
    _check(Map(TEXT), options, "build.options")
    if options and (system not in {"cmake", "meson", "make", "swift"} or app_info.type == "amp"):
        raise AppSpecError("build.options 在该构建系统没有消费者，请删除或改用支持的构建系统")

    staging = raw.get("staging", "")
    if not isinstance(staging, str):
        raise AppSpecError("build.staging 必须是字符串")
    staging = (staging or "").strip()
    if staging:
        path = PurePosixPath(staging)
        if path.is_absolute() or ".." in path.parts:
            raise AppSpecError(f"build.staging 必须是工作目录内的相对路径: {staging!r}")
    if app_info.type == "staging" and not staging:
        raise AppSpecError("app.type=staging 必须声明 build.staging（供下游消费的产物树）")
    deb_outputs = _parse_str_list_value(
        raw.get("deb_outputs", []),
        "build.deb_outputs",
    )
    if deb_outputs and (app_info.type != "vendor" or system != "custom"):
        raise AppSpecError("build.deb_outputs 仅允许用于 app.type=vendor 且 build.system=custom")
    for filename in deb_outputs:
        path = PurePosixPath(filename)
        if (
            path.name != filename
            or not filename.endswith(".deb")
            or filename == ".deb"
            or any(char in filename for char in "*?[]")
        ):
            raise AppSpecError(
                f"build.deb_outputs 只能包含输出目录内的安全 .deb 文件名: {filename!r}"
            )
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

    # custom 命令只接受 argv 数组，不进行 shell 或字符串隐式展开。
    parsed_commands = raw.get("commands", [])
    _check(ListOf(STRINGS), parsed_commands, "build.commands")
    if any(not command for command in parsed_commands):
        raise AppSpecError("build.commands 每个命令必须是非空 argv 列表")
    if parsed_commands and system != "custom":
        raise AppSpecError(
            "build.commands 仅由 build.system=custom 消费，请修改 system 或删除 commands"
        )
    if system == "custom" and not parsed_commands:
        raise AppSpecError("build.system=custom 必须声明非空 build.commands")

    return BuildConfig(
        system=system,
        options=options,
        deb_outputs=deb_outputs,
        staging=staging,
        deps=deps,
        apt_packages=apt_packages,
        commands=parsed_commands,
        swift=_parse_swift_build(raw.get("swift"), app_info, system),
    )


def _parse_systemd(raw: dict) -> SystemdConfig:
    """解析 systemd: 段，填充默认值。"""
    if not isinstance(raw, dict):
        raise AppSpecError("systemd: 段必须是字典")
    _check(SYSTEMD_SCHEMA, raw, "systemd")
    unit = _validate_relative_path(raw.get("unit", ""), "systemd.unit")
    if not unit.endswith(".service"):
        raise AppSpecError("systemd.unit 必须指向 .service 文件")
    auto_start = raw.get("auto_start", False)
    return SystemdConfig(unit=unit, auto_start=auto_start)


def _parse_lib(raw: dict) -> LibConfig:
    """解析 lib: 段，填充默认值。"""
    if not isinstance(raw, dict):
        raise AppSpecError("lib: 段必须是字典")
    _check(LIB_SCHEMA, raw, "lib")
    dev_suffix = raw.get("dev_suffix", "-dev")
    if not re.fullmatch(r"-[a-z0-9][a-z0-9+.-]*", dev_suffix):
        raise AppSpecError("lib.dev_suffix 必须是以连字符开头的 Debian 包名后缀")
    return LibConfig(dev_suffix=dev_suffix)


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
        raw = yaml.load(yaml_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise AppSpecError(f"app.yaml YAML 解析失败：{exc}") from exc

    if not isinstance(raw, dict):
        raise AppSpecError("app.yaml 顶层必须是字典")

    _check(APP_SCHEMA, raw, str(yaml_path))

    # 解析必填顶层段
    if "app" not in raw:
        raise AppSpecError("app.yaml 缺少必填段：app")
    if "maintainer" not in raw:
        raise AppSpecError("app.yaml 缺少必填段：maintainer")

    app_info = _parse_app_info(raw["app"])
    maintainer = _parse_maintainer(raw["maintainer"])

    # 解析可选段：actions。与 Package 共用严格 argv 契约。
    try:
        actions = validate_actions(raw.get("actions", {}))
    except ValueError as exc:
        raise AppSpecError(str(exc)) from exc

    # 解析可选段：build
    build = _parse_build(raw["build"], app_info) if "build" in raw else BuildConfig()

    # 解析可选段：install（文件映射）
    raw_install = raw.get("install", {})
    if not isinstance(raw_install, dict):
        raise AppSpecError("install: 段必须是字典")
    install = dict(raw_install)
    for source, destination in install.items():
        _validate_relative_path(source, f"install.{source}")
        _validate_target_path(destination, f"install.{source}")

    # 解析可选段：systemd
    systemd: Optional[SystemdConfig] = None
    if "systemd" in raw:
        if app_info.type != "service":
            raise AppSpecError("systemd 仅允许 app.type=service")
        systemd = _parse_systemd(raw["systemd"])
    if app_info.type == "service" and systemd is None:
        raise AppSpecError("app.type=service 必须声明 systemd.unit")

    # 解析可选段：depends / conffiles / data_dirs
    def _parse_str_list(key: str) -> List[str]:
        return _parse_str_list_value(raw.get(key, []), key)

    depends = _parse_str_list("depends")
    conffiles = _parse_str_list("conffiles")
    data_dirs = _parse_str_list("data_dirs")
    for name, paths in (("conffiles", conffiles), ("data_dirs", data_dirs)):
        for index, path in enumerate(paths):
            _validate_target_path(path, f"{name}[{index}]")
    if data_dirs and app_info.type != "service":
        raise AppSpecError("data_dirs 仅由 app.type=service 的安装脚本消费")
    runtime = RuntimeConfig(**raw.get("runtime", {}))
    if "runtime" in raw and app_info.type not in {"exec", "test"}:
        raise AppSpecError("runtime 仅允许 app.type=exec 或 test")
    if runtime.executable:
        _validate_target_path(runtime.executable, "runtime.executable")

    # vendor deb 可显式映射安装、升级、卸载脚本与 dpkg trigger。
    maintainer_scripts = _parse_maintainer_scripts(
        raw.get("maintainer_scripts", {}),
        app_dir,
        app_info,
    )

    # 解析可选段：lib
    lib: Optional[LibConfig] = None
    if "lib" in raw:
        if app_info.type != "lib":
            raise AppSpecError("lib 仅允许 app.type=lib")
        lib = _parse_lib(raw["lib"])

    return AppSpec(
        app=app_info,
        maintainer=maintainer,
        runtime=runtime,
        actions=actions,
        build=build,
        install=install,
        systemd=systemd,
        depends=depends,
        conffiles=conffiles,
        data_dirs=data_dirs,
        maintainer_scripts=maintainer_scripts,
        lib=lib,
    )
