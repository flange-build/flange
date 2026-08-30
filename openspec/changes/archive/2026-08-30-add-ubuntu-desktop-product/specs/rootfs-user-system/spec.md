## ADDED Requirements

### Requirement: rootfs SHALL 支持 default_user 的默认图形会话

`rootfs.default_session` SHALL 使用安全的单个 session 名声明 `default_user` 的默认图形会话。设置该字段时
`default_user` MUST 存在；RootfsBuilder MUST 校验对应的 X11 或 Wayland desktop launcher 存在，并将
`XSession=<session>` 写入 `/var/lib/AccountsService/users/<default_user>`。未设置时 MUST 保持 display
manager 的发行版默认行为。

#### Scenario: 为默认用户选择标准 GNOME 会话

- **WHEN** `default_user=flange` 且 `default_session=gnome`
- **THEN** rootfs 构建验证 `gnome.desktop` session launcher 存在
- **AND** `/var/lib/AccountsService/users/flange` 包含 `XSession=gnome`

#### Scenario: 默认会话不存在

- **WHEN** `default_session` 没有对应的 X11 或 Wayland desktop launcher
- **THEN** rootfs 构建失败并指出缺少 session launcher
