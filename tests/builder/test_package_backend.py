"""完整包导入与角色消费的边界测试；不运行设备命令或安装维护脚本。"""

import io
import json
import shutil
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from builder import deploy
from builder.app_model import AppBuildReport
from builder.app_spec import AppSpecError, load_spec
from builder.deb import DebBuilder
from builder.dev import report_data
from builder.packaging.deb import DebPackageBackend
from builder.packaging.model import PackageArtifact
from builder.presentation import render_resource
from builder.rootfs import RootfsBuilder
from tests.builder.app_support import app, builder
from tests.builder.test_deb import _read_ar_members
from tests.builder.test_deploy import FakeDevice


def control(package):
    archive = _read_ar_members(package)
    with tarfile.open(fileobj=io.BytesIO(archive["control.tar.gz"])) as stream:
        return stream.extractfile("./control").read().decode()


def payload(package):
    return tarfile.open(fileobj=io.BytesIO(_read_ar_members(package)["data.tar.gz"]))


def package_fixture(root, name, arch, entries):
    files = []
    for index, (destination, content, mode) in enumerate(entries):
        source = root / f"{name}-{index}"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        files.append((source, destination, mode))
    return DebBuilder().build_deb(
        name,
        "1.0.0",
        arch,
        {
            "control": f"Package: {name}\nVersion: 1.0.0\nArchitecture: {arch}\n"
            "Maintainer: tester <test@localhost>\nDescription: fixture\n",
            "postinst": "#!/bin/sh\n# 首次安装不启用服务\nexit 0\n",
        },
        files,
        root / "packages",
    )


@pytest.fixture
def external(tmp_path):
    runtime = package_fixture(
        tmp_path / "fixture",
        "provider",
        "arm64",
        [
            ("/usr/bin/provider", b"#!/bin/sh\nexit 0\n", 0o755),
            (
                "/lib/systemd/system/provider.service",
                b"[Service]\nExecStart=/usr/bin/provider\n",
                0o644,
            ),
        ],
    )
    development = package_fixture(
        tmp_path / "fixture",
        "provider-dev",
        "all",
        [
            ("/usr/include/provider/api.h", b"int provider(void);\n", 0o644),
            ("/usr/lib/cmake/provider/providerConfig.cmake", b"# SDK\n", 0o644),
        ],
    )
    source = app(
        tmp_path / "provider",
        kind="service",
        system="custom",
        build={"commands": [["produce"]]},
        packaging={
            "format": "deb",
            "outputs": [
                {"file": runtime.name, "role": "runtime"},
                {"file": development.name, "role": "development"},
            ],
        },
    )
    # unit 只存在于包中，源目录的约定文件不是外部交付内容。
    shutil.rmtree(source / "systemd")
    engine = builder(tmp_path, apps={"provider": source})

    def execute(argv, **options):
        if argv == ["produce"]:
            for package in (runtime, development):
                shutil.copy2(
                    package,
                    Path(options["env"]["FLANGE_APP_OUTPUT_DIR"]) / package.name,
                )
        elif argv[:2] == ["dpkg-deb", "--field"]:
            fields = dict(
                line.split(": ", 1) for line in control(Path(argv[2])).splitlines()
            )
            return subprocess.CompletedProcess(argv, 0, fields[argv[3]] + "\n", "")
        elif argv[:2] == ["dpkg-deb", "--extract"]:
            with payload(Path(argv[2])) as archive:
                archive.extractall(argv[3], filter="data")
        else:
            pytest.fail(f"未预期命令：{argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")

    engine._docker.run.side_effect = execute
    return engine, source, (runtime, development), execute


def test_external_service_imports_all_packages_and_deploys_runtime_only(external):
    engine, _, originals, _ = external
    report = engine.build_one("provider")
    result = report.root()
    assert [item.role for item in result.packages] == ["runtime", "development"]
    assert result.service_unit == "provider.service"
    assert (result.install_dir / "usr/include/provider/api.h").is_file()
    assert (
        result.install_dir / "usr/lib/cmake/provider/providerConfig.cmake"
    ).is_file()
    assert [item.path.read_bytes() for item in result.packages] == [
        p.read_bytes() for p in originals
    ]
    assert report.validate()
    assert AppBuildReport.load(engine.report_path(report.roots)).validate()
    assert engine.build_one("provider").root().reused
    device = FakeDevice()
    deploy.operate_report(engine.context, report, "deploy", transport=device)
    assert set(device.uploads.values()) == {result.runtime_packages[0].path}
    assert all("enable" not in call[1] for call in device.calls if call[0] == "shell")
    data = report_data(report)
    assert len(data["apps"][0]["packages"]) == 2
    text = "\n".join(render_resource("build", data))
    assert "运行包" in text and "开发包" in text
    assert all(item.path.name in text for item in result.packages)


