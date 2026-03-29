"""Rootfs 产物收集 — 将构建产物复制到 target/<board>/rootfs/ 目录"""

def _rootfs_collect_impl(ctx):
    rootfs_files = ctx.attr.rootfs.files.to_list()
    board = ctx.var.get("board", "unknown")

    commands = [
        "#!/bin/bash",
        "set -xe",
        'cd "$BUILD_WORKSPACE_DIRECTORY"',
        "",
        'TARGET_DIR="target/{}/rootfs"'.format(board),
        'mkdir -p "$TARGET_DIR"',
    ]
    for f in rootfs_files:
        src = '"$0.runfiles/_main/{}"'.format(f.short_path)
        commands.append('cp -f {} "$TARGET_DIR/{}"'.format(src, f.basename))
    commands.append('echo "=== 产物已收集到 $TARGET_DIR ==="')
    commands.append('ls -la "$TARGET_DIR"')

    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, "\n".join(commands), is_executable = True)

    runfiles = ctx.runfiles(files = rootfs_files)
    return [DefaultInfo(executable = script, runfiles = runfiles)]

rootfs_collect = rule(
    implementation = _rootfs_collect_impl,
    attrs = {
        "rootfs": attr.label(mandatory = True, doc = "Rootfs 构建 target"),
    },
    executable = True,
)
