"""Canonical 配置访问器测试。"""

from builder.config.canonical import (
    bootloader_arch,
    kernel_arch,
    kernel_device_tree,
    userspace_arch,
)


def test_architecture_and_device_tree_dimensions_are_distinct():
    config = {
        "architecture": {
            "userspace": "aarch64",
            "kernel": "arm64",
            "bootloader": "arm",
        },
        "kernel": {
            "device_tree": {"directory": "qcom", "name": "demo"},
        },
    }

    assert userspace_arch(config) == "aarch64"
    assert kernel_arch(config) == "arm64"
    assert bootloader_arch(config) == "arm"
    assert kernel_device_tree(config) == ("qcom", "demo")
