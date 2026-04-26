## MODIFIED Requirements

### Requirement: Recovery Enter
`flange recovery enter` 必须（SHALL）在 normal 系统 USB ADB 在线时请求设备通过
Linux reboot reason 切换下一次启动到 recovery 并重启；如果设备已在 recovery
模式，则必须直接成功返回。该命令不得（MUST NOT）依赖持久修改
`extlinux.conf` 的 `DEFAULT` 行来表达 recovery 请求。

#### Scenario: normal 系统进入 recovery
- **WHEN** normal 系统通过 ADB 在线且用户执行 `flange recovery enter`
- **THEN** host 调用设备端 `recoveryctl recovery`
- **AND** 设备传递 `reboot("recovery")` 并等待 recovery ADB 重新上线

#### Scenario: 已在 recovery
- **WHEN** 设备已经处于 recovery 模式
- **THEN** `flange recovery enter` 返回成功且不重复重启

### Requirement: Recovery Reboot
`flange recovery reboot` 必须（SHALL）默认清理可选 boot-once 请求并重启设备回到
normal 系统。命令必须支持显式目标 `normal`、`recovery` 和 `loader`；目标为
`recovery` 或 `loader` 时必须通过 Linux reboot reason 请求对应模式。

#### Scenario: 重启到 normal
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot`
- **THEN** host 调用设备端 `recoveryctl normal`
- **AND** 设备清理可选 boot-once 请求后重启

#### Scenario: 重启回 recovery
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot recovery`
- **THEN** host 调用设备端 `recoveryctl recovery`
- **AND** 设备传递 `reboot("recovery")`

#### Scenario: 进入 loader
- **WHEN** 用户执行 `flange recovery reboot loader`
- **THEN** host 调用设备端 `recoveryctl loader`
- **AND** 设备传递 `reboot("loader")`
