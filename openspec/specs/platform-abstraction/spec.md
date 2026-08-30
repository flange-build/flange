# platform-abstraction Specification

## Purpose
flange 的平台抽象层契约：`builder/config/registry.py` 自动发现 `components/platform/*/config.jsonnet` 与 `components/platform/*/*/config.jsonnet`；`builder/engine.py` 通过 `config["platform"]` 动态 import `builder.platforms.<platform>` 模块获取 ARTIFACT_NAMES 与 `create_builder`；`builder/flash.py` 的 `FlashStrategy` 接口驱动 pre_flash 配置生成，避免引擎/配置生成层出现平台硬编码分支。
## Requirements
### Requirement: 配置注册表自动发现平台

`builder/config/registry.py` 必须（SHALL）通过扫描 `components/platform/*/config.jsonnet` 自动发现所有可用平台，不得使用硬编码的平台映射表，也不得 import 同目录 Python 配置模块。发现结果 MUST 校验 overlay 中的 platform 身份与目录名一致。

#### Scenario: 新增平台自动识别
- **WHEN** `components/platform/example/config.jsonnet` 存在并声明 `platform: "example"`
- **THEN** 注册表成功发现 `example` 平台

#### Scenario: 现有 Rockchip 平台迁移后兼容
- **WHEN** `components/platform/rockchip/config.jsonnet` 存在且 canonical 求值结果与迁移快照一致
- **THEN** `_load_platform_config("rockchip")` 返回该 Jsonnet overlay

#### Scenario: 不存在的平台报错
- **WHEN** 请求加载一个不存在的平台
- **THEN** 抛出 `ValueError` 且错误信息包含请求的平台名和可用平台列表

#### Scenario: Python 平台配置不再发现
- **WHEN** 某目录只存在旧 `config.py` 而没有 `config.jsonnet`
- **THEN** 注册表不把该目录识别为有效平台

### Requirement: 配置注册表自动发现 SoC

`builder/config/registry.py` 必须（SHALL）通过扫描 `components/platform/*/*/config.jsonnet` 自动发现所有可用 SoC，不得使用硬编码 SoC 映射。SoC 目录的 parent 目录名确定所属平台，overlay 中的 `soc` 与 `platform` 身份 MUST 与路径一致。

#### Scenario: 新增 SoC 自动识别
- **WHEN** `components/platform/example/example-soc/config.jsonnet` 存在且身份字段与路径一致
- **THEN** `_load_soc_config("example-soc")` 成功返回 SoC overlay

#### Scenario: SoC 身份与路径不一致
- **WHEN** SoC overlay 声明的 platform 与 parent 目录名不同
- **THEN** 注册表拒绝该配置并指出两个值

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

