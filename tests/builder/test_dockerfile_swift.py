"""Dockerfile Embedded Swift 工具链安装约束测试。"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"


def test_dockerfile_pins_swift_toolchain_with_sha256():
    """Swift 工具链必须固定版本并做 SHA256 校验。"""
    text = DOCKERFILE.read_text()

    assert "ARG SWIFT_VERSION=6.3.3" in text
    assert (
        "ARG SWIFT_SHA256="
        "da8272a5fddccd65b1529ed0e52e04526e2eadd4237d58d6220efeb973c6cd19"
    ) in text
    assert "sha256sum -c -" in text
    assert "/opt/swift-embedded/bin/swift --version" in text
    assert "/opt/swift-embedded/bin/swiftc --version" in text


def test_dockerfile_exposes_swift_on_path():
    """构建容器内应能通过 PATH 直接调用 swift / swiftc。"""
    text = DOCKERFILE.read_text()

    assert "ENV SWIFT_HOME=/opt/swift-embedded" in text
    assert 'ENV PATH="${SWIFT_HOME}/bin:${PATH}"' in text


def test_dockerfile_installs_swift_runtime_dependencies():
    """Ubuntu tarball 运行依赖应随 build 镜像安装。"""
    text = DOCKERFILE.read_text()

    for package in [
        "libcurl4-openssl-dev",
        "libedit2",
        "libsqlite3-0",
        "libz3-dev",
        "zlib1g-dev",
    ]:
        assert package in text
