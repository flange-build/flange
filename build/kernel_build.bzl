"""内核构建规则 — 框架负责源码管理和产物收集，平台脚本负责实际构建逻辑"""

def _kernel_build_impl(ctx):
    # 声明输出文件
    image = ctx.actions.declare_file(ctx.attr.image_name)
    dtb = ctx.actions.declare_file(ctx.attr.dts + ".dtb")
    modules_tar = ctx.actions.declare_file("modules.tar.gz")
    dtbos_tar = ctx.actions.declare_file("dtbos.tar.gz")

    # 从 kernel_src 输入推导源码根目录，检测本地模式
    src_files = ctx.attr.kernel_src.files.to_list()
    if not src_files:
        fail("kernel_src 不包含任何文件")

    local_mode = False
    makefile = None
    for f in src_files:
        if f.basename == ".local_mode":
            local_mode = True
        if f.basename == "Makefile":
            makefile = f
    if not makefile:
        fail("kernel_src 中未找到 Makefile")
    src_root = makefile.path.rsplit("/Makefile", 1)[0]

    # 收集补丁文件（平台补丁 + 板级补丁）
    platform_patches = []
    for target in ctx.attr.platform_patches:
        platform_patches.extend(target.files.to_list())
    platform_patches = sorted(platform_patches, key = lambda f: f.basename)

    board_patches = []
    for target in ctx.attr.board_patches:
        board_patches.extend(target.files.to_list())
    board_patches = sorted(board_patches, key = lambda f: f.basename)

    all_patches = platform_patches + board_patches

    # 生成补丁应用命令
    patch_cmds = ""
    for p in all_patches:
        patch_cmds += "git apply \"$EXEC_ROOT/{path}\" || patch -p1 < \"$EXEC_ROOT/{path}\"\n".format(
            path = p.path,
        )

    # 平台构建脚本
    build_script = ctx.file.build_script

    # 框架脚本：直接在源码目录原地构建，无需复制
    # 增量编译：保留 .o 等编译产物
    if local_mode:
        reset_and_patch = """\
echo "=== 本地模式：跳过 reset 和补丁 ==="
cd "$BUILD_DIR" """
    else:
        reset_and_patch = """\
echo "=== 重置源码树（保留编译产物） ==="
cd "$BUILD_DIR"
git reset --hard HEAD 2>/dev/null || true

# --- 应用补丁 ---
{patch_cmds}""".format(patch_cmds = patch_cmds if patch_cmds else "")

    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"
BUILD_DIR="$EXEC_ROOT/{src_root}"

{reset_and_patch}

# --- 调用平台构建脚本 ---
export KERNEL_DIR="$BUILD_DIR"
export KERNEL_DEFCONFIG="{defconfig}"
export KERNEL_DTS="{dts}"
export KERNEL_DTS_DIR="{dts_dir}"
export KERNEL_JOBS="{jobs}"

source "$EXEC_ROOT/{build_script}"

# --- 收集构建产物 ---
echo "=== 收集构建产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {image_out})"
mkdir -p "$EXEC_ROOT/$(dirname {dtb_out})"
mkdir -p "$EXEC_ROOT/$(dirname {modules_tar_out})"
cp "$KERNEL_IMAGE" "$EXEC_ROOT/{image_out}"
cp "$KERNEL_DTB" "$EXEC_ROOT/{dtb_out}"
tar -czf "$EXEC_ROOT/{modules_tar_out}" -C "$KERNEL_MODULES_DIR" lib
if [ -d "$KERNEL_DTBOS_DIR" ] && ls "$KERNEL_DTBOS_DIR"/*.dtbo 1>/dev/null 2>&1; then
    tar -czf "$EXEC_ROOT/{dtbos_tar_out}" -C "$KERNEL_DTBOS_DIR" .
else
    tar -czf "$EXEC_ROOT/{dtbos_tar_out}" --files-from /dev/null
fi

echo "=== 内核构建完成 ==="
""".format(
        src_root = src_root,
        reset_and_patch = reset_and_patch,
        defconfig = ctx.attr.defconfig,
        dts = ctx.attr.dts,
        dts_dir = ctx.attr.dts_dir,
        jobs = str(ctx.attr.jobs) if ctx.attr.jobs > 0 else "$(nproc)",
        build_script = build_script.path,
        image_out = image.path,
        dtb_out = dtb.path,
        modules_tar_out = modules_tar.path,
        dtbos_tar_out = dtbos_tar.path,
    )

    ctx.actions.run_shell(
        outputs = [image, dtb, modules_tar, dtbos_tar],
        inputs = src_files + all_patches + [build_script],
        command = script,
        mnemonic = "KernelBuild",
        progress_message = "编译内核: {} + {}".format(
            image.short_path,
            dtb.short_path,
        ),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([image, dtb, modules_tar, dtbos_tar]))]

kernel_build = rule(
    implementation = _kernel_build_impl,
    attrs = {
        "kernel_src": attr.label(
            mandatory = True,
            doc = "内核源码 filegroup（来自 kernel_source repository rule）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台构建脚本，接收 KERNEL_DIR/KERNEL_DEFCONFIG/KERNEL_DTS/KERNEL_DTS_DIR/KERNEL_JOBS 环境变量，"
                  + "须设置 KERNEL_IMAGE 和 KERNEL_DTB 指向产出文件的绝对路径",
        ),
        "image_name": attr.string(
            default = "Image",
            doc = "输出的内核镜像文件名（Image, zImage 等）",
        ),
        "defconfig": attr.string(
            mandatory = True,
            doc = "内核 defconfig 名称",
        ),
        "dts": attr.string(
            mandatory = True,
            doc = "Device Tree 文件名，不含扩展名",
        ),
        "dts_dir": attr.string(
            mandatory = True,
            doc = "DTS 子目录名（如 rockchip）",
        ),
        "platform_patches": attr.label_list(
            allow_files = True,
            default = [],
            doc = "平台通用补丁（优先应用）",
        ),
        "board_patches": attr.label_list(
            allow_files = True,
            default = [],
            doc = "板级特有补丁（在平台补丁之后应用）",
        ),
        "jobs": attr.int(
            default = 0,
            doc = "make 并行任务数，0 表示使用 $(nproc) 自动检测",
        ),
    },
)
