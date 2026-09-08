"""平台依赖与输出扩展必须贯穿实际计划、发布及缓存。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.component_plan import output_contract
from builder.engine import BuildEngine
from builder.graph import DEPENDENCY_GRAPH
from builder.platforms import spec
from builder.workspace import Target, WorkspaceContext


def test_sparse_publish_without_gnu_cp_preserves_holes(tmp_path, monkeypatch):
    import subprocess
    from builder.engine import _copy_sparse

    source, target = tmp_path / "source.img", tmp_path / "target.img"
    with source.open("wb") as stream:
        stream.write(b"EFI")
        stream.seek(8 * 1024 * 1024)
        stream.write(b"end")
        stream.truncate(12 * 1024 * 1024)
    source.chmod(0o640)

    def unsupported(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("builder.engine.subprocess.run", unsupported)
    _copy_sparse(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode == source.stat().st_mode
    # 有些宿主临时目录本身不支持稀疏分配；仅在支持的文件系统比较物理占用。
    if source.stat().st_blocks * 512 < source.stat().st_size // 2:
        assert target.stat().st_blocks * 512 < target.stat().st_size // 2


def context_for(tmp_path):
    return WorkspaceContext(
        tmp_path, tmp_path, tmp_path / ".build", Target("test", "default", "debug")
    )


def test_extra_dependency_controls_order_and_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        EXTRA_DEPENDENCIES={"boot": ["rootfs"]}
    ))
    context = context_for(tmp_path)
    config = {"platform": "rockchip", "board": "test", "product": "default", "variant": "debug"}
    config["kernel"] = {"device_tree": {"directory": "", "name": "test"}}
    config["architecture"] = {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64"}
    engine = BuildEngine(config, context=context, output=MagicMock())
    plans = engine.plan("boot")
    names = [plan.task_id for plan in plans]
    assert names.index("rootfs") < names.index("boot")
    boot = plans[-1]
    assert "rootfs" in boot.dependencies
    dependencies = {name: "original" for name in boot.dependencies}
    previous = boot.fingerprint(dependencies)
    dependencies["rootfs"] = "changed-initrd"
    assert previous.digest != boot.fingerprint(dependencies).digest
    assert "rootfs" not in DEPENDENCY_GRAPH["boot"]


@pytest.mark.parametrize("extra, message", [
    ({"unknown": []}, "未知组件"),
    ({"boot": ["unknown"]}, "未知组件"),
    ({"boot": "rootfs"}, "字符串列表"),
    ({"boot": ["rootfs", "rootfs"]}, "重复依赖"),
    ({"kernel": ["boot"]}, "依赖循环"),
])
def test_invalid_platform_graph_rejected(monkeypatch, extra, message):
    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        EXTRA_DEPENDENCIES=extra
    ))
    with pytest.raises(ValueError, match=message):
        spec.dependency_graph({})


def test_default_graph_is_independent_copy(monkeypatch):
    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace())
    graph = spec.dependency_graph({})
    assert graph == DEPENDENCY_GRAPH
    graph["boot"].append("rootfs")
    assert "rootfs" not in DEPENDENCY_GRAPH["boot"]


def test_engine_executes_added_dependency_and_reuses_cache(tmp_path, monkeypatch):
    def outputs(component, root, config):
        return [ArtifactSpec(component, root / f"{component}.bin", allow_empty=False)]

    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        EXTRA_DEPENDENCIES={"kernel": ["bootloader"]}, required_artifacts=outputs
    ))
    context = context_for(tmp_path)
    config = {"platform": "rockchip", "board": "test", "product": "default", "variant": "debug"}
    engine = BuildEngine(config, context=context, output=MagicMock())
    engine.source.prepare_cache_inputs = lambda *args: None
    engine._get_artifact_names = lambda: {}
    executed = []

    class Recipe:
        def execute(self, plan):
            executed.append(plan.task_id)
            work = context.build_root / "work" / plan.task_id
            work.mkdir(parents=True, exist_ok=True)
            artifact = work / f"{plan.task_id}.bin"
            artifact.write_bytes(plan.task_id.encode())
            return {plan.task_id: artifact}

    engine._get_builder = lambda component: Recipe()
    engine.build("kernel")
    assert executed == ["bootloader", "kernel"]
    assert "bootloader" in engine.cache.load("kernel").dependencies
    engine.build("kernel")
    assert executed == ["bootloader", "kernel"]


def test_platform_outputs_require_loader_and_detect_corruption(tmp_path, monkeypatch):
    def outputs(component, root, config):
        return [ArtifactSpec("firmware", root / "firmware", kind="tree", allow_empty=False),
                ArtifactSpec("loader", root / "firmware/loader.elf", allow_empty=False)]

    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        required_artifacts=outputs
    ))
    context = context_for(tmp_path)
    contract = output_contract("bootloader", {}, context)
    firmware = context.target_dir / "bootloader/firmware"
    firmware.mkdir(parents=True)
    (firmware / "unrelated").write_bytes(b"firmware")
    with pytest.raises(ValueError, match="缺少必需产物 loader"):
        ArtifactManifest.capture("bootloader", "input", contract)
    (firmware / "loader.elf").write_bytes(b"loader")
    manifest = ArtifactManifest.capture("bootloader", "input", contract)
    assert manifest.validate()
    (firmware / "loader.elf").write_bytes(b"tampered")
    assert not manifest.validate()


@pytest.mark.parametrize("mode", ["name", "path", "escape", "empty"])
def test_invalid_platform_outputs_rejected(tmp_path, monkeypatch, mode):
    def outputs(component, root, config):
        if mode == "empty":
            return []
        if mode == "escape":
            return [ArtifactSpec("a", root / "../outside")]
        return [ArtifactSpec("a", root / "a"), ArtifactSpec(
            "a" if mode == "name" else "b", root / ("a" if mode == "path" else "b")
        )]

    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        required_artifacts=outputs
    ))
    with pytest.raises(ValueError):
        output_contract("bootloader", {}, context_for(tmp_path))


def test_image_override_keeps_global_flash_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(spec, "_optional_platform", lambda _: SimpleNamespace(
        required_artifacts=lambda component, root, config: [
            ArtifactSpec("bundle", root / "flash-bundle", kind="tree", allow_empty=False)
        ]
    ))
    context = context_for(tmp_path)
    outputs = output_contract("image", {}, context)
    assert [item.name for item in outputs] == ["bundle", "flash-config"]
    assert outputs[-1].path == context.target_dir / "flash-config.json"


def test_platform_internal_import_error_is_not_hidden(monkeypatch):
    def broken(platform):
        raise ModuleNotFoundError("内部依赖缺失", name="missing_dependency")

    monkeypatch.setattr(spec, "load", broken)
    with pytest.raises(ModuleNotFoundError, match="内部依赖缺失"):
        spec.dependency_graph({"platform": "test"})
