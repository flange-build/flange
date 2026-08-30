# hardware-feature-packages Specification

## Purpose

定义硬件特性包的契约：包清单格式、board 如何 opt-in、包内组件如何按类型分发到既有流水线、按需编译，以及包内容如何纳入增量哈希。

## Requirements
### Requirement: 包清单契约

每个硬件特性包 MUST 位于 `components/packages/<pkg>/` 目录，并 MUST 提供一个 `package.py`，导出名为 `PACKAGE` 的 dict。`PACKAGE` MUST 包含 `name`（kebab-case 字符串，MUST 与目录名一致）与 `components`（列表）。`components` 中每一项 MUST 是 dict 且 MUST 含 `type` 字段，`type` 的取值 MUST 属于 `oot-driver` / `devicetree` / `deb` 之一；未知 `type` MUST 使构建失败并在错误信息中给出该 `type` 与候选集合。

#### Scenario: 合法包清单被加载

- **WHEN** `components/packages/foo/package.py` 导出 `PACKAGE = {"name": "foo", "components": [{"type": "oot-driver", "name": "bar", "dir": "driver/bar", "ko_pattern": ["bar.ko"]}]}`
- **THEN** 构建系统成功加载该包并识别出 1 个 `oot-driver` 类型 component

#### Scenario: 未知 component 类型

- **WHEN** 某 component 的 `type` 为 `firmware`（不在合法集合内）
- **THEN** 构建失败
- **AND** 错误信息包含非法值 `firmware` 与候选集合 `oot-driver` / `devicetree` / `deb`

#### Scenario: name 与目录名不一致

- **WHEN** `components/packages/foo/package.py` 的 `PACKAGE["name"]` 为 `bar`
- **THEN** 构建失败
- **AND** 错误信息指出 `name` 与目录名不一致

### Requirement: board opt-in 启用包

board 配置 MUST 通过 `packages` 字段 opt-in 启用包。`packages` 的每一项 MAY 是字符串（包名，取该包对此 board 的默认启用集），或 MAY 是 dict（含 `name` 及可选的按类型启用子集，如 `drivers`）。未声明 `packages` 或为空时，board 的构建行为 MUST 与不启用任何包保持一致（向后兼容）。引用不存在的包 MUST 使构建失败并给出包名。

#### Scenario: 字符串形式启用整包

- **WHEN** board 配置 `packages: ["meizu-e3-panel"]`
- **THEN** 构建系统加载 `meizu-e3-panel` 包并启用其对此 board 声明的默认 component 集

#### Scenario: dict 形式按需选驱动

- **WHEN** board 配置 `packages: [{"name": "meizu-e3-panel", "drivers": ["sec_ts"]}]`
- **THEN** 仅 `sec_ts` 这个 `oot-driver` 被纳入编译
- **AND** 同包内未被选中的 `oot-driver`（如 `sgm37604a`）MUST NOT 被编译

#### Scenario: 引用不存在的包

- **WHEN** board 配置 `packages: ["does-not-exist"]`
- **THEN** 构建失败
- **AND** 错误信息包含包名 `does-not-exist`

#### Scenario: 未声明 packages 保持兼容

- **WHEN** board 配置未声明 `packages` 或为空列表
- **THEN** kernel / boot / rootfs 组件保持现有不启用包时的构建行为

### Requirement: 按类型分发到既有流水线

构建引擎 MUST 按 component 的 `type` 把包内容分发到对应的既有构建流水线：`oot-driver` MUST 复用 OOT 模块编译与安装路径（`make M=<本地包目录>` → strip → 装入 `lib/modules/.../updates/`）；`devicetree` MUST 复用 device-tree-overlay 的 cpp+dtc 流水线产出 `.dtbo`；`deb` MUST 复用 rootfs deb 安装路径。`oot-driver` 的源目录 MUST 解析为包内本地路径，MUST NOT 要求声明 git 源。

#### Scenario: oot-driver 编译并安装

- **WHEN** 启用的包含 `oot-driver` 名为 `sec_ts`、`dir: "driver/sec_ts"`、`ko_pattern: ["sec_ts.ko"]`
- **THEN** 构建系统在 `components/packages/<pkg>/driver/sec_ts` 处以 `make M=` 对内核源码树编译
- **AND** 产出的 `sec_ts.ko` 经 strip 安装到 `lib/modules/<release>/updates/`

#### Scenario: devicetree 编译为 dtbo

- **WHEN** 启用的包含 `devicetree` component，且其对当前 board 声明了对应 `.dtso`
- **THEN** 该 `.dtso` 经 cpp+dtc 编译为 `.dtbo` 并纳入 boot 分区 overlay 打包集合

### Requirement: 按需编译

`oot-driver` 类型 MUST 支持按需编译：仅当某 board 的启用配置实际选中该驱动时才编译。包内携带但未被任何启用配置选中的 `oot-driver` MUST NOT 被编译，也 MUST NOT 安装其 `.ko`。

#### Scenario: 未选中的驱动不编译

- **WHEN** `meizu-e3-panel` 包内含 `sec_ts` 与 `sgm37604a` 两个 `oot-driver`，board 仅选中 `sec_ts`
- **THEN** `sgm37604a` MUST NOT 被编译
- **AND** rootfs 的 `lib/modules/<release>/updates/` 不包含 `sgm37604a.ko`

### Requirement: 包内容纳入增量哈希

启用包的 board，其包目录内容（驱动源、dtso、固件等被启用 component 涉及的文件）MUST 纳入对应组件（kernel / boot / rootfs）的内容哈希。包内被启用内容变更 MUST 触发相应组件的增量重建；未启用 component 的内容变更 MUST NOT 触发重建。

#### Scenario: 驱动源变更触发 kernel 重建

- **WHEN** 已启用 `sec_ts` 的 board 修改了 `components/packages/meizu-e3-panel/driver/sec_ts` 内任一源文件
- **THEN** 下次构建 kernel 组件因内容哈希变化而重建该 OOT 模块

#### Scenario: dtso 变更触发 boot 重建

- **WHEN** 已启用 panel overlay 的 board 修改了对应 `.dtso`
- **THEN** 下次构建 boot/device-tree-overlay 组件因内容哈希变化而重新编译该 `.dtbo`

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

