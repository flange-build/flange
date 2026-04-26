---
title: flash-config.json
type: concept
status: stable
sources:
  - builder/flash.py
  - roadmap.md
related:
  - "[[FlashStrategy 抽象]]"
  - "[[image 构建器]]"
  - "[[lunch-build-flash 流程]]"
updated: 2026-04-26
---

## TL;DR

构建时由 `FlashConfigGenerator` 从 `partitions.entries` 生成的 JSON 文件；刷写时由 `FlashExecutor` 读取，驱动平台工具按分区写入镜像。替代了过去的偏移硬编码与两套刷写体系。

## 关键设计要点

- **生成时机**：`engine.py` 在 image 组件构建完成后自动生成 `flash-config.json`，落于 `.build/target/<board>/<product>/<variant>/`
- **数据模型字段**：`platform`、`flash_tool`、`board`、`product`、`variant` + `partitions[]`（含 name/offset/type/image 路径/protected 标记）+ `pre_flash.download_boot`（miniloader 路径）
- **offset 语义**：LBA 扇区偏移（十六进制字符串），Rockchip `upgrade_tool WL` 直接消费
- **protected 标记**：raw 类型分区及 `recovery.protected_partitions` 中的分区设为 true；刷写时跳过或要求二次确认
- **宿主机消费**：`FlashExecutor.run()` 读取 JSON，调用平台 `FlashStrategy` 执行；支持全量刷写与单分区 `flange flash <name>`

## 关键代码位置

- [`builder/flash.py:FlashConfig`](../../builder/flash.py) — 数据模型，L86
- [`builder/flash.py:FlashPartition`](../../builder/flash.py) — 分区条目，L67
- [`builder/flash.py:FlashConfig.to_json / from_json`](../../builder/flash.py) — 序列化，L96 / L103

## 延伸阅读

- [[FlashStrategy 抽象]]
- [[分区表系统]]
- [[lunch-build-flash 流程]]
