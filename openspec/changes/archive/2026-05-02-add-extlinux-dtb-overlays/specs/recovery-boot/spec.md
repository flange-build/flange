## MODIFIED Requirements

### Requirement: Boot 分区提供 normal 和 recovery 启动入口
启用 recovery 的 target 必须（SHALL）在 boot 分区中生成
`/extlinux/extlinux.conf` 和 `/extlinux/recovery.conf`。normal 配置必须启动
`rootfs`，recovery 配置必须启动 `recovery` 分区，并携带
`flange.mode=recovery`。当 target 声明 `boot.default_overlays` 时，两份配置必须（MUST）应用同一组默认 Device Tree Overlay（设备树覆盖），并保持相同顺序。

#### Scenario: boot 分区包含两份配置
- **WHEN** 构建启用 recovery 的 boot 分区镜像
- **THEN** `/extlinux/extlinux.conf` 存在并只描述 normal 启动
- **AND** `/extlinux/recovery.conf` 存在并只描述 recovery 启动

#### Scenario: recovery 配置指向 recovery rootfs
- **WHEN** 检查 `/extlinux/recovery.conf` 的 kernel append 参数
- **THEN** 参数包含指向 recovery 分区的 root 定位信息
- **AND** 参数包含 `flange.mode=recovery`

#### Scenario: recovery 配置继承默认 overlay
- **WHEN** 启用 recovery 的 target 声明 `boot.default_overlays == ["i2c1.dtbo", "display.dtbo"]`
- **THEN** `/extlinux/extlinux.conf` 包含按顺序引用 `i2c1.dtbo` 和 `display.dtbo` 的 `fdtoverlays` 行
- **AND** `/extlinux/recovery.conf` 包含按相同顺序引用 `i2c1.dtbo` 和 `display.dtbo` 的 `fdtoverlays` 行
