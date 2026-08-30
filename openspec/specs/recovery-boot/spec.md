# recovery-boot Specification

## Purpose

定义 recovery 从构建到启动的契约：分区配置、镜像构建组件与依赖、boot 分区如何同时提供 normal 与 recovery 入口、默认项如何切换，以及 recovery 如何进入整盘镜像与 flash-config。

## Requirements
### Requirement: Recovery 分区配置
平台或 SoC 配置必须（SHALL）能够声明 `recovery` 分区。启用 recovery 的 target 必须（MUST）在 `partitions.entries` 中包含名称为 `recovery` 的 ext4 分区，且该分区必须有明确 offset 和 size。

#### Scenario: 启用 recovery 的分区表
- **WHEN** 解析启用 recovery 的 target 配置
- **THEN** `partitions.entries` 包含 `name == "recovery"`、`type == "ext4"`、非空 `offset` 和非空 `size`

#### Scenario: recovery 分区缺失
- **WHEN** target 配置声明 `recovery.enabled == True` 但分区表中没有 `recovery`
- **THEN** 构建配置校验失败，错误信息包含 `recovery` 分区缺失

### Requirement: Recovery 镜像构建组件
构建系统必须（SHALL）提供 `recovery` 组件，产出 `recovery/recovery.img`。该镜像必须（MUST）基于 Ubuntu base 构建，文件系统 label 必须为 `recovery`，并包含 `adbd`、`recoveryctl` 和分区维护工具。

#### Scenario: 构建 recovery 组件
- **WHEN** 执行 `flange build recovery`
- **THEN** 构建系统生成 `.build/target/<board>/<product>/<variant>/recovery/recovery.img`

#### Scenario: recovery 镜像内容
- **WHEN** 检查 `recovery.img` 的 rootfs 内容
- **THEN** 镜像内包含 `/usr/bin/recoveryctl`、`adbd` 运行文件、`/etc/flange/recovery-config.json` 和基础分区工具

### Requirement: Recovery 构建依赖
`recovery` 组件必须（SHALL）依赖 `kernel` 和 `app`。当 kernel 模块或 recovery 所需 App 发生变化时，`recovery` 组件必须重新构建。

#### Scenario: kernel 变化触发 recovery 重建
- **WHEN** kernel 组件内容哈希变化
- **THEN** `recovery` 组件的内容哈希随之变化并触发重建

#### Scenario: recovery App 变化触发 recovery 重建
- **WHEN** `adbd` 或 `recoveryctl` App 内容变化
- **THEN** `recovery` 组件的内容哈希随之变化并触发重建

### Requirement: Boot 分区提供 normal 和 recovery 启动入口
启用 recovery 的 target 必须（SHALL）在 boot 分区中生成
`/extlinux/extlinux.conf` 和 `/extlinux/recovery.conf`。normal 配置必须启动
`rootfs`，recovery 配置必须启动 `recovery` 分区，并携带
`flange.mode=recovery`。当 target 声明 `boot.overlays.enabled` 时，两份配置必须（MUST）应用同一组默认 Device Tree Overlay（设备树覆盖），并保持相同顺序。

#### Scenario: boot 分区包含两份配置
- **WHEN** 构建启用 recovery 的 boot 分区镜像
- **THEN** `/extlinux/extlinux.conf` 存在并只描述 normal 启动
- **AND** `/extlinux/recovery.conf` 存在并只描述 recovery 启动

#### Scenario: recovery 配置指向 recovery rootfs
- **WHEN** 检查 `/extlinux/recovery.conf` 的 kernel append 参数
- **THEN** 参数包含指向 recovery 分区的 root 定位信息
- **AND** 参数包含 `flange.mode=recovery`

#### Scenario: recovery 配置继承默认 overlay
- **WHEN** 启用 recovery 的 target 声明 `boot.overlays.enabled == ["i2c1.dtbo", "display.dtbo"]`
- **THEN** `/extlinux/extlinux.conf` 包含按顺序引用 `i2c1.dtbo` 和 `display.dtbo` 的 `fdtoverlays` 行
- **AND** `/extlinux/recovery.conf` 包含按相同顺序引用 `i2c1.dtbo` 和 `display.dtbo` 的 `fdtoverlays` 行

### Requirement: Recovery Boot 默认项切换
系统必须（SHALL）提供 bootloader 支持，使 U-Boot 在 sysboot 前根据
reboot reason 或可选 `flange_boot_once=recovery` 选择本次读取
`extlinux.conf` 或 `recovery.conf`。该状态必须（MUST）按 one-shot 语义消费；
后续无显式请求时默认回到 normal 配置。

#### Scenario: reboot recovery 选择 recovery.conf
- **WHEN** kernel reboot-mode 将启动原因设置为 recovery
- **THEN** U-Boot 本次 sysboot 读取 `/extlinux/recovery.conf`
- **AND** 启动原因被清除或失效

#### Scenario: boot-once env 选择 recovery.conf
- **WHEN** U-Boot 读取到 `flange_boot_once=recovery`
- **THEN** U-Boot 本次 sysboot 读取 `/extlinux/recovery.conf`
- **AND** `flange_boot_once` 被清除或失效

#### Scenario: 无一次性请求时启动 normal
- **WHEN** U-Boot 未读取到 recovery boot reason 或 boot-once env
- **THEN** U-Boot sysboot 读取 `/extlinux/extlinux.conf`

### Requirement: Recovery 纳入整盘镜像
整盘镜像构建必须（SHALL）把 `recovery/recovery.img` 写入 `recovery` 分区，并在 GPT 中创建对应分区条目。

#### Scenario: raw.img 包含 recovery 分区
- **WHEN** 执行 `flange build`
- **THEN** 生成的 `raw.img` 包含 `recovery` GPT 分区，且该分区内容来自 `recovery/recovery.img`

### Requirement: Recovery 纳入 flash-config
`flash-config.json` 必须（SHALL）包含 `recovery` 分区到 `recovery/recovery.img` 的映射，使宿主机分区级刷写能够刷写 recovery 镜像。

#### Scenario: flash-config 包含 recovery
- **WHEN** image 构建完成并生成 `flash-config.json`
- **THEN** `partitions` 列表中包含 `name == "recovery"` 且 `image == "recovery/recovery.img"`

### Requirement: Recovery 配置嵌入
recovery 镜像必须（SHALL）包含 `/etc/flange/recovery-config.json`。该文件必须记录 board、product、variant、分区布局、分区保护策略和首版 USB transport。

#### Scenario: recovery-config 内容
- **WHEN** 读取 recovery 镜像内的 `/etc/flange/recovery-config.json`
- **THEN** 文件包含当前 target 的 board、product、variant、partitions 和 transport 字段

