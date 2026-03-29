"""Bazel module extension — 从 config_registry 读取板级配置，注册内核源码仓库"""

load("//build:config_registry.bzl", "get_board_config")
load("//build:kernel_source.bzl", "kernel_source")

def _kernel_sources_impl(module_ctx):
    for mod in module_ctx.modules:
        for src in mod.tags.source:
            config = get_board_config(src.board)
            kernel_config = config["kernel"]
            repo_name = "kernel_src_" + src.board.replace("-", "_")
            kernel_source(
                name = repo_name,
                remote = kernel_config["repo"],
                branch = kernel_config["branch"],
            )

_source_tag = tag_class(attrs = {
    "board": attr.string(mandatory = True, doc = "已注册的板子名称"),
})

kernel_sources = module_extension(
    implementation = _kernel_sources_impl,
    tag_classes = {"source": _source_tag},
)
