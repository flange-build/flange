---
title: 概念索引
type: index
updated: 2026-08-24
---

# 概念索引

跨切的关键概念，按主题分组。

## 架构与组织
- [[架构总览]]
- [[仓库三层结构]]
- [[路线图与历史演进]]

## 配置体系
- [[三层继承]]
- [[FINAL_CONFIG]]
- [[condition-markers]]
- [[product-variant]]

## 缓存与增量
- [[内容哈希与增量构建]]
- [[Merkle 哈希]]
- [[rootfs 两阶段缓存]]

## 启动链
- [[U-Boot 启动链]]
- [[双 extlinux 配置]]
- [[boot-once 启动切换]]
- [[reboot reason]]

## 刷写
- [[flash-config.json]]
- [[FlashStrategy 抽象]]
- [[分区表系统]]
- [[USB 线刷协议]]

## 内核与模块
- [[out-of-tree 模块]]
- [[硬件特性包]]
- [[Cardputer USB 复合设备]] — GUD 显示、HID 键盘与 UAC1 音频的复合设备 host 契约
- [[Tab5 USB 复合终端]] — GUD、HID、UAC1 与 UVC 合用一根 USB-C 线
- [[sec_ts 触摸 a7a 供电欠压]] — a7a 魅族 E3 触摸不可用真根因＝硬件开机浪涌欠压，软件无解

## AMP / 协处理器
- [[AMP 协处理器与 rpmsg]] — cpu3 切 AArch32 当从核 + Linux↔AMP rpmsg 链路三约束

## Recovery
- [[recovery 系统]]
- [[recoveryctl 协议]]
