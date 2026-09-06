# rootfs-auto-grow Specification

## Purpose

定义 rootfs「初始镜像小、首次启动扩容」的契约：初始镜像大小从哪里来、raw 镜像的初始分区布局、首启动扩容如何触发，以及可增长布局必须通过的校验。

## Requirements
### Requirement: Rootfs 初始镜像大小
构建系统必须（SHALL）支持在 rootfs 分区 entry 中声明 `image_size`，用于控制构建产物中的
`rootfs.img` 文件系统大小。`image_size` 必须（MUST）支持 `M`/`G` 后缀，并允许沿用现有分区
`size` 字段的十六进制 sector 表达。

#### Scenario: remaining 分区使用 image_size 构建 rootfs
- **WHEN** rootfs 分区配置为 `size: "remaining"` 且 `image_size: "2G"`
- **THEN** `flange build rootfs` 生成的 `rootfs.img` 初始大小为 2GB
- **AND** rootfs 分区的最终设备容量语义仍为 `remaining`

#### Scenario: 未配置 image_size 保持兼容
- **WHEN** rootfs 分区配置为 `size: "remaining"` 且未声明 `image_size`
- **THEN** 构建系统继续按兼容默认值生成当前大小的 `rootfs.img`

#### Scenario: rootfs 内容超过 image_size
- **WHEN** rootfs 目录实际内容加保留余量超过 `image_size`
- **THEN** rootfs 构建失败并提示增大 `image_size`

### Requirement: Raw 镜像初始分区布局
整盘镜像构建必须（SHALL）在 raw.img 的 GPT 中使用 rootfs entry 的 `image_size` 作为初始
rootfs 分区大小。若 `size` 为 `remaining`，该配置仅表示设备首次启动后扩容的最终目标，不得强制 raw.img
在构建阶段展开到完整剩余空间。

#### Scenario: raw.img 使用小 rootfs 分区
- **WHEN** rootfs 分区配置为 `size: "remaining"`、`image_size: "2G"`
- **THEN** raw.img 中 rootfs GPT 分区的初始大小为 2GB
- **AND** raw.img 总大小按初始分区布局计算，不再因 `remaining` 固定展开到 4GB

#### Scenario: 分区镜像写入初始分区
- **WHEN** image 构建器把 `rootfs/rootfs.img` 写入 raw.img
- **THEN** 写入偏移使用 rootfs 分区 offset
- **AND** `rootfs.img` 大小不得超过 rootfs 初始 GPT 分区大小

### Requirement: Rootfs 首次启动自动扩容
启用 `grow_on_first_boot` 的 normal rootfs 必须（SHALL）包含首次启动扩容服务。该服务必须（MUST）在
normal 系统启动后修复 GPT backup header、扩展 rootfs 分区，并执行 ext4 在线扩容。

#### Scenario: 首次启动扩展到磁盘末尾
- **WHEN** 设备从小 raw.img 首次启动到 normal 系统
- **THEN** 扩容服务执行 `sgdisk -e` 修复 GPT backup header
- **AND** 执行 `growpart` 扩展 rootfs 分区到磁盘末尾
- **AND** 执行 `resize2fs` 扩展 rootfs ext4 文件系统

#### Scenario: 扩容成功后保持幂等
- **WHEN** 首次启动扩容成功完成
- **THEN** 系统写入 `/var/lib/flange/rootfs-grown` marker
- **AND** 后续启动不重复执行扩容动作

#### Scenario: 扩容失败后可重试
- **WHEN** 首次启动扩容在写入 marker 前失败
- **THEN** systemd 服务返回失败状态
- **AND** 下次启动仍会再次尝试扩容

### Requirement: 可增长 rootfs 布局校验
配置校验必须（SHALL）拒绝不安全的可增长 rootfs 布局，避免首次启动扩容覆盖其它分区。

#### Scenario: 可增长 rootfs 必须是最后一个非 raw 分区
- **WHEN** rootfs 分区配置为 `grow_on_first_boot: True` 且 `size: "remaining"`
- **THEN** 配置校验确认 rootfs 是 `partitions.entries` 中最后一个非 raw 分区

#### Scenario: rootfs 后存在其它非 raw 分区
- **WHEN** rootfs 分区配置为 `grow_on_first_boot: True` 且 rootfs 后还有其它非 raw 分区
- **THEN** 配置校验失败并提示 rootfs 必须位于最后

#### Scenario: 固定分区 image_size 不得超过 size
- **WHEN** rootfs 分区配置为固定 `size` 且声明 `image_size`
- **THEN** 配置校验确认 `image_size` 不大于固定分区大小
