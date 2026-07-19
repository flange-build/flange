## ADDED Requirements

### Requirement: AMP 应用来源不得硬编码为仓内目录

AMP builder SHALL 使用 app-registry 解析 `amp.app`，并允许合法的仓内、local_path、
git 和 external_app_dirs 来源。来源解析 SHALL 在 hal 与 rt-thread mode 使用同一规则。

#### Scenario: OOT RT-Thread AMP 构建

- **WHEN** FINAL_CONFIG 的 amp.app 只存在于 external_apps.local_path
- **THEN** builder 解析、验证并构建该目录，产物仍按既有内存和 FIT 规则生成 amp.img

### Requirement: Embedded Swift 必须匹配 RT-Thread 浮点调用 ABI

Rockchip RT-Thread AMP builder SHALL 从目标 BSP `rtconfig.py` 的静态 `DEVICE` 声明派生
Swift target CPU 与 C 架构 flags，不得为 RK3506 沿用其他 SoC 的 CPU。若 BSP 声明
`-mfloat-abi=hard`，builder MUST 在 Swift archive 和最终 `rtthread.elf` 两个阶段以固定
裸机工具链 `readelf -A` 验证 `Tag_ABI_VFP_args: VFP registers`，缺失时 MUST 终止构建。

#### Scenario: Swift archive 使用错误浮点 PCS

- **WHEN** Swift archive 或最终 ELF 没有声明 VFP register arguments
- **THEN** AMP 构建以明确的 hard-float ABI 错误失败，不生成可刷写 amp.img

### Requirement: Embedded Swift 必须匹配 RT-Thread enum ABI

Rockchip RT-Thread AMP builder SHALL 让 Swift C importer 匹配目标 BSP 与裸机工具链系统库
使用的 variable-size enum ABI，不得通过修改 staged BSP 全局 CFLAGS 把预编译系统库强行
混入 32-bit enum 输出。Swift archive 与最终 `rtthread.elf` MUST 均通过固定裸机工具链
`readelf -A` 验证 `Tag_ABI_enum_size: small`，且链接日志不得包含 enum-size mismatch 告警。

#### Scenario: Swift archive 使用错误 enum ABI

- **WHEN** Swift archive 或最终 ELF 声明 `Tag_ABI_enum_size: int`，或缺少 small enum 属性
- **THEN** AMP 构建以明确的 enum ABI 错误失败，不生成可刷写 amp.img

### Requirement: 最终 RT-Thread ELF 必须满足配置化 heap 门槛

Rockchip RT-Thread AMP runtime profile SHALL 提供正整数 byte 数
`amp.runtime.minimum_heap_size`。builder MUST 在最终链接后、打包 FIT 前，以固定裸机工具链
`nm -n --defined-only` 和 `readelf -SW` 同时验证 `__heap_begin`/`__heap_end` 与 `.heap`：二者
范围必须一致，必须完整落在 `config.amp.memory` 的 CPU firmware carveout 内，且容量不得低于
`minimum_heap_size`。

#### Scenario: 最终 ELF heap 满足门槛

- **WHEN** heap 符号、section 与 firmware carveout 一致，且容量不小于配置门槛
- **THEN** 构建输出可用容量、门槛和余量并继续生成 amp.img

#### Scenario: 最终 ELF heap 不可证明或容量不足

- **WHEN** heap 符号缺失、section 缺失、二者范围不一致、范围越界或容量小于门槛
- **THEN** AMP 构建失败关闭，不生成可刷写 amp.img
