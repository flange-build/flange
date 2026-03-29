"""镜像打包规则 — 聚合 bootloader + boot + rootfs 产物，由平台脚本组装为完整磁盘镜像"""

def _image_build_impl(ctx):
    raw_img = ctx.actions.declare_file("raw.img")

    # boot 分区镜像
    boot_files = ctx.attr.boot.files.to_list()
    boot_img = None
    for f in boot_files:
        if f.basename == "boot.img":
            boot_img = f
    if not boot_img:
        fail("未在 boot 产物中找到 boot.img")

    # bootloader 产物
    bootloader_files = ctx.attr.bootloader.files.to_list()

    # rootfs 产物
    rootfs_files = ctx.attr.rootfs.files.to_list()
    rootfs_file = None
    for f in rootfs_files:
        if f.basename.endswith(".tar.gz"):
            rootfs_file = f
    if not rootfs_file:
        fail("未在 rootfs 产物中找到 tar.gz 文件")

    # 分区配置（可选）
    partition_config = ctx.file.partition_config

    build_script = ctx.file.build_script

    # 将 bootloader 文件复制到临时目录
    bootloader_copy_cmds = []
    for f in bootloader_files:
        bootloader_copy_cmds.append(
            'cp "$EXEC_ROOT/{src}" "$BOOTLOADER_STAGING/{name}"'.format(
                src = f.path,
                name = f.basename,
            ),
        )

    inputs = [boot_img, rootfs_file, build_script] + bootloader_files
    if partition_config:
        inputs.append(partition_config)

    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"

# 准备 bootloader 产物目录
BOOTLOADER_STAGING="$(mktemp -d)"
{bootloader_copy_cmds}

export IMAGE_BOOT="$EXEC_ROOT/{boot_img}"
export IMAGE_BOOTLOADER_DIR="$BOOTLOADER_STAGING"
export IMAGE_ROOTFS="$EXEC_ROOT/{rootfs_file}"
export IMAGE_PARTITION_CONFIG="{partition_config}"

if [ -n "$IMAGE_PARTITION_CONFIG" ]; then
    export IMAGE_PARTITION_CONFIG="$EXEC_ROOT/$IMAGE_PARTITION_CONFIG"
fi

source "$EXEC_ROOT/{build_script}"

echo "=== 收集镜像产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {raw_img_out})"
cp "$IMAGE_OUTPUT" "$EXEC_ROOT/{raw_img_out}"

echo "=== 镜像打包完成 ==="
""".format(
        bootloader_copy_cmds = "\n".join(bootloader_copy_cmds),
        boot_img = boot_img.path,
        rootfs_file = rootfs_file.path,
        partition_config = partition_config.path if partition_config else "",
        build_script = build_script.path,
        raw_img_out = raw_img.path,
    )

    ctx.actions.run_shell(
        outputs = [raw_img],
        inputs = inputs,
        command = script,
        mnemonic = "ImageBuild",
        progress_message = "打包磁盘镜像: {}".format(raw_img.short_path),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([raw_img]))]

image_build = rule(
    implementation = _image_build_impl,
    attrs = {
        "boot": attr.label(
            mandatory = True,
            doc = "boot 分区构建 target（提供 boot.img）",
        ),
        "bootloader": attr.label(
            mandatory = True,
            doc = "Bootloader 构建 target（提供平台特有的引导文件）",
        ),
        "rootfs": attr.label(
            mandatory = True,
            doc = "Rootfs 构建 target（提供 rootfs.tar.gz）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台镜像打包脚本",
        ),
        "partition_config": attr.label(
            default = None,
            allow_single_file = True,
            doc = "分区配置文件（如 Rockchip 的 parameter.txt）",
        ),
    },
)
