---
title: Docker 构建环境
type: subsystem
status: stable
sources:
  - docker/Dockerfile
  - docker/apt/ubuntu.sources
  - docker/meson/cross-aarch64.ini
  - docker/meson/cross-armhf.ini
  - builder/app.py#L38
  - builder/app.py#L53
related:
  - "[[Docker 执行封装]]"
updated: 2026-05-17
---

## TL;DR

容器内**已就位**的工具链与跨架构能力，是所有 app/kernel/u-boot 构建的隐式契约。运行时路由（DockerRunner）见 [[Docker 执行封装]]，本页只列**装了什么**。

## 关键设计要点

- **交叉编译器**：aarch64 走 `gcc-aarch64-linux-gnu`；armhf 走 `gcc-arm-linux-gnueabihf`（hard-float，对应 `_CROSS_COMPILE_PREFIX["armhf"] = arm-linux-gnueabihf-`）；`crossbuild-essential-armel` 沿历史保留（armel = soft-float 老 ABI，与 armhf 是两套）
- **C/C++ 构建系统**：`cmake`、`meson`、`ninja-build`、`pkg-config`、`ccache`；对应 `builder/app.py:53` 的 `_BUILD_SYSTEMS` 模板
- **APT sources**：默认 ubuntu.sources 被 `docker/apt/ubuntu.sources` 替换——`archive.ubuntu.com` 显式限 `amd64`，追加 `ports.ubuntu.com` 服务 `arm64/armhf`。不替换的话 multiarch 启用后 `apt update` 对 arm64 索引发 404
- **dpkg multiarch**：默认启用 `arm64` 与 `armhf`，可 `apt install <pkg>:arm64` / `:armhf` 获取交叉编译用的 `*-dev` 包；预装最小骨架 `libc6-dev:arm64` / `libc6-dev:armhf`
- **meson cross-file**：`/etc/meson/cross-aarch64.ini` 与 `/etc/meson/cross-armhf.ini` 由 Dockerfile `COPY docker/meson/*.ini` 投放，**源文件落仓**，可审可改；meson 模板默认引用 aarch64 那个
- **kernel/u-boot 编译副产物**：`bc bison cpio flex kmod libelf-dev libssl-dev …`（沿用现有），未改动
- **Allwinner 32-bit 工具运行**：`lib32stdc++6 lib32z1`（沿用）
- **调试**：`gdb-multiarch` 已装；on-device gdbserver / launch.json 链路是后续 change

## 关键代码位置

- [`docker/Dockerfile`](../../docker/Dockerfile) — 镜像定义
- [`docker/apt/ubuntu.sources`](../../docker/apt/ubuntu.sources) — 替换默认 ubuntu sources，amd64 + ports（arm64/armhf）分离
- [`docker/meson/cross-aarch64.ini`](../../docker/meson/cross-aarch64.ini) — meson aarch64 cross-file
- [`docker/meson/cross-armhf.ini`](../../docker/meson/cross-armhf.ini) — meson armhf cross-file
- [`builder/app.py:53`](../../builder/app.py#L53) — `_BUILD_SYSTEMS` 命令模板
- [`builder/app.py:38`](../../builder/app.py#L38) — `_CROSS_COMPILE_PREFIX` 架构→前缀表

## 易踩坑

- 写 C++ app 用 cmake/meson 时，**产物默认落在 `build/` 子目录**，但 `collect_files` 只识别约定子目录（`bin/ lib/ include/ …`）；scaffold 模板的 `install(...)` 是死代码——见 [[scaffold 生成器]] 的"易踩坑"段
- `_BUILD_SYSTEMS` 模板里 `"-j$(nproc)"` 是 shell 字面占位，`_build_commands` 末尾会做 `$(nproc) → os.cpu_count()` 替换（[builder/app.py:863 附近](../../builder/app.py#L863)）；不经此替换 cmake/make 会把 `$(nproc)` 当字面字符串报 `invalid number`
- `apt install foo-dev` 默认装 amd64 host 包，**对交叉编译无用**；要装 `foo-dev:arm64` / `:armhf`
- 没装 `crossbuild-essential-arm64`（只有 `-armel`，沿历史），单装的 `gcc-aarch64-linux-gnu` + multiarch `libc6-dev:arm64` 已够用；armhf 走 `gcc-arm-linux-gnueabihf` 而非 `crossbuild-essential-armel`（armel ≠ armhf，前者 soft-float 老 ABI）
