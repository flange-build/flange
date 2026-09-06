---
title: flange 知识库
type: index
updated: 2026-09-05
---

# flange 知识库

本知识库帮助你从概念找到代码，并查阅具体板卡与硬件专题。
命令完整说明集中在 `docs/`，wiki 保留概念摘要、硬件限制与历史验证记录。

## 按当前任务开始

| 你想完成什么 | 从哪里开始 |
| --- | --- |
| 第一次接触嵌入式 Linux，先跑通一个工程 | [初学指南](../docs/first-steps.md) |
| 查工作区、目标、构建、部署和调试命令 | [开发指南](../docs/development-guide.md) |
| 判断失败发生在哪层、解释缓存和检查产物 | [维护指南](../docs/maintenance-guide.md) |
| 增加 App、驱动 Package、板卡或平台 | [扩展指南](../docs/extension-guide.md) |
| 理解框架各模块的责任 | [架构总览](concepts/架构总览.md) → [构建系统设计](../docs/build-system-design.md) |
| 查手头硬件的差异与已有验收 | [板卡索引](boards/index.md) → 对应板卡页 |

## 按主题查阅

- [概念](concepts/index.md)：工作区、配置、增量构建、启动链与分区。
- [子系统](subsystems/index.md)：计划、缓存、源码、容器、打包和宿主设备服务的代码入口。
- [组件](components/index.md)：kernel、bootloader、rootfs、image、App 与 AMP。
- [工作流](workflows/index.md)：把相关概念接成可执行路径。
- [平台](platforms/index.md)：Rockchip、Allwinner、Amlogic、Qualcomm 的策略差异。
- [板卡](boards/index.md)：板级配置摘要、专属硬件约束和验证记录。
- [App 专题](apps/index.md)：已有应用、系统服务和演示固件。

## 如何判断一段说明是否适用

核心工作区、CLI、计划和缓存页在 2026-09-05 按当前 v3 代码核对。
硬件页中的日期、commit、product、内核和介质限定了当时验证范围；
`status: stable` 表示页面或能力的既有记录，不能推导当前所有组合都通过实机验收。

当前目标以 `flange target list/show` 为准，实际目录以 `flange status` 为准，
刷写分区以 `flange flash --list` 为准。读到冲突时继续查页面列出的源码，
维护时同步修改当前说明；历史细节保留适用版本。

- [ProjectSpec](../ProjectSpec.md)：项目约束。
- [设计评审](../docs/build-system-review.md)：已验证范围及仍有边界。
- [路线图与历史演进](concepts/路线图与历史演进.md)：历史背景。
- [OpenSpec 工作流](workflows/OpenSpec-工作流.md)：变更管理；历史决策保存在仓库 OpenSpec 档案中。
