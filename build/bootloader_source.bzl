"""Bootloader 源码拉取 — repository rule，支持远程 git 浅克隆或本地路径 symlink"""

def _bootloader_source_impl(ctx):
    if ctx.attr.local_path:
        # 本地模式：symlink + 变更检测
        local = ctx.path(ctx.attr.local_path)
        if not local.exists:
            fail("本地 Bootloader 源码路径不存在: {}".format(ctx.attr.local_path))

        ctx.symlink(local, "src")

        # 监控 .git/index，git add 后触发 re-fetch
        git_index = local.get_child(".git").get_child("index")
        if git_index.exists:
            ctx.watch(git_index)

        # 每次 fetch 生成新时间戳，强制下游 action 重跑
        res = ctx.execute(["date", "+%s%N"])
        ctx.file(".fetch_stamp", res.stdout.strip())
        ctx.file(".local_mode", "")

        ctx.file("BUILD.bazel", content = """\
# 由 bootloader_source repository rule 自动生成（本地模式）
filegroup(
    name = "src",
    srcs = ["src/Makefile", ".fetch_stamp", ".local_mode"],
    visibility = ["//visibility:public"],
)
""")
    else:
        # 远程模式：浅克隆
        ctx.report_progress("克隆 Bootloader 源码: {} @ {}".format(ctx.attr.remote, ctx.attr.branch))

        result = ctx.execute(
            ["git", "clone", "--depth=1", "--branch", ctx.attr.branch, ctx.attr.remote, "src"],
            timeout = 1800,
            environment = {
                "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new",
            },
        )
        if result.return_code != 0:
            fail("git clone 失败:\n" + result.stderr)

        # 仅导出 Makefile 作为依赖标记，避免对大量源码文件执行 glob
        ctx.file("BUILD.bazel", content = """\
# 由 bootloader_source repository rule 自动生成
filegroup(
    name = "src",
    srcs = ["src/Makefile"],
    visibility = ["//visibility:public"],
)
""")

bootloader_source = repository_rule(
    implementation = _bootloader_source_impl,
    attrs = {
        "remote": attr.string(default = "", doc = "Git 仓库 URL"),
        "branch": attr.string(default = "", doc = "Git 分支名"),
        "commit": attr.string(default = "", doc = "锁定的 commit hash，变更时触发重新拉取"),
        "local_path": attr.string(default = "", doc = "本地源码路径，非空时启用本地模式"),
    },
)
