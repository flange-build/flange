"""components/packages 通用硬件特性包：清单加载 + 校验 + 按类型展开。

一个硬件特性包位于 ``components/packages/<pkg>/``，由 ``package.py`` 导出
``PACKAGE`` dict 描述。包内每个 component 带 ``type``，构建引擎按 type 分发到
**既有**流水线：

- ``oot-driver``：合成 ``kernel.oot_modules`` 条目（``make M=`` 对内核源树
  编译 → strip → 装入 ``lib/modules/.../updates/``），复用
  ``builder/kernel_base.py`` 的 OOT 模块编译/安装路径。
- ``devicetree``：取该 board 对应 ``.dtso``，注册进
  ``boot.overlays.package``，由 ``builder/overlays.py`` 用 cpp+dtc 编译。
- ``vendor``：注册 package 内的本地 App，并加入 ``rootfs.custom_packages``；
  由 AppBuilder / DebBuilder 打成 flange 自有 deb 后安装。

board 通过顶层 ``packages`` 字段 opt-in。``expand_hardware_packages`` 在
``resolve_config`` 解析完三层 + 条件后调用，把包内容注入 config，使下游
builder 无需感知包概念——它们读到的就是普通的 ``oot_modules`` /
``boot.overlays.package``。

注入键：
- ``config["kernel"]["oot_modules"]``：追加 oot-driver 合成条目（绝对路径）。
- ``config["boot"]["overlays"]["package"]``：package overlay 的 ``.dtbo`` 名列表。
- ``config["boot"]["package_overlay_sources"]``：``{name.dtbo: 绝对 .dtso 路径}``。
- ``config["rootfs"]["custom_packages"]``：追加 vendor deb 包名。
- ``config["external_apps"]``：注册 vendor package 的本地 App 路径。
- ``config["packages_meta"]``：``{kernel_src_paths, overlay_src_paths}``（相对
  路径），供 ``builder/cache.py`` 做内容哈希（包源改动触发增量重建）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path, PurePosixPath
from typing import Any

from builder.config.schema import STRING, STRINGS, Map, Object
from builder.actions import validate_actions
from builder.paths import PROJECT_ROOT, components_dir
from builder.layers import stack_for
from builder.platforms.spec import capability as platform_capability

# component 合法类型集合。未知类型 → 构建失败。
#
# 不含 "deb"：它曾作为占位保留在这里，展开循环里却静默无操作 —— 声明合法、
# 行为为空是最难查的一类缺陷（配置写了不报错也不生效）。真要接入第三方 deb
# 时再加，届时展开逻辑与合法性声明一起落地。今天的替代路径是
# rootfs.extra_debs。
VALID_COMPONENT_TYPES = {"oot-driver", "devicetree", "vendor"}


_COMPONENT_COMMON = {"name": STRING, "type": STRING, "variants": STRINGS}
_COMPONENT_SCHEMAS = {
    "oot-driver": Object(
        {**_COMPONENT_COMMON, "dir": STRING, "ko_pattern": STRINGS},
        ("name", "type", "dir", "ko_pattern"),
    ),
    "devicetree": Object(
        {**_COMPONENT_COMMON, "overlays": Map(STRING)}, ("name", "type", "overlays")
    ),
    "vendor": Object(
        {**_COMPONENT_COMMON, "dir": STRING, "inputs": STRINGS}, ("name", "type", "dir")
    ),
}


def _package_path(value: str, field: str, root: Path) -> Path:
    """包内路径不得通过绝对路径、父目录或符号链接越出包边界。"""
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or any(c in value for c in "\0\r\n"):
        raise ValueError(f"{field} 必须是包内相对路径，不能含 '..' 或控制字符")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{field} 经符号链接越出包根目录：{value}")
    return resolved


def _load_package_var(file_path: Path) -> Any:
    """从 package.py 加载 ``PACKAGE`` 变量。

    与 registry._load_module_var 同构——独立实现以避免与 registry 形成
    import 环（registry 在 resolve_config 内延迟 import 本模块）。
    """
    module_name = f"_flange_pkg_{file_path.stem}_{id(file_path)}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载包清单：{file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "PACKAGE"):
        raise ValueError(f"包清单 {file_path} 缺少变量 PACKAGE")
    return module.PACKAGE


def load_package_manifest_dir(package_dir: Path) -> dict:
    """从指定目录加载并校验 ``package.py``，返回 ``PACKAGE`` dict。

    校验：目录存在、含 package.py、name 与目录名一致、components 各项 type
    合法且必备字段齐全、actions 使用安全 argv。目录旁的 ``config.jsonnet``
    不参与此加载过程。
    """
    package_path = Path(package_dir).expanduser()
    pkg_dir = package_path.resolve()
    pkg_name = package_path.name
    if pkg_name in {"", ".", ".."}:
        pkg_name = pkg_dir.name
    manifest = pkg_dir / "package.py"
    if not manifest.is_file():
        raise ValueError(f"硬件特性包不存在: {pkg_name}（缺清单 {manifest}）")

    pkg = _load_package_var(manifest)
    if not isinstance(pkg, dict):
        raise ValueError(f"包 {pkg_name} 的 PACKAGE 必须是 dict")

    unknown = set(pkg) - {"name", "description", "components", "actions"}
    if unknown:
        raise ValueError(f"PACKAGE.{sorted(unknown, key=str)[0]} 是未知字段，请删除或纠正拼写")
    if "description" in pkg:
        STRING.check(pkg["description"], "PACKAGE.description")
    name = pkg.get("name")
    if name != pkg_name:
        raise ValueError(f"包 {pkg_name} 的 PACKAGE['name']={name!r} 与目录名不一致")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError(f"包 {pkg_name} 的 name 必须是 kebab-case：{name!r}")

    components = pkg.get("components")
    if not isinstance(components, list):
        raise ValueError(f"包 {pkg_name} 的 components 必须是列表")

    component_names: set[str] = set()
    for index, comp in enumerate(components):
        if not isinstance(comp, dict) or "type" not in comp:
            raise ValueError(f"包 {pkg_name} 的 component 必须是含 type 字段的 dict: {comp!r}")
        ctype = comp["type"]
        if not isinstance(ctype, str) or ctype not in VALID_COMPONENT_TYPES:
            raise ValueError(
                f"包 {pkg_name} 的 component type 非法: {ctype!r}；"
                f"候选: {', '.join(sorted(VALID_COMPONENT_TYPES))}"
            )
        field = f"PACKAGE.components[{index}]"
        _COMPONENT_SCHEMAS[ctype].check(comp, field)
        if comp["name"] in component_names:
            raise ValueError(f"{field}.name 重复：{comp['name']}，请使用唯一组件名称")
        component_names.add(comp["name"])
        if "dir" in comp:
            _package_path(comp["dir"], f"{field}.dir", pkg_dir)
        for key in ("ko_pattern", "inputs"):
            for item in comp.get(key, []):
                _package_path(item, f"{field}.{key}", pkg_dir)
        for board, overlay in comp.get("overlays", {}).items():
            _package_path(overlay, f"{field}.overlays.{board}", pkg_dir)
        variants = comp.get("variants")
        if variants is not None and (
            not isinstance(variants, list)
            or not variants
            or not all(isinstance(item, str) and item for item in variants)
        ):
            raise ValueError(f"包 {pkg_name} 的 component variants 必须是非空字符串列表: {comp!r}")
        if ctype == "oot-driver":
            if not comp.get("dir") or not comp.get("ko_pattern"):
                raise ValueError(
                    f"包 {pkg_name} 的 oot-driver component 需含 dir 与 ko_pattern: {comp!r}"
                )
        elif ctype == "devicetree":
            if not isinstance(comp.get("overlays"), dict):
                raise ValueError(
                    f"包 {pkg_name} 的 devicetree component 需含 overlays "
                    f"映射（board → .dtso 相对路径）: {comp!r}"
                )
        elif ctype == "vendor":
            if not comp.get("name") or not comp.get("dir"):
                raise ValueError(f"包 {pkg_name} 的 vendor component 需含 name 与 dir: {comp!r}")

    normalized = dict(pkg)
    normalized["actions"] = validate_actions(
        pkg.get("actions", {}),
        field=f"包 {pkg_name} 的 actions",
    )
    return normalized


def load_package_manifest(pkg_name: str, project_root: Path, *, layer_stack=None) -> dict:
    """按仓库内名称加载包清单，保持 board opt-in 的既有 API。"""
    ref = (layer_stack or stack_for(project_root=project_root)).selected(f"components/packages/{pkg_name}")
    pkg_dir = ref.path if ref else components_dir(project_root) / "packages" / pkg_name
    return load_package_manifest_dir(pkg_dir)


def resolve_package_dir(
    name_or_path: str | Path | None,
    project_root: Path | None = None,
    caller_cwd: Path | None = None,
    layer_stack=None,
) -> Path:
    """把仓库内包名或调用者 cwd 下的路径解析为 Package 目录。

    ``None`` 表示调用者当前目录。显式路径或调用者 cwd 下已存在的目录优先；
    其余值按仓库内 ``components/packages/<name>`` 查找。这里只定位清单，调用方
    随后应使用 :func:`load_package_manifest_dir` 做统一内容校验。
    """
    root = Path(project_root or PROJECT_ROOT).expanduser().resolve()
    cwd = Path(caller_cwd or Path.cwd()).expanduser().resolve()

    if name_or_path is None:
        package_dir = cwd
    else:
        raw = str(name_or_path)
        if not raw.strip():
            raise ValueError("Package 名称或路径不能为空")
        path = Path(raw).expanduser()
        candidate = path if path.is_absolute() else cwd / path
        is_path = path.is_absolute() or raw.startswith(".") or "/" in raw or candidate.is_dir()
        ref = (layer_stack or stack_for(project_root=root)).selected(f"components/packages/{raw}") if not is_path else None
        package_dir = candidate if is_path else (ref.path if ref else components_dir(root) / "packages" / raw)

    resolved = package_dir.resolve()
    manifest = resolved / "package.py"
    if not resolved.is_dir() or not manifest.is_file():
        raise FileNotFoundError(f"Package 路径不存在或缺少 package.py：{resolved}")
    return resolved


def _parse_opt_in(entry: Any) -> tuple[str, set[str] | None]:
    """解析 board.packages 中一项 opt-in 声明。

    返回 ``(包名, 选中的 oot-driver 名集合或 None)``。None 表示「取该包默认
    集」——即包内全部 oot-driver。

    - 字符串 ``"foo"`` → ``("foo", None)``
    - dict ``{"name": "foo", "drivers": ["bar"]}`` → ``("foo", {"bar"})``
    - dict ``{"name": "foo"}``（无 drivers）→ ``("foo", None)``
    """
    if isinstance(entry, str):
        STRING.check(entry, "packages.name")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry):
            raise ValueError("packages.name 必须是 kebab-case 名称，不能使用路径")
        return entry, None
    if isinstance(entry, dict):
        Object({"name": STRING, "drivers": STRINGS}, ("name",)).check(entry, "packages")
        name = entry.get("name")
        _parse_opt_in(name)
        if not name:
            raise ValueError(f"packages 项缺少 name: {entry!r}")
        drivers = entry.get("drivers")
        if drivers is None:
            return name, None
        if not isinstance(drivers, list):
            raise ValueError(f"packages 项 {name} 的 drivers 必须是列表: {entry!r}")
        if len(set(drivers)) != len(drivers):
            raise ValueError("packages.drivers 不得含重复名称")
        return name, set(drivers)
    raise TypeError(f"packages 项必须是字符串或 dict: {entry!r}")


def _vendor_inputs(pkg_name: str, comp: dict, pkg_dir: Path) -> list[str]:
    """解析 vendor component 的 ``inputs`` 声明（相对包根的路径列表）。

    未声明时返回空列表 —— App 目录自身的内容已由 ``BuildCache`` 递归哈希，
    只有目录之外的内容需要显式登记。
    """
    inputs = comp.get("inputs")
    if inputs is None:
        return []
    if not isinstance(inputs, list) or not all(isinstance(item, str) and item for item in inputs):
        raise ValueError(f"包 {pkg_name} 的 vendor component inputs 必须是非空字符串列表: {comp!r}")
    for item in inputs:
        if not (pkg_dir / item).exists():
            raise FileNotFoundError(
                f"包 {pkg_name} 的 vendor component 声明的 inputs 不存在: {pkg_dir / item}"
            )
    return list(inputs)


def expand_hardware_packages(config: dict, project_root: Path | None = None) -> dict:
    """把 board 启用的硬件特性包按类型展开注入 config。

    幂等性不保证：应仅在 resolve_config 末尾对新解析的 config 调用一次。
    未声明 ``packages`` 或为空 → 原样返回（向后兼容）。
    """
    pkgs = config.get("packages")
    if not pkgs:
        return config
    if not isinstance(pkgs, list):
        raise TypeError("顶层 packages 字段必须是列表")

    root = Path(project_root) if project_root else PROJECT_ROOT
    board = config.get("board")

    kernel_cfg = config.setdefault("kernel", {})
    oot_modules = kernel_cfg.setdefault("oot_modules", [])
    if not isinstance(oot_modules, list):
        raise TypeError("kernel.oot_modules 必须是列表")

    boot_cfg = config.setdefault("boot", {})
    overlay_cfg = boot_cfg.setdefault("overlays", {})
    package_overlays: list[str] = overlay_cfg.setdefault("package", [])
    overlay_sources: dict[str, str] = boot_cfg.setdefault("package_overlay_sources", {})

    meta = config.setdefault("packages_meta", {})
    kernel_src_paths: list[str] = meta.setdefault("kernel_src_paths", [])
    overlay_src_paths: list[str] = meta.setdefault("overlay_src_paths", [])
    app_src_paths: dict[str, list[str]] = meta.setdefault("app_src_paths", {})

    def resource_path(path: Path) -> str:
        # 基础层保留既有相对路径，外部层记录实际归属。
        return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)

    seen_packages: set[str] = set()
    for entry in pkgs:
        pkg_name, selected = _parse_opt_in(entry)
        if pkg_name in seen_packages:
            raise ValueError(f"packages 重复选择包：{pkg_name}，请合并为一项")
        seen_packages.add(pkg_name)
        stack = stack_for(config, project_root=root)
        pkg = load_package_manifest(pkg_name, root, layer_stack=stack)
        pkg_dir = stack.selected(f"components/packages/{pkg_name}").path

        # 校验显式选中的 driver 都存在于包内
        if selected is not None:
            available = {c["name"] for c in pkg["components"] if c["type"] == "oot-driver"}
            missing = selected - available
            if missing:
                raise ValueError(
                    f"包 {pkg_name} 的 opt-in 选中了不存在的 driver: "
                    f"{', '.join(sorted(missing))}；可用: "
                    f"{', '.join(sorted(available)) or '无'}"
                )

        for comp in pkg["components"]:
            if comp.get("variants") and config.get("variant") not in comp["variants"]:
                continue
            ctype = comp["type"]
            if ctype == "oot-driver":
                # 按需编译：未选中的 driver 不注入 oot_modules（不编译/不安装）
                if selected is not None and comp["name"] not in selected:
                    continue
                driver_rel = resource_path(pkg_dir / comp["dir"])
                driver_abs = (pkg_dir / comp["dir"]).resolve()
                ko_abs = [str(driver_abs / ko) for ko in comp["ko_pattern"]]
                oot_modules.append(
                    {
                        "dir": str(driver_abs),
                        "label": f"{pkg_name}/{comp['name']} (package OOT driver)",
                        "make_args": [
                            "ARCH={arch}",
                            "CROSS_COMPILE={cross_compile}",
                            "KSRC={kernel_src_abs}",
                            f"M={driver_abs}",
                        ],
                        "ko_pattern": ko_abs,
                    }
                )
                kernel_src_paths.append(driver_rel)

            elif ctype == "devicetree":
                overlays = comp["overlays"]
                if board not in overlays:
                    continue  # 该包未对此 board 提供 overlay
                dtso_rel = overlays[board]
                dtso_abs = (pkg_dir / dtso_rel).resolve()
                if not dtso_abs.is_file():
                    raise FileNotFoundError(
                        f"包 {pkg_name} 为 board {board} 声明的 overlay 源不存在: {dtso_abs}"
                    )
                dtbo_name = dtso_abs.name.removesuffix(".dtso") + ".dtbo"
                if dtbo_name not in package_overlays:
                    package_overlays.append(dtbo_name)
                if platform_capability(config, "dtbo_merge_at_build"):
                    build_overlays = kernel_cfg.setdefault("device_tree", {}).setdefault(
                        "build_overlays", []
                    )
                    if dtbo_name not in build_overlays:
                        build_overlays.append(dtbo_name)
                overlay_sources[dtbo_name] = str(dtso_abs)
                overlay_src_paths.append(resource_path(dtso_abs))

            elif ctype == "vendor":
                app_dir = (pkg_dir / comp["dir"]).resolve()
                if not (app_dir / "app.yaml").is_file():
                    raise FileNotFoundError(f"包 {pkg_name} 的 vendor App 缺少 app.yaml: {app_dir}")
                app_name = comp["name"]
                external_apps = config.setdefault("external_apps", {})
                existing = external_apps.get(app_name)
                app_source = {"local_path": str(app_dir)}
                if existing is not None and existing != app_source:
                    raise ValueError(
                        f"包 {pkg_name} 的 vendor App 与 external_apps[{app_name!r}] 冲突"
                    )
                external_apps[app_name] = app_source
                custom_packages = config.setdefault("rootfs", {}).setdefault("custom_packages", [])
                if app_name not in custom_packages:
                    custom_packages.append(app_name)
                # 位于 App 目录之外、但确实参与该 App 构建的包内内容（补丁、
                # 共享脚本等）：登记为附加哈希输入，否则改补丁不会触发重建。
                extra = [
                    resource_path(pkg_dir / item)
                    for item in _vendor_inputs(pkg_name, comp, pkg_dir)
                ]
                if extra:
                    app_src_paths.setdefault(app_name, []).extend(extra)

    return config
