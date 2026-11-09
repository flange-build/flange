## ADDED Requirements

### Requirement: 发行版声明 init 系统
每个发行版策略 MUST 声明 init 系统（`systemd` 或 `openrc`）与默认包格式；未声明时 MUST 视为 `systemd`/`deb`，
保持 Ubuntu 现有行为。

#### Scenario: Ubuntu 默认
- **WHEN** 目标未选择外部发行版
- **THEN** init 系统为 systemd，App 默认打包为 DEB，构建命令序列与变更前一致

### Requirement: service App 按目标 init 提供服务文件
`app.type=service` 的 App MUST 至少声明一种 init 的服务文件（`systemd.unit` 或 `openrc.script`）；
为某目标构建时 MUST 存在该目标 init 对应的文件，否则构建失败并指出缺失项。

#### Scenario: 仅有 systemd unit 的 App 用于 OpenRC 目标
- **WHEN** service App 只声明 `systemd.unit`，目标发行版 init 为 openrc
- **THEN** App 构建失败，错误指出需要 `openrc.script`

### Requirement: 设备操作按 init 系统生成
`flange app run/log/debug` 对 service App MUST 使用 App 报告记录的 init 系统生成设备命令：
systemd 使用 `systemctl`/`journalctl`，OpenRC 使用 `rc-service` 与服务日志文件。

#### Scenario: OpenRC 重启服务
- **WHEN** 对 OpenRC 目标执行 `flange app run <service>`
- **THEN** 设备上执行 `rc-service <name> restart`
