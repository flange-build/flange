"""Dockerfile APT HTTPS 信任链引导约束测试。"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
APT_SOURCES = REPO_ROOT / "docker" / "apt" / "ubuntu.sources"


def test_apt_sources_use_https():
    """项目维护的 Ubuntu APT 源必须全部使用 HTTPS。"""
    source_lines = APT_SOURCES.read_text().splitlines()
    uris = [line for line in source_lines if line.startswith("URIs:")]

    assert uris
    assert all(line.startswith("URIs: https://") for line in uris)


def test_ca_certificates_installed_before_https_sources():
    """复制 HTTPS 源前必须先通过基础镜像默认源安装 CA 证书。"""
    text = DOCKERFILE.read_text()
    install_ca = (
        "apt-get install -y --no-install-recommends ca-certificates"
    )
    copy_sources = (
        "COPY docker/apt/ubuntu.sources "
        "/etc/apt/sources.list.d/ubuntu.sources"
    )

    assert text.index(install_ca) < text.index(copy_sources)
    assert (
        "test -s /etc/ssl/certs/ca-certificates.crt"
        in text[: text.index(copy_sources)]
    )


def test_dockerfile_does_not_disable_tls_verification():
    """不得通过关闭证书校验掩盖 APT 信任链错误。"""
    text = DOCKERFILE.read_text()

    assert "Acquire::https::Verify-Peer=false" not in text
    assert "Acquire::https::Verify-Host=false" not in text
