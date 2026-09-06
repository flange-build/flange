---
title: Docker 构建环境
type: subsystem
status: stable
sources:
  - docker/Dockerfile
  - docker/apt/ubuntu.sources
  - docker/meson/cross-aarch64.ini
  - docker/meson/cross-armhf.ini
  - builder/toolchain.py
  - builder/app_build.py
  - docs/development-guide.md
  - builder/base.py
related:
  - "[[Docker 执行封装]]"
updated: 2026-09-05
---

## TL;DR

容器内**已就位**的工具链与跨架构能力，是app/kernel/u-boot 构建的环境基础。运行时路由（DockerRunner）见 [[Docker 执行封装]]，本页只列**装了什么**。

## 关键设计要点

- **交叉编译器（aarch64 按构建类型分两套）**：**app 构建**走系统 `gcc-aarch64-linux-gnu`（Ubuntu 24.04 = gcc-13，当前 `Toolchain.for_arch("aarch64")` 提供 `aarch64-linux-gnu-` 前缀）；**u-boot/kernel 构建**走 kernel.org crosstool **gcc-10.5**（容器内 `/opt/aarch64-gcc10/bin/aarch64-linux-`，由 `builder/base.py` `ComponentBuilder.CROSS` 全平台默认、各 platform builder 不覆盖；老 rockchip u-boot 用 gcc-13 编会致 RK3576 UFS 崩，详见 [[radxa-rock-4d]]）。armhf 走 `gcc-arm-linux-gnueabihf`（hard-float，当前用户态 Toolchain 提供 `arm-linux-gnueabihf-` 前缀）；`crossbuild-essential-armel` 沿历史保留（armel = soft-float 老 ABI，与 armhf 是两套）
- **C/C++ 构建系统**：`cmake`、`meson`、`ninja-build`、`pkg-config`、`ccache`；当前原生编译/安装命令由 `builder/toolchain.py` 统一生成
- **APT sources**：默认 ubuntu.sources 被 `docker/apt/ubuntu.sources` 替换——`archive.ubuntu.com` 显式限 `amd64`，追加 `ports.ubuntu.com` 服务 `arm64/armhf`。不替换的话 multiarch 启用后 `apt update` 对 arm64 索引发 404
- **dpkg multiarch**：默认启用 `arm64` 与 `armhf`，可 `apt install <pkg>:arm64` / `:armhf` 获取交叉编译用的 `*-dev` 包；预装最小骨架 `libc6-dev:arm64` / `libc6-dev:armhf`
- **meson cross-file**：`/etc/meson/cross-aarch64.ini` 与 `/etc/meson/cross-armhf.ini` 由 Dockerfile `COPY docker/meson/*.ini` 投放，**源文件落仓**，可审可改；当前 App 构建按实际架构与依赖前缀另生成节点独立的 cross-file，不靠固定 aarch64 文件选择目标
- **kernel/u-boot 编译副产物**：`bc bison cpio flex kmod libelf-dev libssl-dev …`（apt 装，沿用现有）；另起独立一层 `curl` 下载 kernel.org crosstool **gcc-10.5**（`x86_64-gcc-10.5.0-nolibc-aarch64-linux.tar.xz`）解包到 `/opt`、`ln` 为 `/opt/aarch64-gcc10`，作 u-boot/kernel 默认工具链（见上「交叉编译器」条）
- **Allwinner 32-bit 工具运行**：`lib32stdc++6 lib32z1`（沿用）
- **调试**：`gdb-multiarch` 已装；当前 CLI 已有设备端 GDB 和 `--mode remote` 的 gdbserver + ADB 转发流程；IDE 配置与完整系统符号仍需额外准备

## 关键代码位置

- [`docker/Dockerfile`](../../docker/Dockerfile) — 镜像定义
- [`docker/apt/ubuntu.sources`](../../docker/apt/ubuntu.sources) — 替换默认 ubuntu sources，amd64 + ports（arm64/armhf）分离
- [`docker/meson/cross-aarch64.ini`](../../docker/meson/cross-aarch64.ini) — meson aarch64 cross-file
- [`docker/meson/cross-armhf.ini`](../../docker/meson/cross-armhf.ini) — meson armhf cross-file
- [`builder/toolchain.py`](../../builder/toolchain.py) — 当前架构、编译器、原生构建与安装命令
- [`builder/app_build.py`](../../builder/app_build.py) — App 隔离执行、依赖前缀与产物发布

## 易踩坑

- 当前 CMake/Meson/Make 会执行原生安装阶段，安装树用于打包；旧版本“install 是死代码”的绕行建议已失效。
- App 构建并行数由 Toolchain 直接生成 argv，不应自行把 Shell 的 `$(nproc)` 字符串当作数字参数传给构建工具。
- `apt install foo-dev` 默认装 amd64 host 包，**对交叉编译无用**；要装 `foo-dev:arm64` / `:armhf`
- 没装 `crossbuild-essential-arm64`（只有 `-armel`，沿历史），单装的 `gcc-aarch64-linux-gnu` + multiarch `libc6-dev:arm64` 已够用；armhf 走 `gcc-arm-linux-gnueabihf` 而非 `crossbuild-essential-armel`（armel ≠ armhf，前者 soft-float 老 ABI）

宿主环境、ARM 宿主运行 amd64 容器、QEMU/binfmt 与大小写敏感工作目录要求见[开发指南](../../docs/development-guide.md)。
