"""aarch64-linux-gnu 交叉编译工具链配置"""

load("@bazel_tools//tools/cpp:cc_toolchain_config_lib.bzl", "tool_path")

def _impl(ctx):
    tool_paths = [
        tool_path(name = "gcc", path = "/usr/bin/aarch64-linux-gnu-gcc"),
        tool_path(name = "g++", path = "/usr/bin/aarch64-linux-gnu-g++"),
        tool_path(name = "cpp", path = "/usr/bin/aarch64-linux-gnu-cpp"),
        tool_path(name = "ar", path = "/usr/bin/aarch64-linux-gnu-ar"),
        tool_path(name = "ld", path = "/usr/bin/aarch64-linux-gnu-ld"),
        tool_path(name = "nm", path = "/usr/bin/aarch64-linux-gnu-nm"),
        tool_path(name = "objdump", path = "/usr/bin/aarch64-linux-gnu-objdump"),
        tool_path(name = "strip", path = "/usr/bin/aarch64-linux-gnu-strip"),
        tool_path(name = "objcopy", path = "/usr/bin/aarch64-linux-gnu-objcopy"),
        tool_path(name = "gcov", path = "/usr/bin/aarch64-linux-gnu-gcov"),
    ]

    return cc_common.create_cc_toolchain_config_info(
        ctx = ctx,
        toolchain_identifier = "aarch64-linux-gnu",
        host_system_name = "x86_64-linux-gnu",
        target_system_name = "aarch64-linux-gnu",
        target_cpu = "aarch64",
        target_libc = "glibc",
        compiler = "gcc",
        abi_version = "gcc",
        abi_libc_version = "glibc",
        tool_paths = tool_paths,
        cxx_builtin_include_directories = [
            "/usr/lib/gcc-cross/aarch64-linux-gnu/13/include",
            "/usr/aarch64-linux-gnu/include",
            "/usr/include",
        ],
    )

cc_toolchain_config = rule(
    implementation = _impl,
    attrs = {},
    provides = [CcToolchainConfigInfo],
)
