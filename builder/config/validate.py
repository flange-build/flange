"""FINAL_CONFIG 校验。

把"配置上的隐性约定"显式化，让早期错误（缺字段、布局不一致）在 lunch /
load_current_config 阶段就抛出，而不是等到 build/flash 失败时才暴露。

结构规则集中在 schema.py；本模块校验引用、平台能力、账户和分区等跨字段语义。

Recovery 子配置 schema（顶层 ``config["recovery"]``，全部可选；缺省即关闭）:

    recovery:
      enabled: bool                       # 默认 False。开启后 recovery 组件
                                          # 进入构建图，分区表必须含 recovery
      packages: list[str]                 # recovery rootfs 内 apt 安装的包
                                          # （systemd / udev / parted 等）
      install_recommends: bool          # 默认 False，进入共用 Phase 1 计划
      extra_apt_sources: list[dict]       # 与 rootfs 相同的源/key 下载声明
      custom_packages: list[str]          # 装入 recovery rootfs 的 custom App
                                          # 名（构建系统会从 components/app/ 取）
      transport: str                      # 首版仅支持 "adb"（USB ADB）
      protected_partitions: list[str]     # 显式声明的受保护分区名集合；
                                          # type=="raw" 的分区无论是否在表内
                                          # 都默认受保护，由设备端 recoveryctl
                                          # 强制（这里只补充非 raw 的额外名单）

可执行校验：调用方在拿到 ``resolve_config`` 结果之后立刻 ``validate_config(cfg)``。
"""

from __future__ import annotations

import importlib
import re
from pathlib import PurePosixPath

from builder.config.canonical import kernel_arch, kernel_device_tree
from builder.config import schema as _schema
from builder.config.schema import SchemaError, validate_system_shape
from builder.partition.size import parse_size
from builder.patches import normalize_excluded_patches
from builder.platforms.spec import capability as platform_capability
from builder.platforms.spec import known_platforms


class ConfigError(ValueError):
    """配置层面的硬错误：在构建/刷写之前就应阻断。"""


# 字段集合从结构 schema 派生，语义校验不维护第二份字段白名单。
_CANONICAL_COMPONENT_FIELDS = {
    name: set(_schema.SYSTEM.fields[name].fields)
    for name in ("kernel", "bootloader", "boot", "kernel_bsp", "kernel_device", "rkbin", "rootfs")
}
_CANONICAL_SOURCE_FIELDS = set(_schema.SOURCE.fields)
_CANONICAL_SOURCE_REF_FIELDS = set(_schema.SOURCE_REF.fields)
_CANONICAL_DEVICE_TREE_FIELDS = set(_schema.SYSTEM.fields["kernel"].fields["device_tree"].fields)
_CANONICAL_OVERLAY_FIELDS = set(_schema.SYSTEM.fields["boot"].fields["overlays"].fields)
_DOWNLOAD_FIELDS = set(_schema.DOWNLOAD_FIELDS)
_CANONICAL_OOT_SOURCE_FIELDS = {"source"}
_CANONICAL_EXTRA_DEB_FIELDS = set(_schema.ROOTFS.fields["extra_debs"].item.fields)
_CANONICAL_EXTRA_FIRMWARE_FIELDS = set(_schema.ROOTFS.fields["extra_firmware"].item.fields)


def _reject_unknown(mapping: dict, allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ConfigError(f"{path} 包含未知字段: {', '.join(unknown)}")


def _validate_download_descriptor(descriptor, path: str) -> None:
    if not isinstance(descriptor, dict):
        raise ConfigError(f"{path} 必须是下载 descriptor")
    _reject_unknown(descriptor, _DOWNLOAD_FIELDS, path)
    if not isinstance(descriptor.get("url"), str) or not descriptor["url"]:
        raise ConfigError(f"{path}.url 必须是非空字符串")
    sha256 = descriptor.get("sha256")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in sha256)
    ):
        raise ConfigError(f"{path}.sha256 必须是 64 位十六进制 SHA256")
    filename = descriptor.get("filename")
    if filename is not None and (
        not isinstance(filename, str) or not filename or PurePosixPath(filename).name != filename
    ):
        raise ConfigError(f"{path}.filename 必须是安全的单个文件名")


