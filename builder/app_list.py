"""``flange list apps`` 的数据收集与展示模块。

负责遍历 App 的三个来源层级，按查找优先级挑选"主来源"并记录同名 App 的
其它发现位置，供 CLI 渲染为行：

  <name>   <type>   <version>   <description>   [<source_label>]
       (also found in: <其它来源>)

若未指定配置（例如尚未 lunch），仅扫描本地 ``components/app/*``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class _Found:
    """一次发现：一个 (名称, 来源标签, 绝对路径) 元组，不含 App 元数据。"""
    name: str
    source_label: str
    path: Path


@dataclass
class AppEntry:
    """``list apps`` 的一行输出。"""
    name: str
    type: str
    version: str
    description: str
    source_label: str           # 主来源（即查找优先级命中的那一层）
    source_path: Path
    also_found_in: list[tuple[str, Path]] = field(default_factory=list)


def _load_app_meta(app_dir: Path) -> Optional[dict]:
    """加载 ``<app_dir>/app.yaml`` 并返回 ``app`` 段的 dict；失败时返回 None。"""
    yaml_path = app_dir / "app.yaml"
    if not yaml_path.is_file():
        return None
    try:
        import yaml  # 仅在需要时导入，便于纯单元测试 mock
    except ImportError:
        return None
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    app = data.get("app") if isinstance(data.get("app"), dict) else {}
    return app or None


def _scan_local(project_root: Path) -> list[_Found]:
    """扫描 ``<project_root>/components/app/*/app.yaml``，返回发现列表。"""
    base = project_root / "components" / "app"
    if not base.is_dir():
        return []
    found: list[_Found] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if not (child / "app.yaml").is_file():
            continue
        # name 以 app.yaml 的 app.name 为权威，回退到目录名
        meta = _load_app_meta(child)
        name = meta.get("name", child.name) if meta else child.name
        found.append(_Found(name=name, source_label="local", path=child))
    return found


def _scan_external_apps(config: dict) -> list[_Found]:
    """遍历 ``external_apps[*]``，按 local_path / git 标签区分来源。"""
    raw = config.get("external_apps", {}) or {}
    found: list[_Found] = []
    for name, entry in sorted(raw.items()):
        if not isinstance(entry, dict):
            continue
        if "local_path" in entry:
            found.append(_Found(
                name=name,
                source_label="external:local",
                path=Path(entry["local_path"]),
            ))
        elif "git" in entry:
            # git 分支：路径是克隆目标（若已克隆则存在，否则仅占位）；
            # 我们取一个占位 Path 便于展示，不强求其存在
            found.append(_Found(
                name=name,
                source_label="external:git",
                path=Path(f"(git){entry.get('git', '')}"),
            ))
    return found


def _scan_external_app_dirs(config: dict) -> list[_Found]:
    """顺序遍历每个搜索目录下的子目录，挑出含 ``app.yaml`` 的那些。"""
    dirs: list[str] = config.get("external_app_dirs", []) or []
    found: list[_Found] = []
    for d in dirs:
        d_path = Path(d)
        if not d_path.is_dir():
            continue
        for child in sorted(d_path.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            if not (child / "app.yaml").is_file():
                continue
            meta = _load_app_meta(child)
            name = meta.get("name", child.name) if meta else child.name
            found.append(_Found(
                name=name,
                source_label=f"dir:{d_path}",
                path=child,
            ))
    return found


def list_all(
    project_root: Path,
    config: Optional[dict] = None,
) -> list[AppEntry]:
    """收集全部 App，按主来源排序返回 ``AppEntry`` 列表。

    优先级：本地 > external_apps（显式注册）> external_app_dirs（搜索路径）。
    同名 App 保留主来源，其它出现位置进入 ``also_found_in``。

    参数：
        project_root: flange 项目根目录（含 ``components/`` 的那个目录）。
        config:       FINAL_CONFIG；``None`` 时仅扫描本地层。
    """
    groups: list[list[_Found]] = []
    groups.append(_scan_local(project_root))
    if config is not None:
        groups.append(_scan_external_apps(config))
        groups.append(_scan_external_app_dirs(config))

    # 把所有发现合并成 {name: [Found ...]}，list 中顺序即优先级（先入为主）
    by_name: dict[str, list[_Found]] = {}
    for group in groups:
        for f in group:
            by_name.setdefault(f.name, []).append(f)

    entries: list[AppEntry] = []
    for name in sorted(by_name.keys()):
        finds = by_name[name]
        primary = finds[0]
        others = finds[1:]

        meta = _load_app_meta(primary.path) or {}
        app_type = meta.get("type", "unknown")
        version = str(meta.get("version", ""))
        desc = str(meta.get("description", ""))

        entries.append(AppEntry(
            name=name,
            type=app_type,
            version=version,
            description=desc,
            source_label=primary.source_label,
            source_path=primary.path,
            also_found_in=[(o.source_label, o.path) for o in others],
        ))

    return entries


def format_lines(entries: list[AppEntry]) -> list[str]:
    """把 ``AppEntry`` 列表格式化为可直接 print 的字符串行。

    行格式：
      ``    <name:20s> <type:10s> <version:10s> <desc>  [<source>]``
    含 also_found_in 时追加一行：
      ``        (also found in: <label1>, <label2>)``
    """
    if not entries:
        return ["    （未找到任何 App）"]
    out: list[str] = []
    for e in entries:
        out.append(
            f"    {e.name:20s} {e.type:10s} {e.version:10s} "
            f"{e.description}  [{e.source_label}]"
        )
        if e.also_found_in:
            labels = ", ".join(f"{lbl}" for lbl, _ in e.also_found_in)
            out.append(f"        (also found in: {labels})")
    return out