def test_dependency_prefix_contains_development_package(external, tmp_path):
    engine, source, _, execute = external
    consumer = app(
        tmp_path / "consumer",
        system="custom",
        deps=[str(source)],
        build={"commands": [["consume"]]},
    )

    def run(argv, **options):
        if argv != ["consume"]:
            return execute(argv, **options)
        prefix = Path(options["env"]["FLANGE_SYSROOT"])
        assert (
            prefix / "usr/include/provider/api.h"
        ).read_text() == "int provider(void);\n"
        output = Path(options["env"]["DESTDIR"]) / "usr/bin/consumer"
        output.parent.mkdir(parents=True)
        output.write_text("#!/bin/sh\nexit 0\n")
        output.chmod(0o755)

    engine._docker.run.side_effect = run
    report = engine.build_one(consumer)
    assert [item.name for item in report.ordered] == ["provider", "consumer"]
    assert len(report.runtime_packages) == 2
    assert all(item.role == "runtime" for item in report.runtime_packages)


@pytest.mark.parametrize(
    "failure", ["missing", "architecture", "collision", "runtime", "elf"]
)
def test_import_failure_preserves_previous_publication(external, failure):
    engine, _, originals, execute = external
    previous = engine.build_one("provider").root()

    def run(argv, **options):
        result = execute(argv, **options)
        if argv == ["produce"] and failure == "missing":
            (Path(options["env"]["FLANGE_APP_OUTPUT_DIR"]) / originals[1].name).unlink()
        if argv[:2] == ["dpkg-deb", "--field"] and failure == "architecture":
            return subprocess.CompletedProcess(argv, 0, "amd64\n", "")
        if argv[:2] == ["dpkg-deb", "--extract"]:
            root = Path(argv[3])
            if failure == "collision" and "-dev_" in argv[2]:
                (root / "usr/bin").mkdir(parents=True)
                (root / "usr/bin/provider").write_text("conflict")
            if failure == "runtime" and "-dev_" not in argv[2]:
                (root / "lib/systemd/system/provider.service").unlink()
            if failure == "runtime" and "-dev_" in argv[2]:
                unit = root / "lib/systemd/system/provider.service"
                unit.parent.mkdir(parents=True)
                unit.write_text("[Service]\nExecStart=/usr/bin/provider\n")
            if failure == "elf" and "-dev_" not in argv[2]:
                header = bytearray(20)
                header[:6] = b"\x7fELF\x02\x01"
                header[18:20] = (62).to_bytes(2, "little")
                (root / "usr/bin/provider").write_bytes(header)
        return result

    engine._docker.run.side_effect = run
    with pytest.raises(ValueError):
        engine.build_one("provider", force=True)
    assert previous.validate()


def test_development_content_and_role_are_verified(external):
    engine, _, _, _ = external
    report = engine.build_one("provider")
    result = report.root()
    forged = replace(
        result,
        packages=(
            result.packages[0],
            replace(result.packages[1], role="runtime"),
        ),
    )
    assert not forged.validate()
    result.development_packages[0].path.write_text("tampered")
    assert not report.validate()
    assert not engine.build_one("provider").root().reused
    path = engine.report_path(report.roots)
    data = json.loads(path.read_text())
    data["ordered"][0]["packages"][1]["role"] = "runtime"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="校验失败"):
        AppBuildReport.load(path)


@pytest.mark.parametrize(
    "packaging",
    [
        {"format": "rpm"},
        {"format": "deb", "unknown": True},
        {"outputs": [{"file": "a.deb", "role": "dev"}]},
        {"outputs": [{"file": "../a.deb", "role": "runtime"}]},
        {"outputs": [{"file": "*.deb", "role": "runtime"}]},
        {"outputs": [{"file": "a.rpm", "role": "runtime"}]},
        {"outputs": [{"file": "a.deb"}]},
        {"outputs": [{"file": "a.deb", "role": "runtime"}] * 2},
        {"outputs": "a.deb"},
    ],
)
def test_invalid_package_contract_fails_before_build(tmp_path, packaging):
    source = app(tmp_path / "example", packaging=packaging)
    with pytest.raises(AppSpecError):
        load_spec(source)


def test_legacy_outputs_normalize_without_new_segment(tmp_path):
    source = app(
        tmp_path / "legacy",
        kind="vendor",
        system="custom",
        build={
            "commands": [["produce"]],
            "deb_outputs": ["first.deb", "second.deb"],
        },
    )
    spec = load_spec(source)
    assert spec.build.deb_outputs == ["first.deb", "second.deb"]
    assert [item.role for item in spec.packaging.outputs] == ["runtime", "runtime"]


def test_legacy_multiple_packages_are_imported_as_runtime(external):
    engine, source, originals, _ = external
    path = source / "app.yaml"
    value = yaml.safe_load(path.read_text())
    value.pop("packaging")
    value.pop("systemd")
    value["app"]["type"] = "vendor"
    value["build"]["deb_outputs"] = [item.name for item in originals]
    path.write_text(yaml.safe_dump(value))
    result = engine.build_one("provider").root()
    assert len(result.runtime_packages) == 2
    assert result.development_packages == ()
    assert (result.install_dir / "usr/include/provider/api.h").is_file()


