---
title: flash-config.json
type: concept
status: stable
sources:
  - builder/flash.py
  - builder/platforms/rockchip/image.py
related:
  - "[[FlashStrategy 抽象]]"
  - "[[image 构建器]]"
  - "[[lunch-build-flash 流程]]"
updated: 2026-07-14
---

## TL;DR

构建期生成、宿主机刷写期消费的不可变契约。它把板级身份、存储模型、parameter 摘要、分区容量和镜像路径绑定到同一 target，避免拿旧布局或错误板型执行持久写入。

## 关键设计要点

- **生成时机**：`engine.py` 在 image 组件构建完成后自动生成 `flash-config.json`，落于 `.build/target/<board>/<product>/<variant>/`
- **基础字段**：`platform/soc/board/product/variant`、`flash_tool`、`sector_size`、`storage/storage_type`、`partition_format`
- **布局字段**：`partitions[]` 含 name/offset/size/type/image/protected；SPI NAND 另带 `parameter`、`parameter_sha256`、`storage_size`、`rootfs_mtd_index`
- **身份字段**：`identity.chip_patterns/storage_patterns/require_rid`；Rockchip 在 `UL/DI/WL` 前用 RCI/RFI/RID 匹配，且要求只连接一台设备
- **offset 语义**：LBA 扇区偏移（十六进制字符串），Rockchip `upgrade_tool WL` 直接消费
- **protected 标记**：raw 类型分区及 `recovery.protected_partitions` 中的分区设为 true；刷写时跳过或要求二次确认
- **宿主机消费**：`FlashExecutor.run()` 读取 JSON，调用平台 `FlashStrategy` 执行；支持全量刷写与单分区 `flange flash <name>`
- **原子性**：JSON 先写同目录临时文件、`fsync` 后原子替换；生成失败直接令 image build 失败，不留下半写配置

## 关键代码位置

- [`builder/flash.py:FlashConfig`](../../builder/flash.py) — 数据模型，L86
- [`builder/flash.py:FlashPartition`](../../builder/flash.py) — 分区条目，L67
- [`builder/flash.py:FlashConfig.to_json / from_json`](../../builder/flash.py) — 序列化，L96 / L103

## 延伸阅读

- [[FlashStrategy 抽象]]
- [[分区表系统]]
- [[lunch-build-flash 流程]]
