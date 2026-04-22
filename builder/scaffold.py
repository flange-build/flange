"""App 脚手架生成器 — 根据 type × build-system 组合生成 App 工程目录。

支持的组合矩阵：
  type \\ build-system | none | cmake | meson | make | swift
  exec               |  Y   |   Y   |   Y   |   Y  |   Y
  service            |  Y   |   Y   |   Y   |   Y  |   Y
  lib                |  -   |   Y   |   Y   |   Y  |   -
  test               |  Y   |   -   |   -   |   -  |   -
"""

from __future__ import annotations

import shutil
import string
from pathlib import Path
from typing import Optional

# 模板目录（与本文件同级的 templates/ 子目录）
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# ---------------------------------------------------------------------------
# 合法组合表：(type, build_system) -> True
# ---------------------------------------------------------------------------

_VALID_COMBINATIONS: set[tuple[str, str]] = {
    # exec
    ("exec",    "none"),
    ("exec",    "cmake"),
    ("exec",    "meson"),
    ("exec",    "make"),
    ("exec",    "swift"),
    # service
    ("service", "none"),
    ("service", "cmake"),
    ("service", "meson"),
    ("service", "make"),
    ("service", "swift"),
    # lib（不支持 none / swift）
    ("lib",     "cmake"),
    ("lib",     "meson"),
    ("lib",     "make"),
    # test（仅 none）
    ("test",    "none"),
}


class ScaffoldError(ValueError):
    """脚手架生成失败时抛出。"""


class AppScaffold:
    """App 工程脚手架生成器。

    用法示例::

        scaffold = AppScaffold()
        path = scaffold.create("my-app", "exec", "cmake")
        print(path)  # /path/to/components/app/my-app/
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        # 项目根目录：默认取本文件所在包的父目录
        if project_root is None:
            self._root = Path(__file__).parent.parent
        else:
            self._root = Path(project_root)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        app_type: str,
        build_system: str,
        target_dir: Optional[Path] = None,
        *,
        version: str = "0.1.0",
        description: str = "",
    ) -> Path:
        """生成 App 工程目录。

        参数：
            name:         App 名称，用作目录名与模板变量 $name
            app_type:     App 类型（exec / service / lib / test）
            build_system: 构建系统（none / cmake / meson / make / swift）
            target_dir:   目标父目录；None 时默认为 <project_root>/components/app/<name>/
            version:      版本字符串，默认 0.1.0
            description:  描述字符串，默认空

        返回：
            已创建的 App 目录路径（Path）

        抛出：
            ScaffoldError: 参数无效或模板目录缺失
        """
        # 1. 参数校验
        self._validate(name, app_type, build_system)

        # 2. 确定目标目录
        if target_dir is None:
            dest = self._root / "components" / "app" / name
        else:
            dest = Path(target_dir)

        if dest.exists():
            raise ScaffoldError(f"目标目录已存在：{dest}")

        # 3. 构建模板变量映射
        variables = self._make_variables(name, app_type, build_system, version, description)

        # 4. 渲染并写入文件
        try:
            dest.mkdir(parents=True, exist_ok=False)
            self._render_app_yaml(dest, variables)
            self._render_type_templates(dest, app_type, build_system, variables)
        except Exception:
            # 出错时清理已创建目录，保证原子性
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise

        print(f"脚手架已生成：{dest}（type={app_type}, build={build_system}）")
        return dest

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(name: str, app_type: str, build_system: str) -> None:
        """校验参数合法性。"""
        if not name or not name.strip():
            raise ScaffoldError("name 不能为空")
        # 名称只允许字母、数字、连字符、下划线
        import re
        if not re.match(r'^[A-Za-z0-9_-]+$', name):
            raise ScaffoldError(f"name 包含非法字符：'{name}'，仅允许字母、数字、'-'、'_'")

        if (app_type, build_system) not in _VALID_COMBINATIONS:
            valid_systems = sorted(
                bs for (at, bs) in _VALID_COMBINATIONS if at == app_type
            )
            if not valid_systems:
                raise ScaffoldError(f"不支持的 App 类型：'{app_type}'")
            raise ScaffoldError(
                f"类型 '{app_type}' 不支持构建系统 '{build_system}'，"
                f"允许值：{valid_systems}"
            )

    @staticmethod
    def _make_variables(
        name: str,
        app_type: str,
        build_system: str,
        version: str,
        description: str,
    ) -> dict[str, str]:
        """构造模板变量字典。"""
        # 将 name 中的连字符替换为下划线作为 C 标识符
        name_ident = name.replace("-", "_")
        return {
            "name":         name,
            "name_upper":   name_ident.upper(),
            "name_ident":   name_ident,
            "version":      version,
            "description":  description or f"{name} App",
            "type":         app_type,
            "build_system": build_system,
        }

    def _render_app_yaml(self, dest: Path, variables: dict[str, str]) -> None:
        """渲染通用 app.yaml 模板并写入目标目录。"""
        tpl_path = _TEMPLATES_DIR / "app.yaml.tpl"
        if not tpl_path.exists():
            raise ScaffoldError(f"模板文件不存在：{tpl_path}")
        self._render_file(tpl_path, dest / "app.yaml", variables)

    def _render_type_templates(
        self,
        dest: Path,
        app_type: str,
        build_system: str,
        variables: dict[str, str],
    ) -> None:
        """渲染类型专属模板目录下的所有文件。

        模板目录结构：builder/templates/<type>/<build_system>/
        service 类型还会额外渲染 systemd/ 和 conf/ 两个共享子目录。
        """
        type_bs_dir = _TEMPLATES_DIR / app_type / build_system

        if type_bs_dir.exists():
            self._render_dir(type_bs_dir, dest, variables)
        # service 类型附加 systemd/ 和 conf/ 共享模板
        if app_type == "service":
            for shared in ("systemd", "conf"):
                shared_dir = _TEMPLATES_DIR / app_type / shared
                if shared_dir.exists():
                    self._render_dir(shared_dir, dest / shared, variables)

    def _render_dir(
        self,
        src_dir: Path,
        dest_dir: Path,
        variables: dict[str, str],
    ) -> None:
        """递归渲染 src_dir 下的所有 .tpl 文件到 dest_dir，保持相对路径结构。

        文件名中的 ${name} 占位符也会被替换（用于 lib 头文件/源文件命名）。
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        for tpl_path in sorted(src_dir.rglob("*.tpl")):
            # 计算相对路径，并将文件名中的 ${name} 替换
            rel = tpl_path.relative_to(src_dir)
            rendered_name = self._substitute_path(str(rel), variables)
            # 去掉 .tpl 后缀
            if rendered_name.endswith(".tpl"):
                rendered_name = rendered_name[:-4]
            out_path = dest_dir / rendered_name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            self._render_file(tpl_path, out_path, variables)

    @staticmethod
    def _substitute_path(path_str: str, variables: dict[str, str]) -> str:
        """对路径字符串执行模板变量替换（仅用于路径，不抛出 KeyError）。"""
        try:
            return string.Template(path_str).substitute(variables)
        except (KeyError, ValueError):
            # 路径中出现未知变量时原样保留
            return string.Template(path_str).safe_substitute(variables)

    @staticmethod
    def _render_file(
        tpl_path: Path,
        out_path: Path,
        variables: dict[str, str],
    ) -> None:
        """读取模板文件，替换变量后写入目标路径。"""
        raw = tpl_path.read_text(encoding="utf-8")
        rendered = string.Template(raw).safe_substitute(variables)
        out_path.write_text(rendered, encoding="utf-8")
