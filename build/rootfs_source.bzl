"""Rootfs 源码拉取 — repository rule，从 HTTP 下载 ubuntu-base tarball"""

def _rootfs_source_impl(ctx):
    ctx.report_progress("下载 ubuntu-base tarball: {}".format(ctx.attr.url))

    ctx.download(
        url = ctx.attr.url,
        output = "ubuntu-base.tar.gz",
        sha256 = ctx.attr.sha256 if ctx.attr.sha256 else "",
    )

    ctx.file("BUILD.bazel", content = """\
# 由 rootfs_source repository rule 自动生成
exports_files(["ubuntu-base.tar.gz"], visibility = ["//visibility:public"])
""")

rootfs_source = repository_rule(
    implementation = _rootfs_source_impl,
    attrs = {
        "url": attr.string(mandatory = True, doc = "ubuntu-base tarball 下载 URL"),
        "sha256": attr.string(default = "", doc = "tarball SHA256 校验值（可选）"),
    },
)
