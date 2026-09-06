"""配置结构的单一事实源：闭合对象、严格类型与显式动态映射。

这里只校验数据形状，不访问文件、不解析平台能力，也不执行配置展开。
对象中未列出的字段一律拒绝；只有 Map 明确允许调用者定义键名。
语义约束由 validate.py 负责，避免把平台规则混入通用解析器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SchemaError(ValueError):
    """带字段路径的结构错误。"""


@dataclass(frozen=True)
class Scalar:
    kind: type
    empty: bool = False

    def check(self, value: Any, path: str) -> None:
        # bool 是 int 的子类，配置语义中必须明确区分。
        if type(value) is not self.kind:
            expected = {str: "字符串", int: "整数", bool: "布尔值", type(None): "null"}
            raise SchemaError(
                f"{path} 必须是{expected[self.kind]}，实际为 {type(value).__name__}；"
                "请按字段类型修改配置，不能依赖隐式转换"
            )
        if self.kind is str and ("\0" in value or (not self.empty and not value.strip())):
            raise SchemaError(f"{path} 必须是非空且不含 NUL 的字符串")


@dataclass(frozen=True)
class ListOf:
    item: Any

    def check(self, value: Any, path: str) -> None:
        if not isinstance(value, list):
            raise SchemaError(f"{path} 必须是列表，请使用 [...] 而非单个值")
        for index, item in enumerate(value):
            self.item.check(item, f"{path}[{index}]")


@dataclass(frozen=True)
class Map:
    item: Any

    def check(self, value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise SchemaError(f"{path} 必须是键值映射")
        for key, item in value.items():
            STRING.check(key, f"{path}.<键>")
            self.item.check(item, f"{path}.{key}")


@dataclass(frozen=True)
class Object:
    fields: dict[str, Any]
    required: tuple[str, ...] = ()

    def check(self, value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise SchemaError(f"{path} 必须是对象（字段到值的映射）")
        for key in value:
            if key not in self.fields:
                raise SchemaError(
                    f"{path}.{key} 是未知字段；请删除或改为允许字段："
                    + ", ".join(sorted(self.fields))
                )
        for key in self.required:
            if key not in value:
                raise SchemaError(f"{path}.{key} 是必填字段，请补全配置")
        for key, item in value.items():
            self.fields[key].check(item, f"{path}.{key}")


@dataclass(frozen=True)
class OneOf:
    choices: tuple[Any, ...]

    def check(self, value: Any, path: str) -> None:
        errors = []
        for choice in self.choices:
            try:
                choice.check(value, path)
                return
            except SchemaError as exc:
                errors.append(str(exc))
        raise SchemaError("；或 ".join(errors))


class ExtensionObject:
    """延迟到 provider 的闭合结构校验；这里不接受对象以外的值。"""

    def check(self, value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise SchemaError(f"{path} 必须是策略配置对象")


STRING = Scalar(str)
TEXT = Scalar(str, empty=True)
INTEGER = Scalar(int)
BOOLEAN = Scalar(bool)
NULL = Scalar(type(None))
STRINGS = ListOf(STRING)
OPTIONAL_TEXT = OneOf((TEXT, NULL))
SOURCE_REF = Object({"name": STRING, "subpath": TEXT}, ("name",))
SOURCE = Object(
    {
        "url": STRING,
        "local_path": STRING,
        "branch": STRING,
        "commit": STRING,
        "recurse_submodules": BOOLEAN,
    }
)
APP_SOURCE = Object(
    {
        "git": STRING,
        "local_path": STRING,
        "branch": STRING,
        "commit": STRING,
        "tag": STRING,
        "recurse_submodules": BOOLEAN,
    }
)
DOWNLOAD_FIELDS = {"url": STRING, "sha256": STRING, "filename": STRING}
DOWNLOAD = Object(DOWNLOAD_FIELDS, ("url", "sha256"))
PACKAGE_SELECTION = OneOf((STRING, Object({"name": STRING, "drivers": STRINGS}, ("name",))))
USER = Object(
    {
        "password": OPTIONAL_TEXT,
        "shell": STRING,
        "groups": STRINGS,
        "sudo": OneOf((BOOLEAN, Object({"nopasswd": BOOLEAN}))),
    }
)
FIRMWARE_FILE = OneOf((STRING, Object({"src": STRING, "dest": STRING}, ("src", "dest"))))
OOT_MODULE = Object(
    {
        "dir": STRING,
        "label": STRING,
        "make_args": STRINGS,
        "ko_pattern": STRINGS,
        "pre_build": STRINGS,
        "post_build": STRINGS,
    },
    ("dir", "label", "ko_pattern"),
)
PARTITION = Object(
    {
        "name": STRING,
        "type": STRING,
        "label": STRING,
        "offset": STRING,
        "size": STRING,
        "image_size": STRING,
        "grow_on_first_boot": BOOLEAN,
    },
    ("name", "size"),
)

ROOTFS = Object(
    {
        "filename": STRING,
        "url": STRING,
        "sha256": STRING,
        "hostname": STRING,
        "custom_packages": STRINGS,
        "packages": STRINGS,
        "package_set": STRINGS,
        "package_sets": Map(STRINGS),
        "default_locale": Object({"lang": STRING, "language": STRING}, ("lang", "language")),
        "default_session": OPTIONAL_TEXT,
        "default_user": OPTIONAL_TEXT,
        "disable_root_login": BOOLEAN,
        "emulator": STRING,
        "groups": STRINGS,
        "gnome_remote_desktop_login": BOOLEAN,
        "image_format": STRING,
        "install_recommends": BOOLEAN,
        "root_password": OPTIONAL_TEXT,
        "users": Map(USER),
        "extra_apt_sources": ListOf(
            Object({"name": STRING, "source": STRING, "key": DOWNLOAD}, ("name", "source", "key"))
        ),
        "extra_debs": ListOf(
            Object(
                {
                    **DOWNLOAD_FIELDS,
                    "name": STRING,
                    "force_overwrite": BOOLEAN,
                    "hold_packages": STRINGS,
                },
                ("name", "url", "sha256"),
            )
        ),
        "extra_firmware": ListOf(
            Object(
                {
                    **DOWNLOAD_FIELDS,
                    "name": STRING,
                    "source": SOURCE_REF,
                    "files": ListOf(FIRMWARE_FILE),
                    "dest": STRING,
                },
                ("name",),
            )
        ),
        "panel_firmware": ListOf(Object({"src": STRING, "dest": STRING}, ("src", "dest"))),
        "ubi": Object(
            {
                **dict.fromkeys(
                    (
                        "leb_size",
                        "max_leb_count",
                        "min_io_size",
                        "mtd_index",
                        "peb_size",
                        "reserved_pebs",
                        "subpage_size",
                        "vid_hdr_offset",
                    ),
                    INTEGER,
                ),
                "space_fixup": BOOLEAN,
                "volume_size": STRING,
            }
        ),
    }
)

SYSTEM = Object(
    {
        "distro": STRING,
        "extensions": Map(ExtensionObject()),
        "build_environment": STRING,
        "userland_toolchain": STRING,
        **dict.fromkeys(
            (
                "board",
                "platform",
                "soc",
                "product",
                "variant",
                "vendor",
                "flash_storage",
                "flash_tool",
            ),
            STRING,
        ),
        "products": STRINGS,
        "variants": STRINGS,
        "flash_spi_loader": BOOLEAN,
        "jobs": INTEGER,
        "architecture": Object(
            dict.fromkeys(("userspace", "kernel", "bootloader"), STRING),
            ("userspace", "kernel", "bootloader"),
        ),
        "sources": Map(SOURCE),
        "external_apps": Map(APP_SOURCE),
        "external_app_dirs": STRINGS,
        "packages": ListOf(PACKAGE_SELECTION),
        "packages_meta": Object(
            {
                "kernel_src_paths": STRINGS,
                "overlay_src_paths": STRINGS,
                "app_src_paths": Map(STRINGS),
            }
        ),
        "kernel": Object(
            {
                "boot_format": STRING,
                "boot_its": STRING,
                "config": Map(TEXT),
                "cross_compile": STRING,
                "defconfig": STRINGS,
                "exclude_patches": STRINGS,
                "image": STRING,
                "source": SOURCE_REF,
                "oot_modules": ListOf(OOT_MODULE),
                "oot_sources": Map(Object({"source": SOURCE_REF}, ("source",))),
                "device_tree": Object(
                    {"directory": TEXT, "name": STRING, "build_overlays": STRINGS}
                ),
            }
        ),
        "bootloader": Object(
            {
                "config": Map(TEXT),
                "defconfig": STRINGS,
                "source": SOURCE_REF,
                "exclude_patches": STRINGS,
                "idbloader_selfbuilt_spl": BOOLEAN,
                **dict.fromkeys(
                    (
                        "cross_compile",
                        "fip_board_dir",
                        "fip_tool",
                        "firehose_loader",
                        "idbloader_method",
                        "spi_patch",
                        "spi_rawprogram",
                        "target",
                        "trust_mode",
                    ),
                    STRING,
                ),
                **dict.fromkeys(
                    ("edk2_firmware", "toolchain", "riscv_toolchain", "ufs_firehose"), DOWNLOAD
                ),
                "ufs_provisions": Map(DOWNLOAD),
                "fit_pack": Object(
                    {"copies": INTEGER, "slot_size_kb": INTEGER, "external_data_offset": STRING}
                ),
            }
        ),
        "boot": Object(
            {
                "kernel_args": TEXT,
                "overlays": Object(
                    dict.fromkeys(("intree", "vendor", "board", "package", "enabled"), STRINGS)
                ),
                "package_overlay_sources": Map(STRING),
            }
        ),
        "device-tree-overlay": Object({"source": SOURCE_REF}),
        "kernel_bsp": Object({"dtsi_dir": STRING, "source": SOURCE_REF}),
        "kernel_device": Object(
            {"board_dts_path": STRING, "bsp_defconfig_path": STRING, "source": SOURCE_REF}
        ),
        "rkbin": Object(
            {
                "source": SOURCE_REF,
                **dict.fromkeys(
                    ("ini_prefix", "loader_ini", "mkimage_chip", "trust_ini", "trust_ini_prefix"),
                    STRING,
                ),
            }
        ),
        "rootfs": ROOTFS,
        "storage": Object({"size": STRING, "type": STRING}),
        "partitions": Object(
            {
                "format": STRING,
                "sector_size": INTEGER,
                "parameter": STRING,
                "entries": ListOf(PARTITION),
            }
        ),
        "flash_identity": Object(
            {"chip_patterns": STRINGS, "storage_patterns": STRINGS, "require_rid": BOOLEAN}
        ),
        "recovery": Object(
            {
                "enabled": BOOLEAN,
                "packages": STRINGS,
                "custom_packages": STRINGS,
                "install_recommends": BOOLEAN,
                "extra_apt_sources": ROOTFS.fields["extra_apt_sources"],
                "protected_partitions": STRINGS,
                "transport": STRING,
            }
        ),
        "amp": Object(
            {
                "enabled": BOOLEAN,
                "app": STRING,
                "max_image_size": STRING,
                "mode": STRING,
                "soc_project": STRING,
                "memory": Object(
                    dict.fromkeys(
                        (
                            "cpu",
                            "cpu_base",
                            "dram_size",
                            "sram_base",
                            "sram_size",
                            "shmem_base",
                            "shmem_size",
                            "rpmsg_base",
                            "rpmsg_size",
                        ),
                        INTEGER,
                    )
                ),
                "runtime": Object(
                    {
                        **dict.fromkeys(
                            (
                                "amp_mpidr",
                                "linux_mpidr",
                                "link_id",
                                "mailbox_irq",
                                "endpoint_address",
                                "minimum_heap_size",
                                "linux_load",
                            ),
                            INTEGER,
                        ),
                        **dict.fromkeys(
                            ("cpu_delete", "endpoint_name", "gic_profile", "linux_arch"), STRING
                        ),
                        "firmware_reserved_in_dts": BOOLEAN,
                        "fit_requires_sram": BOOLEAN,
                        "mailboxes": STRINGS,
                    }
                ),
            }
        ),
    }
)


def validate_system_shape(config: dict, *, authored: bool = False) -> None:
    """在任何展开或消费者运行前校验形状；派生字段不得由配置作者注入。"""
    SYSTEM.check(config, "config")
    if authored:
        for name in ("packages_meta",):
            if name in config:
                raise SchemaError(f"config.{name} 是解析器派生字段，请从配置源删除")
        if "package_overlay_sources" in config.get("boot", {}):
            raise SchemaError(
                "config.boot.package_overlay_sources 是解析器派生字段，请从配置源删除"
            )
