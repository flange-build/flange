---
title: 组件索引
type: index
updated: 2026-04-26
---

# 组件索引

flange 把"可独立构建并落到设备上的产物"称为组件，每个组件由 ComponentBuilder 子类承担。

- [[kernel 构建器]] — Linux 内核交叉编译，产出 Image / DTB / modules
- [[bootloader 构建器]] — U-Boot + SPL 编译与平台特定打包（trust.img、loader 等）
- [[rootfs 构建器]] — ubuntu-base + apt + overlay + 自定义 deb 两阶段构建
- [[recovery 构建器]] — 独立 recovery rootfs 镜像，含 recoveryctl / adbd
- [[image 构建器]] — 分区聚合 + flash-config.json 生成
- [[app 打包系统]] — app.yaml → .deb 流程；6 种构建系统 × 4 种类型
