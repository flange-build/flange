"""独立 libc 运行时必须自足，且不能放宽同包原生程序的 ABI 校验。"""

from pathlib import Path
import struct

import pytest

from builder.app_spec import AppSpecError, load_spec
from builder.elf import validate_elf_abi, validate_isolated_runtime
from builder.packaging.model import IsolatedRuntime
from tests.builder.app_support import app, builder


RUNTIME = IsolatedRuntime("/opt/vendor", "lib/ld-vendor.so.0")


def elf(path: Path, *, needed=(), interpreter="", machine=40, flags=0x5000400) -> Path:
    """构造带真实 ELF 动态表的最小 ARM 夹具，不模拟解析函数。"""
    data = bytearray(2048)
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into(
        "<HHIIIIIHHHHHH", data, 16, 3, machine, 1, 0, 52, 0, flags, 52, 32, 3, 0, 0, 0,
    )
    struct.pack_into("<IIIIIIII", data, 52, 1, 0, 0, 0, len(data), len(data), 5, 4096)
    encoded = interpreter.encode() + b"\0"
    data[160:160 + len(encoded)] = encoded
    struct.pack_into("<IIIIIIII", data, 84, 3, 160, 160, 0, len(encoded), len(encoded), 4, 1)
    strings = b"\0"
    dynamic = []
    for name in needed:
        dynamic.append((1, len(strings)))
        strings += name.encode() + b"\0"
    data[512:512 + len(strings)] = strings
    dynamic += [(5, 512), (10, len(strings)), (0, 0)]
    for index, entry in enumerate(dynamic):
        struct.pack_into("<iI", data, 1024 + index * 8, *entry)
    struct.pack_into("<IIIIIIII", data, 116, 2, 1024, 1024, 0,
                     len(dynamic) * 8, len(dynamic) * 8, 4, 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def files(root: Path):
    return [(path, "/" + path.relative_to(root).as_posix(), 0o755)
            for path in root.rglob("*") if path.is_symlink() or path.is_file()]


def runtime_tree(root: Path) -> Path:
    private = root / "opt/vendor"
    elf(private / "lib/ld-vendor.so.0")
    elf(private / "lib/libc.so.0")
    elf(private / "usr/lib/libmedia.so", needed=("libc.so.0",))
    elf(private / "bin/check", needed=("libmedia.so", "libc.so.0"),
        interpreter="/opt/vendor/lib/ld-vendor.so.0")
    return private


def test_private_runtime_keeps_native_files_subject_to_system_abi(tmp_path):
    runtime_tree(tmp_path)
    native = elf(tmp_path / "usr/bin/native", needed=("libc.so.0",))
    remaining = validate_isolated_runtime(files(tmp_path), "armhf", tmp_path, RUNTIME)
    assert [entry[0] for entry in remaining] == [native]
    sdk = tmp_path / "sdk"
    elf(sdk / "lib/libc.musl-armhf.so.1")
    with pytest.raises(ValueError, match="libc ABI"):
        validate_elf_abi(remaining, "armhf", sdk, "arm-linux-musleabihf")


@pytest.mark.parametrize("failure", [
    "missing_library", "missing_loader", "loader_permissions", "host_loader",
    "soft_float", "wrong_machine", "absolute_link", "escaping_link", "dangling_link",
    "invalid_library",
])
def test_invalid_private_runtime_is_rejected(tmp_path, failure):
    private = runtime_tree(tmp_path)
    if failure == "missing_library":
        (private / "usr/lib/libmedia.so").unlink()
    elif failure == "invalid_library":
        (private / "lib/libc.so.0").write_text("这不是动态库")
    elif failure == "missing_loader":
        (private / "lib/ld-vendor.so.0").unlink()
    elif failure == "loader_permissions":
        (private / "lib/ld-vendor.so.0").chmod(0o644)
    elif failure == "host_loader":
        elf(private / "bin/check", interpreter="/lib/ld-vendor.so.0")
    elif failure == "soft_float":
        elf(private / "lib/libc.so.0", flags=0x5000200)
    elif failure == "wrong_machine":
        elf(private / "lib/libc.so.0", machine=183)
    else:
        target = {"absolute_link": "/lib/libc.so.0", "escaping_link": "../../../outside",
                  "dangling_link": "missing.so"}[failure]
        (private / "lib/extra.so").symlink_to(target)
    with pytest.raises(ValueError):
        validate_isolated_runtime(files(tmp_path), "armhf", tmp_path, RUNTIME)


def test_runtime_accepts_relative_soname_links(tmp_path):
    private = runtime_tree(tmp_path)
    (private / "usr/lib/libmedia.so.1").symlink_to("libmedia.so")
    assert validate_isolated_runtime(files(tmp_path), "armhf", tmp_path, RUNTIME) == []


def test_private_libraries_cannot_be_exported_to_system_directory(tmp_path):
    runtime_tree(tmp_path)
    alias = tmp_path / "usr/lib/libmedia.so"
    alias.parent.mkdir(parents=True)
    alias.symlink_to("/opt/vendor/usr/lib/libmedia.so")
    with pytest.raises(ValueError, match="私有目录之外"):
        validate_isolated_runtime(files(tmp_path), "armhf", tmp_path, RUNTIME)


@pytest.mark.parametrize("value", [
    {"root": "/usr/lib/vendor", "loader": "lib/ld.so"},
    {"root": "/opt/../lib", "loader": "lib/ld.so"},
    {"root": "/opt/vendor/", "loader": "lib/ld.so"},
    {"root": "/opt/vendor", "loader": "/lib/ld.so"},
    {"root": "/opt/vendor", "loader": "../ld.so"},
    {"root": "/opt/vendor", "loader": "lib/ld.so", "unknown": True},
])
def test_invalid_runtime_declaration_is_rejected(tmp_path, value):
    source = app(tmp_path / "vendor", kind="vendor", packaging={"isolated_runtime": value})
    with pytest.raises(AppSpecError):
        load_spec(source)


def test_only_vendor_can_declare_private_runtime(tmp_path):
    source = app(tmp_path / "native", packaging={"isolated_runtime": vars(RUNTIME)})
    with pytest.raises(AppSpecError, match="vendor"):
        load_spec(source)


def test_private_runtime_rejects_external_package_split(tmp_path):
    source = app(tmp_path / "vendor", kind="vendor", packaging={
        "isolated_runtime": vars(RUNTIME),
        "outputs": [{"file": "vendor.deb", "role": "runtime"}],
    })
    with pytest.raises(AppSpecError, match="不能导入外部包"):
        load_spec(source)


def test_private_runtime_validation_runs_before_publication(tmp_path):
    source = app(tmp_path / "vendor", kind="vendor", arch="armhf",
                 packaging={"isolated_runtime": vars(RUNTIME)})
    runtime_tree(source / "rootfs")
    engine = builder(tmp_path, arch="armhf", apps={"vendor": source}, variant="release")
    first = engine.build_one("vendor").root()
    assert first.runtime_packages and first.manifest_path.is_file()
    (source / "rootfs/opt/vendor/lib/libc.so.0").unlink()
    with pytest.raises(ValueError, match="缺少依赖"):
        engine.build_one("vendor")
    assert first.runtime_packages[0].path.is_file()
