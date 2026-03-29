"""内核产物收集 — 将构建产物复制到 target/<board>/kernel/ 目录"""

def _kernel_collect_impl(ctx):
    kernel_files = ctx.attr.kernel.files.to_list()
    # TODO: flange 脚手架完成后，从 --define 读取 product/variant，
    # 拼成 target/<board>/<product>/<variant>/kernel/
    board = ctx.var.get("board", "unknown")

    commands = [
        "#!/bin/bash",
        "set -xe",
        'cd "$BUILD_WORKSPACE_DIRECTORY"',
        "",
        'TARGET_DIR="target/{}/kernel"'.format(board),
        'mkdir -p "$TARGET_DIR"',
    ]
    for f in kernel_files:
        src = '"$0.runfiles/_main/{}"'.format(f.short_path)
        if f.basename == "dtbos.tar.gz":
            commands.append('mkdir -p "$TARGET_DIR/dtbos"')
            commands.append('tar -xzf {} -C "$TARGET_DIR/dtbos"'.format(src))
        elif f.basename.endswith(".tar.gz"):
            commands.append('tar -xzf {} -C "$TARGET_DIR"'.format(src))
        else:
            commands.append('cp -f {} "$TARGET_DIR/{}"'.format(src, f.basename))
    commands.append('echo "=== 产物已收集到 $TARGET_DIR ==="')
    commands.append('ls -la "$TARGET_DIR"')

    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, "\n".join(commands), is_executable = True)

    runfiles = ctx.runfiles(files = kernel_files)
    return [DefaultInfo(executable = script, runfiles = runfiles)]

kernel_collect = rule(
    implementation = _kernel_collect_impl,
    attrs = {
        "kernel": attr.label(mandatory = True, doc = "内核构建 target"),
    },
    executable = True,
)
