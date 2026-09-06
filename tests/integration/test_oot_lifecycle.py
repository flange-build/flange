"""真实 Docker 交叉编译验收。显式 FLANGE_RUN_DOCKER_TESTS=1 启用。"""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest
import yaml

from builder.paths import PROJECT_ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="需要预先准备 Docker 镜像，设置 FLANGE_RUN_DOCKER_TESTS=1 运行真实编译",
)


def cli(root: Path, *args) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "builder", "--json", "-C", str(root), *map(str, args)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value["schema_version"] == 1 and value["ok"] is True
    return value["data"]


def workspace(root):
    cli(root, "init", ".", "--tool-root", PROJECT_ROOT, "--target", "radxa-zero3w-default-debug")


@pytest.mark.parametrize("system", ["make", "cmake", "meson"])
@pytest.mark.parametrize(
    "target,arch,machine",
    [
        ("radxa-zero3w-default-debug", "aarch64", 183),
        ("atk-rk3506b-default-debug", "armhf", 40),
    ],
)
def test_外部App真实交叉编译缓存和产物修复(tmp_path, system, target, arch, machine):
    workspace(tmp_path)
    created = cli(tmp_path, "app", "create", "hello", "--build-system", system)
    source = Path(created["path"])
    spec = yaml.safe_load((source / "app.yaml").read_text())
    spec["app"]["arch"] = [arch]
    (source / "app.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False))
    before = {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()
    }
    first = cli(tmp_path, "--target", target, "app", "build", source)
    log = Path(first["build_log"])
    assert log.is_file()
    assert "\x1b[" not in log.read_text()
    assert first["architecture"] == arch
    assert first["apps"][0]["reused"] is False
    manifest = Path(first["apps"][0]["manifest_path"])
    binary = manifest.parent / "install/usr/bin/hello"
    data = binary.read_bytes()
    assert data[:4] == b"\x7fELF"
    assert struct.unpack_from("<H", data, 18)[0] == machine
    assert {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()
    } == before
    second = cli(tmp_path, "--target", target, "app", "build", source)
    assert log.with_name("build.log.1").is_file()
    assert second["apps"][0]["reused"] is True
    assert first["identity"] == second["identity"]
    binary.chmod(binary.stat().st_mode ^ 0o100)
    repaired = cli(tmp_path, "--target", target, "app", "build", source)
    assert repaired["apps"][0]["reused"] is False
    assert binary.stat().st_mode & 0o100


def test_单App请求实际构建库依赖并消费其安装前缀(tmp_path):
    workspace(tmp_path)
    cli(tmp_path, "app", "create", "greeting", "--type", "lib")
    cli(tmp_path, "app", "create", "consumer")
    app = tmp_path / "consumer"
    spec = yaml.safe_load((app / "app.yaml").read_text())
    spec["build"]["deps"] = ["../greeting"]
    (app / "app.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False))
    (app / "src/main.c").write_text(
        "#include <greeting.h>\n#include <stdio.h>\nint main(void) { puts(greeting_version()); return 0; }\n"
    )
    (app / "CMakeLists.txt").write_text("""cmake_minimum_required(VERSION 3.16)
project(consumer C)
find_path(GREETING_INCLUDE greeting.h REQUIRED)
find_library(GREETING_LIBRARY NAMES greeting REQUIRED)
add_executable(consumer src/main.c)
target_include_directories(consumer PRIVATE ${GREETING_INCLUDE})
target_link_libraries(consumer PRIVATE ${GREETING_LIBRARY})
install(TARGETS consumer RUNTIME DESTINATION bin)
""")
    result = cli(tmp_path, "app", "build", app)
    assert [item["name"] for item in result["apps"]] == ["greeting", "consumer"]
    assert all(Path(path).is_file() for item in result["apps"] for path in item["runtime_debs"])
    assert len(result["apps"][0]["runtime_debs"]) == 1


@pytest.mark.parametrize(
    "target,deb_arch",
    [
        ("khadas-vim3-default-debug", "arm64"),
        ("atk-rk3506b-default-debug", "armhf"),
    ],
)
def test_内置recoveryctl从描述打包并执行真实入口(tmp_path, target, deb_arch):
    from builder.docker import DockerRunner

    workspace(tmp_path)
    result = cli(tmp_path, "--target", target, "app", "build", "recoveryctl")
    app = result["apps"][0]
    published = Path(app["manifest_path"]).parent
    metadata = json.loads((published / "resource.json").read_text())
    assert metadata["executable"] == "/usr/sbin/recoveryctl"

    # 在容器临时目录解包并运行 --help，验证实际 deb，而非只验证源脚本。
    program = """
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

package, executable, expected_arch = sys.argv[1:]
architecture = subprocess.check_output(
    ["dpkg-deb", "--field", package, "Architecture"], text=True
).strip()
assert architecture == expected_arch, architecture
with TemporaryDirectory(prefix="flange-recoveryctl-") as directory:
    subprocess.run(["dpkg-deb", "--extract", package, directory], check=True)
    entry = Path(directory) / executable.lstrip("/")
    assert entry.stat().st_mode & 0o111
    assert not (Path(directory) / "usr/bin/recoveryctl").exists()
    subprocess.run([str(entry), "--help"], check=True)
"""
    completed = DockerRunner(PROJECT_ROOT).run(
        ["python3", "-c", program, app["runtime_debs"][0], metadata["executable"], deb_arch],
        capture=True,
        extra_mounts=[tmp_path],
    )
    assert "usage: recoveryctl" in completed.stdout
