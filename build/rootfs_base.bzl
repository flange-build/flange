"""Rootfs Base 构建规则 — 从 ubuntu-base tarball 构建基础 rootfs（apt 包安装），产出 base-rootfs.tar.zst"""

def _rootfs_base_impl(ctx):
    base_tar = ctx.actions.declare_file("base-rootfs.tar.zst")

    tarball = ctx.file.rootfs_src
    build_script = ctx.file.build_script
    packages = " ".join(ctx.attr.packages)

    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"

# --- 调用平台 base 构建脚本 ---
export ROOTFS_TARBALL="$EXEC_ROOT/{tarball}"
export ROOTFS_PACKAGES="{packages}"
export ROOTFS_APT_CACHE_DIR="{apt_cache_dir}"
export ROOTFS_ARCH="{arch}"

source "$EXEC_ROOT/{build_script}"

# --- 收集构建产物 ---
echo "=== 收集 base rootfs 产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {base_out})"
cp "$ROOTFS_BASE_OUTPUT" "$EXEC_ROOT/{base_out}"

echo "=== Base rootfs 构建完成 ==="
""".format(
        tarball = tarball.path,
        packages = packages,
        apt_cache_dir = "/cache/apt",
        arch = ctx.attr.arch,
        build_script = build_script.path,
        base_out = base_tar.path,
    )

    ctx.actions.run_shell(
        outputs = [base_tar],
        inputs = [tarball, build_script],
        command = script,
        mnemonic = "RootfsBase",
        progress_message = "构建 Base Rootfs: {}".format(base_tar.short_path),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([base_tar]))]

rootfs_base = rule(
    implementation = _rootfs_base_impl,
    attrs = {
        "rootfs_src": attr.label(
            mandatory = True,
            allow_single_file = [".tar.gz", ".tar.xz"],
            doc = "ubuntu-base tarball 文件（来自 rootfs_source repository rule）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台 base 构建脚本，须设置 ROOTFS_BASE_OUTPUT 指向产出的 base-rootfs.tar.zst 绝对路径",
        ),
        "packages": attr.string_list(
            default = [],
            doc = "apt 包列表",
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
