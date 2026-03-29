"""内核产物收集 — 将构建产物复制到 target/kernel/ 目录"""

def _kernel_collect_impl(ctx):
    kernel_files = ctx.attr.kernel.files.to_list()

    # 生成收集脚本
    commands = [
        "#!/bin/bash",
        "set -xe",
        'cd "$BUILD_WORKSPACE_DIRECTORY"',
        "mkdir -p target/kernel",
    ]
    for f in kernel_files:
        src = '"$0.runfiles/_main/{}"'.format(f.short_path)
        if f.basename.endswith(".tar.gz"):
            # tarball 解压到 target/kernel/
            commands.append("tar -xzf {} -C target/kernel".format(src))
        else:
            commands.append("cp -f {} target/kernel/{}".format(src, f.basename))
    commands.append('echo "=== 产物已收集到 target/kernel/ ==="')
    commands.append("ls -la target/kernel/")

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