@pytest.mark.parametrize(
    "sections",
    [
        {"install": {}},
        {"depends": []},
        {"conffiles": []},
        {"data_dirs": []},
        {"maintainer_scripts": {}},
        {"lib": {}},
        {"systemd": {"unit": "provider.service", "auto_start": True}},
        {"build": {"deb_outputs": ["provider.deb"]}},
    ],
)
def test_external_package_rejects_competing_delivery_settings(external, sections):
    engine, source, _, _ = external
    path = source / "app.yaml"
    value = yaml.safe_load(path.read_text())
    for name, section in sections.items():
        if name == "build":
            value["app"]["type"] = "vendor"
            value[name].update(section)
        else:
            value[name] = section
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(AppSpecError, match="完整外部包|不可混用"):
        engine.build_one("provider")
    engine._docker.run.assert_not_called()


def test_rootfs_installs_only_runtime_from_complete_report(external, tmp_path):
    engine, _, _, _ = external
    report = engine.build_one("provider")
    rootfs = RootfsBuilder(MagicMock(), MagicMock())
    rootfs.app_report = report
    with patch("builder.rootfs.ChrootContext") as chroot:
        rootfs._install_app_debs(
            tmp_path / "rootfs", {"rootfs": {"custom_packages": ["provider"]}}
        )
        installed = chroot.return_value.__enter__.return_value.run.call_args.args[0]
    assert installed == [
        "dpkg",
        "-i",
        "--force-confnew",
        "/tmp/flange-debs/" + report.root().runtime_packages[0].path.name,
    ]


def test_old_report_requires_rebuild(external):
    engine, _, _, _ = external
    report = engine.build_one("provider")
    path = engine.report_path(report.roots)
    data = json.loads(path.read_text())
    data["schema_version"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="重新运行 flange app build"):
        AppBuildReport.load(path)


def test_backend_recipe_tracks_code_but_ignores_python_bytecode(tmp_path):
    source = app(tmp_path / "example")
    engine = builder(tmp_path)
    recipe = next(
        item
        for item in engine.plan([source])[0].inputs
        if item.name == "recipe:packaging"
    )
    isolated = tmp_path / "recipe"
    isolated.mkdir()
    code = isolated / "deb.py"
    code.write_text("# 第一版后端\n")
    recipe = replace(recipe, location=isolated)
    original = recipe.digest()
    cache = isolated / "__pycache__"
    cache.mkdir()
    (cache / "deb.cpython-312.pyc").write_bytes(b"Docker bytecode")
    (cache / "deb.cpython-313.pyc").write_bytes(b"host bytecode")
    assert recipe.digest() == original
    code.write_text("# 第二版后端\n")
    assert recipe.digest() != original


def test_default_library_places_linker_and_cmake_files_in_development(tmp_path):
    source = app(tmp_path / "sdk", kind="lib")
    library = source / "lib"
    library.mkdir()
    (library / "libsdk.so.1").write_text("target library")
    (library / "libsdk.so").symlink_to("libsdk.so.1")
    (library / "sdkConfig.cmake").write_text("# CMake SDK\n")
    engine = builder(tmp_path, apps={"sdk": source})
    result = engine.build_one("sdk").root()
    with payload(result.runtime_packages[0].path) as archive:
        runtime_names = {Path(item.name).name for item in archive.getmembers()}
    with payload(result.development_packages[0].path) as archive:
        development_names = {Path(item.name).name for item in archive.getmembers()}
    assert "libsdk.so.1" in runtime_names and "libsdk.so" not in runtime_names
    assert {"libsdk.so", "sdkConfig.cmake"} <= development_names


def test_merge_rejects_symlink_parent_and_keeps_directory_mode(tmp_path):
    extracted, install = tmp_path / "extracted", tmp_path / "install"
    (extracted / "private").mkdir(parents=True)
    (extracted / "private").chmod(0o700)
    install.mkdir()
    DebPackageBackend._merge(extracted, install)
    assert (install / "private").stat().st_mode & 0o777 == 0o700
    (extracted / "usr/lib").mkdir(parents=True)
    (extracted / "usr/lib/data").write_text("payload")
    (install / "usr").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="冲突|符号链接"):
        DebPackageBackend._merge(extracted, install)


def test_ubuntu_rootfs_rejects_other_package_format(tmp_path):
    from builder.docker import BuildError

    rootfs = RootfsBuilder(MagicMock(), MagicMock())
    rootfs.app_report = MagicMock()
    rootfs.app_report.runtime_packages_for.return_value = (
        PackageArtifact(tmp_path / "other.pkg", "other", "runtime"),
    )
    with pytest.raises(BuildError, match="仅支持.*DEB"):
        rootfs._install_app_debs(
            tmp_path / "rootfs", {"rootfs": {"custom_packages": ["other"]}}
        )
