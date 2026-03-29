"""内核源码拉取 — repository rule，从 git 仓库浅克隆内核源码"""

def _kernel_source_impl(ctx):
    ctx.report_progress("克隆内核源码: {} @ {}".format(ctx.attr.remote, ctx.attr.branch))

    result = ctx.execute(
        ["git", "clone", "--depth=1", "--branch", ctx.attr.branch, ctx.attr.remote, "src"],
        timeout = 1800,
        environment = {
            "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new",
        },
    )
    if result.return_code != 0:
        fail("git clone 失败:\n" + result.stderr)

    # 仅导出 Makefile 作为依赖标记，避免对 70k+ 内核文件执行 glob
    # 源码通过 repository rule 固定，变更需 bazel sync 触发重新拉取
    ctx.file("BUILD.bazel", content = """\
# 由 kernel_source repository rule 自动生成
filegroup(
    name = "src",
    srcs = ["src/Makefile"],
    visibility = ["//visibility:public"],
)
""")

kernel_source = repository_rule(
    implementation = _kernel_source_impl,
    attrs = {
        "remote": attr.string(mandatory = True, doc = "Git 仓库 URL"),
        "branch": attr.string(mandatory = True, doc = "Git 分支名"),
    },
)
