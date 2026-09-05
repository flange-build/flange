"""DEB 格式适配：默认拆包、完整包导入以及 dpkg 设备命令。"""

from __future__ import annotations

import stat
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from builder.app_spec import AppSpec
from builder.deb import DebBuilder, _map_arch
from builder.digest import hash_path
from builder.file_tree import copy_entry
from builder.packaging.base import InstalledFile, PackageBackend
from builder.packaging.model import PackageOutput


class DebPackageBackend(PackageBackend):
    """DEB 输出保持原包字节，不执行外部包中的维护脚本。"""

    format = "deb"

    def validate_output(self, output: PackageOutput) -> None:
        if not output.file.endswith(".deb"):
            raise ValueError(f"DEB 输出必须使用 .deb 后缀：{output.file!r}")

    def plan(self, spec: AppSpec, arch: str) -> tuple[PackageOutput, ...]:
        if spec.app.type in {"staging", "amp"}:
            return ()
        if spec.packaging.outputs:
            return tuple(spec.packaging.outputs)
        name = f"lib{spec.app.name}" if spec.app.type == "lib" else spec.app.name
        names = [(name, "runtime")]
        if spec.app.type == "lib":
            names.append(
                (name + (spec.lib.dev_suffix if spec.lib else "-dev"), "development")
            )
        return tuple(
            PackageOutput(
                f"{name}_{spec.app.version}_{self.architecture(arch)}.deb", role
            )
            for name, role in names
        )

    @staticmethod
    def _is_development(entry: InstalledFile) -> bool:
        source, path, _ = entry
        name = Path(path).name
        return (
            path.startswith("/usr/include/")
            or name.endswith((".a", ".pc", ".cmake"))
            or "/cmake/" in path
            or (source.is_symlink() and name.endswith(".so"))
        )

    def build(
        self, spec: AppSpec, arch: str, files: Sequence[InstalledFile], output: Path
    ) -> None:
        if spec.app.type == "staging":
            return
        if spec.app.type != "lib":
            DebBuilder().build_from_spec(spec, arch, list(files), output)
            return
        name = f"lib{spec.app.name}"
        runtime_spec = replace(spec, app=replace(spec.app, name=name))
        suffix = spec.lib.dev_suffix if spec.lib else "-dev"
        development_spec = replace(
            spec,
            app=replace(spec.app, name=name + suffix),
            depends=[f"{name} (= {spec.app.version})", *spec.depends],
        )
        runtime, development = [], []
        for entry in files:
            (development if self._is_development(entry) else runtime).append(entry)
        DebBuilder().build_from_spec(runtime_spec, arch, runtime, output)
        DebBuilder().build_from_spec(development_spec, arch, development, output)

    @staticmethod
    def _merge(source: Path, install: Path) -> set[str]:
        paths = set()
        directories = []
        for entry in sorted(source.rglob("*")):
            relative = entry.relative_to(source)
            destination = install / relative
            for parent in relative.parents:
                if (install / parent).is_symlink():
                    raise ValueError(f"包安装路径穿过符号链接：/{relative}")
            if entry.is_dir() and not entry.is_symlink():
                if destination.exists() and not destination.is_dir():
                    raise ValueError(f"包安装路径冲突：/{relative}")
                if destination.is_symlink():
                    raise ValueError(f"包安装路径冲突：/{relative}")
                destination.mkdir(parents=True, exist_ok=True)
                directories.append((entry, destination))
                continue
            if not entry.is_symlink() and not entry.is_file():
                raise ValueError(f"包包含不支持的安装节点：/{relative}")
            if destination.exists() or destination.is_symlink():
                if hash_path(entry) != hash_path(destination):
                    raise ValueError(f"包安装路径冲突：/{relative}")
            else:
                copy_entry(entry, destination)
            paths.add("/" + relative.as_posix())
        for entry, destination in reversed(directories):
            destination.chmod(stat.S_IMODE(entry.stat().st_mode))
        return paths

    def import_outputs(
        self,
        outputs: Sequence[PackageOutput],
        arch: str,
        output: Path,
        install: Path,
        runner,
    ) -> set[str]:
        runtime_paths = set()
        for item in outputs:
            package = output / item.file
            if package.is_symlink() or not package.is_file():
                raise ValueError(f"缺少声明的包产物或包不是普通文件：{package}")
            inspected = runner.run(
                ["dpkg-deb", "--field", str(package), "Architecture"],
                capture=True,
            )
            actual = inspected.stdout.strip()
            if actual not in {self.architecture(arch), "all"}:
                raise ValueError(
                    f"DEB 架构不匹配：{item.file} 是 {actual}，目标为 {self.architecture(arch)}"
                )
            # 位于资源工作目录内，容器和宿主能以相同绝对路径访问。
            with tempfile.TemporaryDirectory(
                prefix="unpack-", dir=install.parent
            ) as temporary:
                runner.run(["dpkg-deb", "--extract", str(package), temporary])
                paths = self._merge(Path(temporary), install)
                if item.role == "runtime":
                    runtime_paths.update(paths)
        return runtime_paths

    def architecture(self, arch: str) -> str:
        return _map_arch(arch)

    def architecture_command(self) -> list[str]:
        return ["dpkg", "--print-architecture"]

    def install_command(self, paths: Sequence[str]) -> list[str]:
        return ["dpkg", "-i", *paths]

    def recipe_paths(self) -> tuple[Path, ...]:
        return (Path(__file__).resolve().parents[1] / "deb.py",)
