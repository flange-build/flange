---
title: flange 知识库
type: index
updated: 2026-05-03
---

# flange 知识库

> 仓库自身的"心智地图"。综合层不复刻代码与 ProjectSpec，
> 只做提炼与交叉引用。**以代码为准**，wiki 可能滞后。
> Schema 与工作流见 [[CLAUDE]]，演进足迹见 [[log]]。

## 从这里开始
- [[架构总览]] — flange 是什么 / 三层结构 / 端到端数据流
- [[lunch-build-flash 流程]] — 一次完整构建刷写
- [[FINAL_CONFIG]] — 配置如何流转
- [[内容哈希与增量构建]] — 为什么改一行不会全量重建
- [[recovery 系统]] — 独立 rootfs + boot-once + USB 在线刷写
- [[OpenSpec 工作流]] — 变更管理流程

## 组件 (components/)
- [[kernel 构建器]] · [[bootloader 构建器]] · [[rootfs 构建器]] · [[recovery 构建器]] · [[image 构建器]] · [[app 打包系统]]

## 平台 (platforms/)
- [[rockchip 平台]] — RK3566 已落地
- [[allwinnera733 平台]] — Radxa Cubie A7Z，进行中

## 板子 (boards/)
- [[radxa-zero3w]]（首个打样） · [[tspi-rk3566]] · [[neons-core3566-nanob]] · [[orangepi-cm4]] · [[radxa-cubie-a7z]]

## 关键概念 (concepts/)
- 配置：[[三层继承]] · [[condition-markers]] · [[product-variant]]
- 缓存：[[内容哈希与增量构建]] · [[Merkle 哈希]] · [[rootfs 两阶段缓存]]
- 启动：[[U-Boot 启动链]] · [[双 extlinux 配置]] · [[boot-once 启动切换]] · [[reboot reason]]
- 刷写：[[flash-config.json]] · [[FlashStrategy 抽象]] · [[分区表系统]] · [[USB 线刷协议]]
- 内核：[[out-of-tree 模块]]
- Recovery：[[recovery 系统]] · [[recoveryctl 协议]]

## 子系统 (subsystems/)
- [[配置子系统]] · [[构建引擎 BuildEngine]] · [[ComponentBuilder 基类]] · [[Docker 执行封装]] · [[源码管理 SourceManager]]
- [[缓存系统]] · [[chroot 上下文]] · [[deb 打包引擎]] · [[输出系统 BuildOutput]] · [[scaffold 生成器]]
- [[路径锚点 paths]] · [[recovery-host-CLI]]

## 端到端流程 (workflows/)
- [[lunch-build-flash 流程]] · [[recovery 在线刷写流程]] · [[scaffold 新建 app 流程]] · [[external_apps 装载]]
- [[新增板级支持]] · [[新增平台支持]] · [[OpenSpec 工作流]]

## App (apps/)
- [[recoveryctl]] · [[adbd]] · [[flange-rootfs-grow]]

## 项目演进
- [[路线图与历史演进]] — v1 Bazel → v2 Python 概要 + 当前节点
- 设计决策档案：直接读 `openspec/changes/` 与 `git log`；本 wiki 不复刻
