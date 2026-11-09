## Context

ROCK 5B 已启用 `rockchip-multimedia` 本地构建包。RK3588 SoC 配置通过 `rk3588_panthor.config`
关闭 BSP GPU；板级已有将 GPU compatible 改为 `arm,mali-valhall` 的 overlay。
BSP defconfig 已启用 CSF、MPP 和 MULTI_RGA。

## Goals / Non-Goals

目标：提供独立 `rockmedia` 产品，包含厂商 GPU、现有媒体栈及检查工具，支持 debug/release。
非目标：GNOME 默认桌面、完整 SDK 分发、未经实机验证的硬件性能承诺。

## Decisions

- 在板级 product 条件中移除 Panthor fragment，并通过已有 `kernel.config` 显式启用 Bifrost CSF、
  禁用 Panthor/Panfrost/旧 Mali 驱动，启用已有 compatible overlay。无新增引擎字段。
- 新建 `rockchip-mali-g610` 本地 vendor package。固定上游 g24p0 X11/Wayland/GBM DEB 的 URL 和
  SHA-256，只提取用户态文件，由 flange 的默认 DEB 后端生成自有包；不直接安装上游 DEB。
- 保留上游私有 `mali/` wrapper（封装库）、GBM hook（兼容层）、动态链接器路径及 ICD（驱动加载描述），
  避免与 Ubuntu 的 EGL/GLES/GBM 文件争用。自有维护脚本运行 ldconfig，保留版权文件。
- 固件使用 BSP 内核自带 CSF firmware 编译注入，丢弃上游 DEB 中另一版本的固件，避免跨版本混用。
- 多媒体运行库继续使用现有固定版本本地构建链。增加 clinfo、mesa-utils、v4l-utils、libdrm-tests；
  编译开发优先使用 flange App 的构建 sysroot，不混装发行版 GStreamer dev 包覆盖自编版本。

## Risks / Trade-offs

- DDK（驱动开发套件）内核/用户态 ABI 和显示输出需要实机确认 → 文档列出 mali0、EGL、OpenCL、MPP 验收。
- 厂商 OpenGL 能力与 Mesa 不同 → 将产品定位于 EGL/GLES、多媒体开发，不承诺 GNOME 或桌面 OpenGL 兼容。
- 上游二进制供应和许可 → 固定摘要，保留版权及来源，下载失败早失败。

## Migration Plan

选择新 target 后构建完整镜像；更新现有设备时同时更新 boot 和 rootfs。回退时重新构建并成套刷写原产品。
禁止仅修改 overlay 作为 GPU 驱动切换。
