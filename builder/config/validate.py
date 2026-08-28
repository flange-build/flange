"""FINAL_CONFIG 校验。

把"配置上的隐性约定"显式化，让早期错误（缺字段、布局不一致）在 lunch /
load_current_config 阶段就抛出，而不是等到 build/flash 失败时才暴露。

覆盖范围（按需扩展，不追求完备）：
- recovery 子配置启用时，partitions.entries 必须包含 recovery 分区。

Recovery 子配置 schema（顶层 ``config["recovery"]``，全部可选；缺省即关闭）:

    recovery:
      enabled: bool                       # 默认 False。开启后 recovery 组件
                                          # 进入构建图，分区表必须含 recovery
      packages: list[str]                 # recovery rootfs 内 apt 安装的包
                                          # （systemd / udev / parted 等）
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
from pathlib import PurePosixPath

from builder.config.canonical import kernel_arch, kernel_device_tree
from builder.config.jsonnet import ResolvedConfig
from builder.partition.size import parse_size
from builder.patches import normalize_excluded_patches


class ConfigError(ValueError):
    """配置层面的硬错误：在构建/刷写之前就应阻断。"""


_CANONICAL_TOP_LEVEL_FIELDS = {
    "amp", "architecture", "board", "boot", "bootloader",
    "device-tree-overlay", "external_app_dirs", "external_apps",
    "flash_identity", "flash_spi_loader", "flash_storage", "flash_tool",
    "jobs", "kernel", "kernel_bsp", "kernel_device", "packages",
    "packages_meta", "partitions", "platform", "product", "products",
    "recovery", "rkbin", "rootfs", "soc", "sources", "storage",
    "variant", "variants", "vendor",
}

_CANONICAL_COMPONENT_FIELDS = {
    "kernel": {
        "boot_format", "boot_its", "config", "cross_compile", "defconfig",
        "device_tree", "exclude_patches", "image", "oot_modules",
        "oot_sources", "source",
    },
    "bootloader": {
        "config", "cross_compile", "defconfig", "edk2_firmware",
        "exclude_patches", "fip_board_dir", "fip_tool", "firehose_loader",
        "fit_pack", "idbloader_method", "idbloader_selfbuilt_spl",
        "riscv_toolchain", "source", "spi_patch", "spi_rawprogram", "target",
        "toolchain", "trust_mode", "ufs_firehose", "ufs_provisions",
    },
    "boot": {"kernel_args", "overlays", "package_overlay_sources"},
    "kernel_bsp": {"dtsi_dir", "source"},
    "kernel_device": {"board_dts_path", "bsp_defconfig_path", "source"},
    "rkbin": {
        "ini_prefix", "loader_ini", "mkimage_chip", "source", "trust_ini",
        "trust_ini_prefix",
    },
    "rootfs": {
        "custom_packages", "default_user", "disable_root_login", "emulator",
        "extra_apt_sources", "extra_debs", "extra_firmware", "groups",
        "gnome_remote_desktop_login", "image_format", "package_set",
        "package_sets", "packages", "panel_firmware", "root_password",
        "sha256", "ubi", "url", "users",
    },
}

_CANONICAL_SOURCE_FIELDS = {
    "url", "branch", "commit", "recurse_submodules", "local_path",
}
_CANONICAL_SOURCE_REF_FIELDS = {"name", "subpath"}
_CANONICAL_DEVICE_TREE_FIELDS = {"directory", "name", "build_overlays"}
_CANONICAL_OVERLAY_FIELDS = {
    "intree", "vendor", "board", "package", "enabled",
}
_DOWNLOAD_FIELDS = {"url", "sha256", "filename"}
_CANONICAL_OOT_SOURCE_FIELDS = {"source"}
_CANONICAL_EXTRA_FIRMWARE_FIELDS = {
    "name", "source", "files", "dest", "url", "sha256", "filename",
}


def _reject_unknown(mapping: dict, allowed: set[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ConfigError(f"{path} 包含未知字段: {', '.join(unknown)}")


def _validate_no_nested_dimensions(value, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if path and key in ("product", "variant"):
                raise ConfigError(f"{child_path} 只允许出现在 canonical JSON 顶层")
            if key.startswith("+") or ":" in key:
                raise ConfigError(f"{child_path} 是未求值的旧配置操作字段")
            _validate_no_nested_dimensions(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_nested_dimensions(child, f"{path}[{index}]")


def _validate_download_descriptor(descriptor, path: str) -> None:
    if not isinstance(descriptor, dict):
        raise ConfigError(f"{path} 必须是下载 descriptor")
    _reject_unknown(descriptor, _DOWNLOAD_FIELDS, path)
    if not isinstance(descriptor.get("url"), str) or not descriptor["url"]:
        raise ConfigError(f"{path}.url 必须是非空字符串")
    sha256 = descriptor.get("sha256")
    if (not isinstance(sha256, str) or len(sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in sha256)):
        raise ConfigError(f"{path}.sha256 必须是 64 位十六进制 SHA256")
    filename = descriptor.get("filename")
    if filename is not None and (
            not isinstance(filename, str) or not filename
            or PurePosixPath(filename).name != filename):
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
    _reject_unknown(config, _CANONICAL_TOP_LEVEL_FIELDS, "配置顶层")
    _validate_no_nested_dimensions(config)

    architecture = config.get("architecture") or {}
    if not isinstance(architecture, dict):
        raise ConfigError("architecture 必须是字典")
    _reject_unknown(
        architecture, {"userspace", "kernel", "bootloader"}, "architecture"
    )
    if not architecture.get("userspace") or architecture.get("kernel") not in (
        "arm", "arm64",
    ) or architecture.get("bootloader") not in ("arm", "arm64"):
        raise ConfigError(
            "architecture 必须声明 userspace，且 kernel/bootloader 须为 arm 或 arm64"
        )

    sources = config.get("sources") or {}
    if not isinstance(sources, dict):
        raise ConfigError("sources 必须是字典")
    for name, descriptor in sources.items():
        if not isinstance(descriptor, dict):
            raise ConfigError(f"sources.{name} 必须是字典")
        _reject_unknown(
            descriptor, _CANONICAL_SOURCE_FIELDS, f"sources.{name}"
        )
        has_local = bool(descriptor.get("local_path"))
        has_remote = bool(descriptor.get("url"))
        if has_local == has_remote:
            raise ConfigError(
                f"sources.{name} 必须且只能声明 local_path 或 url 之一"
            )
        if has_local and any(
            key in descriptor
            for key in ("branch", "commit", "recurse_submodules")
        ):
            raise ConfigError(
                f"sources.{name}.local_path 与远端 revision 字段互斥"
            )

    for component_name, allowed in _CANONICAL_COMPONENT_FIELDS.items():
        component = config.get(component_name)
        if component is None:
            continue
        if not isinstance(component, dict):
            raise ConfigError(f"{component_name} 必须是字典")
        _reject_unknown(component, allowed, component_name)
        source = component.get("source")
        if source is not None:
            _validate_source_ref(
                source, sources, f"{component_name}.source")

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
            device_tree, _CANONICAL_DEVICE_TREE_FIELDS,
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
        if platform.startswith("qualcomm") and runtime:
            raise ConfigError(
                f"平台 {platform} 不支持 boot 运行期 overlay；"
                "请改用 kernel.device_tree.build_overlays")
        if not platform.startswith("qualcomm") and build:
            raise ConfigError(
                f"平台 {platform} 不支持构建期 DTBO 合并；"
                "请改用 boot.overlays.enabled")

    bootloader = config.get("bootloader") or {}
    for field in ("edk2_firmware", "toolchain", "riscv_toolchain",
                  "ufs_firehose"):
        descriptor = bootloader.get(field)
        if descriptor is not None:
            _validate_download_descriptor(descriptor, f"bootloader.{field}")
    for name, descriptor in (bootloader.get("ufs_provisions") or {}).items():
        _validate_download_descriptor(
            descriptor, f"bootloader.ufs_provisions.{name}")

    rootfs = config.get("rootfs") or {}
    if rootfs.get("url") is not None:
        _validate_download_descriptor(
            {key: rootfs[key] for key in _DOWNLOAD_FIELDS if key in rootfs},
            "rootfs",
        )
    for index, descriptor in enumerate(rootfs.get("extra_debs") or []):
        if not isinstance(descriptor, dict) or not descriptor.get("name"):
            raise ConfigError(f"rootfs.extra_debs[{index}].name 未声明")
        _validate_download_descriptor(
            {key: descriptor[key] for key in _DOWNLOAD_FIELDS
             if key in descriptor},
            f"rootfs.extra_debs[{index}]",
        )
    for index, apt_source in enumerate(rootfs.get("extra_apt_sources") or []):
        if not isinstance(apt_source, dict) or not apt_source.get("name"):
            raise ConfigError(f"rootfs.extra_apt_sources[{index}].name 未声明")
        _validate_download_descriptor(
            apt_source.get("key"),
            f"rootfs.extra_apt_sources[{index}].key",
        )
    for index, descriptor in enumerate(rootfs.get("extra_firmware") or []):
        path = f"rootfs.extra_firmware[{index}]"
        if not isinstance(descriptor, dict) or not descriptor.get("name"):
            raise ConfigError(f"{path}.name 未声明")
        _reject_unknown(descriptor, _CANONICAL_EXTRA_FIRMWARE_FIELDS, path)
        source = descriptor.get("source")
        has_source = isinstance(source, dict)
        has_download = "url" in descriptor
        if has_source == has_download:
            raise ConfigError(
                f"{path} 必须且只能声明 source 或下载 descriptor 之一")
        if has_source:
            _validate_source_ref(source, sources, f"{path}.source")
        else:
            _validate_download_descriptor(
                {key: descriptor[key] for key in _DOWNLOAD_FIELDS
                 if key in descriptor},
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
            f"architecture.kernel 非法: {kernel_arch_value!r}"
            "（须为 'arm' 或 'arm64'）")
    for field in ("cross_compile", "image"):
        value = kernel.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise ConfigError(f"kernel.{field} 必须是非空字符串")
    dts_dir, _ = kernel_device_tree(config) if kernel else ("", "")
    if not isinstance(dts_dir, str):
        raise ConfigError(
            "kernel.device_tree.directory 必须是字符串（根目录使用空字符串）"
        )
    boot_format = kernel.get("boot_format", "extlinux")
    if boot_format not in ("extlinux", "fit"):
        raise ConfigError(
            f"kernel.boot_format 非法: {boot_format!r}（须为 extlinux 或 fit）")
    if boot_format == "fit" and not kernel.get("boot_its"):
        raise ConfigError(
            "kernel.boot_format=fit 时必须声明 kernel.boot_its")

    bootloader = config.get("bootloader") or {}
    cross_compile = bootloader.get("cross_compile")
    if cross_compile is not None and (
        not isinstance(cross_compile, str) or not cross_compile
    ):
        raise ConfigError("bootloader.cross_compile 必须是非空字符串")

    rootfs_format = (config.get("rootfs") or {}).get(
        "image_format", "ext4")
    if rootfs_format not in ("ext4", "ubi"):
        raise ConfigError(
            f"rootfs.image_format 非法: {rootfs_format!r}（须为 ext4 或 ubi）")
    partition_format = (config.get("partitions") or {}).get("format", "gpt")
    if partition_format not in ("gpt", "mtd"):
        raise ConfigError(
            f"partitions.format 非法: {partition_format!r}（须为 gpt 或 mtd）")
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
        raise ConfigError(
            "rootfs.ubi 缺少 NAND/UBI 几何字段: " + ", ".join(missing))
    if "space_fixup" in ubi and not isinstance(ubi["space_fixup"], bool):
        raise ConfigError("rootfs.ubi.space_fixup 必须是 bool")

    min_io = _positive_int(ubi["min_io_size"], "rootfs.ubi.min_io_size")
    peb = _positive_int(ubi["peb_size"], "rootfs.ubi.peb_size")
    subpage = _positive_int(ubi["subpage_size"], "rootfs.ubi.subpage_size")
    vid = _positive_int(ubi["vid_hdr_offset"], "rootfs.ubi.vid_hdr_offset")
    leb = _positive_int(ubi["leb_size"], "rootfs.ubi.leb_size")
    max_leb = _positive_int(ubi["max_leb_count"], "rootfs.ubi.max_leb_count")
    reserved = _positive_int(
        ubi["reserved_pebs"], "rootfs.ubi.reserved_pebs", allow_zero=True)
    volume_size = _byte_size(ubi["volume_size"], "rootfs.ubi.volume_size")

    if peb % min_io:
        raise ConfigError("rootfs.ubi.peb_size 必须是 min_io_size 的整数倍")
    if min_io % subpage:
        raise ConfigError("rootfs.ubi.min_io_size 必须是 subpage_size 的整数倍")
    if vid % subpage or vid >= peb:
        raise ConfigError(
            "rootfs.ubi.vid_hdr_offset 必须按 subpage_size 对齐且小于 peb_size")
    data_offset = ((vid + 64 + min_io - 1) // min_io) * min_io
    expected_leb = peb - data_offset
    if leb != expected_leb:
        raise ConfigError(
            f"rootfs.ubi.leb_size={leb} 与几何推导值 {expected_leb} 不一致")
    if volume_size > max_leb * leb:
        raise ConfigError(
            "rootfs.ubi.volume_size 超过 max_leb_count × leb_size")
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
        raise ConfigError(
            f"recovery 分区 type 必须为 ext4，当前: {entry.get('type')!r}"
        )

    for field in ("offset", "size"):
        value = entry.get(field)
        if not value:
            raise ConfigError(
                f"recovery 分区缺少 {field}；offset 与 size 都必须显式声明。"
            )


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
            raise ConfigError(
                "grow_on_first_boot=True 时 rootfs 分区必须声明 image_size。"
            )

        image = parse_size(image_size)
        size = entry.get("size")
        if size == "remaining":
            for later in entries[index + 1:]:
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
        raise ConfigError(
            "amp.enabled=True 但缺少 amp.soc_project（如 rk3566 应设为 'rk3568'）。"
        )

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
    missing_memory = [field for field in memory_fields
                      if memory.get(field) is None]
    if missing_memory:
        raise ConfigError(
            "amp.enabled=True 但 amp.memory 缺少字段: "
            + ", ".join(missing_memory))



def validate_amp(config: dict) -> None:
    """兼容入口：校验通用 AMP schema，再分派平台分区规则。"""
    validate_amp_common(config)
    _run_platform_validation(config, "validate_amp")


def validate_config(config: dict) -> None:
    """对 FINAL_CONFIG 执行全部已知校验，第一项失败即抛 ConfigError。"""
    if isinstance(config, ResolvedConfig):
        validate_canonical_config(config)
    validate_build_routes(config)
    validate_flash_identity(config)
    validate_recovery_partition(config)
    validate_rootfs_auto_grow(config)
    validate_ubi_geometry(config)
    validate_amp_common(config)
    _run_platform_validation(config, "validate_config")
