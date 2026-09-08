"""系统组件的计划装配；平台配方与缓存共享声明的配置、源码和输出。"""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
from pathlib import Path

from builder.artifacts import ArtifactSpec
from builder.config.canonical import kernel_device_tree
from builder.dtb_overlay import board_overlays, intree_overlays, package_overlays, vendor_overlays
from builder.environment import environment_identity
from builder.graph import InputSpec, TaskPlan, component_enabled
from builder.platforms.spec import dependency_graph, required_artifacts
from builder.patches import normalize_excluded_patches
from builder.source import SourceManager

# 这些是配方实际收到的配置边界。字段被剔除后执行器也读不到它，
# 不再存在“执行读取全配置、缓存自行猜哪些字段无关”的两套语义。
CONFIG_BOUNDARIES = {
    "kernel": {
        "rootfs",
        "recovery",
        "image",
        "storage",
        "amp",
        "partitions",
        "external_apps",
        "external_app_dirs",
    },
    "bootloader": {
        "rootfs",
        "recovery",
        "image",
        "partitions",
        "kernel",
        "kernel_bsp",
        "kernel_device",
        "external_apps",
        "external_app_dirs",
    },
    "device-tree-overlay": {
        "rootfs",
        "recovery",
        "image",
        "storage",
        "amp",
        "partitions",
        "external_apps",
        "external_app_dirs",
    },
    "boot": {"rootfs", "image", "external_apps", "external_app_dirs"},
    "amp": {
        "rootfs",
        "recovery",
        "kernel_bsp",
        "kernel_device",
        "bootloader",
        "boot",
        "image",
        "partitions",
        "storage",
        "rkbin",
    },
}


def output_contract(component: str, config: dict, context) -> tuple[ArtifactSpec, ...]:
    root = context.target_dir / component
    platform_outputs = required_artifacts(component, root, config)
    if platform_outputs is not None:
        if component == "image":
            return (*platform_outputs, ArtifactSpec(
                "flash-config", context.target_dir / "flash-config.json", allow_empty=False
            ))
        return platform_outputs
    outputs: list[ArtifactSpec] = []

    def file(name: str, relative: str, required: bool = True):
        outputs.append(ArtifactSpec(name, root / relative, required=required, allow_empty=False))

    if component == "kernel":
        _, dts = kernel_device_tree(config)
        file("image", (config.get("kernel") or {}).get("image", "Image"))
        if dts:
            file("dtb", f"{dts}.dtb")
        outputs.append(ArtifactSpec("modules", root / "modules", kind="tree", allow_empty=True))
        if (config.get("kernel") or {}).get("boot_format") == "fit":
            file("fit_boot", "boot.img")
        if intree_overlays(config):
            outputs.append(ArtifactSpec("dtbos", root / "overlay", kind="tree", allow_empty=False))
    elif component == "device-tree-overlay":
        outputs.append(ArtifactSpec("overlays", root / "overlays", kind="tree", allow_empty=True))
        for name in vendor_overlays(config) + board_overlays(config) + package_overlays(config):
            file(f"overlay:{name}", f"overlays/{name}")
    elif component == "rootfs":
        format_ = (config.get("rootfs") or {}).get("image_format", "ext4")
        file("packages", "packages.manifest")
        file(
            "ubi" if format_ == "ubi" else "rootfs",
            "rootfs.ubi" if format_ == "ubi" else "rootfs.img",
        )
    elif component in {"boot", "recovery", "amp"}:
        if component == "recovery":
            file("packages", "packages.manifest")
        file(component, f"{component}.img")
    elif component == "bootloader":
        platform = config["platform"]
        if platform == "rockchip":
            file("miniloader", "miniloader.bin")
            if not (config.get("bootloader") or {}).get("prebuilt_spi_image"):
                file("bootloader", "u-boot.itb")
                file("idbloader", "idbloader.img")
        elif platform == "amlogic":
            file("fip", "u-boot.bin")
            file("sd", "u-boot.bin.sd.bin")
        elif platform == "allwinnera733":
            for key, name in (
                ("boot0_sdcard", "boot0_sdcard.bin"),
                ("boot0_ufs", "boot0_ufs.bin"),
                ("boot_package", "boot_package.fex"),
            ):
                file(key, name)
        elif (config.get("bootloader") or {}).get("edk2_firmware"):
            firmware_root = root / "edk2-spi-firmware"
            outputs.append(ArtifactSpec("edk2", firmware_root, kind="tree", allow_empty=False))
            loader = (config.get("bootloader") or {}).get(
                "firehose_loader", "prog_firehose_ddr.elf"
            )
            outputs.append(ArtifactSpec("firehose", firmware_root / loader, allow_empty=False))
    elif component == "image":
        partitions = config.get("partitions") or {}
        mtd = (
            partitions.get("format") == "mtd"
            or (config.get("storage") or {}).get("type") == "spinand"
        )
        file("bundle" if mtd else "image", "mtd-bundle.json" if mtd else "raw.img")
        if mtd:
            file("parameter", "parameter.txt")
        outputs.append(
            ArtifactSpec(
                "flash-config", context.target_dir / "flash-config.json", allow_empty=False
            )
        )
        if config.get("platform") == "rockchip":
            if mtd or config.get("flash_storage"):
                outputs.append(
                    ArtifactSpec(
                        "flash-parameter", context.target_dir / "parameter.txt", allow_empty=False
                    )
                )
            if config.get("flash_spi_loader") or (config.get("bootloader") or {}).get(
                "prebuilt_spi_image"
            ):
                outputs.append(
                    ArtifactSpec(
                        "spi", context.target_dir / "bootloader/spi.img", allow_empty=False
                    )
                )
    return tuple(outputs)


