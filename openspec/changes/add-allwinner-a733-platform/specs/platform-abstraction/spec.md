## ADDED Requirements

### Requirement: 配置注册表自动发现平台
`config/registry.py` 必须（SHALL）通过扫描 `platform/*/config.py` 自动发现所有可用平台，不得使用硬编码的平台映射表。

#### Scenario: 新增平台自动识别
- **WHEN** `platform/allwinner/config.py` 存在且导出 `PLATFORM` 变量
- **THEN** `_load_platform_config("allwinner")` 成功返回平台配置字典

#### Scenario: 现有 Rockchip 平台兼容
- **WHEN** `platform/rockchip/config.py` 保持不变
- **THEN** `_load_platform_config("rockchip")` 返回与重构前完全相同的配置

#### Scenario: 不存在的平台报错
- **WHEN** 请求加载一个不存在的平台 `"qualcomm"`
- **THEN** 抛出 `ValueError` 且错误信息包含平台名

### Requirement: 配置注册表自动发现 SoC
`config/registry.py` 必须（SHALL）通过扫描 `platform/*/soc_name/config.py` 自动发现所有可用 SoC，不得使用硬编码的 SoC 映射表。SoC 目录的 parent 目录名确定其所属平台。

#### Scenario: 新增 SoC 自动识别
- **WHEN** `platform/allwinner/a733/config.py` 存在且导出 `SOC` 变量
- **THEN** `_load_soc_config("a733")` 成功返回 SoC 配置字典

#### Scenario: 现有 RK3566 SoC 兼容
- **WHEN** `platform/rockchip/rk3566/config.py` 保持不变
- **THEN** `_load_soc_config("rk3566")` 返回与重构前完全相同的配置

### Requirement: 产物映射由平台定义
`builder/engine.py` 的产物名映射（`_ARTIFACT_NAMES`）必须（SHALL）从各平台模块获取，不得硬编码于 engine 中。

#### Scenario: Rockchip 产物映射
- **WHEN** 构建 Rockchip 平台组件
- **THEN** engine 使用 `builder.platforms.rockchip.ARTIFACT_NAMES` 中定义的映射规则

#### Scenario: Allwinner 产物映射
- **WHEN** 构建 Allwinner 平台组件
- **THEN** engine 使用 `builder.platforms.allwinner.ARTIFACT_NAMES` 中定义的映射规则

#### Scenario: 未定义的产物 key 使用原始文件名
- **WHEN** 平台的 ARTIFACT_NAMES 中未包含某 (component, key) 对
- **THEN** engine 使用源文件的原始文件名作为目标文件名

### Requirement: Flash 配置生成无平台硬编码
`FlashConfigGenerator.generate()` 必须（SHALL）通过 `FlashStrategy` 接口获取 pre_flash 配置，不得包含 `if platform == "xxx"` 形式的平台判断。

#### Scenario: Rockchip pre_flash 配置
- **WHEN** 生成 Rockchip 平台的 flash-config.json
- **THEN** `RockchipFlashStrategy.generate_pre_flash_config()` 返回包含 `download_boot: "bootloader/miniloader.bin"` 的配置

#### Scenario: Allwinner pre_flash 配置
- **WHEN** 生成 Allwinner 平台的 flash-config.json
- **THEN** `AllwinnerFlashStrategy.generate_pre_flash_config()` 返回空的 `PreFlashConfig`（SD 卡模式无需 pre_flash）
