"""App 脚手架生成器 — 根据 type × build-system 组合生成 App 工程目录。

支持的组合矩阵：
  type \\ build-system | none | cmake | meson | make | swift | amp
  exec               |  Y   |   Y   |   Y   |   Y  |   Y   |  -
  service            |  Y   |   Y   |   Y   |   Y  |   Y   |  -
  lib                |  -   |   Y   |   Y   |   Y  |   -   |  -
  test               |  Y   |   -   |   -   |   -  |   -   |  -
  amp                |  -   |   -   |   -   |   -  |   -   |  Y

amp 类型 = 协处理器固件工程（裸机 HAL / RT-Thread 之上的用户应用），其 src/
被 amp 组件 stage 进 SDK 应用槽位、打进 amp.img；不打 deb、不进 rootfs。
amp+scons 可通过 embedded_swift=True 额外生成 SwiftPM static library 骨架。
"""

from __future__ import annotations

import shutil
import string
from pathlib import Path
from typing import Optional

import yaml

from builder.app_spec import APP_VERSION_PATTERN, SUPPORTED_APP_ARCHITECTURES

# 模板目录（与本文件同级的 templates/ 子目录）
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# ---------------------------------------------------------------------------
# 合法组合表：(type, build_system) -> True
# ---------------------------------------------------------------------------

