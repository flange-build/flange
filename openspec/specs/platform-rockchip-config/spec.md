# platform-rockchip-config Specification

## Purpose

定义 Rockchip 平台层与 SoC 层配置 overlay 的职责边界：哪些事实属于"整个
平台共有"，哪些属于"这颗芯片特有"，以及两层如何组合。

## Requirements

### Requirement: Rockchip 平台层 overlay 声明平台共有事实

`components/platform/rockchip/config.jsonnet` MUST 声明整个 Rockchip 平台
共有的事实：`platform`、`vendor`、三个 `architecture` 字段、可用
`products` / `variants`、`flash_tool`，以及平台层共享的 `sources`。

平台层 MUST NOT 声明任何单颗 SoC 才成立的值 —— 放上来的后果是所有 SoC
都继承到一个只对其中一颗正确的默认值，而且不会报错。

#### Scenario: 平台身份与刷写工具
- **WHEN** 求值 Rockchip 平台 overlay
- **THEN** 包含 `platform: "rockchip"`、`vendor: "rockchip"` 与 `flash_tool`

#### Scenario: 三个架构在平台层声明
- **WHEN** 求值 Rockchip 平台 overlay
- **THEN** `architecture` 同时包含 `userspace`、`kernel` 与 `bootloader`
- **AND** `bootloader` 可与 `kernel` 不同（Rockchip 的 bootloader 有 32 位阶段）

#### Scenario: 平台层共享源码
- **WHEN** 多颗 SoC 使用同一份 rkbin / U-Boot 仓库
- **THEN** 该 source 在平台层 `sources` 中声明一次，SoC 层不重复声明

### Requirement: SoC 层 overlay 声明芯片特有事实

`components/platform/rockchip/<soc>/config.jsonnet` MUST 声明该芯片的
`soc` 标识与所属 `platform`，以及芯片级的 Kconfig、设备树目录与固件参数。

SoC 层与平台层同名字段冲突时，SoC 层 MUST 以 overlay 语义覆盖，而不是让
board 层重复声明一遍。

#### Scenario: SoC 身份
- **WHEN** 求值 RK3566 的 SoC overlay
- **THEN** 包含 `soc: "rk3566"` 与 `platform: "rockchip"`

#### Scenario: 芯片与 BootROM 标签不一致
- **WHEN** 某颗 SoC 的 BootROM 把自己识别成另一个型号（RK3566 与 RK3568 同 die）
- **THEN** SoC overlay 显式声明打包用的 chip 标签，而不是从 `soc` 推导

#### Scenario: board 不重复 SoC 事实
- **WHEN** board 与同 SoC 其他 board 使用相同的芯片级配置
- **THEN** board overlay 不重复声明，最终配置从 SoC overlay 继承

### Requirement: 平台数据与平台逻辑分离

平台层的**数据**（patches、配置清单、SoC 子目录）MUST 位于
`components/platform/<平台>/`；平台的**构建逻辑** MUST 位于
`builder/platforms/<平台>/`。补丁的归属规则见 `repo-layout`。

#### Scenario: 平台补丁归属
- **WHEN** Rockchip 平台需要一个影响所有 SoC 的内核补丁
- **THEN** 补丁位于 `components/platform/rockchip/patches/`，而不是 `builder/` 下

#### Scenario: 平台构建逻辑归属
- **WHEN** Rockchip 需要平台特有的镜像装配逻辑
- **THEN** 逻辑位于 `builder/platforms/rockchip/image.py`，与数据分开维护
