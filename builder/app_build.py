"""按完整依赖计划构建 App，并原子发布可验证的资源产物。"""

from __future__ import annotations

import json
import shutil
import stat
import sys
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path
from typing import Sequence

from builder.app_model import AppBuildReport, AppBuildResult
from builder.app_resolver import AppResolver, AppResource
from builder.app_spec import AppSpec
from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.build_dependencies import UbuntuBuildDependencies
from builder.config.apps import gather_custom_packages
from builder.config.canonical import userspace_arch
from builder.digest import digest_value, hash_path
from builder.environment import environment_identity
from builder.file_tree import copy_entry, copy_tree
from builder.graph import InputSpec, TaskPlan
from builder.locking import FileLock
from builder.packaging import get_backend
from builder.packaging.model import PackageArtifact, PackageOutput
from builder.toolchain import Toolchain
from builder.workspace import WorkspaceContext


def validate_elf_architecture(files: Sequence[tuple[Path, str, int]], arch: str) -> None:
    """直接读取 ELF 头，拒绝把宿主二进制错误标记为目标架构包。"""
    expected = {
        "aarch64": (2, 183),
        "armhf": (1, 40),
        "x86_64": (2, 62),
        "i386": (1, 3),
        "riscv64": (2, 243),
    }[arch]
    for source, destination, _ in files:
        if source.is_symlink():
            continue
        # 固件和 /usr/share 里的 DSP payload 可能是另一处理器的 ELF。
        # 只验证 Linux 用户态执行目录与动态库搜索目录。
        if destination.startswith("/lib/firmware/") or not destination.startswith(
            ("/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/", "/lib/", "/usr/lib/", "/usr/lib64/")
        ):
            continue
        with source.open("rb") as stream:
            header = stream.read(20)
        if header[:4] != b"\x7fELF":
            continue
        if len(header) != 20 or header[5] not in {1, 2}:
            raise ValueError(f"无效 ELF 文件：{destination}")
        machine = int.from_bytes(header[18:20], "little" if header[5] == 1 else "big")
        if (header[4], machine) != expected:
            raise ValueError(
                f"ELF 架构与 {arch} 不符：{destination}（class={header[4]}, machine={machine}）"
            )


