## ADDED Requirements

### Requirement: vendor component MAY 交付多 DEB 构建单元

硬件特性包的 `vendor` component MAY 引用声明 `build.deb_outputs` 的本地 App。包展开 MUST 将该 App 注册到 `external_apps`
与 `rootfs.custom_packages`，并将 App 目录中的脚本、补丁、udev 规则和清单全部纳入 app 内容哈希。

#### Scenario: 展开 Rockchip 多媒体构建单元

- **WHEN** board 的 `packages` 包含 `rockchip-multimedia`
- **THEN** 多媒体构建 App 与 udev 配置 App 均进入 `rootfs.custom_packages`
- **AND** 多媒体构建 App 的多个 DEB 通过既有 app→rootfs 流水线安装

#### Scenario: 未启用 package

- **WHEN** board 未声明 `rockchip-multimedia`
- **THEN** 该 package 不注册 App、不构建 DEB，也不改变 rootfs 软件集合
