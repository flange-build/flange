## MODIFIED Requirements

### Requirement: Boot 分区提供 normal 和 recovery 启动入口
启用 recovery 的 target 必须（SHALL）在 boot 分区中生成
`/extlinux/extlinux.conf` 和 `/extlinux/recovery.conf`。normal 配置必须启动
`rootfs`，recovery 配置必须启动 `recovery` 分区，并携带
`flange.mode=recovery`。

#### Scenario: boot 分区包含两份配置
- **WHEN** 构建启用 recovery 的 boot 分区镜像
- **THEN** `/extlinux/extlinux.conf` 存在并只描述 normal 启动
- **AND** `/extlinux/recovery.conf` 存在并只描述 recovery 启动

#### Scenario: recovery 配置指向 recovery rootfs
- **WHEN** 检查 `/extlinux/recovery.conf` 的 kernel append 参数
- **THEN** 参数包含指向 recovery 分区的 root 定位信息
- **AND** 参数包含 `flange.mode=recovery`

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
