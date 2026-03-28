### Requirement: Rockchip 平台级配置声明
`platform/rockchip/config.bzl` SHALL 导出 `ROCKCHIP_PLATFORM` dict，包含 Rockchip 平台通用的配置值，至少包括 `vendor` 和 `flash_tool` 字段。

#### Scenario: 平台配置包含 vendor 标识
- **WHEN** 查看 `ROCKCHIP_PLATFORM` dict
- **THEN** 包含 `"vendor": "rockchip"`

#### Scenario: 平台配置包含刷写工具声明
- **WHEN** 查看 `ROCKCHIP_PLATFORM` dict
- **THEN** 包含 `"flash_tool"` 字段，值为 Rockchip 平台对应的刷写工具名称

### Requirement: RK3566 SoC 级配置声明
`platform/rockchip/rk3566/config.bzl` SHALL 导出 `RK3566_SOC` dict，包含 RK3566 芯片特有的配置值，至少包括 `soc`、`arch` 字段，并声明所属 platform。

#### Scenario: SoC 配置包含芯片标识
- **WHEN** 查看 `RK3566_SOC` dict
- **THEN** 包含 `"soc": "rk3566"` 和 `"arch": "aarch64"`

#### Scenario: SoC 配置声明所属平台
- **WHEN** 查看 `RK3566_SOC` dict
- **THEN** 包含 `"platform": "rockchip"`

### Requirement: platform 目录仅含配置声明文件
`platform/rockchip/` 及其子目录 SHALL 仅包含 `.bzl` 配置文件和必要的 `BUILD.bazel` 包声明文件，MUST NOT 包含补丁、脚本、数据文件等非配置资源。

#### Scenario: platform 目录无数据文件
- **WHEN** 查看 `platform/rockchip/` 目录树
- **THEN** 仅有 `config.bzl`、`BUILD.bazel` 和子目录（如 `rk3566/`），不存在 `patches/`、`scripts/` 等目录
