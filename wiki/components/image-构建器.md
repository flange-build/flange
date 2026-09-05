---
title: image 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/image.py
  - builder/flash/generate.py
  - builder/image.py
  - builder/partition/layout.py
  - builder/partition/rockchip.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[分区表系统]]"
  - "[[flash-config.json]]"
  - "[[lunch-build-flash 流程]]"
updated: 2026-09-05
---

## TL;DR

按存储模型生成最终刷写清单。块设备继续组装 GPT 整盘 `raw.img`；SPI NAND 不伪造块设备镜像，而是从同一 `partitions.entries` 生成 Rockchip `parameter.txt`、分区 manifest 与具名镜像映射。

## 关键设计要点

- **跳过源码阶段**：`build()` 直接调 `compile(None, config)`，跳过 source.ensure/reset/patch
- **分区布局**：共享 `PartitionLayout` 解析 entries 并换算目标介质逻辑扇区；`GptImageBuilder` 装配 GPT 与分区镜像
- **raw 分区**：`type=="raw"`（如 idbloader）不进 GPT 表，仅 dd；GPT 分区按顺序 `parted mkpart`
- **分区顺序**（commit fa745b0）：idbloader → uboot → boot → recovery → rootfs；recovery 在 rootfs 之前
- **产物映射**：`PARTITION_IMAGES` 映射分区名→路径，按当前组件启用状态过滤；启用组件缺少必需产物会失败，不由历史文件存在与否决定启用
- **rootfs PARTUUID**：固定 `"614e0000-0000-4000-8000-000000000000"`，供 kernel cmdline 引用
- **collect**：`{"image": raw_img}`；引擎调用 `FlashConfigGenerator` 生成当前目标的 flash-config.json
- **SPI NAND 路由**：`storage.type=spinand` 时校验总容量与分区边界，生成 `parameter.txt`；`idbloader` 由 `UL` 负责，不再作为具名分区重复写入，rootfs 使用 `rootfs.ubi`
- **单一布局来源**：parameter、manifest 与 `flash-config.json` 都由解析后的 entries 生成；flash-config 记录 parameter SHA-256，刷写前再次交叉校验，拒绝混用旧产物

## 关键代码位置

- [`builder/platforms/rockchip/image.py:RockchipImageBuilder`](../../builder/platforms/rockchip/image.py) — 主类，L25
- [`builder/platforms/rockchip/image.py:compile`](../../builder/platforms/rockchip/image.py) — GPT + dd，L49
- [`builder/platforms/rockchip/image.py:PARTITION_IMAGES`](../../builder/platforms/rockchip/image.py) — 产物路径表，L31

## 易踩坑

- `remaining`、`image_size` 与实际存储容量要共同核对，不能预期刷写工具自动截断镜像来适配小容量设备。
- `parted`/`sfdisk` 须在 Docker 内执行；`self.docker.run` 已封装，勿在宿主机直接调
- SPI NAND 必须走 loader 的坏块感知具名 `DI`，不可按 LBA `WL` 或把 UBI dd 进伪 GPT `raw.img`
