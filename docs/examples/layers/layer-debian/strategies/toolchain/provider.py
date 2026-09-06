"""SDK 来自 Debian arm64 开发包；环境镜像摘要记录实际包输入。"""
from builder.toolchain import Toolchain

def create_toolchain(config, context):
    return Toolchain("aarch64", "aarch64-linux-gnu", "aarch64", "aarch64",
                     profile="debian13", target_sysroot="/opt/flange-sdk",
                     sdk_identity="debian13-trixie-arm64-v1")
