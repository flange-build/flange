"""系统组件的计划装配；平台配方与缓存共享声明的配置、源码和输出。"""

from __future__ import annotations

import ast
from builder.platforms.spec import load_for as load_platform
from builder.layers import stack_for
from builder.layer_resources import patch_resources, overlay_resources, overlay_entries, content_path
import inspect
import subprocess
from pathlib import Path

from builder.artifacts import ArtifactSpec
from builder.config.canonical import kernel_device_tree
from builder.dtb_overlay import board_overlays, intree_overlays, package_overlays, vendor_overlays
from builder.environment import environment_identity
from builder.graph import DEPENDENCY_GRAPH, InputSpec, TaskPlan, component_enabled
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
    stack = stack_for(config, context)
    provider = stack.provider("platform", config.get("platform", ""))
    if provider is not None and hasattr(provider, "output_contract"):
        result = provider.output_contract(component, config, context)
        if result is not None:
            for item in result:
                if not isinstance(item, ArtifactSpec) or not item.path.is_relative_to(context.target_dir):
                    raise ValueError("平台 output_contract 必须返回目标目录内的 ArtifactSpec")
            return tuple(result)
    root = context.target_dir / component
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
    module = load_platform(config)
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
    stack = stack_for(config, context)
    external = stack.provider_inputs("platform", config["platform"])
    if external:
        found.update(ref.path for ref in external)
    else:
        found.add(context.tool_root / "builder/platforms" / config["platform"] / "__init__.py")
    return found


def create_component_plan(component: str, config: dict, context, source: SourceManager) -> TaskPlan:
    from builder.config.jsonnet import ResolvedConfig
    config = ResolvedConfig(config)
    config.layer_stack = stack_for(context=context)
    stack = config.layer_stack
    enabled = component_enabled(config, component)
    execution_config = {
        key: value
        for key, value in config.items()
        if key not in CONFIG_BOUNDARIES.get(component, set()) and key not in {"verbose", "quiet"}
    }
    dependencies = tuple(
        name for name in DEPENDENCY_GRAPH[component] if component_enabled(config, name)
    )
    if not enabled:
        return TaskPlan(component, f"component:{component}:v1", (), (), (), False)
    inputs = [
        InputSpec.value("config", execution_config),
        InputSpec.value("environment", environment_identity(config=config, context=context)),
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
            file(f"recipe:{stack.reference(path).identity}", path)
    else:
        tree("recipe:builder", context.tool_root / "builder")
    from builder.build_environment import resolve_environment
    if resolve_environment(config, context) is None:
        file("environment:dockerfile", context.tool_root / "docker/Dockerfile")

    provider = stack.provider("platform", config["platform"])
    if provider is not None:
        for ref in stack.provider_inputs("platform", config["platform"]):
            name = f"recipe:{ref.identity}"
            if not any(item.name == name for item in inputs):
                file(name, ref.path)
        if hasattr(provider, "extra_inputs"):
            inputs.extend(provider.extra_inputs(component, config, context))
    from builder.build_environment import environment_inputs
    inputs.extend(environment_inputs(config, context))
    if component in {"rootfs", "recovery"}:
        for ref in stack.provider_inputs("distro", config.get("distro", "ubuntu")):
            file(f"distro:{ref.identity}", ref.path)
    if component == "image":
        for ref in stack.provider_inputs("flash_plan", config["platform"]):
            file(f"flash-plan:{ref.identity}", ref.path)
        flash_ref = stack.provider_ref("flash", config["platform"])
        inputs.append(InputSpec.value("flash:provider", flash_ref.identity if flash_ref else ""))
    components = context.components_root
    platform, board = config["platform"], config["board"]
    if component in {"kernel", "bootloader"}:
        patches = patch_resources(stack, config, component)
        inputs.append(InputSpec.value("patch:sequence", [ref.identity for ref in patches]))
        for ref in patches:
            file(f"patch:{ref.identity}", ref.path)
        for directory in (
            f"components/board/{board}/patches/{component}",
            f"components/platform/{platform}/{config.get('soc', '')}/patches/{component}",
            f"components/platform/{platform}/patches/{component}",
        ):
            for ref in stack.files(directory, "*.config"):
                file(f"fragment:{ref.identity}", ref.path)
    if component in {"rootfs", "recovery"}:
        overlays = overlay_resources(stack, config, component)
        inputs.append(InputSpec.value("overlay:sequence", [ref.identity for ref in overlays]))
        import stat
        for relative, ref in overlay_entries(stack, config, component).items():
            mode = ref.path.lstat().st_mode
            if stat.S_ISDIR(mode):
                inputs.append(InputSpec.value(f"overlay:directory:{relative}", stat.S_IMODE(mode)))
            else:
                file(f"overlay:file:{relative}", ref.path)
        for entry in (config.get("rootfs") or {}).get("panel_firmware") or []:
            path = Path(entry["src"])
            file(f"panel:{entry['src']}", path if path.is_absolute() else
                 content_path(stack, f"board/{board}/{entry['src']}"))
    meta = config.get("packages_meta") or {}
    if component == "kernel":
        for relative in meta.get("kernel_src_paths") or []:
            tree(f"driver:{relative}", context.tool_root / relative)
    if component == "device-tree-overlay":
        for ref in stack.files(f"components/board/{board}/dtso", "**/*"):
            file(f"overlay:board:{ref.identity}", ref.path)
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
