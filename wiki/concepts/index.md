---
title: 概念索引
type: index
updated: 2026-09-05
---

# 概念索引

先读[架构总览](架构总览.md)、[工作区路径](仓库三层结构.md)与[目标维度](product-variant.md)，
再按所需主题深入。操作见[开发指南](../../docs/development-guide.md)，扩展见[扩展指南](../../docs/extension-guide.md)。

## 架构与组织
- [架构总览](架构总览.md)
- [仓库三层结构](仓库三层结构.md)
- [路线图与历史演进](路线图与历史演进.md)

## 配置体系
- [三层继承](三层继承.md)
- [FINAL_CONFIG](FINAL_CONFIG.md)
- [condition-markers](condition-markers.md)
- [product-variant](product-variant.md)

## 缓存与增量
- [内容哈希与增量构建](内容哈希与增量构建.md)
- [Merkle 哈希](Merkle-哈希.md)
- [rootfs 两阶段缓存](rootfs-两阶段缓存.md)

## 启动链
- [U-Boot 启动链](U-Boot-启动链.md)
- [双 extlinux 配置](双-extlinux-配置.md)
- [boot-once 启动切换](boot-once-启动切换.md)
- [reboot reason](reboot-reason.md)

## 刷写
- [flash-config.json](flash-config-json.md)
- [FlashStrategy 抽象](FlashStrategy-抽象.md)
- [分区表系统](分区表系统.md)
- [USB 线刷协议](USB-线刷协议.md)

## 内核与模块
- [out-of-tree 模块](out-of-tree模块.md)
- [硬件特性包](硬件特性包.md)
- [Cardputer USB 复合设备](cardputer-usb复合设备.md) — GUD 显示、HID 键盘与 UAC1 音频的复合设备 host 契约
- [Tab5 USB 复合终端](tab5-usb复合终端.md) — GUD、HID、UAC1 与 UVC 合用一根 USB-C 线
- [sec_ts 触摸 a7a 供电欠压](sec_ts触摸a7a供电欠压.md) — a7a 魅族 E3 触摸不可用真根因＝硬件开机浪涌欠压，软件无解

## AMP / 协处理器
- [AMP 协处理器与 rpmsg](AMP-协处理器与rpmsg.md) — cpu3 切 AArch32 当从核 + Linux↔AMP rpmsg 链路三约束

## Recovery
- [recovery 系统](recovery-系统.md)
- [recoveryctl 协议](recoveryctl-协议.md)