def source_references(component: str, config: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name in [component] + (["kernel_bsp", "kernel_device"] if component == "kernel" else []):
        ref = (config.get(name) or {}).get("source")
        if ref:
            result[name] = ref
    if component in {"device-tree-overlay", "amp"} and (config.get("kernel") or {}).get("source"):
        result["kernel"] = config["kernel"]["source"]
    if component == "kernel":
        for name, spec in (config.get("kernel", {}).get("oot_sources") or {}).items():
            result[f"oot:{name}"] = spec["source"]
    if component == "bootloader":
        ref = (config.get("rkbin") or {}).get("source")
        if ref:
            result["rkbin"] = ref
        if "amlogic-boot-fip" in (config.get("sources") or {}):
            result["amlogic-boot-fip"] = {"name": "amlogic-boot-fip"}
    if component == "rootfs":
        for index, entry in enumerate((config.get("rootfs") or {}).get("extra_firmware") or []):
            if entry.get("source"):
                result[f"firmware:{index}"] = entry["source"]
    return result


def _source_input(name: str, ref: dict, config: dict, context, source) -> InputSpec:
    descriptor = config["sources"][ref["name"]]
    if descriptor.get("local_path"):
        path = Path(descriptor["local_path"])
        if not path.is_absolute():
            path = context.tool_root / path
        if ref.get("subpath"):
            path /= ref["subpath"]
        if path.exists():
            return InputSpec.tree(
                name,
                path,
                exclude_names={".git", "__pycache__"},
                exclude_paths={context.build_root},
            )
        return InputSpec.value(name, {"missing": str(path)})
    path = source._ensure_source_ref(ref, config, name, sync_remote=False)
    if path.exists():
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
        ).stdout.strip()
        return InputSpec.git(name, path, revision)
    return InputSpec.value(name, {"unresolved": descriptor})


def recipe_files(component: str, config: dict, context) -> set[Path]:
    """从实际配方继承链展开静态 builder 依赖；动态平台工厂只记录选中的实现。"""
    module = importlib.import_module(f"builder.platforms.{config['platform']}")
    instance = module.create_builder(component, None, None)
    actual_root = Path(__file__).resolve().parent.parent
    pending = [
        context.tool_root / Path(inspect.getfile(cls)).resolve().relative_to(actual_root)
        for cls in type(instance).__mro__
        if cls.__module__.startswith("builder.")
    ]
    found: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in found or not path.is_file():
            continue
        found.add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            for name in names:
                if not name.startswith("builder."):
                    continue
                relative = Path(*name.split("."))
                file = context.tool_root / relative.with_suffix(".py")
                package = context.tool_root / relative / "__init__.py"
                if file.is_file():
                    pending.append(file)
                elif package.is_file():
                    pending.append(package)
    # 编排会改变落盘语义，但不展开 engine 的调度/渲染模块导入。
    found.update(
        context.tool_root / "builder" / name
        for name in (
            "engine.py",
            "component_plan.py",
            "graph.py",
            "artifacts.py",
            "digest.py",
            "locking.py",
        )
    )
    found.add(context.tool_root / "builder/platforms" / config["platform"] / "__init__.py")
    return found


