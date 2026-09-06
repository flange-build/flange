# image-build-rule Specification

## Purpose

定义整机镜像装配的框架/策略分离契约：哪些步骤对所有平台一致由框架实现，
平台差异通过哪几个声明位表达。

## Requirements

### Requirement: 整机装配由公共框架实现

整机 GPT 镜像的装配 SHALL 由 `GptImageBuilder` 一份实现完成：按分区表算出
总容量、建空镜像、写 GPT 分区表、把各分区镜像 dd 到对应偏移。平台子类
MUST NOT 复制整段装配流程。

这份编排此前在各平台各抄一份，AST 归一化对比显示 761 行中 261 行是冗余，
且 7 组同名函数中 5 组已经漂移 —— 漂移的代价不是重复，而是基类新增的能力
接不上抄件（`raw` 分区过滤、稀疏 dd 只在其中一个平台上生效）。

#### Scenario: 平台不重写装配流程
- **WHEN** 新增一个平台的 image 构建器
- **THEN** 它继承 `GptImageBuilder`，只覆写声明位，不实现 `compile`

#### Scenario: 命令序列可回归
- **WHEN** 修改公共装配实现
- **THEN** 各平台发出的命令序列有 golden 快照逐条比对

### Requirement: 平台差异通过声明位表达

平台差异 SHALL 只通过以下声明位表达：

- `PARTITION_IMAGES` / `_partition_images(config)`：分区名 → 产物相对路径。
  可按配置路由（UBI / recovery 开关等）。
- `ROOTFS_PARTUUID`：给 rootfs 分区钉固定 PARTUUID，供 kernel cmdline 的
  `root=PARTUUID=` 引用；`None` 表示不钉。
- `_gpt_partition_ops(entry, index, device)`：某分区在 `mkpart` 之后的额外
  GPT 操作（ESP 标记、Type-UUID 伪装等启动固件 quirk）。
- `SECTOR_SIZE` / `partitions.sector_size`：目标介质的逻辑块大小。

#### Scenario: 分区产物映射按配置路由
- **WHEN** rootfs 的 `image_format` 为 `ubi`
- **THEN** 平台的 `_partition_images` 返回 `rootfs.ubi` 而不是 `rootfs.img`

#### Scenario: 启动固件 quirk
- **WHEN** 某平台的固件要求 ESP 分区带特定 Type-UUID
- **THEN** 该平台在 `_gpt_partition_ops` 中补充，而不是改公共的 `_write_gpt`

### Requirement: raw 分区不进 GPT 分区表

`type == "raw"` 表示"这块区域不是文件系统，直接 dd 裸数据"。框架 SHALL
把这类分区排除出 GPT 分区表 —— 建成 GPT 分区 —— 建了会占用分区号，并给固件一个不存在的文件系统
分区。这条规则对所有平台一致，MUST 由框架统一执行。

#### Scenario: raw 分区只被 dd
- **WHEN** 分区表含 `idbloader`（type=raw）
- **THEN** 它的镜像被 dd 到对应偏移，但不出现在任何 `mkpart` 命令中

### Requirement: 几何解析只发生一次

偏移与大小 MUST 由 `PartitionLayout` 从配置解析一次，装配侧与刷写侧共享
同一份结果。消费方 MUST NOT 自行解析 `partitions.entries` 里的字符串。

分区表是"镜像怎么装配"与"设备怎么刷写"共同的契约；两侧各算一次的后果是
算出不同的偏移，刷进去起不来，而且要到真刷机那一刻才发现。

#### Scenario: 4K 介质换算
- **WHEN** `partitions.sector_size` 为 4096
- **THEN** 按 512B 声明的偏移与大小统一换算到 4K 扇区，且换算只在一处完成

#### Scenario: flash-config 与 GPT 一致
- **WHEN** 同一份配置分别生成 raw.img 的 GPT 与 flash-config.json
- **THEN** 两者记录的每个分区偏移与大小相同

### Requirement: 分区镜像超出分区大小时明确失败

把某个分区镜像 dd 进整机镜像之前 MUST 校验它不超过该分区的初始大小，
超出 SHALL 报出分区名、实际大小与上限。

静默截断的后果是文件系统损坏，而现象是"随机的启动失败"。

#### Scenario: 镜像过大
- **WHEN** rootfs.img 大于 rootfs 分区的 `image_size`
- **THEN** 构建失败并指出应增大 `image_size` 或分区 `size`

### Requirement: 稀疏写入

各分区镜像 dd 进整机镜像 SHALL 使用稀疏写入并保证不截断已写入的 GPT 与
前序分区。

rootfs.img 的声明尺寸远大于实占（实测 8GiB 声明只用 2.7GiB），写全零块
既慢又让 raw.img 本身失去稀疏性。

#### Scenario: 稀疏且不截断
- **WHEN** 把 rootfs.img dd 进 raw.img
- **THEN** 使用 `conv=notrunc,sparse`

### Requirement: 产出整机 raw.img

装配 SHALL 产出 `raw.img`：含分区表与全部分区数据的完整磁盘镜像，可直接
dd 写入存储设备。

#### Scenario: raw.img 可直接刷写
- **WHEN** 将 raw.img 通过 `dd` 写入 SD 卡
- **THEN** 目标设备可正常启动