def _validate_source_ref(ref, sources: dict, path: str) -> None:
    if not isinstance(ref, dict):
        raise ConfigError(f"{path} 必须是字典")
    _reject_unknown(ref, _CANONICAL_SOURCE_REF_FIELDS, path)
    source_name = ref.get("name")
    if not source_name or source_name not in sources:
        raise ConfigError(f"{path}.name 引用了未知 source: {source_name!r}")
    subpath = ref.get("subpath", "")
    if not isinstance(subpath, str):
        raise ConfigError(f"{path}.subpath 必须是字符串")
    subpath_obj = PurePosixPath(subpath)
    if subpath_obj.is_absolute() or ".." in subpath_obj.parts:
        raise ConfigError(f"{path}.subpath 不得越出 source 根目录")


def validate_canonical_config(config: dict) -> None:
    """校验 Jsonnet 求值后的 canonical JSON 契约。"""
    try:
        validate_system_shape(config)
    except SchemaError as exc:
        raise ConfigError(str(exc)) from exc

    architecture = config.get("architecture") or {}
    if not isinstance(architecture, dict):
        raise ConfigError("architecture 必须是字典")
    _reject_unknown(architecture, {"userspace", "kernel", "bootloader"}, "architecture")
    if (
        not architecture.get("userspace")
        or architecture.get("kernel")
        not in (
            "arm",
            "arm64",
        )
        or architecture.get("bootloader") not in ("arm", "arm64")
    ):
        raise ConfigError("architecture 必须声明 userspace，且 kernel/bootloader 须为 arm 或 arm64")

    if architecture["userspace"] not in {"aarch64", "armhf"}:
        raise ConfigError("architecture.userspace 必须是 aarch64 或 armhf")
    if config.get("jobs", 0) < 0:
        raise ConfigError("jobs 必须是非负整数；0 表示自动选择并行数")
    sources = config.get("sources") or {}
    if not isinstance(sources, dict):
        raise ConfigError("sources 必须是字典")
    for name, descriptor in sources.items():
        if not isinstance(descriptor, dict):
            raise ConfigError(f"sources.{name} 必须是字典")
        _reject_unknown(descriptor, _CANONICAL_SOURCE_FIELDS, f"sources.{name}")
        has_local = bool(descriptor.get("local_path"))
        has_remote = bool(descriptor.get("url"))
        if has_local == has_remote:
            raise ConfigError(f"sources.{name} 必须且只能声明 local_path 或 url 之一")
        if has_local and any(
            key in descriptor for key in ("branch", "commit", "recurse_submodules")
        ):
            raise ConfigError(f"sources.{name}.local_path 与远端 revision 字段互斥")

    from builder.config.apps import AppSourceConfigError, validate_app_source_entry

    for name, entry in config.get("external_apps", {}).items():
        try:
            validate_app_source_entry(name, entry)
        except AppSourceConfigError as exc:
            raise ConfigError(str(exc)) from exc
    for namespace in ("sources", "external_apps"):
        for name in config.get(namespace, {}):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]*", name):
                raise ConfigError(f"{namespace}.{name} 的名称必须是单个资源标识，不能使用路径")

    from builder.packages import _parse_opt_in

    selections = []
    for index, entry in enumerate(config.get("packages", [])):
        try:
            selections.append(_parse_opt_in(entry)[0])
        except ValueError as exc:
            raise ConfigError(f"packages[{index}]: {exc}") from exc
    if len(selections) != len(set(selections)):
        raise ConfigError("packages 不得重复选择同一个包，请合并为一项")

    for component_name, allowed in _CANONICAL_COMPONENT_FIELDS.items():
        component = config.get(component_name)
        if component is None:
            continue
        if not isinstance(component, dict):
            raise ConfigError(f"{component_name} 必须是字典")
        _reject_unknown(component, allowed, component_name)
        source = component.get("source")
        if source is not None:
            _validate_source_ref(source, sources, f"{component_name}.source")

    kernel = config.get("kernel") or {}
    for name, descriptor in (kernel.get("oot_sources") or {}).items():
        path = f"kernel.oot_sources.{name}"
        if not isinstance(descriptor, dict):
            raise ConfigError(f"{path} 必须是字典")
        _reject_unknown(descriptor, _CANONICAL_OOT_SOURCE_FIELDS, path)
        _validate_source_ref(descriptor.get("source"), sources, f"{path}.source")
    device_tree = kernel.get("device_tree")
    if device_tree is not None:
        if not isinstance(device_tree, dict):
            raise ConfigError("kernel.device_tree 必须是字典")
        _reject_unknown(
            device_tree,
            _CANONICAL_DEVICE_TREE_FIELDS,
            "kernel.device_tree",
        )
        for field in ("directory", "name"):
            if not isinstance(device_tree.get(field), str):
                raise ConfigError(f"kernel.device_tree.{field} 必须是字符串")

    boot = config.get("boot") or {}
    overlays = boot.get("overlays")
    if overlays is not None:
        if not isinstance(overlays, dict):
            raise ConfigError("boot.overlays 必须是字典")
        _reject_unknown(overlays, _CANONICAL_OVERLAY_FIELDS, "boot.overlays")
        try:
            from builder.dtb_overlay import build_overlays, runtime_overlays

            runtime = runtime_overlays(config)
            build = build_overlays(config)
        except (TypeError, ValueError) as exc:
            raise ConfigError(str(exc)) from exc
        platform = config.get("platform", "")
        # 走平台声明的能力，而不是按名字前缀猜：能力和命名解耦后，新增一个
        # 构建期合并 DTBO 的非高通平台只需在它自己的包里声明一行。
        merge_at_build = platform_capability(config, "dtbo_merge_at_build")
        if merge_at_build and runtime:
            raise ConfigError(
                f"平台 {platform} 不支持 boot 运行期 overlay；"
                "请改用 kernel.device_tree.build_overlays"
            )
        if not merge_at_build and build:
            raise ConfigError(
                f"平台 {platform} 不支持构建期 DTBO 合并；请改用 boot.overlays.enabled"
            )

    bootloader = config.get("bootloader") or {}
    for field in (
        "edk2_firmware", "toolchain", "riscv_toolchain", "ufs_firehose", "recovery_firmware"
    ):
        descriptor = bootloader.get(field)
        if descriptor is not None:
            _validate_download_descriptor(descriptor, f"bootloader.{field}")
    for name, descriptor in (bootloader.get("ufs_provisions") or {}).items():
        _validate_download_descriptor(descriptor, f"bootloader.ufs_provisions.{name}")

    rootfs = config.get("rootfs") or {}
    if "hostname" in rootfs:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", rootfs["hostname"]):
            raise ConfigError("rootfs.hostname 必须是有效的主机名，不能包含空格或换行")
    users = rootfs.get("users", {})
    default_user = rootfs.get("default_user")
    if default_user is not None and default_user not in users:
        raise ConfigError("rootfs.default_user 必须引用 rootfs.users 中已声明的用户")
    if rootfs.get("disable_root_login") and not users:
        raise ConfigError(
            "rootfs.disable_root_login=true 时必须声明 rootfs.users，避免系统无法登录"
        )
    if rootfs.get("gnome_remote_desktop_login") and (
        default_user is None or not users[default_user].get("password")
    ):
        raise ConfigError(
            "rootfs.gnome_remote_desktop_login=true 需要具有密码的 rootfs.default_user"
        )
    recovery = config.get("recovery", {})
    if "transport" in recovery and recovery["transport"] != "adb":
        raise ConfigError("recovery.transport 当前只支持 adb，请修改为 adb")
    install_recommends = rootfs.get("install_recommends", False)
    if not isinstance(install_recommends, bool):
        raise ConfigError("rootfs.install_recommends 必须是布尔值")
    default_locale = rootfs.get("default_locale")
    if default_locale is not None:
        if not isinstance(default_locale, dict):
            raise ConfigError("rootfs.default_locale 必须是字典")
        _reject_unknown(
            default_locale,
            {"lang", "language"},
            "rootfs.default_locale",
        )
        for field in ("lang", "language"):
            value = default_locale.get(field)
            if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
                raise ConfigError(f"rootfs.default_locale.{field} 必须是非空单行字符串")
    default_session = rootfs.get("default_session")
    if default_session is not None and (
        not isinstance(default_session, str)
        or not default_session
        or "\n" in default_session
        or "\r" in default_session
        or PurePosixPath(default_session).name != default_session
    ):
        raise ConfigError("rootfs.default_session 必须是安全的非空 session 名")
    if default_session and rootfs.get("default_user") is None:
        raise ConfigError("设置 rootfs.default_session 时 rootfs.default_user 不能为空")
    if rootfs.get("url") is not None:
        _validate_download_descriptor(
            {key: rootfs[key] for key in _DOWNLOAD_FIELDS if key in rootfs},
            "rootfs",
        )
    for index, descriptor in enumerate(rootfs.get("extra_debs") or []):
        path = f"rootfs.extra_debs[{index}]"
        if not isinstance(descriptor, dict) or not descriptor.get("name"):
            raise ConfigError(f"{path}.name 未声明")
        _reject_unknown(descriptor, _CANONICAL_EXTRA_DEB_FIELDS, path)
        _validate_download_descriptor(
            {key: descriptor[key] for key in _DOWNLOAD_FIELDS if key in descriptor},
            path,
        )
        force_overwrite = descriptor.get("force_overwrite", False)
        if not isinstance(force_overwrite, bool):
            raise ConfigError(f"{path}.force_overwrite 必须是布尔值")
        hold_packages = descriptor.get("hold_packages", [])
        if not isinstance(hold_packages, list) or any(
            not isinstance(package, str) or not package for package in hold_packages
        ):
            raise ConfigError(f"{path}.hold_packages 必须是非空字符串数组")
    for component in ("rootfs", "recovery"):
        apt_names = set()
        for index, apt_source in enumerate(config.get(component, {}).get("extra_apt_sources", [])):
            path = f"{component}.extra_apt_sources[{index}]"
            name = apt_source["name"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise ConfigError(f"{path}.name 必须是单个安全名称，不能包含路径")
            if name in apt_names:
                raise ConfigError(f"{path}.name 重复；请为每个 APT 源指定唯一名称")
            apt_names.add(name)
            _validate_download_descriptor(apt_source["key"], f"{path}.key")
    for index, descriptor in enumerate(rootfs.get("extra_firmware") or []):
        path = f"rootfs.extra_firmware[{index}]"
        if not isinstance(descriptor, dict) or not descriptor.get("name"):
            raise ConfigError(f"{path}.name 未声明")
        _reject_unknown(descriptor, _CANONICAL_EXTRA_FIRMWARE_FIELDS, path)
        source = descriptor.get("source")
        has_source = isinstance(source, dict)
        has_download = "url" in descriptor
        if has_source == has_download:
            raise ConfigError(f"{path} 必须且只能声明 source 或下载 descriptor 之一")
        if has_source:
            _validate_source_ref(source, sources, f"{path}.source")
        else:
            _validate_download_descriptor(
                {key: descriptor[key] for key in _DOWNLOAD_FIELDS if key in descriptor},
                path,
            )


def _is_recovery_enabled(config: dict) -> bool:
    """读取 ``config["recovery"]["enabled"]``，缺省视为 False。"""
    recovery_cfg = config.get("recovery") or {}
    return bool(recovery_cfg.get("enabled", False))


def _find_partition(config: dict, name: str) -> dict | None:
    """在 ``config["partitions"]["entries"]`` 中按名查询单个分区。"""
    entries = (config.get("partitions") or {}).get("entries") or []
    for entry in entries:
        if entry.get("name") == name:
            return entry
    return None


def _positive_int(value, field: str, *, allow_zero: bool = False) -> int:
    """解析配置中的十进制/十六进制整数并校验正值。"""
    try:
        result = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} 必须是整数，当前: {value!r}") from exc
    minimum = 0 if allow_zero else 1
    if result < minimum:
        qualifier = "非负" if allow_zero else "大于 0"
        raise ConfigError(f"{field} 必须{qualifier}，当前: {result}")
    return result


