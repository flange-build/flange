"""Bootloader 构建规则 — 框架负责源码管理和产物收集，平台脚本负责实际构建逻辑"""

def _bootloader_build_impl(ctx):
    # 声明输出文件
    bootloader_img = ctx.actions.declare_file("bootloader.img")
    idbloader = ctx.actions.declare_file("idbloader.img")
    miniloader = ctx.actions.declare_file("miniloader.bin")

    # 从 bootloader_src 输入推导源码根目录
    src_files = ctx.attr.bootloader_src.files.to_list()
    if not src_files:
        fail("bootloader_src 不包含任何文件")
    makefile = src_files[0]
    src_root = makefile.path.rsplit("/Makefile", 1)[0]

    # 固件仓库（可选）
    firmware_files = []
    firmware_root = ""
    if ctx.attr.firmware_src:
        firmware_files = ctx.attr.firmware_src.files.to_list()
        if firmware_files:
            fw_marker = firmware_files[0]
            # 从标记文件路径推导仓库根目录（标记在 src/ 子目录下）
            firmware_root = fw_marker.path.rsplit("/src/", 1)[0] + "/src"

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

    # 框架脚本
    script = """\
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

EXEC_ROOT="$(pwd)"
BUILD_DIR="$EXEC_ROOT/{src_root}"

echo "=== 重置源码树（保留编译产物） ==="
cd "$BUILD_DIR"
git reset --hard HEAD 2>/dev/null || true

# --- 应用补丁 ---
{patch_cmds}

# --- 调用平台构建脚本 ---
export BOOTLOADER_DIR="$BUILD_DIR"
export BOOTLOADER_DEFCONFIG="{defconfig}"
export BOOTLOADER_JOBS="{jobs}"
export FIRMWARE_DIR="{firmware_dir}"
export RKBIN_INI_PREFIX="{ini_prefix}"
export RKBIN_TRUST_INI_PREFIX="{trust_ini_prefix}"

source "$EXEC_ROOT/{build_script}"

# --- 收集构建产物 ---
echo "=== 收集构建产物 ==="
mkdir -p "$EXEC_ROOT/$(dirname {bootloader_img_out})"
mkdir -p "$EXEC_ROOT/$(dirname {idbloader_out})"
mkdir -p "$EXEC_ROOT/$(dirname {miniloader_out})"
cp "$BOOTLOADER_IMG" "$EXEC_ROOT/{bootloader_img_out}"
cp "$BOOTLOADER_IDBLOADER" "$EXEC_ROOT/{idbloader_out}"
cp "$BOOTLOADER_MINILOADER" "$EXEC_ROOT/{miniloader_out}"

echo "=== Bootloader 构建完成 ==="
""".format(
        src_root = src_root,
        patch_cmds = patch_cmds if patch_cmds else "",
        defconfig = ctx.attr.defconfig,
        jobs = str(ctx.attr.jobs) if ctx.attr.jobs > 0 else "$(nproc)",
        firmware_dir = ("$EXEC_ROOT/" + firmware_root) if firmware_root else "",
        ini_prefix = ctx.attr.ini_prefix,
        trust_ini_prefix = ctx.attr.trust_ini_prefix if ctx.attr.trust_ini_prefix else ctx.attr.ini_prefix,
        build_script = build_script.path,
        bootloader_img_out = bootloader_img.path,
        idbloader_out = idbloader.path,
        miniloader_out = miniloader.path,
    )

    ctx.actions.run_shell(
        outputs = [bootloader_img, idbloader, miniloader],
        inputs = src_files + firmware_files + all_patches + [build_script],
        command = script,
        mnemonic = "BootloaderBuild",
        progress_message = "编译 Bootloader: {} + {}".format(
            bootloader_img.short_path,
            miniloader.short_path,
        ),
        execution_requirements = {
            "no-sandbox": "1",
            "no-remote": "1",
        },
    )

    return [DefaultInfo(files = depset([bootloader_img, idbloader, miniloader]))]

bootloader_build = rule(
    implementation = _bootloader_build_impl,
    attrs = {
        "bootloader_src": attr.label(
            mandatory = True,
            doc = "Bootloader 源码 filegroup（来自 bootloader_source repository rule）",
        ),
        "build_script": attr.label(
            mandatory = True,
            allow_single_file = [".sh"],
            doc = "平台构建脚本，接收 BOOTLOADER_DIR/BOOTLOADER_DEFCONFIG/BOOTLOADER_JOBS/"
                  + "FIRMWARE_DIR/RKBIN_INI_PREFIX 环境变量，"
                  + "须设置 BOOTLOADER_IMG、BOOTLOADER_IDBLOADER 和 BOOTLOADER_MINILOADER",
        ),
        "firmware_src": attr.label(
            default = None,
            doc = "固件仓库 filegroup（可选，如 Rockchip 的 rkbin）",
        ),
        "defconfig": attr.string(
            mandatory = True,
            doc = "U-Boot defconfig 名称",
        ),
        "ini_prefix": attr.string(
            default = "",
            doc = "rkbin RKBOOT INI 文件前缀（如 RK3566），非 Rockchip 平台留空",
        ),
        "trust_ini_prefix": attr.string(
            default = "",
            doc = "rkbin RKTRUST INI 文件前缀（如 RK3568），留空时使用 ini_prefix",
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
