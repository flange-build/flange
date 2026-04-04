"""flange 构建规则统一导出入口

App 的 BUILD.bazel 统一从此文件加载规则:
    load("//build:defs.bzl", "flange_deb")
"""

load("//build:deb.bzl", _flange_deb = "flange_deb")

flange_deb = _flange_deb
