"""Rootfs Customize 构建规则 — 在 base rootfs 上应用自定义 deb 包和 overlay，产出 rootfs.tar.gz"""

def _rootfs_customize_impl(ctx):
    rootfs_tar = ctx.actions.declare_file("rootfs.tar.gz")

    base_file = ctx.file.base
    build_script = ctx.file.build_script

    # overlay 文件
    overlay_files = []
    overlay_dir = ""
    if ctx.attr.overlay:
        overlay_files = ctx.attr.overlay.files.to_list()
        if overlay_files:
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
                custom_pkg_dir = first.rsplit("/", 2)[0] if "/" in first else ""

    custom_packages = " ".join(ctx.attr.custom_packages)

    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"

# --- 调用平台 customize 构建脚本 ---
export ROOTFS_BASE="$EXEC_ROOT/{base}"
export ROOTFS_CUSTOM_PACKAGES="{custom_packages}"
export ROOTFS_PACKAGES_DIR="{custom_pkg_dir}"
export ROOTFS_OVERLAY_DIR="{overlay_dir}"
export ROOTFS_ARCH="{arch}"

source "$EXEC_ROOT/{build_script}"

# --- 收集构建产物 ---
echo "=== 收集 rootfs 产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {rootfs_out})"
cp "$ROOTFS_OUTPUT" "$EXEC_ROOT/{rootfs_out}"

echo "=== Rootfs 定制化构建完成 ==="
""".format(
        base = base_file.path,
        custom_packages = custom_packages,
        custom_pkg_dir = ("$EXEC_ROOT/" + custom_pkg_dir) if custom_pkg_dir else "",
        overlay_dir = ("$EXEC_ROOT/" + overlay_dir) if overlay_dir else "",
        arch = ctx.attr.arch,
        build_script = build_script.path,
        rootfs_out = rootfs_tar.path,
    )

    ctx.actions.run_shell(
        outputs = [rootfs_tar],
        inputs = [base_file, build_script] + overlay_files + custom_pkg_files,
        command = script,
        mnemonic = "RootfsCustomize",
        progress_message = "定制化 Rootfs: {}".format(rootfs_tar.short_path),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([rootfs_tar]))]

rootfs_customize = rule(
    implementation = _rootfs_customize_impl,
    attrs = {
        "base": attr.label(
            mandatory = True,
            allow_single_file = [".tar.zst"],
            doc = "base-rootfs.tar.zst 文件（来自 rootfs_base rule）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台 customize 构建脚本，须设置 ROOTFS_OUTPUT 指向产出的 rootfs.tar.gz 绝对路径",
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
    },
)
