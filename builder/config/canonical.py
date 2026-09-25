"""Canonical 配置的无默认值访问器。"""

from __future__ import annotations


def userspace_arch(config: dict) -> str:
    return config["architecture"]["userspace"]


def kernel_arch(config: dict) -> str:
    return config["architecture"]["kernel"]


def bootloader_arch(config: dict) -> str:
    return config["architecture"]["bootloader"]


def kernel_headers_package(config: dict) -> bool:
    """是否打包 linux-headers deb 并装进 rootfs，供设备端编译外部模块。"""
    return bool((config.get("kernel") or {}).get("headers_package"))


def kernel_device_tree(config: dict) -> tuple[str, str]:
    device_tree = config["kernel"]["device_tree"]
    return device_tree["directory"], device_tree["name"]