def create_component_plan(component: str, config: dict, context, source: SourceManager) -> TaskPlan:
    enabled = component_enabled(config, component)
    execution_config = {
        key: value
        for key, value in config.items()
        if key not in CONFIG_BOUNDARIES.get(component, set()) and key not in {"verbose", "quiet"}
    }
    dependencies = tuple(
        name for name in dependency_graph(config)[component] if component_enabled(config, name)
    )
    if not enabled:
        return TaskPlan(component, f"component:{component}:v1", (), (), (), False)
    inputs = [
        InputSpec.value("config", execution_config),
        InputSpec.value("environment", environment_identity()),
    ]
    refs = source_references(component, config)
    for name, ref in sorted(refs.items()):
        inputs.append(_source_input(f"source:{name}", ref, config, context, source))

    def tree(name: str, path: Path):
        if path.is_dir():
            inputs.append(
                InputSpec.tree(
                    name,
                    path,
                    exclude_names={".git", "__pycache__"},
                    exclude_paths={context.build_root},
                )
            )
        else:
            inputs.append(InputSpec.value(name, {"absent": str(path)}))

    def file(name: str, path: Path):
        if path.is_file() or path.is_symlink():
            inputs.append(InputSpec.file(name, path))
        else:
            inputs.append(InputSpec.value(name, {"absent": str(path)}))

    # 配方实现是声明输入；叶子组件采用实际实现类的继承链，其他动态流程覆盖构建代码。
    if component in {"kernel", "bootloader"}:
        for path in sorted(recipe_files(component, config, context)):
            file(f"recipe:{path.relative_to(context.tool_root)}", path)
    else:
        tree("recipe:builder", context.tool_root / "builder")
    file("environment:dockerfile", context.tool_root / "docker/Dockerfile")

    components = context.components_root
    platform = config.get("platform", "")
    board = config["board"]
    if component in {"kernel", "bootloader"}:
        excluded = set(
            normalize_excluded_patches(
                (config.get(component) or {}).get("exclude_patches"), f"{component}.exclude_patches"
            )
        )
        for scope, directory in (
            ("platform", components / "platform" / platform / "patches" / component),
            ("board", components / "board" / board / "patches" / component),
        ):
            for patch in sorted(directory.glob("*.patch")):
                relative = patch.relative_to(context.tool_root).as_posix()
                if patch.name not in excluded and relative not in excluded:
                    file(f"patch:{scope}:{patch.name}", patch)
        # 同目录中的配置片段也被平台配方读取。
        for directory in (
            components / "board" / board / "patches" / component,
            components / "platform" / platform / config.get("soc", "") / "patches" / component,
        ):
            for fragment in sorted(directory.glob("*.config")):
                file(f"fragment:{fragment.relative_to(components)}", fragment)
    if component in {"rootfs", "recovery"}:
        subdir = "overlay" if component == "rootfs" else "recovery-overlay"
        for name, path in (
            ("base", components / component / "overlay"),
            ("platform", components / "platform" / platform / subdir),
            ("board", components / "board" / board / subdir),
        ):
            tree(f"overlay:{name}", path)
        for entry in (config.get("rootfs") or {}).get("panel_firmware") or []:
            file(f"panel:{entry['src']}", components / "board" / board / entry["src"])
    meta = config.get("packages_meta") or {}
    if component == "kernel":
        for relative in meta.get("kernel_src_paths") or []:
            tree(f"driver:{relative}", context.tool_root / relative)
    if component == "device-tree-overlay":
        tree("overlay:board-sources", components / "board" / board / "dtso")
        for relative in meta.get("overlay_src_paths") or []:
            file(f"overlay:{relative}", context.tool_root / relative)
    if component == "amp":
        tree("amp:sdk", components / "amp")
        tree("amp:platform", components / "platform" / platform / "amp")
        app_name = (config.get("amp") or {}).get("app")
        if app_name:
            from builder.app_resolver import AppResolver

            try:
                path = AppResolver(context, source, config, read_only=True).resolve(app_name)
            except (ValueError, FileNotFoundError) as exc:
                inputs.append(InputSpec.value("amp:application", {"unresolved": str(exc)}))
            else:
                tree("amp:application", path)
    if component in {"rootfs", "recovery", "boot", "image"}:
        parameter = (config.get("partitions") or {}).get("parameter")
        if parameter:
            path = Path(parameter)
            file("partition:parameter", path if path.is_absolute() else context.tool_root / path)
    return TaskPlan(
        component,
        f"component:{component}:v1",
        tuple(inputs),
        output_contract(component, config, context),
        dependencies,
    )
