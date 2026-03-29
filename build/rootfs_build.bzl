"""Rootfs 构建规则 — 框架负责 tarball 管理和产物收集，平台脚本负责实际构建逻辑"""

def _rootfs_build_impl(ctx):
    # 声明输出文件
    rootfs_tar = ctx.actions.declare_file("rootfs.tar.gz")

    # tarball 文件
    tarball = ctx.file.rootfs_src

    # overlay 文件
    overlay_files = []
    overlay_dir = ""
    if ctx.attr.overlay:
        overlay_files = ctx.attr.overlay.files.to_list()
        if overlay_files:
            # 从 overlay 文件路径推导 overlay 根目录
            # overlay 文件路径形如 board/radxa-zero3w/overlay/etc/hostname
            # 需要找到 overlay/ 目录本身
            first = overlay_files[0].path
            if "/overlay/" in first:
                overlay_dir = first.split("/overlay/")[0] + "/overlay"

    # 自定义 deb 包目录
    custom_pkg_files = []
    custom_pkg_dir = ""
    if ctx.attr.custom_packages_dir:
        custom_pkg_files = ctx.attr.custom_packages_dir.files.to_list()
        if custom_pkg_files:
            first = custom_pkg_files[0].path
            if "/packages/" in first:
                custom_pkg_dir = first.split("/packages/")[0] + "/packages"
            else:
                # 回退：使用第一个文件的目录的上级
                custom_pkg_dir = first.rsplit("/", 2)[0] if "/" in first else ""

    # 平台构建脚本
    build_script = ctx.file.build_script

    # 包列表
    packages = " ".join(ctx.attr.packages)
    custom_packages = " ".join(ctx.attr.custom_packages)

    # 框架脚本
    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"

# --- 调用平台构建脚本 ---
export ROOTFS_TARBALL="$EXEC_ROOT/{tarball}"
export ROOTFS_PACKAGES="{packages}"
export ROOTFS_CUSTOM_PACKAGES="{custom_packages}"
export ROOTFS_PACKAGES_DIR="{custom_pkg_dir}"
export ROOTFS_OVERLAY_DIR="{overlay_dir}"
export ROOTFS_ARCH="{arch}"
export ROOTFS_JOBS="{jobs}"

source "$EXEC_ROOT/{build_script}"

# --- 收集构建产物 ---
echo "=== 收集构建产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {rootfs_out})"
cp "$ROOTFS_OUTPUT" "$EXEC_ROOT/{rootfs_out}"

echo "=== Rootfs 构建完成 ==="
""".format(
        tarball = tarball.path,
        packages = packages,
        custom_packages = custom_packages,
        custom_pkg_dir = ("$EXEC_ROOT/" + custom_pkg_dir) if custom_pkg_dir else "",
        overlay_dir = ("$EXEC_ROOT/" + overlay_dir) if overlay_dir else "",
        arch = ctx.attr.arch,
        jobs = str(ctx.attr.jobs) if ctx.attr.jobs > 0 else "$(nproc)",
        build_script = build_script.path,
        rootfs_out = rootfs_tar.path,
    )

    ctx.actions.run_shell(
        outputs = [rootfs_tar],
        inputs = [tarball, build_script] + overlay_files + custom_pkg_files,
        command = script,
        mnemonic = "RootfsBuild",
        progress_message = "构建 Rootfs: {}".format(rootfs_tar.short_path),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([rootfs_tar]))]

rootfs_build = rule(
    implementation = _rootfs_build_impl,
    attrs = {
        "rootfs_src": attr.label(
            mandatory = True,
            allow_single_file = [".tar.gz", ".tar.xz"],
            doc = "ubuntu-base tarball 文件（来自 rootfs_source repository rule）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台构建脚本，接收 ROOTFS_TARBALL/ROOTFS_PACKAGES/ROOTFS_OVERLAY_DIR 等环境变量，"
                  + "须设置 ROOTFS_OUTPUT 指向产出的 rootfs.tar.gz 绝对路径",
        ),
        "packages": attr.string_list(
            default = [],
            doc = "apt 包列表",
        ),
        "custom_packages": attr.string_list(
            default = [],
            doc = "自定义 deb 包组件名列表（对应 packages/ 下的子目录名）",
        ),
        "custom_packages_dir": attr.label(
            default = None,
            doc = "自定义 deb 包目录 filegroup（//packages:all_debs）",
        ),
        "overlay": attr.label(
            default = None,
            doc = "Board overlay filegroup（如 //board/radxa-zero3w:overlay）",
        ),
        "arch": attr.string(
            default = "arm64",
            doc = "目标架构（arm64, armhf 等）",
        ),
        "jobs": attr.int(
            default = 0,
            doc = "并行任务数，0 表示使用 $(nproc) 自动检测",
        ),
    },
)
