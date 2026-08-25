# platform-abstraction Specification

## Purpose
flange 的平台抽象层契约：`builder/config/registry.py` 自动发现 `components/platform/*/config.jsonnet` 与 `components/platform/*/*/config.jsonnet`；`builder/engine.py` 通过 `config["platform"]` 动态 import `builder.platforms.<platform>` 模块获取 ARTIFACT_NAMES 与 `create_builder`；`builder/flash.py` 的 `FlashStrategy` 接口驱动 pre_flash 配置生成，避免引擎/配置生成层出现平台硬编码分支。

## Requirements
### Requirement: 配置注册表自动发现平台
`builder/config/registry.py` 必须（SHALL）通过扫描 `components/platform/*/config.jsonnet` 自动发现所有可用平台，不得使用硬编码的平台映射表。

#### Scenario: 新增平台自动识别
- **WHEN** `components/platform/allwinnera733/config.jsonnet` 存在且 manifest 的 `platform` 为 `allwinnera733`
- **THEN** `_load_platform_config("allwinnera733")` 成功返回平台配置字典

#### Scenario: 现有 Rockchip 平台兼容
- **WHEN** `components/platform/rockchip/config.jsonnet` 保持不变
- **THEN** `_load_platform_config("rockchip")` 返回与重构前完全相同的配置

#### Scenario: 不存在的平台报错
- **WHEN** 请求加载一个不存在的平台 `"qualcomm"`
- **THEN** 抛出 `ValueError` 且错误信息包含平台名

#### Scenario: 旧平台名不再可识别
- **WHEN** 请求加载旧平台名 `"allwinner"`
- **THEN** 抛出 `ValueError`，错误信息提示可用平台列表中包含 `allwinnera733` 而不包含 `allwinner`

### Requirement: 配置注册表自动发现 SoC
`builder/config/registry.py` 必须（SHALL）通过扫描 `components/platform/*/soc_name/config.jsonnet` 自动发现所有可用 SoC，不得使用硬编码的 SoC 映射表。SoC 目录的 parent 目录名确定其所属平台。

#### Scenario: 新增 SoC 自动识别
- **WHEN** `components/platform/allwinnera733/a733/config.jsonnet` 存在且 manifest 的 `soc` 为 `a733`
- **THEN** `_load_soc_config("a733")` 成功返回 SoC 配置字典

#### Scenario: 现有 RK3566 SoC 兼容
- **WHEN** `components/platform/rockchip/rk3566/config.jsonnet` 保持不变
- **THEN** `_load_soc_config("rk3566")` 返回与重构前完全相同的配置

### Requirement: 产物映射由平台定义
`builder/engine.py` 的产物名映射（`_ARTIFACT_NAMES`）必须（SHALL）从各平台模块获取，不得硬编码于 engine 中。

#### Scenario: Rockchip 产物映射
- **WHEN** 构建 Rockchip 平台组件
- **THEN** engine 使用 `builder.platforms.rockchip.ARTIFACT_NAMES` 中定义的映射规则

#### Scenario: Allwinner A733 产物映射
- **WHEN** 构建 `allwinnera733` 平台组件
- **THEN** engine 使用 `builder.platforms.allwinnera733.ARTIFACT_NAMES` 中定义的映射规则

#### Scenario: 未定义的产物 key 使用原始文件名
- **WHEN** 平台的 ARTIFACT_NAMES 中未包含某 (component, key) 对
- **THEN** engine 使用源文件的原始文件名作为目标文件名

### Requirement: Flash 配置生成无平台硬编码
`FlashConfigGenerator.generate()` 必须（SHALL）通过 `FlashStrategy` 接口获取 pre_flash 配置，不得包含 `if platform == "xxx"` 形式的平台判断。

#### Scenario: Rockchip pre_flash 配置
- **WHEN** 生成 Rockchip 平台的 flash-config.json
- **THEN** `RockchipFlashStrategy.generate_pre_flash_config()` 返回包含 `download_boot: "bootloader/miniloader.bin"` 的配置

#### Scenario: Allwinner A733 pre_flash 配置
- **WHEN** 生成 `allwinnera733` 平台的 flash-config.json
- **THEN** `AllwinnerA733FlashStrategy.generate_pre_flash_config()` 返回空的 `PreFlashConfig`（SD 卡模式无需 pre_flash）
