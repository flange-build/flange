---
title: 组件索引
type: index
updated: 2026-09-05
---

# 组件索引

系统计划由多个组件组成，依赖由引擎展开；App 构建另有统一闭包。先读[架构总览](../concepts/架构总览.md)。

- [kernel 构建器](kernel-构建器.md) — Linux 内核交叉编译，产出 Image / DTB / modules
- [bootloader 构建器](bootloader-构建器.md) — U-Boot + SPL 编译与平台特定打包（trust.img、loader 等）
- [rootfs 构建器](rootfs-构建器.md) — ubuntu-base + apt + overlay + 自定义 deb 两阶段构建
- [recovery 构建器](recovery-构建器.md) — 独立 recovery rootfs 镜像，含 recoveryctl / adbd
- [image 构建器](image-构建器.md) — 分区聚合 + flash-config.json 生成
- [app 打包系统](app-打包系统.md) — app.yaml → 依赖闭包 → 安装树 → deb 与产物报告
- [amp 构建器](amp-构建器.md) — Rockchip AMP 协处理器固件 amp.img（cmake 构建引用 SDK 的 amp app）
