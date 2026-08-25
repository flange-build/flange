"""受限且确定性的 Jsonnet 配置求值边界。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import _jsonnet

from builder.paths import components_dir


class JsonnetConfigError(ValueError):
    """Jsonnet 配置无法安全求值。"""


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _expand_package_sets(config: dict) -> None:
    rootfs = config.get("rootfs") or {}
    selected = rootfs.get("package_set") or []
    selected = [selected] if isinstance(selected, str) else selected
    package_sets = rootfs.get("package_sets") or {}
    packages: list[str] = []
    for name in selected:
        if name not in package_sets:
            raise JsonnetConfigError(
                f"rootfs.package_set 引用了未知集合: {name}")
        packages.extend(package_sets[name])
    rootfs["packages"] = _unique(packages + (rootfs.get("packages") or []))


class ResolvedConfig(dict):
    """保持 plain dict 行为，同时携带不进入 JSON 的求值元数据。"""

    jsonnet_dependencies: tuple[Path, ...] = ()
    jsonnet_hash: str = ""


@dataclass(frozen=True)
class JsonnetResult:
    """一次 Jsonnet 求值的配置、依赖与规范化文本。"""

    config: dict[str, Any]
    dependencies: tuple[Path, ...]
    canonical_json: str


class JsonnetEvaluator:
    """只允许读取项目 components 配置树的 Jsonnet evaluator。"""

    _ALLOWED_SUFFIXES = {".jsonnet", ".libsonnet"}

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.config_root = components_dir(self.project_root).resolve()
        self._dependencies: set[Path] = set()

    def evaluate_file(
        self,
        path: Path,
        *,
        ext_vars: dict[str, str] | None = None,
    ) -> JsonnetResult:
        entry = self._resolve_config_path(Path(path), label="配置入口")
        self._dependencies = {entry}
        try:
            rendered = _jsonnet.evaluate_file(
                str(entry),
                ext_vars=ext_vars or {},
                import_callback=self._import_callback,
            )
        except RuntimeError as exc:
            raise JsonnetConfigError(str(exc)) from exc
        return self._result(rendered)

    def evaluate_snippet(
        self,
        filename: Path,
        snippet: str,
        *,
        ext_vars: dict[str, str] | None = None,
        dependencies: tuple[Path, ...] = (),
    ) -> JsonnetResult:
        source_name = Path(filename)
        if not source_name.is_absolute():
            source_name = self.config_root / source_name
        source_name = source_name.resolve()
        self._dependencies = {
            self._resolve_config_path(path, label="配置依赖")
            for path in dependencies
        }
        try:
            rendered = _jsonnet.evaluate_snippet(
                str(source_name),
                snippet,
                ext_vars=ext_vars or {},
                import_callback=self._import_callback,
            )
        except RuntimeError as exc:
            raise JsonnetConfigError(str(exc)) from exc
        return self._result(rendered)

    def content_hash(
        self,
        result: JsonnetResult,
        *,
        board: str,
        product: str,
        variant: str,
    ) -> str:
        """计算只受实际求值输入影响的配置哈希。"""
        digest = hashlib.sha256()
        for value in (board, product, variant, result.canonical_json):
            digest.update(value.encode())
            digest.update(b"\0")
        for path in result.dependencies:
            digest.update(str(path.relative_to(self.project_root)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _result(self, rendered: str) -> JsonnetResult:
        try:
            config = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise JsonnetConfigError(f"Jsonnet 未生成合法 JSON: {exc}") from exc
        if not isinstance(config, dict):
            raise JsonnetConfigError("Jsonnet 配置顶层必须求值为 object")
        canonical = json.dumps(
            config, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return JsonnetResult(
            config=config,
            dependencies=tuple(sorted(self._dependencies)),
            canonical_json=canonical,
        )

    def _import_callback(self, base: str, relative: str) -> tuple[str, bytes]:
        rel_path = PurePosixPath(relative)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise RuntimeError(f"Jsonnet import 越过允许根目录: {relative}")
        rel = Path(*rel_path.parts)
        local_path = Path(base) / rel
        path = local_path if local_path.exists() else self.config_root / rel
        path = self._resolve_config_path(path, label=f"Jsonnet import {relative}")
        self._dependencies.add(path)
        return str(path), path.read_bytes()

    def _resolve_config_path(self, path: Path, *, label: str) -> Path:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise JsonnetConfigError(f"{label}不存在: {path}") from exc
        try:
            resolved.relative_to(self.config_root)
        except ValueError as exc:
            raise JsonnetConfigError(
                f"{label}越过允许根目录 {self.config_root}: {path}"
            ) from exc
        if resolved.suffix not in self._ALLOWED_SUFFIXES:
            raise JsonnetConfigError(
                f"{label}扩展名必须是 .jsonnet 或 .libsonnet: {path}"
            )
        return resolved


class JsonnetConfigLoader:
    """发现身份并组合 rootfs/platform/SoC/board 四层 overlay。"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.config_root = components_dir(self.project_root).resolve()
        self.evaluator = JsonnetEvaluator(self.project_root)

    def board_identity(self, board: str) -> dict[str, Any]:
        if Path(board).name != board:
            raise JsonnetConfigError(f"非法 board 名称: {board}")
        board_path = self.config_root / "board" / board / "config.jsonnet"
        identity = self._identity_projection(
            board_path, ("board", "platform", "soc", "products", "variants")
        )
        if identity.get("board") != board:
            raise JsonnetConfigError(
                f"board 身份与目录不一致: {identity.get('board')!r} != {board!r}"
            )
        identity.setdefault("products", ["default"])
        identity.setdefault("variants", ["release"])
        return identity

    def evaluate_board(
        self,
        board: str,
        product: str,
        variant: str,
    ) -> ResolvedConfig:
        identity = self.board_identity(board)
        if product not in identity["products"]:
            raise JsonnetConfigError(f"board {board} 不支持 product: {product}")
        if variant not in identity["variants"]:
            raise JsonnetConfigError(f"board {board} 不支持 variant: {variant}")

        platform = identity["platform"]
        soc = identity["soc"]
        rootfs_path = self.config_root / "rootfs" / "config.jsonnet"
        overlay_path = (
            self.config_root / "device-tree-overlay" / "config.jsonnet"
        )
        platform_path = self.config_root / "platform" / platform / "config.jsonnet"
        soc_path = self.config_root / "platform" / platform / soc / "config.jsonnet"
        board_path = self.config_root / "board" / board / "config.jsonnet"

        platform_identity = self._identity_projection(platform_path, ("platform",))
        if platform_identity.get("platform") != platform:
            raise JsonnetConfigError(
                f"platform 身份与目录不一致: "
                f"{platform_identity.get('platform')!r} != {platform!r}"
            )
        soc_identity = self._identity_projection(soc_path, ("platform", "soc"))
        if soc_identity.get("platform") != platform or soc_identity.get("soc") != soc:
            raise JsonnetConfigError(
                f"SoC 身份与路径不一致: {soc_identity!r}，期望 "
                f"platform={platform!r}, soc={soc!r}"
            )

        imports = [rootfs_path]
        if overlay_path.is_file():
            imports.append(overlay_path)
        baseline_count = len(imports)
        imports.extend([platform_path, soc_path, board_path])
        platform_result = self._evaluate_layers(
            imports[:baseline_count + 1], product=product, variant=variant
        )
        soc_result = self._evaluate_layers(
            imports[:baseline_count + 2], product=product, variant=variant
        )
        self._audit_soc_layer(platform_result.config, soc_result.config)
        result = self._evaluate_layers(imports, product=product, variant=variant)
        resolved = ResolvedConfig(result.config)
        _expand_package_sets(resolved)
        from builder.packages import expand_hardware_packages
        expand_hardware_packages(resolved, project_root=self.project_root)
        from builder.config.apps import normalize_app_sources
        normalized = normalize_app_sources(resolved, self.project_root)
        resolved = ResolvedConfig(normalized)
        resolved.jsonnet_dependencies = result.dependencies
        canonical_json = json.dumps(
            resolved, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        normalized_result = JsonnetResult(
            config=resolved,
            dependencies=result.dependencies,
            canonical_json=canonical_json,
        )
        resolved.jsonnet_hash = self.evaluator.content_hash(
            normalized_result, board=board, product=product, variant=variant
        )
        from builder.config.validate import validate_config
        validate_config(resolved)
        return resolved

    def _evaluate_layers(
        self,
        paths: list[Path],
        *,
        product: str,
        variant: str,
    ) -> JsonnetResult:
        import_exprs = [
            f'(import {json.dumps(self._import_name(path))})'
            for path in paths
        ]
        snippet = " + ".join([
            *import_exprs,
            "{ product: std.extVar('product'), variant: std.extVar('variant') }",
        ])
        return self.evaluator.evaluate_snippet(
            "config/__compose__.jsonnet",
            snippet,
            ext_vars={"product": product, "variant": variant},
        )

    def _audit_soc_layer(self, before: dict, after: dict) -> None:
        changed = self._changed_paths(before, after)
        forbidden = (
            ("display",),
            ("storage",),
            ("kernel", "device_tree", "name"),
            ("rootfs", "package_set"),
            ("rootfs", "packages"),
            ("rootfs", "custom_packages"),
        )
        for path in sorted(changed):
            if any(path[:len(prefix)] == prefix for prefix in forbidden):
                raise JsonnetConfigError(
                    "SoC overlay 不得声明板级事实或产品策略: "
                    + ".".join(path)
                )
        if ("amp", "enabled") in changed:
            enabled = (after.get("amp") or {}).get("enabled")
            if enabled:
                raise JsonnetConfigError("SoC overlay 不得启用 amp.enabled")

    @classmethod
    def _changed_paths(
        cls,
        before: Any,
        after: Any,
        prefix: tuple[str, ...] = (),
    ) -> set[tuple[str, ...]]:
        if isinstance(before, dict) and isinstance(after, dict):
            changed: set[tuple[str, ...]] = set()
            for key in set(before) | set(after):
                child_prefix = (*prefix, key)
                if key not in before:
                    changed.update(cls._leaf_paths(after[key], child_prefix))
                    continue
                if key not in after:
                    changed.update(cls._leaf_paths(before[key], child_prefix))
                    continue
                changed.update(cls._changed_paths(
                    before[key], after[key], child_prefix
                ))
            return changed
        return set() if before == after else {prefix}

    @classmethod
    def _leaf_paths(
        cls,
        value: Any,
        prefix: tuple[str, ...],
    ) -> set[tuple[str, ...]]:
        if isinstance(value, dict) and value:
            paths: set[tuple[str, ...]] = set()
            for key, child in value.items():
                paths.update(cls._leaf_paths(child, (*prefix, key)))
            return paths
        return {prefix}

    def _identity_projection(
        self,
        path: Path,
        fields: tuple[str, ...],
    ) -> dict[str, Any]:
        import_name = json.dumps(self._import_name(path))
        projected = ", ".join(
            f"{field}: if std.objectHas(config, {json.dumps(field)}) "
            f"then config[{json.dumps(field)}] else null"
            for field in fields
        )
        result = self.evaluator.evaluate_snippet(
            "config/__identity__.jsonnet",
            f"local config = import {import_name}; {{{projected}}}",
            ext_vars={"product": "", "variant": ""},
        )
        return {
            key: value for key, value in result.config.items() if value is not None
        }

    def _import_name(self, path: Path) -> str:
        resolved = self.evaluator._resolve_config_path(path, label="配置层")
        return resolved.relative_to(self.config_root).as_posix()
