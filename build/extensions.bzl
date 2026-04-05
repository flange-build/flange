"""Bazel module extension — 从 config_registry 读取板级配置，注册源码仓库"""

load("//build:bootloader_source.bzl", "bootloader_source")
load("//build:config_registry.bzl", "get_board_config")
load("//build:kernel_source.bzl", "kernel_source")
load("//build:rkbin_source.bzl", "rkbin_source")
load("//build:rootfs_source.bzl", "rootfs_source")

# --- 内核源码 ---

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
                commit = kernel_config.get("commit", ""),
                local_path = kernel_config.get("local_path", ""),
            )

_source_tag = tag_class(attrs = {
    "board": attr.string(mandatory = True, doc = "已注册的板子名称"),
})

kernel_sources = module_extension(
    implementation = _kernel_sources_impl,
    tag_classes = {"source": _source_tag},
)

# --- Bootloader 源码 + rkbin ---

def _bootloader_sources_impl(module_ctx):
    rkbin_created = {}  # 平台级去重：{platform: True}

    for mod in module_ctx.modules:
        for src in mod.tags.source:
            config = get_board_config(src.board)
            bootloader_config = config["bootloader"]
            platform = config["platform"]

            # U-Boot 源码（每板一个）
            repo_name = "bootloader_src_" + src.board.replace("-", "_")
            bootloader_source(
                name = repo_name,
                remote = bootloader_config["repo"],
                branch = bootloader_config["branch"],
                commit = bootloader_config.get("commit", ""),
                local_path = bootloader_config.get("local_path", ""),
            )

            # rkbin 固件仓库（平台级共享，去重）
            rkbin_config = config.get("rkbin")
            if rkbin_config and platform not in rkbin_created:
                rkbin_source(
                    name = "rkbin_" + platform,
                    remote = rkbin_config["repo"],
                    branch = rkbin_config["branch"],
                )
                rkbin_created[platform] = True

_bootloader_source_tag = tag_class(attrs = {
    "board": attr.string(mandatory = True, doc = "已注册的板子名称"),
})

bootloader_sources = module_extension(
    implementation = _bootloader_sources_impl,
    tag_classes = {"source": _bootloader_source_tag},
)

# --- Rootfs 源码（ubuntu-base tarball） ---

def _rootfs_sources_impl(module_ctx):
    for mod in module_ctx.modules:
        for src in mod.tags.source:
            config = get_board_config(src.board)
            rootfs_config = config["rootfs"]

            repo_name = "rootfs_src_" + src.board.replace("-", "_")
            rootfs_source(
                name = repo_name,
                url = rootfs_config["url"],
                sha256 = rootfs_config.get("sha256", ""),
            )

_rootfs_source_tag = tag_class(attrs = {
    "board": attr.string(mandatory = True, doc = "已注册的板子名称"),
})

rootfs_sources = module_extension(
    implementation = _rootfs_sources_impl,
    tag_classes = {"source": _rootfs_source_tag},
)
