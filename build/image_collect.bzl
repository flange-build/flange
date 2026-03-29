"""镜像产物收集 — 将构建产物复制到 target/<board>/image/ 目录"""

def _image_collect_impl(ctx):
    all_files = []
    all_files.extend(ctx.attr.image.files.to_list())
    all_files.extend(ctx.attr.boot.files.to_list())
    all_files.extend(ctx.attr.bootloader.files.to_list())
    all_files.extend(ctx.attr.rootfs.files.to_list())

    extra_files = []
    if ctx.attr.partition_config:
        extra_files = ctx.attr.partition_config.files.to_list()

    board = ctx.var.get("board", "unknown")

    commands = [
        "#!/bin/bash",
        "set -xe",
        'cd "$BUILD_WORKSPACE_DIRECTORY"',
        "",
        'BOARD="{}"'.format(board),
        'BUILD_DATE="$(date +%Y%m%d)"',
        'TARGET_DIR="target/$BOARD/image"',
        'rm -rf "$TARGET_DIR"',
        'mkdir -p "$TARGET_DIR"',
    ]
    for f in all_files:
        src = '"$0.runfiles/_main/{}"'.format(f.short_path)
        if f.basename == "raw.img":
            commands.append('cp -f {} "$TARGET_DIR/${{BOARD}}_firmware_${{BUILD_DATE}}.img"'.format(src))
        else:
            commands.append('cp -f {} "$TARGET_DIR/{}"'.format(src, f.basename))
    for f in extra_files:
        src = '"$0.runfiles/_main/{}"'.format(f.short_path)
        commands.append('cp -f {} "$TARGET_DIR/{}"'.format(src, f.basename))
    commands.append('echo "=== 产物已收集到 $TARGET_DIR ==="')
    commands.append('ls -lh "$TARGET_DIR"')

    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, "\n".join(commands), is_executable = True)

    runfiles = ctx.runfiles(files = all_files + extra_files)
    return [DefaultInfo(executable = script, runfiles = runfiles)]

image_collect = rule(
    implementation = _image_collect_impl,
    attrs = {
        "image": attr.label(mandatory = True, doc = "镜像构建 target（收集时重命名为 <board>_firmware_<date>.img）"),
        "boot": attr.label(mandatory = True, doc = "boot 分区 target（boot.img）"),
        "bootloader": attr.label(mandatory = True, doc = "Bootloader 构建 target"),
        "rootfs": attr.label(mandatory = True, doc = "Rootfs 构建 target"),
        "partition_config": attr.label(
            default = None,
            doc = "分区配置文件（如 parameter.txt）",
        ),
    },
    executable = True,
)
