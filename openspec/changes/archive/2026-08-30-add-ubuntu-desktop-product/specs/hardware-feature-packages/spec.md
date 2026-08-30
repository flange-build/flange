## ADDED Requirements

### Requirement: component package MAY 携带通用 Jsonnet 配置

具有合法 `package.py` 清单的 `components/packages/<pkg>/` MAY 同时提供 `config.jsonnet`。board 通过顶层 `packages` 直接 opt-in 该包时，配置注册表 MUST 将其作为 board 后置 overlay 求值；未选择该包时 MUST NOT 求值或应用该文件。

#### Scenario: 选中带配置的 package

- **WHEN** board 的最终 `packages` 包含 `ubuntu-desktop` 且该目录含 `config.jsonnet`
- **THEN** `config.jsonnet` 的 rootfs 与分区 overlay 出现在 canonical 配置中

#### Scenario: 未选中 package

- **WHEN** board 的最终 `packages` 不包含 `ubuntu-desktop`
- **THEN** `components/packages/ubuntu-desktop/config.jsonnet` 不进入 Jsonnet 依赖集合
- **AND** canonical 配置不包含其新增策略

### Requirement: package Jsonnet 源 SHALL 遵循配置安全边界

package 的 `config.jsonnet` MUST 位于对应 package 目录内，第一条非空内容 MUST 是中文职责注释，并 MUST 通过现有 Jsonnet import 白名单和 canonical validator。引用不存在 package 或缺少合法 `package.py` MUST 继续使配置解析失败。

#### Scenario: package config 尝试越界 import

- **WHEN** package config 使用绝对路径或 `..` 越过 `components/`
- **THEN** Jsonnet 求值失败且错误指出 import 越过允许根目录

### Requirement: desktop package SHALL 作为标准 vendor App 插接

`ubuntu-desktop` package MUST 通过 `package.py` 的 `vendor` component 注册本地 App，App 目录 MUST 包含可由现有 `AppSpec` 和 `AppBuilder` 直接处理的 `app.yaml`，不得为 desktop 引入旁路安装格式。

#### Scenario: 展开 desktop package

- **WHEN** board 直接启用 `ubuntu-desktop`
- **THEN** canonical 配置将 `flange-ubuntu-desktop-config` 注册到 `external_apps` 与 `rootfs.custom_packages`
- **AND** 该 App 的 locale 文件与 systemd unit 通过现有 DebBuilder 打包安装

### Requirement: vendor GStreamer 版本 SHALL 在 desktop rootfs 中保留

Rockchip vendor GStreamer deb 与 Ubuntu 拆分包文件重叠时，构建 MUST 仅对显式声明的 vendor deb
启用 dpkg overwrite，并 MUST 锁定 vendor 包及发生重叠的已安装 Ubuntu 包。其他 `extra_debs` MUST
继续使用 dpkg 默认的冲突拒绝行为。

#### Scenario: Ubuntu Desktop 已安装同版本拆分包

- **WHEN** Phase 1 已安装 Ubuntu `gstreamer1.0-tools`、`plugins-base-apps` 和 `libgstreamer-*` 拆分包
- **THEN** Phase 2 成功安装 Rockchip patched GStreamer 1.24.2 deb
- **AND** 相关已安装包被 APT hold，后续升级不得覆盖 vendor 文件
