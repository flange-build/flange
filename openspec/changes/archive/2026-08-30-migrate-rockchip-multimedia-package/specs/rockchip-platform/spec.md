## ADDED Requirements

### Requirement: 支持的 RK35xx board SHALL 显式启用本地多媒体 package

现有 RK3566、RK3568、RK3576、RK3582、RK3588 与 RK3588S board MUST 在 board 层通过顶层 `packages` opt-in
`rockchip-multimedia`。对应 SoC 配置 MUST NOT 再注入 `common.multimediaDebs`，共享配置 MUST NOT 保留远程 release DEB、
`force_overwrite` 或 `hold_packages` 描述。

#### Scenario: RK3588 board 解析本地 package

- **WHEN** 解析 `radxa-rock5b-default-debug` 或 `orangepi-5-plus-default-debug`
- **THEN** 顶层 `packages` 含 `rockchip-multimedia`
- **AND** `rootfs.custom_packages` 含其多 DEB 构建 App 与 udev 配置 App
- **AND** `rootfs.extra_debs` 不含旧 `CmST0us/rockchip-multimedia-ubuntu` URL

#### Scenario: 新 board 不隐式继承

- **WHEN** 新增相同 SoC 但未 opt-in `rockchip-multimedia` 的 board
- **THEN** 该 board 不构建或安装多媒体 package