def _byte_size(value, field: str) -> int:
    """解析带 B/M/G 后缀的字节容量，拒绝含糊的裸 sector 数。"""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} 必须使用带 B/M/G 后缀的容量字符串")
    if not value.strip()[-1].isalpha():
        raise ConfigError(f"{field} 必须使用带 B/M/G 后缀的容量字符串")
    try:
        return parse_size(value).bytes
    except ValueError as exc:
        raise ConfigError(f"{field} 非法: {exc}") from exc


def validate_build_routes(config: dict) -> None:
    """校验架构、boot/rootfs/partition 构建路由的枚举契约。"""
    kernel = config.get("kernel") or {}
    kernel_arch_value = kernel_arch(config)
    if kernel_arch_value not in ("arm", "arm64"):
        raise ConfigError(
            f"architecture.kernel 非法: {kernel_arch_value!r}（须为 'arm' 或 'arm64'）"
        )
    for field in ("cross_compile", "image"):
        value = kernel.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ConfigError(f"kernel.{field} 必须是非空字符串")
    dts_dir, _ = kernel_device_tree(config) if kernel else ("", "")
    if not isinstance(dts_dir, str):
        raise ConfigError("kernel.device_tree.directory 必须是字符串（根目录使用空字符串）")
    boot_format = kernel.get("boot_format", "extlinux")
    if boot_format not in ("extlinux", "fit"):
        raise ConfigError(f"kernel.boot_format 非法: {boot_format!r}（须为 extlinux 或 fit）")
    if boot_format == "fit" and not kernel.get("boot_its"):
        raise ConfigError("kernel.boot_format=fit 时必须声明 kernel.boot_its")

    from builder.kconfig import defconfig_targets, render_kconfig

    for name in ("kernel", "bootloader"):
        component = config.get(name, {})
        try:
            defconfig_targets(component.get("defconfig", []), f"{name}.defconfig")
            render_kconfig(component.get("config", {}), f"{name}.config")
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc

    bootloader = config.get("bootloader") or {}
    cross_compile = bootloader.get("cross_compile")
    if cross_compile is not None and (not isinstance(cross_compile, str) or not cross_compile):
        raise ConfigError("bootloader.cross_compile 必须是非空字符串")

    rootfs_format = (config.get("rootfs") or {}).get("image_format", "ext4")
    if rootfs_format not in ("ext4", "ubi"):
        raise ConfigError(f"rootfs.image_format 非法: {rootfs_format!r}（须为 ext4 或 ubi）")
    partition_format = (config.get("partitions") or {}).get("format", "gpt")
    if partition_format not in ("gpt", "mtd"):
        raise ConfigError(f"partitions.format 非法: {partition_format!r}（须为 gpt 或 mtd）")
    # parameter、存储介质与 mtd index 属于平台语义，由平台扩展校验。
    for component, component_config in config.items():
        if not isinstance(component_config, dict):
            continue
        if "exclude_patches" not in component_config:
            continue
        try:
            normalize_excluded_patches(
                component_config["exclude_patches"],
                f"{component}.exclude_patches",
            )
        except TypeError as exc:
            raise ConfigError(str(exc)) from exc


