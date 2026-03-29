"""rkbin 固件仓库拉取 — repository rule，从 git 仓库浅克隆 Rockchip 预编译固件"""

def _rkbin_source_impl(ctx):
    ctx.report_progress("克隆 rkbin 固件仓库: {} @ {}".format(ctx.attr.remote, ctx.attr.branch))

    result = ctx.execute(
        ["git", "clone", "--depth=1", "--branch", ctx.attr.branch, ctx.attr.remote, "src"],
        timeout = 1800,
        environment = {
            "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new",
        },
    )
    if result.return_code != 0:
        fail("git clone 失败:\n" + result.stderr)

    # 仅导出 Makefile 作为依赖标记
    # rkbin 无 Makefile，使用 README 或目录标记
    ctx.file("BUILD.bazel", content = """\
# 由 rkbin_source repository rule 自动生成
filegroup(
    name = "src",
    srcs = ["src/RKBOOT/.placeholder"],
    visibility = ["//visibility:public"],
)
""")

    # 创建占位文件确保 filegroup 有效
    ctx.execute(["touch", "src/RKBOOT/.placeholder"])

rkbin_source = repository_rule(
    implementation = _rkbin_source_impl,
    attrs = {
        "remote": attr.string(mandatory = True, doc = "Git 仓库 URL"),
        "branch": attr.string(mandatory = True, doc = "Git 分支名"),
    },
)
