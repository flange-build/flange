"""在 Docker 中验证真实 CPack 拆包、SDK 消费和开发包缓存校验。"""

import os
import struct
from pathlib import Path

import pytest
import yaml

from builder.app_model import AppBuildReport
from builder.docker import DockerRunner
from builder.paths import PROJECT_ROOT
from tests.integration.test_oot_lifecycle import cli, workspace

pytestmark = pytest.mark.skipif(
    os.environ.get("FLANGE_RUN_DOCKER_TESTS") != "1",
    reason="设置 FLANGE_RUN_DOCKER_TESTS=1 并准备 Docker 镜像后运行",
)


def test_CPack完整运行开发包用于下游实际链接(tmp_path):
    workspace(tmp_path)
    source = tmp_path / "provider"
    source.mkdir()
    spec = {
        "app": {
            "name": "provider",
            "version": "1.0.0",
            "description": "CPack 集成夹具",
            "type": "service",
            "arch": ["aarch64"],
        },
        "maintainer": {"name": "tester", "email": "test@localhost"},
        "systemd": {"unit": "provider.service", "auto_start": False},
        "build": {"system": "custom", "commands": [["python3", "package.py"]]},
        "packaging": {
            "format": "deb",
            "outputs": [
                {"file": "provider_1.0.0_arm64.deb", "role": "runtime"},
                {"file": "provider-dev_1.0.0_arm64.deb", "role": "development"},
            ],
        },
    }
    (source / "app.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True))
    (source / "main.c").write_text("int main(void) { return 0; }\n")
    (source / "client.c").write_text("int provider_version(void) { return 1; }\n")
    (source / "provider.h").write_text("int provider_version(void);\n")
    (source / "provider.service").write_text("[Service]\nExecStart=/usr/bin/provider\n")
    (source / "postinst").write_text(
        "#!/bin/sh\n# 不启用服务，也不修改用户数据\nexit 0\n"
    )
    (source / "CMakeLists.txt").write_text("""cmake_minimum_required(VERSION 3.16)
project(provider VERSION 1.0.0 LANGUAGES C)
add_executable(provider main.c)
add_library(provider_client STATIC client.c)
target_include_directories(provider_client PUBLIC $<INSTALL_INTERFACE:include>)
install(TARGETS provider RUNTIME DESTINATION bin COMPONENT Runtime)
install(TARGETS provider_client EXPORT ProviderTargets ARCHIVE DESTINATION lib COMPONENT Development)
install(EXPORT ProviderTargets FILE ProviderConfig.cmake NAMESPACE Provider::
        DESTINATION lib/cmake/Provider COMPONENT Development)
install(FILES provider.h DESTINATION include COMPONENT Development)
install(FILES provider.service DESTINATION lib/systemd/system COMPONENT Runtime)
set(CPACK_GENERATOR DEB)
set(CPACK_PACKAGE_CONTACT "tester <test@localhost>")
set(CPACK_DEB_COMPONENT_INSTALL ON)
set(CPACK_COMPONENTS_ALL Runtime Development)
set(CPACK_DEBIAN_PACKAGE_ARCHITECTURE arm64)
set(CPACK_DEBIAN_RUNTIME_PACKAGE_NAME provider)
set(CPACK_DEBIAN_DEVELOPMENT_PACKAGE_NAME provider-dev)
set(CPACK_DEBIAN_RUNTIME_FILE_NAME provider_1.0.0_arm64.deb)
set(CPACK_DEBIAN_DEVELOPMENT_FILE_NAME provider-dev_1.0.0_arm64.deb)
set(CPACK_DEBIAN_RUNTIME_PACKAGE_CONTROL_EXTRA "${CMAKE_CURRENT_SOURCE_DIR}/postinst")
include(CPack)
""")
    # CPack 直接交付完整包，不执行 install 或 dpkg-deb --extract 到 DESTDIR。
    (source / "package.py").write_text("""import os
from pathlib import Path
import subprocess

build = Path(os.environ["FLANGE_APP_WORK_DIR"]) / "cpack-build"
output = Path(os.environ["FLANGE_APP_OUTPUT_DIR"])
subprocess.run(["cmake", "-S", ".", "-B", str(build),
                "-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_C_COMPILER=" + os.environ["CC"],
                "-DCMAKE_INSTALL_PREFIX=/usr", "-DCMAKE_BUILD_TYPE=Debug"], check=True)
subprocess.run(["cmake", "--build", str(build)], check=True)
subprocess.run(["cpack", "--config", str(build / "CPackConfig.cmake"),
                "-B", str(output)], check=True)
""")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    consumer_spec = {
        "app": {
            "name": "consumer",
            "version": "1.0.0",
            "description": "SDK 消费者",
            "type": "exec",
            "arch": ["aarch64"],
        },
        "maintainer": {"name": "tester", "email": "test@localhost"},
        "build": {"system": "cmake", "deps": ["../provider"]},
    }
    (consumer / "app.yaml").write_text(
        yaml.safe_dump(consumer_spec, allow_unicode=True)
    )
    (consumer / "main.c").write_text(
        "#include <provider.h>\nint main(void) { return provider_version() != 1; }\n"
    )
    (consumer / "CMakeLists.txt").write_text("""cmake_minimum_required(VERSION 3.16)
project(consumer C)
find_package(Provider CONFIG REQUIRED)
add_executable(consumer main.c)
target_link_libraries(consumer PRIVATE Provider::provider_client)
install(TARGETS consumer RUNTIME DESTINATION bin)
""")
    first = cli(tmp_path, "app", "build", consumer)
    assert [item["name"] for item in first["apps"]] == ["provider", "consumer"]
    provider = first["apps"][0]
    assert [package["role"] for package in provider["packages"]] == [
        "runtime",
        "development",
    ]
    install = Path(provider["manifest_path"]).parent / "install"
    assert (install / "usr/include/provider.h").is_file()
    assert (install / "usr/lib/libprovider_client.a").is_file()
    binary = Path(first["apps"][1]["manifest_path"]).parent / "install/usr/bin/consumer"
    assert struct.unpack_from("<H", binary.read_bytes(), 18)[0] == 183
    second = cli(tmp_path, "app", "build", consumer)
    assert all(item["reused"] for item in second["apps"])
    report_dir = Path(provider["manifest_path"]).parent.parent / "reports"
    report = next(AppBuildReport.load(path) for path in report_dir.glob("*.json"))
    assert len(report.runtime_packages) == 2
    assert all("-dev_" not in package.path.name for package in report.runtime_packages)
    package = provider["packages"][0]["path"]
    check = DockerRunner(PROJECT_ROOT).run(
        [
            "python3",
            "-c",
            """import subprocess, sys, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as root:
    subprocess.run(["dpkg-deb", "--control", sys.argv[1], root], check=True)
    assert "exit 0" in (Path(root) / "postinst").read_text()
""",
            package,
        ],
        capture=True,
        extra_mounts=[tmp_path],
    )
    assert check.returncode == 0
    Path(provider["packages"][1]["path"]).unlink()
    repaired = cli(tmp_path, "app", "build", consumer)
    assert repaired["apps"][0]["reused"] is False
    assert all(
        Path(package["path"]).is_file() for package in repaired["apps"][0]["packages"]
    )
    # 只验证本地构建、打包与链接；未连接或部署实际设备。
    assert not list(
        (Path(provider["manifest_path"]).parent.parent.parent / "sessions").glob("*")
    )
