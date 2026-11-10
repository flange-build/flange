"""Debian 用户态闭环：实际 App 构建、rootfs 安装、QEMU 运行与 ext4 验证。"""
import argparse
import json
import shutil
from pathlib import Path

from builder.app_build import AppBuilder
from builder.artifacts import ArtifactManifest
from builder.component_plan import create_component_plan
from builder.docker import DockerRunner, _is_inside_container
from builder.layers import stack_for
from builder.oot_mounts import workspace_mounts
from builder.source import SourceManager
from builder.workspace import load_workspace, resolve_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    context = load_workspace(args.workspace, target="layerdemo-minimal-release")
    config = resolve_config(context)
    runner = DockerRunner(context=context, config=config)
    if not _is_inside_container():
        from builder.digest import hash_path
        roots = [item.root for item in context.layer_stack.layers[1:]]
        def inputs():
            return {str(root): hash_path(root, exclude_names={".build", ".flange"}) for root in roots}
        before = inputs()
        runner.run(["python3", "-m", "docs.examples.layers.validate", str(context.workspace_root)],
                   cwd=str(context.tool_root), privileged=True,
                   extra_mounts=workspace_mounts(context, config))
        assert inputs() == before, "构建不得改写扩展层输入"
        print("扩展层输入未修改")
        return
    source = SourceManager(context=context)
    apps = AppBuilder(runner, source, config, context=context)
    report = apps.build_all()
    repeated = apps.build_all()
    assert all(item.reused for item in repeated.ordered), "第二次 App 构建必须复用"
    stack = stack_for(config, context)
    platform = stack.provider("platform", "layerdemo")
    builder = platform.create_builder("rootfs", runner, source)
    builder.context = context
    builder.app_report = report
    # 用户态证明无需内核模块；这是显式测试夹具，不代表已构建硬件 BSP。
    (context.target_dir / "kernel/modules").mkdir(parents=True, exist_ok=True)
    plan = create_component_plan("rootfs", config, context, source)
    outputs = builder.execute(plan)
    for spec in plan.outputs:
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(outputs[spec.name], spec.path)
    from builder.digest import hash_path, digest_value
    dependencies = {"app": report.identity,
        "kernel": hash_path(context.target_dir / "kernel/modules"),
        "device-tree-overlay": digest_value({"fixture": "无 DT overlay 的用户态验证"})}
    fingerprint = plan.fingerprint(dependencies)
    manifest = ArtifactManifest.capture(plan.task_id, fingerprint.digest, plan.outputs,
                                        input_segments=fingerprint.segments, dependencies=dependencies)
    manifest.write(context.target_dir / "rootfs/manifest.json")
    image = context.target_dir / "rootfs/rootfs.img"
    runner.run(["e2fsck", "-fn", str(image)])
    runner.run(["debugfs", "-R", "stat /usr/bin/layer-check", str(image)])
    evidence = {"environment": runner.environment_identity(), "userland": report.userland_identity,
                "app_report": report.identity, "all_apps_reused": True,
                "image": str(image), "rootfs_manifest": manifest.identity,
                "runtime": builder.runtime_output,
                "sdk_packages": Path("/opt/flange-sdk-metadata/packages.txt").read_text(),
                "scope": "Debian 用户态验证；未构建内核/bootloader，未执行实机刷写"}
    (context.build_root / "debian-evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
