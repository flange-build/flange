"""Dockerfile 的 RK3506B ARM32 gcc-10 工具链约束测试。"""

from pathlib import Path


DOCKERFILE = Path(__file__).parents[2] / "docker" / "Dockerfile"


def test_dockerfile_pins_atk_sdk_arm_linux_gcc10_with_sha256():
    text = DOCKERFILE.read_text()

    assert "ARM_LINUX_GCC_RELEASE=10.3-2021.07" in text
    assert (
        "ARM_LINUX_GCC_SHA256="
        "aa074fa8371a4f73fecbd16bd62c8b1945f23289e26414794f130d6ccdf8e39c"
    ) in text
    assert "/opt/arm-linux-gcc10" in text
    assert "libmpc-dev" in text
    assert "libmpfr-dev" in text
    assert (
        "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-gcc --version"
        in text
    )
