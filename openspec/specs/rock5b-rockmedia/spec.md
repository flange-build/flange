# rock5b-rockmedia Specification

## Purpose

定义 ROCK 5B rockmedia 产品的契约：以独立 product 承载厂商 GPU 与多媒体栈，GPU 驱动、用户态库与设备树成套切换且与默认 product 隔离，厂商用户态交付可校验。

## Requirements
### Requirement: 独立多媒体产品


系统 MUST 提供 `radxa-rock5b-rockmedia-debug` 和 `radxa-rock5b-rockmedia-release`，复用现有多媒体组件。

#### Scenario: 选择产品
- **WHEN** 求值 rockmedia 的任一 variant
- **THEN** 配置包含厂商 GPU package、MPP、RGA 和 GStreamer Rockchip 插件及检查工具

### Requirement: GPU 成套切换与隔离


rockmedia MUST 启用 BSP mali_kbase CSF、匹配设备树和 BSP 固件，禁用 Panthor/Panfrost；其他产品 MUST 保持原 GPU 路线。

#### Scenario: 厂商产品内核
- **WHEN** 生成 rockmedia 内核与 boot 配置
- **THEN** 不应用 Panthor fragment，启用 MALI_BIFROST、MALI_CSF_SUPPORT、内置固件和 mali-valhall overlay

#### Scenario: 原产品不变
- **WHEN** 求值 default、desktop 或 meizu-e3-bringup
- **THEN** 仍保留 Panthor fragment，不启用厂商 GPU package 或 compatible overlay

### Requirement: 可校验厂商用户态交付


厂商文件 MUST 固定来源和 SHA-256，经本地 vendor App 重打自有 DEB，保留版权、设备权限和动态链接维护语义；
MUST NOT 覆盖 Ubuntu EGL/GLES/GBM 文件或安装不匹配的独立固件。

#### Scenario: 正常构建
- **WHEN** 上游摘要验证通过
- **THEN** 生成 flange 自有包，使用独立 mali wrapper 路径，配置 ldconfig 和 mali0 的 video 组权限

#### Scenario: 下载损坏
- **WHEN** 上游或缓存文件 SHA-256 不匹配
- **THEN** 构建失败，不解包或发布该文件