_VALID_COMBINATIONS: set[tuple[str, str]] = {
    # exec
    ("exec", "none"),
    ("exec", "cmake"),
    ("exec", "meson"),
    ("exec", "make"),
    ("exec", "swift"),
    # service
    ("service", "none"),
    ("service", "cmake"),
    ("service", "meson"),
    ("service", "make"),
    ("service", "swift"),
    # lib（不支持 none / swift）
    ("lib", "cmake"),
    ("lib", "meson"),
    ("lib", "make"),
    # test（仅 none）
    ("test", "none"),
    # amp（协处理器固件）：amp=hal（CMake 引用 HAL SDK），scons=rt-thread
    # （叠到 RT-Thread BSP 模板的轻量 overlay）
    ("amp", "amp"),
    ("amp", "scons"),
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
        parent_dir: Optional[Path] = None,
        version: str = "0.1.0",
        description: str = "",
        embedded_swift: bool = False,
        show_registration_hint: bool = True,
        arch: str = "aarch64",
    ) -> Path:
        """生成 App 工程目录。

        参数：
            name:         App 名称，用作目录名与模板变量 $name
            app_type:     App 类型（exec / service / lib / test）
            build_system: 构建系统（none / cmake / meson / make / swift）
            target_dir:   完整目标目录（含 <name> 自身）；
                          None 时退回 parent_dir 或默认位置
            parent_dir:   父目录语义 —— 实际目标为 <parent_dir>/<name>/；
                          与 target_dir 互斥（同时指定将报错）
            version:      版本字符串，默认 0.1.0
            description:  描述字符串，默认空
            embedded_swift: amp+scons 专用；生成 SwiftPM static library 骨架
            show_registration_hint: 是否输出仓库外 registry 注册提示
            arch: 用户态架构，由 CLI 默认取当前工作区 target

        返回：
            已创建的 App 目录路径（Path）

        抛出：
            ScaffoldError: 参数无效、模板目录缺失或目标已存在
        """
        # 1. 参数校验
        self._validate(name, app_type, build_system, version)
        if arch not in SUPPORTED_APP_ARCHITECTURES:
            raise ScaffoldError(f"未知用户态架构：{arch}")
        if embedded_swift and (app_type, build_system) != ("amp", "scons"):
            raise ScaffoldError("embedded_swift 仅支持 type=amp 且 build_system=scons")
        if target_dir is not None and parent_dir is not None:
            raise ScaffoldError("target_dir 与 parent_dir 不能同时指定，请二选一")

        # 2. 确定目标目录
        if target_dir is not None:
            dest = Path(target_dir)
        elif parent_dir is not None:
            dest = Path(parent_dir) / name
        else:
            dest = self._root / "components" / "app" / name

        if dest.exists():
            raise ScaffoldError(f"目标目录已存在：{dest}")

        # 3. 构建模板变量映射
        variables = self._make_variables(
            name, app_type, build_system, version, description, embedded_swift
        )
        variables["arch"] = arch

        # 4. 渲染并写入文件
        try:
            dest.mkdir(parents=True, exist_ok=False)
            self._render_app_yaml(dest, variables)
            self._render_type_templates(
                dest, app_type, build_system, variables, embedded_swift=embedded_swift
            )
        except Exception:
            # 出错时清理已创建目录，保证原子性
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise

        print(f"脚手架已生成：{dest}（type={app_type}, build={build_system}）")

        # 5. 当 App 位于默认 components/app/ 之外时，输出注册指引
        hint = self._registration_hint(dest, name) if show_registration_hint else None
        if hint:
            print(hint)

        return dest

    def _registration_hint(self, dest: Path, name: str) -> Optional[str]:
        """当 dest 不在 <project_root>/components/app/ 下时，生成注册指引字符串。

        返回 None 表示无需提示（默认路径）；否则返回一段可直接打印的多行文本，
        同时给出 ``external_apps`` 与 ``external_app_dirs`` 两种示例片段。
        """
        import os as _os

        # 用 realpath 比较：在 macOS 上 /var 是 /private/var 的符号链接，
        # .resolve() 在路径不存在的中间段行为不稳，realpath 能更一致地展平前缀。
        # 拼 os.sep 避免 "/a/apps" 被误匹配到 "/a/app" 下。
        default_prefix = _os.path.realpath(str(self._root / "components" / "app")) + _os.sep
        abs_dest_str = _os.path.realpath(str(dest))
        if abs_dest_str.startswith(default_prefix):
            return None

        parent_str = _os.path.dirname(abs_dest_str)
        lines = [
            "",
            "[注册指引] App 位于默认 components/app/ 之外，flange 默认扫描不到。",
            "请在 board / platform config 的 BOARD / PLATFORM / SOC 字典中追加"
            "以下任一片段（择一即可）：",
            "",
            "  # 方式 A：external_apps 显式注册单个 App",
            '  "external_apps": {',
            f'      "{name}": {{"local_path": "{abs_dest_str}"}},',
            "  },",
            "",
            "  # 方式 B：external_app_dirs 把整个父目录加入搜索路径",
            '  "external_app_dirs": [',
            f'      "{parent_str}",',
            "  ],",
            "",
            "详见 docs/app-architecture.md。",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(
        name: str,
        app_type: str,
        build_system: str,
        version: str,
    ) -> None:
        """校验参数合法性。"""
        if not name or not name.strip():
            raise ScaffoldError("name 不能为空")
        # 名称只允许字母、数字、连字符、下划线
        import re

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ScaffoldError(
                f"name 包含非法字符：'{name}'，仅允许字母、数字、'-'、'_'，且必须以字母或数字开头"
            )
        if not isinstance(version, str) or not APP_VERSION_PATTERN.fullmatch(version):
            raise ScaffoldError("version 包含非法字符")

        if (app_type, build_system) not in _VALID_COMBINATIONS:
            valid_systems = sorted(bs for (at, bs) in _VALID_COMBINATIONS if at == app_type)
            if not valid_systems:
                raise ScaffoldError(f"不支持的 App 类型：'{app_type}'")
            raise ScaffoldError(
                f"类型 '{app_type}' 不支持构建系统 '{build_system}'，允许值：{valid_systems}"
            )

    @staticmethod
    def _make_variables(
        name: str,
        app_type: str,
        build_system: str,
        version: str,
        description: str,
        embedded_swift: bool = False,
    ) -> dict[str, str]:
        """构造模板变量字典。"""
        # 将 name 中的连字符替换为下划线作为 C 标识符
        name_ident = name.replace("-", "_")
        return {
            "name": name,
            "name_upper": name_ident.upper(),
            "name_ident": name_ident,
            "version": version,
            "description": description or f"{name} App",
            "type": app_type,
            "build_system": build_system,
            "embedded_swift": "true" if embedded_swift else "false",
        }

    def _render_app_yaml(self, dest: Path, variables: dict[str, str]) -> None:
        """渲染通用 app.yaml 模板并写入目标目录。"""
        tpl_path = _TEMPLATES_DIR / "app.yaml.tpl"
        if not tpl_path.exists():
            raise ScaffoldError(f"模板文件不存在：{tpl_path}")
        out_path = dest / "app.yaml"
        yaml_variables = variables.copy()
        for key in ("name", "version", "description", "type", "build_system"):
            yaml_variables[key] = yaml.safe_dump(
                variables[key], allow_unicode=True, default_style='"'
            ).strip()
        self._render_file(tpl_path, out_path, yaml_variables)
        if variables.get("embedded_swift") == "true":
            content = out_path.read_text(encoding="utf-8")
            content += (
                "  swift:\n"
                "    enabled: true\n"
                "    package_path: .\n"
                "    product: AmpLogic\n"
                "    c_header: include/swift_bridge.h\n"
                "    target_triple: armv7-none-none-eabi\n"
                "    extra_flags: []\n"
            )
            out_path.write_text(content, encoding="utf-8")

    def _render_type_templates(
        self,
        dest: Path,
        app_type: str,
        build_system: str,
        variables: dict[str, str],
        *,
        embedded_swift: bool = False,
    ) -> None:
        """渲染类型专属模板目录下的所有文件。

        模板目录结构：builder/templates/<type>/<build_system>/
        service 类型还会额外渲染 systemd/ 和 conf/ 两个共享子目录。
        """
        type_bs_dir = _TEMPLATES_DIR / app_type / build_system

        if type_bs_dir.exists():
            self._render_dir(type_bs_dir, dest, variables)
        if embedded_swift:
            swift_dir = _TEMPLATES_DIR / app_type / f"{build_system}-swift"
            if not swift_dir.exists():
                raise ScaffoldError(f"模板目录不存在：{swift_dir}")
            self._render_dir(swift_dir, dest, variables)
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


class PackageScaffold:
    """生成一个可直接走 vendor App 流水线的最小 Package。"""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._root = Path(project_root or Path(__file__).parent.parent)

    def create(
        self,
        name: str,
        *,
        parent_dir: Path,
        app_type: str = "exec",
        build_system: str = "cmake",
        version: str = "0.1.0",
        description: str = "",
        arch: str = "aarch64",
    ) -> Path:
        """在 ``parent_dir/name`` 创建 Package 与内嵌 vendor App。"""
        import re

        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ScaffoldError("Package 名称必须是 kebab-case 小写字母、数字和连字符")

        dest = Path(parent_dir).expanduser().resolve() / name
        if dest.exists():
            raise ScaffoldError(f"目标目录已存在：{dest}")

        dest.mkdir(parents=True)
        try:
            AppScaffold(self._root).create(
                name,
                app_type,
                build_system,
                target_dir=dest / "app",
                version=version,
                description=description,
                show_registration_hint=False,
                arch=arch,
            )
            package = (
                '"""Package 清单。"""\n\n'
                "PACKAGE = {\n"
                f'    "name": {name!r},\n'
                f'    "description": {(description or f"{name} Package")!r},\n'
                '    "components": [\n'
                '        {"type": "vendor", "name": '
                f'{name!r}, "dir": "app"}},\n'
                "    ],\n"
                "}\n"
            )
            (dest / "package.py").write_text(package, encoding="utf-8")
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise

        print(f"Package 脚手架已生成：{dest}")
        return dest
