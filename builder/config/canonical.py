"""Canonical 配置的无默认值访问器。"""

from __future__ import annotations


def userspace_arch(config: dict) -> str:
    return config["architecture"]["userspace"]


def kernel_arch(config: dict) -> str:
    return config["architecture"]["kernel"]


def bootloader_arch(config: dict) -> str:
    return config["architecture"]["bootloader"]


def kernel_device_tree(config: dict) -> tuple[str, str]:
    device_tree = config["kernel"]["device_tree"]
    return device_tree["directory"], device_tree["name"]
