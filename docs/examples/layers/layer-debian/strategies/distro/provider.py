"""Debian 13 使用共用 APT 流程，基线包集合来自本层。"""
from builder.distro import AptDistro
BUILD_ENVIRONMENT = "debian13"
def create_distro():
    return AptDistro()
