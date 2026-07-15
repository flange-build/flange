## MODIFIED Requirements

### Requirement: 刷写主入口脚本

宿主机刷写主入口 SHALL 为 `flange flash`，由 `builder.flash` 的 Python CLI 读取 `.build/target/<board>/<product>/<variant>/flash-config.json` 并执行；不得依赖已删除的 `scripts/flange-flash.sh`。构建时生成的 flash config SHALL 冻结平台、目标和分区到镜像映射，使 target 目录可独立搬运到另一台宿主机刷写。

#### Scenario: 整盘 dd 刷写

- **WHEN** 执行 `flange flash --raw --device /dev/sdX`
- **THEN** `FlashExecutor` 在确认后把 target 中的整盘镜像写入指定设备

#### Scenario: USB 全量刷写

- **WHEN** 执行 `flange flash`
- **THEN** Python 平台策略按 flash-config 的分区顺序写入全部适用镜像并按选项重启设备

#### Scenario: 组件级刷写

- **WHEN** 执行 `flange flash rootfs`
- **THEN** 只写 flash-config 中名为 rootfs 的分区

#### Scenario: flash config 不存在

- **WHEN** 当前 target 目录缺少 `flash-config.json`
- **THEN** 命令在接触设备前失败并提示先构建 image

### Requirement: 平台刷写模块化架构

刷写逻辑 SHALL 采用 Python strategy（策略）架构：`FlashExecutor` 负责通用流程，`FlashStrategy` 子类负责工具发现、设备检测、pre-flash、分区写入和重启；平台通过注册表选择策略。新增平台 SHALL 通过增加对应 Python strategy 接入，不得恢复 source shell 模块机制。

#### Scenario: Rockchip 平台刷写策略

- **WHEN** flash-config 的 platform 为 rockchip
- **THEN** 执行器选择 `RockchipFlashStrategy` 并调用匹配宿主系统的 upgrade_tool

#### Scenario: 新增平台注册

- **WHEN** 新平台实现 `FlashStrategy` 并加入策略注册表
- **THEN** `FlashExecutor` 可按 flash-config platform 选择该实现而无需修改通用刷写流程

### Requirement: 刷写工具检测

平台 strategy SHALL 在写入前定位并校验所需宿主工具；工具不存在或不可执行时 SHALL 在连接/写入设备前失败，并给出工具名称与解决指引。

#### Scenario: upgrade_tool 不存在

- **WHEN** Rockchip target 对应宿主工具路径不存在
- **THEN** `flange flash` 抛出 `FlashError` 且不执行任何设备写入命令

#### Scenario: dd 整盘模式

- **WHEN** 用户选择 raw 模式
- **THEN** 执行器使用宿主 dd/sync 路径，并在命令失败时传播非零结果

### Requirement: 刷写安全确认

刷写执行器 SHALL 在破坏性整盘写入前要求明确确认，并在 USB 分区刷写前检测或等待目标设备进入支持模式。未知分区、缺失镜像、设备歧义或等待超时 MUST 在写入前失败。

#### Scenario: dd 刷写确认

- **WHEN** 执行 `--raw --device /dev/sdX`
- **THEN** 显示目标设备与镜像，并仅在用户确认后执行 dd

#### Scenario: USB 刷写等待设备

- **WHEN** 执行 USB 刷写且设备尚未进入 MaskROM/Loader 模式
- **THEN** strategy 在配置的超时内轮询等待，超时后报错且不写入

#### Scenario: 未知分区名

- **WHEN** 执行 `flange flash <name>` 且 flash-config 无该分区
- **THEN** 本地校验失败并列出可用分区，不调用平台写入工具
