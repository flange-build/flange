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
- ``deb``：复用 rootfs deb 安装路径（当前仅在 schema 预留，未落地）。

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
from pathlib import Path
from typing import Any

from builder.paths import PROJECT_ROOT, components_dir

# component 合法类型集合。未知类型 → 构建失败。
VALID_COMPONENT_TYPES = {"oot-driver", "devicetree", "vendor", "deb"}


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


def load_package_manifest(pkg_name: str, project_root: Path) -> dict:
    """加载并校验单个包清单，返回 ``PACKAGE`` dict。

    校验：目录存在、含 package.py、name 与目录名一致、components 各项 type
    合法且必备字段齐全。任一不满足 → 抛 ValueError（信息含候选集合）。
    """
    pkg_dir = components_dir(project_root) / "packages" / pkg_name
    manifest = pkg_dir / "package.py"
    if not manifest.is_file():
        raise ValueError(
            f"硬件特性包不存在: {pkg_name}（缺清单 {manifest}）"
        )

    pkg = _load_package_var(manifest)
    if not isinstance(pkg, dict):
        raise ValueError(f"包 {pkg_name} 的 PACKAGE 必须是 dict")

    name = pkg.get("name")
    if name != pkg_name:
        raise ValueError(
            f"包 {pkg_name} 的 PACKAGE['name']={name!r} 与目录名不一致"
        )

    components = pkg.get("components")
    if not isinstance(components, list):
        raise ValueError(f"包 {pkg_name} 的 components 必须是列表")

    for comp in components:
        if not isinstance(comp, dict) or "type" not in comp:
            raise ValueError(
                f"包 {pkg_name} 的 component 必须是含 type 字段的 dict: {comp!r}"
            )
        ctype = comp["type"]
        if ctype not in VALID_COMPONENT_TYPES:
            raise ValueError(
                f"包 {pkg_name} 的 component type 非法: {ctype!r}；"
                f"候选: {', '.join(sorted(VALID_COMPONENT_TYPES))}"
            )
        variants = comp.get("variants")
        if variants is not None and (
            not isinstance(variants, list)
            or not variants
            or not all(isinstance(item, str) and item for item in variants)
        ):
            raise ValueError(
                f"包 {pkg_name} 的 component variants 必须是非空字符串列表: "
                f"{comp!r}"
            )
        if ctype == "oot-driver":
            if not comp.get("dir") or not comp.get("ko_pattern"):
                raise ValueError(
                    f"包 {pkg_name} 的 oot-driver component 需含 dir 与 "
                    f"ko_pattern: {comp!r}"
                )
        elif ctype == "devicetree":
            if not isinstance(comp.get("overlays"), dict):
                raise ValueError(
                    f"包 {pkg_name} 的 devicetree component 需含 overlays "
                    f"映射（board → .dtso 相对路径）: {comp!r}"
                )
        elif ctype == "vendor":
            if not comp.get("name") or not comp.get("dir"):
                raise ValueError(
                    f"包 {pkg_name} 的 vendor component 需含 name 与 dir: "
                    f"{comp!r}"
                )

    return pkg


def _parse_opt_in(entry: Any) -> tuple[str, set[str] | None]:
    """解析 board.packages 中一项 opt-in 声明。

    返回 ``(包名, 选中的 oot-driver 名集合或 None)``。None 表示「取该包默认
    集」——即包内全部 oot-driver。

    - 字符串 ``"foo"`` → ``("foo", None)``
    - dict ``{"name": "foo", "drivers": ["bar"]}`` → ``("foo", {"bar"})``
    - dict ``{"name": "foo"}``（无 drivers）→ ``("foo", None)``
    """
    if isinstance(entry, str):
        return entry, None
    if isinstance(entry, dict):
        name = entry.get("name")
        if not name:
            raise ValueError(f"packages 项缺少 name: {entry!r}")
        drivers = entry.get("drivers")
        if drivers is None:
            return name, None
        if not isinstance(drivers, list):
            raise ValueError(
                f"packages 项 {name} 的 drivers 必须是列表: {entry!r}"
            )
        return name, set(drivers)
    raise TypeError(f"packages 项必须是字符串或 dict: {entry!r}")


