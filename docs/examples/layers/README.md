# Debian 13 多层验证

本示例把 BSP、公共 App/Package、Debian 发行版/环境/SDK、产品分别放在四个独立层中。
`prepare.py` 将它们复制到仓库外，产品目录同时作为工作区及最高层；基础仓库无需放置产品私有内容。
层清单同时演示多个依赖。该示例验证用户态闭环，没有为真实硬件提供内核或 bootloader。

在 flange 工具根执行：

```sh
# 基础构建镜像提供已有的 gcc10。
flange docker build
docker pull --platform linux/arm64 debian:trixie-slim
.venv/bin/python -m docs.examples.layers.prepare /absolute/new-workspace --tool-root "$PWD"
flange -C /absolute/new-workspace/product target select layerdemo-minimal-release
flange -C /absolute/new-workspace/product layer check
flange -C /absolute/new-workspace/product docker build
flange -C /absolute/new-workspace/product app build layer-check
.venv/bin/python -m docs.examples.layers.validate /absolute/new-workspace/product
```

`prepare.py` 要求新目录，不覆盖已有工作区。它将本地 Debian arm64 镜像导出为基础归档，
保存源镜像身份和 SHA256，并更新工作区副本中的 `base.libsonnet`。
源示例中的全零摘要是待准备占位符，不能直接构建。

验证脚本通过所选环境执行真实 App 构建及公共 rootfs 配方。内核模块为空目录、DT overlay 无输入，
两者是显式的用户态测试夹具，不能据此宣称硬件可引导或执行 `flange build image`。
脚本不会访问设备或刷写。它会：

1. 编译 `layer-lib` 共享库及依赖它的 `layer-check`，后者还动态链接 libc、zlib。
2. 生成运行 DEB 和开发 DEB；再次构建检查 App 缓存命中。
3. 由直接启用的 `layer-suite` Package 将应用闭包安装到 Debian rootfs。
4. 用 QEMU/chroot 实际运行 `layer-check`，检查 `answer=42 zlib=...`。
5. 生成 512 MiB ext4，运行 `e2fsck -fn`，用 debugfs 检查镜像内应用。
6. 检查扩展层输入没有被构建改写，保存 `.build/debian-evidence.json`。

Debian 构建环境的 SDK 独立于最终 rootfs，以 Debian arm64 开发包生成。
`/opt/flange-sdk-metadata/` 保存包版本与下载摘要，实际镜像摘要进入缓存和 App ABI 身份。
此示例不实现远端版本锁定；重新准备镜像时 Debian 安全更新可能改变包版本和镜像身份。

2026-09-06 实测通过：Debian 13/trixie、AArch64，环境为 linux/amd64 Docker；
低层 gcc 10.5.0 与用户态 gcc 14.2.0 共存。目标运行输出：

```text
layer-check: answer=42 zlib=1.3.1
```

实测 SDK 的 libc6/libc6-dev 为 `2.41-12+deb13u3`，zlib 为
`1:1.3.dfsg+really1.3.1-1+b1`，linux-libc-dev 为 `6.12.107-1`。
完整验证身份见同目录 [verification.json](verification.json)；它是本次运行记录，不是跨环境固定的期望摘要。
