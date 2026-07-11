## ADDED Requirements

### Requirement: RT-Thread AMP 使用 flange 平台基线配置

Rockchip RT-Thread AMP 构建 SHALL 按 `BSP .config → flange AMP 基线 → app .config`
的顺序按符号合并配置，并在完成合并后通过 `scons --useconfig=.config` 重生成
`rtconfig.h`。平台基线 MUST 位于
`components/platform/rockchip/amp/rt-thread.config`，且 MUST 包含：

- `# CONFIG_RT_USING_SMP is not set`
- `CONFIG_RT_USING_RPMSG_LITE=y`
- `CONFIG_RT_USING_LINUX_RPMSG=y`
- `CONFIG_RT_USING_WITH_LINUX=y`

平台基线目录 MUST 纳入 amp 内容哈希；app `.config` SHALL 只声明应用或板级差异，
不得重复维护上述四个公共选项。

#### Scenario: 最终配置应用单核 Linux AMP 基线

- **WHEN** 构建任一 Rockchip `mode=rt-thread` AMP app
- **THEN** staged BSP 最终 `.config` 关闭 `RT_USING_SMP`
- **AND** 最终 `.config` 启用 RPMsg-Lite、Linux RPMsg 与 Linux 协同选项
- **AND** 编译使用由该 `.config` 重生成的 `rtconfig.h`

#### Scenario: 修改平台基线触发重建

- **WHEN** 修改 `components/platform/rockchip/amp/rt-thread.config`
- **THEN** amp 组件内容哈希变化并重新构建

### Requirement: RT-Thread staging 容忍 vendor 子模块占位

RT-Thread AMP staging SHALL 只复制目标 Rockchip BSP 与 `bsp/rockchip/common` 的可写
内容，其余 SDK 内容 SHALL 以只读方式引用。复制过程 MUST 容忍不带目标的 symlink，
MUST 排除 vendor `common/hal`，并 MUST 显式把 staged `common/hal` 链接到
`components/amp/rockchip/hal`。构建 SHALL NOT 依赖嵌套仓库的 `.git` 元数据。

#### Scenario: 断链子模块占位不阻塞 staging

- **WHEN** vendor BSP 中存在 `rockit`、`rkadk`、`common_algorithm`、`librga` 或嵌套
  `.git` 等断链 symlink
- **THEN** staging 成功完成，不因 `shutil.copytree` 跟随断链而失败
- **AND** 必需的 HAL 头文件和源码来自 flange 管理的 HAL SDK symlink

#### Scenario: SDK 源树保持只读

- **WHEN** 完成 RT-Thread AMP 构建
- **THEN** `.o`、`.sconsign`、`rtthread.elf`、`gcc_arm.ld` 和 SwiftPM 中间产物均不写入
  `components/amp/rockchip/rt-thread`
