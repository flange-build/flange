"""Package 显式构建动作的隔离执行与产物清单。"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from builder.app_build import AppBuilder
from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.digest import digest_value
from builder.environment import environment_identity
from builder.graph import InputSpec, TaskPlan
from builder.locking import FileLock
from builder.workspace import WorkspaceContext


class PackageBuilder:
    """自定义 Package 以专属 artifacts 目录声明全部交付内容。"""

    def __init__(self, context: WorkspaceContext, docker):
        self.context = context
        self.docker = docker

    def plan(self, directory: Path, package: dict) -> TaskPlan:
        key = f"{package['name']}-{digest_value(str(directory.resolve()))[:12]}"
        output = self.context.target_dir / "packages" / key
        return TaskPlan(
            f"package:{key}",
            "package-action-v1",
            (
                InputSpec.value("package", package),
                InputSpec.value("target", asdict(self.context.target)),
                InputSpec.value("environment", environment_identity()),
                InputSpec.tree(
                    "source",
                    directory,
                    exclude_names=(".git",),
                    exclude_paths=(self.context.build_root,)
                    if self.context.build_root.is_relative_to(directory)
                    else (),
                ),
                InputSpec.file("recipe", Path(__file__)),
                InputSpec.file("publish_recipe", Path(__file__).with_name("app_build.py")),
            ),
            (
                ArtifactSpec("artifacts", output / "artifacts", "tree", allow_empty=False),
                ArtifactSpec("resource", output / "resource.json", allow_empty=False),
            ),
        )

    def build(
        self, directory: Path, package: dict, *, force=False, no_build=False
    ) -> ArtifactManifest:
        plan = self.plan(directory, package)
        output = plan.outputs[0].path.parent
        with FileLock(self.context.build_root / "locks" / f"{self.context.target.key}.lock"):
            previous = ArtifactManifest.load(output / "manifest.json")
            if no_build:
                if previous is None or not previous.validate():
                    raise ValueError("Package 尚无完整的构建产物，请先执行 package build")
                return previous
            fingerprint = plan.fingerprint()
            if (
                not force
                and previous
                and previous.input_digest == fingerprint.digest
                and previous.validate()
            ):
                return previous
            work = (
                self.context.build_root
                / "work"
                / self.context.target.key
                / "packages"
                / plan.task_id.split(":", 1)[1]
            )
            source, publish = work / "source", work / "publish"
            for path in (source, publish):
                if path.exists():
                    shutil.rmtree(path)

            def excluded(parent, names):
                return [
                    name
                    for name in names
                    if name == ".git" or (Path(parent) / name).resolve() == self.context.build_root
                ]

            shutil.copytree(plan.path("source"), source, symlinks=True, ignore=excluded)
            artifacts = publish / "artifacts"
            artifacts.mkdir(parents=True)
            model = plan.value("package")
            self.docker.run(
                model["actions"]["build"],
                cwd=str(source),
                env={
                    "FLANGE_SOURCE_DIR": str(source),
                    "FLANGE_PROJECT_ROOT": str(self.context.tool_root),
                    "FLANGE_TARGET_DIR": str(artifacts),
                    "FLANGE_PACKAGE_OUTPUT_DIR": str(artifacts),
                    "FLANGE_BUILD_ROOT": str(self.context.build_root),
                    "FLANGE_BOARD": self.context.target.board,
                    "FLANGE_PRODUCT": self.context.target.product,
                    "FLANGE_VARIANT": self.context.target.variant,
                },
                extra_mounts=[source],
            )
            (publish / "resource.json").write_text(
                json.dumps(
                    {
                        "name": model["name"],
                        "source_dir": str(directory),
                        "target": plan.value("target"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            if plan.fingerprint().digest != fingerprint.digest:
                raise ValueError("Package 构建期间输入发生变化，拒绝发布")
            AppBuilder._publish(publish, output, plan, fingerprint, {})
            result = ArtifactManifest.load(output / "manifest.json")
            assert result is not None
            return result