def expand_hardware_packages(
    config: dict, project_root: Path | None = None
) -> dict:
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
    overlay_sources: dict[str, str] = boot_cfg.setdefault(
        "package_overlay_sources", {})

    meta = config.setdefault("packages_meta", {})
    kernel_src_paths: list[str] = meta.setdefault("kernel_src_paths", [])
    overlay_src_paths: list[str] = meta.setdefault("overlay_src_paths", [])

    for entry in pkgs:
        pkg_name, selected = _parse_opt_in(entry)
        pkg = load_package_manifest(pkg_name, root)
        pkg_dir = components_dir(root) / "packages" / pkg_name

        # 校验显式选中的 driver 都存在于包内
        if selected is not None:
            available = {
                c["name"] for c in pkg["components"]
                if c["type"] == "oot-driver"
            }
            missing = selected - available
            if missing:
                raise ValueError(
                    f"包 {pkg_name} 的 opt-in 选中了不存在的 driver: "
                    f"{', '.join(sorted(missing))}；可用: "
                    f"{', '.join(sorted(available)) or '无'}"
                )

        for comp in pkg["components"]:
            if (comp.get("variants")
                    and config.get("variant") not in comp["variants"]):
                continue
            ctype = comp["type"]
            if ctype == "oot-driver":
                # 按需编译：未选中的 driver 不注入 oot_modules（不编译/不安装）
                if selected is not None and comp["name"] not in selected:
                    continue
                driver_rel = f"components/packages/{pkg_name}/{comp['dir']}"
                driver_abs = (pkg_dir / comp["dir"]).resolve()
                ko_abs = [str(driver_abs / ko) for ko in comp["ko_pattern"]]
                oot_modules.append({
                    "dir": str(driver_abs),
                    "label": f"{pkg_name}/{comp['name']} (package OOT driver)",
                    "make_args": [
                        "ARCH={arch}",
                        "CROSS_COMPILE={cross_compile}",
                        "KSRC={kernel_src_abs}",
                        f"M={driver_abs}",
                    ],
                    "ko_pattern": ko_abs,
                })
                kernel_src_paths.append(driver_rel)

            elif ctype == "devicetree":
                overlays = comp["overlays"]
                if board not in overlays:
                    continue  # 该包未对此 board 提供 overlay
                dtso_rel = overlays[board]
                dtso_abs = (pkg_dir / dtso_rel).resolve()
                if not dtso_abs.is_file():
                    raise FileNotFoundError(
                        f"包 {pkg_name} 为 board {board} 声明的 overlay 源不存在: "
                        f"{dtso_abs}"
                    )
                dtbo_name = dtso_abs.name.removesuffix(".dtso") + ".dtbo"
                if dtbo_name not in package_overlays:
                    package_overlays.append(dtbo_name)
                if config.get("platform", "").startswith("qualcomm"):
                    build_overlays = kernel_cfg.setdefault(
                        "device_tree", {}).setdefault("build_overlays", [])
                    if dtbo_name not in build_overlays:
                        build_overlays.append(dtbo_name)
                overlay_sources[dtbo_name] = str(dtso_abs)
                overlay_src_paths.append(
                    f"components/packages/{pkg_name}/{dtso_rel}")

            elif ctype == "vendor":
                app_dir = (pkg_dir / comp["dir"]).resolve()
                if not (app_dir / "app.yaml").is_file():
                    raise FileNotFoundError(
                        f"包 {pkg_name} 的 vendor App 缺少 app.yaml: {app_dir}"
                    )
                app_name = comp["name"]
                external_apps = config.setdefault("external_apps", {})
                existing = external_apps.get(app_name)
                app_source = {"local_path": str(app_dir)}
                if existing is not None and existing != app_source:
                    raise ValueError(
                        f"包 {pkg_name} 的 vendor App 与 external_apps"
                        f"[{app_name!r}] 冲突"
                    )
                external_apps[app_name] = app_source
                custom_packages = config.setdefault("rootfs", {}).setdefault(
                    "custom_packages", [])
                if app_name not in custom_packages:
                    custom_packages.append(app_name)

            # ctype == "deb"：预留，尚未接入构建流水线

    return config
