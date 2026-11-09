## ADDED Requirements

### Requirement: 服务管理不假定 systemd
usbmoded 启停 adbd 等能力服务时 MUST 按运行环境选择服务管理后端：systemd 系统使用 `systemctl`，
OpenRC 系统使用 `rc-service`；仅在存在 `NOTIFY_SOCKET` 时发送 sd_notify。

#### Scenario: OpenRC 下启用 adb
- **WHEN** usbmoded 在 OpenRC 系统中切换到含 adb 的模式
- **THEN** 通过 `rc-service usbmoded-adbd start` 启动 adbd，且不因缺少 systemctl 报错
