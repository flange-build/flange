"""完整 Debian 构建环境，保留低层 gcc10。"""
from pathlib import Path
from builder.build_environment import BuildEnvironmentSpec

def create_environment(config, context):
    directory = Path(__file__).parent / "image"
    return BuildEnvironmentSpec(
        name="debian13", image="flange-debian13:layers", dockerfile=directory / "Dockerfile",
        build_context=directory, toolchain="debian13",
        required_tools=(("/opt/aarch64-gcc10/bin/aarch64-linux-gcc", "10.5.0"),
                        ("/usr/bin/aarch64-linux-gnu-gcc", "14.")))
