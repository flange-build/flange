"""App 来源配置的校验与路径归一化。

本模块作为 `resolve_config` 的后置处理步骤，负责把两个与 App 来源相关的
顶层键转成下游模块（SourceManager、AppBuilder、app_list）可以直接消费的
规范形式：

- ``external_apps``: ``dict[name, dict]`` —— 逐条校验 ``local_path`` 与 ``git``
  必须二选一且只能其一；``local_path`` 做 ``~`` 展开和相对 ``project_root``
  的绝对化。
- ``external_app_dirs``: ``list[str]`` —— 可选，默认空列表；每一项做同样的
  ``~`` 展开与绝对化。

不在此处校验路径是否存在——这样允许 dev 机 / CI 共享同一份配置，存在性
检查延后到 ``SourceManager.ensure_app()`` 真正访问时，错误信息更贴近触发
现场。
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from builder.config.schema import APP_SOURCE, STRINGS, Map, SchemaError


class AppSourceConfigError(ValueError):
    """``external_apps`` / ``external_app_dirs`` 校验失败时抛出。"""


def gather_custom_packages(config: dict) -> list[str]:
    """收集所有需要由 AppBuilder 构建的 custom package 名（去重 + 排序）。

    既包括 ``rootfs.custom_packages``（normal 系统装入），也包括启用 recovery
    时 ``recovery.custom_packages``（recovery 系统装入）。这是 AppBuilder 与
    BuildCache._mix_app_sources 的单一事实源——确保 recoveryctl 这样的"只用
    在 recovery 内"的 deb 也能进入构建集合。

    禁用 recovery（``recovery.enabled is False`` 或缺省）时不读 recovery 列表。
    """
    rootfs_cfg = config.get("rootfs") or {}
    rootfs_pkgs = list(rootfs_cfg.get("custom_packages") or [])
    if rootfs_cfg.get("image_format", "ext4") == "ubi":
        # flange-rootfs-grow 只会调用 growpart/resize2fs，属于 GPT/ext4 首启
        # 扩容逻辑；UBI volume 由 ubinize 与 UBI 层管理，安装该 app 既无效又会
        # 在 SPI NAND 系统上误操作不存在的块设备分区。
        rootfs_pkgs = [package for package in rootfs_pkgs if package != "flange-rootfs-grow"]
    seen: set[str] = set(rootfs_pkgs)
    merged: list[str] = list(rootfs_pkgs)

    recovery_cfg = config.get("recovery") or {}
    if recovery_cfg.get("enabled", False):
        for pkg in recovery_cfg.get("custom_packages") or []:
            if pkg not in seen:
                seen.add(pkg)
                merged.append(pkg)

    return sorted(merged)


def _resolve_path(raw: str, project_root: Path) -> str:
    """把可能含 ``~`` / 相对路径的字符串解析为绝对路径字符串。

    相对路径的锚点是 ``project_root`` ——与 ``sources.*.local_path`` 一致。
    返回字符串而非 ``Path``，便于 JSON 序列化与下游比较。
    """
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path(project_root) / p).resolve()
    else:
        p = p.resolve()
    return str(p)


def validate_app_source_entry(name: str, entry: Any) -> None:
    """只验证来源契约，不把路径归一化或访问源码。"""
    try:
        APP_SOURCE.check(entry, f"external_apps.{name}")
    except SchemaError as exc:
        raise AppSourceConfigError(str(exc)) from exc
    has_local = "local_path" in entry
    has_git = "git" in entry

    if has_local and has_git:
        raise AppSourceConfigError(
            f"external_apps[{name!r}] 不允许同时声明 local_path 和 git，请二选一"
        )
    if not has_local and not has_git:
        raise AppSourceConfigError(f"external_apps[{name!r}] 必须声明 local_path 或 git 之一")

    if has_local and set(entry) != {"local_path"}:
        raise AppSourceConfigError(
            f"external_apps.{name}.local_path 与远端 revision 字段互斥，请删除远端字段"
        )
    if "commit" in entry and "tag" in entry:
        raise AppSourceConfigError(
            f"external_apps.{name} 的 commit 与 tag 互斥，请选择一个固定 revision"
        )


def _validate_and_normalize_entry(
    name: str,
    entry: Any,
    project_root: Path,
) -> dict:
    """校验并归一化 ``external_apps[<name>]`` 条目，返回新 dict。

    规则：
      - 必须是 dict
      - ``local_path`` 与 ``git`` 互斥：同时存在 → 错；二者都不存在 → 错
      - ``local_path`` 存在：解析为绝对路径字符串并存回
      - ``git`` 存在：字段原样透传（由 ``SourceManager`` 消费）
    """
    if not isinstance(entry, dict):
        raise AppSourceConfigError(
            f"external_apps[{name!r}] 必须是字典，实际为 {type(entry).__name__}"
        )

    validate_app_source_entry(name, entry)
    has_local = "local_path" in entry
    normalized = copy.deepcopy(entry)

    if has_local:
        raw = entry["local_path"]
        if not isinstance(raw, str) or not raw.strip():
            raise AppSourceConfigError(f"external_apps[{name!r}].local_path 必须是非空字符串")
        normalized["local_path"] = _resolve_path(raw, project_root)

    return normalized


def normalize_app_sources(config: dict, project_root: Path) -> dict:
    """对 FINAL_CONFIG 就地返回一个处理过 App 来源字段的副本。

    输入不被修改。返回的 dict 中：
      - ``external_apps``: 每条被校验；``local_path`` 字段已解析为绝对路径
      - ``external_app_dirs``: 存在且合法即解析为绝对路径字符串列表；
        不存在时写入空列表，方便下游统一处理

    若配置中两者都未声明，仍会把 ``external_app_dirs`` 补为 ``[]``，
    这样下游无须关心"键是否存在"的情况分支。
    """
    try:
        if "external_apps" in config:
            Map(APP_SOURCE).check(config["external_apps"], "external_apps")
        if "external_app_dirs" in config:
            STRINGS.check(config["external_app_dirs"], "external_app_dirs")
    except SchemaError as exc:
        raise AppSourceConfigError(str(exc)) from exc
    result = copy.deepcopy(config)

    # external_apps：仅做校验和 local_path 归一化
    raw_apps = result.get("external_apps")
    if raw_apps is not None:
        if not isinstance(raw_apps, dict):
            raise AppSourceConfigError(
                f"external_apps 必须是字典，实际为 {type(raw_apps).__name__}"
            )
        normalized_apps: dict[str, dict] = {}
        for name, entry in raw_apps.items():
            if not isinstance(name, str) or not name.strip():
                raise AppSourceConfigError(f"external_apps 的键必须是非空字符串，实际为 {name!r}")
            normalized_apps[name] = _validate_and_normalize_entry(
                name,
                entry,
                project_root,
            )
        result["external_apps"] = normalized_apps

    # external_app_dirs：规范化为绝对路径字符串列表
    raw_dirs = result.get("external_app_dirs", [])
    if not isinstance(raw_dirs, list):
        raise AppSourceConfigError(
            f"external_app_dirs 必须是列表，实际为 {type(raw_dirs).__name__}"
        )
    normalized_dirs: list[str] = []
    for i, raw in enumerate(raw_dirs):
        if not isinstance(raw, str) or not raw.strip():
            raise AppSourceConfigError(f"external_app_dirs[{i}] 必须是非空字符串")
        normalized_dirs.append(_resolve_path(raw, project_root))
    result["external_app_dirs"] = normalized_dirs

    return result
