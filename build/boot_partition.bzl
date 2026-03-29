"""Boot 分区构建规则 — 将 Image + DTB + DTBO + extlinux.conf 组装为 ext4 boot.img"""

def _boot_partition_impl(ctx):
    boot_img = ctx.actions.declare_file("boot.img")

    # 内核产物
    kernel_files = ctx.attr.kernel.files.to_list()
    kernel_image = None
    kernel_dtb = None
    dtbos_tar = None
    for f in kernel_files:
        if f.basename == ctx.attr.image_name:
            kernel_image = f
        elif f.basename.endswith(".dtb"):
            kernel_dtb = f
        elif f.basename == "dtbos.tar.gz":
            dtbos_tar = f

    if not kernel_image:
        fail("未在 kernel 产物中找到 {}".format(ctx.attr.image_name))
    if not kernel_dtb:
        fail("未在 kernel 产物中找到 DTB 文件")

    build_script = ctx.file.build_script
    default_overlays = " ".join(ctx.attr.default_overlays)

    inputs = [kernel_image, kernel_dtb, build_script]
    if dtbos_tar:
        inputs.append(dtbos_tar)

    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"

export BOOT_KERNEL_IMAGE="$EXEC_ROOT/{kernel_image}"
export BOOT_DTB="$EXEC_ROOT/{kernel_dtb}"
export BOOT_DTBOS_TAR="{dtbos_tar}"
export BOOT_DTS="{dts}"
export BOOT_DTS_DIR="{dts_dir}"
export BOOT_DEFAULT_OVERLAYS="{default_overlays}"
export BOOT_KERNEL_ARGS="{kernel_args}"
export BOOT_SIZE_MB="{boot_size_mb}"

if [ -n "$BOOT_DTBOS_TAR" ]; then
    export BOOT_DTBOS_TAR="$EXEC_ROOT/$BOOT_DTBOS_TAR"
fi

source "$EXEC_ROOT/{build_script}"

echo "=== 收集 boot 分区产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {boot_img_out})"
cp "$BOOT_IMG_OUTPUT" "$EXEC_ROOT/{boot_img_out}"

echo "=== Boot 分区构建完成 ==="
""".format(
        kernel_image = kernel_image.path,
        kernel_dtb = kernel_dtb.path,
        dtbos_tar = dtbos_tar.path if dtbos_tar else "",
        dts = ctx.attr.dts,
        dts_dir = ctx.attr.dts_dir,
        default_overlays = default_overlays,
        kernel_args = ctx.attr.kernel_args,
        boot_size_mb = str(ctx.attr.boot_size_mb),
        build_script = build_script.path,
        boot_img_out = boot_img.path,
    )

    ctx.actions.run_shell(
        outputs = [boot_img],
        inputs = inputs,
        command = script,
        mnemonic = "BootPartition",
        progress_message = "构建 boot 分区: {}".format(boot_img.short_path),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([boot_img]))]

boot_partition = rule(
    implementation = _boot_partition_impl,
    attrs = {
        "kernel": attr.label(
            mandatory = True,
            doc = "内核构建 target（提供 Image + DTB + dtbos.tar.gz）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台 boot 分区构建脚本",
        ),
        "image_name": attr.string(
            default = "Image",
            doc = "内核镜像文件名（Image, zImage 等）",
        ),
        "dts": attr.string(
            mandatory = True,
            doc = "DTS 文件名（不含扩展名）",
        ),
        "dts_dir": attr.string(
            mandatory = True,
            doc = "DTS 子目录名（如 rockchip）",
        ),
        "default_overlays": attr.string_list(
            default = [],
            doc = "默认启用的 DTB overlay 列表",
        ),
        "kernel_args": attr.string(
            default = "",
            doc = "内核启动参数",
        ),
        "boot_size_mb": attr.int(
            default = 256,
            doc = "boot 分区大小（MB）",
        ),
    },
)