class AppBuilder:
    """单 App 与系统 App 共用的闭包计划、执行和产物发布服务。"""

    output = None

    def __init__(self, docker, source, config: dict, *, context: WorkspaceContext) -> None:
        actual_target = {key: config.get(key) for key in ("board", "product", "variant")}
        if actual_target != asdict(context.target):
            raise ValueError(
                f"App config target 与 WorkspaceContext 不匹配：{actual_target} / {asdict(context.target)}"
            )
        self.context = context
        self._docker = docker
        self._source = source
        self._config = config
        self._arch = userspace_arch(config)
        self.toolchain = Toolchain.for_arch(self._arch)
        self.resolver = AppResolver(context, source, config)
        self.build_dependencies = UbuntuBuildDependencies(docker, context.build_root)

    def _status(self, message: str) -> None:
        if self.output:
            self.output.status(message)
        else:
            print(message, file=sys.stderr)

    @staticmethod
    def _expanded(resources: Sequence[AppResource]) -> tuple[AppResource, ...]:
        completed: dict[str, AppResource] = {}
        for resource in resources:
            wanted = set(resource.dependency_ids)
            for key in resource.dependency_ids:
                wanted.update(completed[key].dependency_ids)
            completed[resource.resource_id] = replace(
                resource, dependency_ids=tuple(key for key in completed if key in wanted)
            )
        return tuple(completed.values())

    def plan(self, requests: Sequence[str | Path]) -> tuple[TaskPlan, ...]:
        resolver = AppResolver(self.context, self._source, self._config, read_only=True)
        _, resources = resolver.closure(requests)
        return tuple(self._plan(resource) for resource in self._expanded(resources))

    def build_one(self, request: str | Path, force: bool = False) -> AppBuildReport:
        return self.build([request], force=force)

    def build_all(self, force: bool = False) -> AppBuildReport:
        report = self.build(gather_custom_packages(self._config), force=force)
        report.write(self.context.target_dir / "apps/build-report.json")
        return report

    def report_path(self, roots: Sequence[str]) -> Path:
        key = digest_value(list(roots))[:20]
        return self.context.target_dir / "apps/reports" / f"{key}.json"

    def existing(self, requests: Sequence[str | Path]) -> AppBuildReport:
        roots, _ = AppResolver(self.context, self._source, self._config, read_only=True).closure(
            requests
        )
        report = AppBuildReport.load(self.report_path(roots))
        if report.target != asdict(self.context.target):
            raise ValueError("App 报告与当前工作区目标不匹配")
        return report

    def build(self, requests: Sequence[str | Path], force: bool = False) -> AppBuildReport:
        with FileLock(self.context.build_root / "locks" / f"{self.context.target.key}.lock"):
            return self._build(requests, force)

    def _build(self, requests: Sequence[str | Path], force: bool) -> AppBuildReport:
        roots, resources = self.resolver.closure(requests)
        for resource in resources:
            if self._arch not in resource.spec.app.arch:
                raise ValueError(f"App {resource.spec.app.name!r} 未声明支持架构 {self._arch}")
            if resource.spec.app.type == "amp":
                raise ValueError("AMP App 必须通过 amp 系统组件构建，不能把无产物当成成功")
        results: dict[str, AppBuildResult] = {}
        for resource in self._expanded(resources):
            dependencies = [results[key] for key in resource.dependency_ids]
            results[resource.resource_id] = self._build_resource(resource, dependencies, force)
        report = AppBuildReport(
            roots, tuple(results.values()), asdict(self.context.target), self._arch
        )
        report.write(self.report_path(roots))
        return report

    def _source_root(self, source: Path) -> Path:
        for candidate in (source, *source.parents):
            if (candidate / "package.py").is_file():
                return candidate
            if candidate == self.context.tool_root:
                return source
            if (candidate / ".git").exists():
                return candidate
        return source

    def _package_outputs(self, spec: AppSpec) -> tuple[PackageOutput, ...]:
        return get_backend(spec.packaging.format).plan(spec, self._arch)

    def _plan(self, resource: AppResource) -> TaskPlan:
        directory = self.context.target_dir / "apps" / resource.resource_id
        outputs = [
            ArtifactSpec("install", directory / "install", "tree"),
            ArtifactSpec("resource", directory / "resource.json", allow_empty=False),
        ]
        if self.context.target.variant == "debug":
            outputs.append(ArtifactSpec("debug-source", directory / "debug-source", "tree"))
        outputs.extend(
            ArtifactSpec(item.file, directory / "artifacts" / item.file, allow_empty=False)
            for item in self._package_outputs(resource.spec)
        )
        logic = Path(__file__).parent
        inputs = [
            InputSpec.value("spec", resource.spec),
            InputSpec.value("target", asdict(self.context.target)),
            InputSpec.value("toolchain", self.toolchain),
            InputSpec.value("environment", environment_identity()),
            InputSpec.tree(
                "source",
                self._source_root(resource.source_dir),
                exclude_names=(".git",),
                exclude_paths=(self.context.build_root,)
                if self.context.build_root.is_relative_to(self._source_root(resource.source_dir))
                else (),
            ),
            InputSpec.value(
                "app_subpath",
                str(resource.source_dir.relative_to(self._source_root(resource.source_dir))),
            ),
        ]
        for name in (
            "app.py",
            "app_build.py",
            "app_resolver.py",
            "app_spec.py",
            "app_model.py",
            "build_dependencies.py",
            "file_tree.py",
            "toolchain.py",
        ):
            inputs.append(InputSpec.file(f"recipe:{name}", logic / name))
        inputs.append(InputSpec.tree(
            "recipe:packaging", logic / "packaging", exclude_names=("__pycache__",),
        ))
        for path in get_backend(resource.spec.packaging.format).recipe_paths():
            inputs.append(InputSpec.file(f"recipe:{path.name}", path))
        docker_root = self.context.tool_root / "docker"
        if docker_root.is_dir():
            inputs.append(InputSpec.tree("container_recipe", docker_root))
        compose = self.context.tool_root / "docker-compose.yml"
        if compose.is_file():
            inputs.append(InputSpec.file("compose", compose))
        return TaskPlan(
            f"app:{resource.resource_id}",
            "app-build-v1",
            tuple(inputs),
            tuple(outputs),
            tuple(f"app:{key}" for key in resource.dependency_ids),
        )

    def _build_resource(
        self, resource: AppResource, dependencies: list[AppBuildResult], force: bool
    ) -> AppBuildResult:
        work = (
            self.context.build_root
            / "work"
            / self.context.target.key
            / "apps"
            / resource.resource_id
        )
        output = self.context.target_dir / "apps" / resource.resource_id
        work.mkdir(parents=True, exist_ok=True)
        with FileLock(work / "build.lock"):
            if self.output:
                self.output.feed_line(f"App 资源：{resource.resource_id}")
            plan = self._plan(resource)
            identities = {f"app:{item.resource_id}": item.identity for item in dependencies}
            fingerprint = plan.fingerprint(identities)
            previous = ArtifactManifest.load(output / "manifest.json")
            if (
                not force
                and previous
                and previous.input_digest == fingerprint.digest
                and previous.validate()
            ):
                self._status(f"App {resource.spec.app.name}：产物完整，复用缓存")
                return self._result(output, previous, reused=True)
            progress = (
                self.output.step(f"构建 App {resource.spec.app.name}")
                if self.output else nullcontext()
            )
            with progress:
                publish = work / "publish"
                if publish.exists():
                    shutil.rmtree(publish)
                (publish / "artifacts").mkdir(parents=True)
                install = publish / "install"
                install.mkdir()
                dependency_root = work / "sysroot"
                self._compose_dependencies(dependencies, dependency_root)
                source = self._prepare_source(plan, work)
                if self.context.target.variant == "debug":
                    self._snapshot_source(plan.path("source"), publish / "debug-source")
                spec: AppSpec = plan.value("spec")
                toolchain: Toolchain = plan.value("toolchain")
                target = plan.value("target")
                source_dir = source / plan.value("app_subpath")
                env = {
                    **toolchain.environment(dependency_root),
                    "FLANGE_PROJECT_ROOT": str(self.context.tool_root),
                    "FLANGE_SOURCE_DIR": str(source_dir),
                    "FLANGE_BUILD_ROOT": str(self.context.build_root),
                    "FLANGE_APP_WORK_DIR": str(work),
                    "FLANGE_APP_OUTPUT_DIR": str(publish / "artifacts"),
                    "FLANGE_TARGET_DIR": str(self.context.target_dir),
                    "FLANGE_TARGET_ARCH": self._arch,
                    "FLANGE_SYSROOT": str(dependency_root),
                    "FLANGE_DEPENDENCY_DIRS": json.dumps(
                        {item.name: str(item.install_dir) for item in dependencies}
                    ),
                    "DESTDIR": str(install),
                }
                self.build_dependencies.install(spec.build.apt_packages, self._arch)
                commands, install_command = toolchain.commands(
                    spec,
                    source=source_dir,
                    build=work / "build",
                    install=install,
                    dependency_root=dependency_root,
                    variant=target["variant"],
                )
                if "build" in spec.actions:
                    commands, install_command = [spec.actions["build"]], None
                for command in commands:
                    self._docker.run(command, cwd=str(source_dir), env=env)
                if install_command:
                    self._docker.run(install_command, cwd=str(source_dir), env=env)
                if spec.build.staging:
                    staged = work / spec.build.staging
                    if not staged.is_dir() or not any(staged.iterdir()):
                        raise ValueError(f"缺少 App staging 产物：{staged}")
                    copy_tree(staged, install)
                backend = get_backend(spec.packaging.format)
                package_outputs = backend.plan(spec, self._arch)
                runtime_paths = None
                if spec.packaging.outputs:
                    runtime_paths = backend.import_outputs(
                        package_outputs, self._arch, publish / "artifacts", install, self._docker,
                    )
                    # 完整外部包是安装内容的来源，不用源目录约定覆盖包中的文件。
                    files = self._installed_files(install)
                else:
                    files = self._collect(source_dir, spec, install)
                validate_elf_architecture(files, self._arch)
                # 原生安装与约定文件组成单一发布树，依赖与调试读取同一份内容。
                for source_file, destination, mode in files:
                    target_file = install / destination.lstrip("/")
                    if source_file != target_file:
                        copy_entry(source_file, target_file)
                        if not target_file.is_symlink():
                            target_file.chmod(mode)
                files = self._installed_files(install)
                executable, unit = self._runtime(
                    spec, files if runtime_paths is None else [
                        entry for entry in files if entry[1] in runtime_paths
                    ],
                )
                if not spec.packaging.outputs:
                    backend.build(spec, self._arch, files, publish / "artifacts")
                packages = tuple(
                    PackageArtifact(output / "artifacts" / item.file, backend.format, item.role)
                    for item in package_outputs
                )
                metadata = {
                    "resource_id": resource.resource_id,
                    "name": spec.app.name,
                    "source_dir": str(resource.source_dir),
                    "dependency_ids": resource.dependency_ids,
                    "packages": [package.metadata() for package in packages],
                    "executable": executable,
                    "service_unit": unit,
                    "app_type": spec.app.type,
                    "target": target,
                    "architecture": self._arch,
                    "compile_source_dir": str(source),
                    "debug_source_dir": str(output / "debug-source")
                    if target["variant"] == "debug"
                    else "",
                }
                (publish / "resource.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
                )
                # 用户编辑或构建脚本更改了输入时，不能把先前输入指纹标记为成功。
                if plan.fingerprint(identities).digest != fingerprint.digest:
                    raise ValueError(f"构建期间 App 输入变化，拒绝发布：{resource.spec.app.name}")
                self._publish(publish, output, plan, fingerprint, identities)
                manifest = ArtifactManifest.load(output / "manifest.json")
                assert manifest is not None
                return self._result(output, manifest)

    def _prepare_source(self, plan: TaskPlan, work: Path) -> Path:
        original = plan.path("source")
        spec = plan.value("spec")
        if spec.build.system not in {"make", "custom"}:
            return original
        snapshot = work / "source"
        for path in (snapshot, work / "build"):
            if path.exists():
                shutil.rmtree(path)
        if spec.build.staging and (work / spec.build.staging).exists():
            shutil.rmtree(work / spec.build.staging)

        self._snapshot_source(original, snapshot)
        return snapshot

    def _snapshot_source(self, original: Path, snapshot: Path) -> None:
        def excluded(directory: str, names: list[str]) -> list[str]:
            return [
                name
                for name in names
                if name == ".git" or (Path(directory) / name).resolve() == self.context.build_root
            ]

        copy_tree(original, snapshot, ignore=excluded)

    @staticmethod
    def _compose_dependencies(dependencies: Sequence[AppBuildResult], target: Path) -> None:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for dependency in dependencies:
            if not dependency.validate():
                raise ValueError(f"依赖产物已变化：{dependency.name}")
            for source in sorted(dependency.install_dir.rglob("*")):
                destination = target / source.relative_to(dependency.install_dir)
                if source.is_dir() and not source.is_symlink():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if destination.exists() or destination.is_symlink():
                    if hash_path(source) != hash_path(destination):
                        raise ValueError(f"依赖安装路径冲突：{destination.relative_to(target)}")
                else:
                    copy_entry(source, destination)
        # .pc 的 /usr 前缀属于目标安装布局；只重定位依赖副本，保留系统 APT
        # 的 pkg-config 搜索根，不能把局部依赖树冒充完整系统 sysroot。
        for metadata in target.rglob("*.pc"):
            if metadata.is_symlink():
                continue
            content = metadata.read_text()
            content = content.replace("=/usr", f"={target}/usr")
            metadata.write_text(content)

    @staticmethod
    def _installed_files(directory: Path) -> list[tuple[Path, str, int]]:
        return [
            (path, "/" + path.relative_to(directory).as_posix(), stat.S_IMODE(path.lstat().st_mode))
            for path in sorted(directory.rglob("*"))
            if path.is_symlink() or path.is_file()
        ]

    def _collect(self, source: Path, spec: AppSpec, install: Path) -> list[tuple[Path, str, int]]:
        from builder.app import collect_files

        files = {
            destination: (path, destination, mode)
            for path, destination, mode in collect_files(source, spec, self._arch)
        }
        files.update(
            {
                destination: (path, destination, mode)
                for path, destination, mode in self._installed_files(install)
            }
        )
        for relative, destination in spec.install.items():
            path = source / relative
            if not path.exists() and not path.is_symlink():
                raise ValueError(f"install 声明的源文件不存在：{path}")
            if destination.endswith("/"):
                destination += path.name
            from builder.app import _infer_mode

            files[destination] = (path, destination, _infer_mode(destination, relative))
        return list(files.values())

    @staticmethod
    def _runtime(spec: AppSpec, files: Sequence[tuple[Path, str, int]]) -> tuple[str, str]:
        installed = {destination: mode for _, destination, mode in files}
        if spec.app.type in {"exec", "test"}:
            runtime = getattr(spec, "runtime", None)
            executable = getattr(runtime, "executable", "") or f"/usr/bin/{spec.app.name}"
            if executable not in installed or not installed[executable] & 0o111:
                raise ValueError(f"App 运行入口未安装或不可执行：{executable}")
            return executable, ""
        if spec.app.type == "service":
            unit = (
                Path(spec.systemd.unit).name
                if spec.systemd and spec.systemd.unit
                else f"{spec.app.name}.service"
            )
            if not any(path.endswith(f"/systemd/system/{unit}") for path in installed):
                raise ValueError(f"App service unit 未安装：{unit}")
            return "", unit
        return "", ""

    @staticmethod
    def _publish(
        staging: Path, destination: Path, plan: TaskPlan, fingerprint, identities: dict
    ) -> None:
        # 发布前先使用临时路径验证所有声明，防止缺失产物破坏上一版。
        for output in plan.outputs:
            relative = output.path.relative_to(destination)
            temporary = replace(output, path=staging / relative)
            ArtifactManifest.capture(plan.task_id, fingerprint.digest, [temporary])
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = destination.with_name(f".{destination.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        try:
            staging.replace(destination)
            manifest = ArtifactManifest.capture(
                plan.task_id,
                fingerprint.digest,
                plan.outputs,
                input_segments=fingerprint.segments,
                dependencies=identities,
            )
            manifest.write(destination / "manifest.json")
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            if backup.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    @staticmethod
    def _result(
        directory: Path, manifest: ArtifactManifest, reused: bool = False
    ) -> AppBuildResult:
        metadata = json.loads((directory / "resource.json").read_text())
        return AppBuildResult(
            resource_id=metadata["resource_id"],
            name=metadata["name"],
            source_dir=Path(metadata["source_dir"]),
            dependency_ids=tuple(metadata["dependency_ids"]),
            manifest_path=directory / "manifest.json",
            manifest=manifest,
            packages=tuple(
                PackageArtifact(directory / "artifacts" / item["file"], item["format"], item["role"])
                for item in metadata["packages"]
            ),
            install_dir=directory / "install",
            executable=metadata["executable"],
            service_unit=metadata["service_unit"],
            app_type=metadata["app_type"],
            reused=reused,
            compile_source_dir=metadata["compile_source_dir"],
            debug_source_dir=metadata["debug_source_dir"],
        )