def validate_flash_identity(config: dict) -> None:
    """校验刷写身份匹配规则，避免字符串被误拆成逐字符正则。"""
    identity = config.get("flash_identity") or {}
    if not isinstance(identity, dict):
        raise ConfigError("flash_identity 必须是字典")
    for field in ("chip_patterns", "storage_patterns"):
        value = identity.get(field, [])
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ConfigError(f"flash_identity.{field} 必须是非空字符串列表")
    require_rid = identity.get("require_rid", False)
    if not isinstance(require_rid, bool):
        raise ConfigError("flash_identity.require_rid 必须是 bool")


def validate_ubi_geometry(config: dict) -> None:
    """校验平台无关的 UBI/UBIFS 几何，不推断介质或分区模型。"""
    rootfs = config.get("rootfs") or {}
    if rootfs.get("image_format", "ext4") != "ubi":
        return
    ubi = rootfs.get("ubi") or {}
    required = (
        "min_io_size",
        "peb_size",
        "subpage_size",
        "vid_hdr_offset",
        "leb_size",
        "max_leb_count",
        "volume_size",
        "reserved_pebs",
    )
    missing = [field for field in required if ubi.get(field) is None]
    if missing:
        raise ConfigError("rootfs.ubi 缺少 NAND/UBI 几何字段: " + ", ".join(missing))
    if "space_fixup" in ubi and not isinstance(ubi["space_fixup"], bool):
        raise ConfigError("rootfs.ubi.space_fixup 必须是 bool")

    min_io = _positive_int(ubi["min_io_size"], "rootfs.ubi.min_io_size")
    peb = _positive_int(ubi["peb_size"], "rootfs.ubi.peb_size")
    subpage = _positive_int(ubi["subpage_size"], "rootfs.ubi.subpage_size")
    vid = _positive_int(ubi["vid_hdr_offset"], "rootfs.ubi.vid_hdr_offset")
    leb = _positive_int(ubi["leb_size"], "rootfs.ubi.leb_size")
    max_leb = _positive_int(ubi["max_leb_count"], "rootfs.ubi.max_leb_count")
    reserved = _positive_int(ubi["reserved_pebs"], "rootfs.ubi.reserved_pebs", allow_zero=True)
    volume_size = _byte_size(ubi["volume_size"], "rootfs.ubi.volume_size")

    if peb % min_io:
        raise ConfigError("rootfs.ubi.peb_size 必须是 min_io_size 的整数倍")
    if min_io % subpage:
        raise ConfigError("rootfs.ubi.min_io_size 必须是 subpage_size 的整数倍")
    if vid % subpage or vid >= peb:
        raise ConfigError("rootfs.ubi.vid_hdr_offset 必须按 subpage_size 对齐且小于 peb_size")
    data_offset = ((vid + 64 + min_io - 1) // min_io) * min_io
    expected_leb = peb - data_offset
    if leb != expected_leb:
        raise ConfigError(f"rootfs.ubi.leb_size={leb} 与几何推导值 {expected_leb} 不一致")
    if volume_size > max_leb * leb:
        raise ConfigError("rootfs.ubi.volume_size 超过 max_leb_count × leb_size")
    _ = (reserved, peb)


def _run_platform_validation(config: dict, function: str) -> None:
    """动态调用平台扩展校验；没有 validation 模块的平台直接跳过。"""
    platform = config.get("platform")
    if not platform:
        return
    module_name = f"builder.platforms.{platform}.validation"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return
        raise
    validator = getattr(module, function, None)
    if validator:
        validator(config)


def validate_mtd_ubi(config: dict) -> None:
    """兼容入口：校验通用 UBI 几何，再分派平台存储规则。"""
    validate_ubi_geometry(config)
    _run_platform_validation(config, "validate_storage")


def validate_recovery_partition(config: dict) -> None:
    """recovery 启用时，强制 partitions.entries 中存在合规的 recovery 分区。

    要求：name=="recovery" 且 type=="ext4"，offset/size 必须非空字符串。
    """
    if not _is_recovery_enabled(config):
        return

    entry = _find_partition(config, "recovery")
    if entry is None:
        raise ConfigError(
            "recovery.enabled=True 但 partitions.entries 中缺少 recovery 分区；"
            "请在 SoC 或 board 配置的 partitions.entries 中加入 "
            "{name: 'recovery', type: 'ext4', offset, size}。"
        )

    if entry.get("type") != "ext4":
        raise ConfigError(f"recovery 分区 type 必须为 ext4，当前: {entry.get('type')!r}")

    for field in ("offset", "size"):
        value = entry.get(field)
        if not value:
            raise ConfigError(f"recovery 分区缺少 {field}；offset 与 size 都必须显式声明。")


def validate_rootfs_auto_grow(config: dict) -> None:
    """校验 rootfs 首次启动扩容布局。

    只有显式声明 ``grow_on_first_boot`` 的 rootfs 分区会进入校验。
    """
    entries = (config.get("partitions") or {}).get("entries") or []
    for index, entry in enumerate(entries):
        if not entry.get("grow_on_first_boot"):
            continue

        if entry.get("name") != "rootfs":
            raise ConfigError("grow_on_first_boot 仅支持 rootfs 分区。")
        if entry.get("type") != "ext4":
            raise ConfigError("grow_on_first_boot 要求 rootfs 分区 type 为 ext4。")
        image_size = entry.get("image_size")
        if not image_size:
            raise ConfigError("grow_on_first_boot=True 时 rootfs 分区必须声明 image_size。")

        image = parse_size(image_size)
        size = entry.get("size")
        if size == "remaining":
            for later in entries[index + 1 :]:
                if later.get("type") != "raw":
                    raise ConfigError(
                        "grow_on_first_boot=True 且 size=remaining 时，"
                        "rootfs 必须是最后一个非 raw 分区。"
                    )
            continue

        partition = parse_size(size)
        if image.bytes > partition.bytes:
            raise ConfigError(
                f"rootfs image_size ({image.bytes} bytes) 不得大于 "
                f"分区 size ({partition.bytes} bytes)。"
            )


def _is_amp_enabled(config: dict) -> bool:
    """读取 ``config["amp"]["enabled"]``，缺省视为 False。"""
    return bool((config.get("amp") or {}).get("enabled", False))


def validate_amp_common(config: dict) -> None:
    """校验平台无关的 AMP mode、SoC project 与内存 schema。"""
    if not _is_amp_enabled(config):
        return

    amp = config.get("amp") or {}
    mode = amp.get("mode")
    if mode not in ("hal", "rt-thread"):
        raise ConfigError(
            f"amp.enabled=True 但 amp.mode 非法: {mode!r}（须为 'hal' 或 'rt-thread'）。"
        )
    if not amp.get("soc_project"):
        raise ConfigError("amp.enabled=True 但缺少 amp.soc_project（如 rk3566 应设为 'rk3568'）。")

    memory = amp.get("memory") or {}
    memory_fields = (
        "cpu",
        "cpu_base",
        "dram_size",
        "sram_base",
        "sram_size",
        "shmem_base",
        "shmem_size",
        "rpmsg_base",
        "rpmsg_size",
    )
    missing_memory = [field for field in memory_fields if memory.get(field) is None]
    if missing_memory:
        raise ConfigError("amp.enabled=True 但 amp.memory 缺少字段: " + ", ".join(missing_memory))


def validate_amp(config: dict) -> None:
    """兼容入口：校验通用 AMP schema，再分派平台分区规则。"""
    validate_amp_common(config)
    _run_platform_validation(config, "validate_amp")


def validate_platform(config: dict) -> None:
    """`platform` 必须对应一个已注册的平台包。

    此前平台名从不校验：写错只会在 engine 里抛 ModuleNotFoundError，而按名字
    前缀判断能力的地方（`startswith("qualcomm")`）连报错都没有 —— `qualcom`
    少一个 m 就静默走进非高通分支。校验放在这里，能顺带列出可选值。
    """
    platform = config.get("platform")
    if not platform:
        return
    known = known_platforms()
    if platform not in known:
        raise ConfigError(f"未知平台 {platform!r}；已注册的平台: {', '.join(known)}")


def validate_partition_values(config: dict) -> None:
    """校验通用布局值；平台负责约束自身分区名称和路由。"""
    partitions = config.get("partitions", {})
    sector_size = partitions.get("sector_size", 512)
    if sector_size not in {512, 4096}:
        raise ConfigError("partitions.sector_size 必须是 512 或 4096 字节")
    names = set()
    for index, entry in enumerate(partitions.get("entries", [])):
        field = f"partitions.entries[{index}]"
        name = entry["name"]
        if name in names:
            raise ConfigError(f"{field}.name 重复：{name}")
        names.add(name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ConfigError(f"{field}.name 必须是安全的单个分区名")
        if "offset" in entry:
            try:
                offset = int(entry["offset"], 0)
                if offset < 0:
                    raise ValueError("不能为负数")
            except ValueError as exc:
                raise ConfigError(
                    f"{field}.offset 必须是非负十进制或 0x 十六进制 sector 数"
                ) from exc
        for key in ("size", "image_size"):
            if key not in entry or (key == "size" and entry[key] == "remaining"):
                continue
            try:
                parse_size(entry[key])
            except ValueError as exc:
                raise ConfigError(
                    f"{field}.{key}: {exc}；请使用有效的 sector 数或 M/G 容量"
                ) from exc


def validate_config(config: dict) -> None:
    """对 FINAL_CONFIG 执行全部已知校验，第一项失败即抛 ConfigError。"""
    validate_canonical_config(config)
    validate_platform(config)
    validate_build_routes(config)
    validate_partition_values(config)
    validate_flash_identity(config)
    validate_recovery_partition(config)
    validate_rootfs_auto_grow(config)
    validate_ubi_geometry(config)
    validate_amp_common(config)
    _run_platform_validation(config, "validate_config")
