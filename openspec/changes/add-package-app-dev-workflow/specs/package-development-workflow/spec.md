## ADDED Requirements

### Requirement: Package 命令 SHALL 覆盖完整开发生命周期

CLI SHALL 提供 `flange package create|build|deploy|run|debug|log`。除 `create` 外，目标 MAY 是仓库内
Package 名称或含 `package.py` 的目录路径；省略时 SHALL 使用调用者当前目录。所有命令 SHALL 可从 flange
仓库外执行，且构建产物仍写入当前 lunch target 的统一 `.build/target` 目录。

#### Scenario: 在仓库外创建并构建 Package

- **WHEN** 用户在 `/work/vendor` 执行 `flange package create demo`，随后进入 `demo` 执行
  `flange package build`
- **THEN** 脚手架创建于 `/work/vendor/demo`
- **AND** 源目录被挂载进构建容器并由当前 lunch target 构建
- **AND** 构建产物写入 flange 仓库的统一 target 输出目录

#### Scenario: 以仓库内名称定位 Package

- **WHEN** 用户执行 `flange package build meizu-e3-panel`
- **THEN** CLI 从 `<project_root>/components/packages/meizu-e3-panel/package.py` 加载清单

### Requirement: Package SHALL 复用既有 component 流水线

Package 生命周期 SHALL 基于既有 `components`。vendor component 的 build/deploy/run/debug/log SHALL 复用
AppBuilder、DebBuilder 与 App 的设备操作；Package 仅含一个 vendor 时 SHALL 自动选择它，含多个 vendor
时 run/debug/log SHALL 要求 `--component`。不能由 component 类型安全推断的生命周期 SHALL 明确失败，
除非 Package 为该 action 提供显式定义。

#### Scenario: 单 vendor Package 自动运行

- **WHEN** Package 仅含一个指向 App 的 vendor component，且执行 `flange package run <path>`
- **THEN** CLI 构建并部署该 App 后使用 App 的运行方式启动它

#### Scenario: 驱动 Package 没有部署契约

- **WHEN** 仅含 `oot-driver` 的 Package 未定义 `deploy` action，且用户执行 package deploy
- **THEN** 命令失败并说明该 component 类型没有安全的独立 deploy 语义
- **AND** 命令不自动刷写任何分区

#### Scenario: 混合 Package 不静默忽略 component

- **WHEN** Package 同时含 vendor 和不可推断该生命周期的 component，且未定义显式 action
- **THEN** 整个 Package 命令失败并列出未处理的 component
- **AND** 只有用户显式使用 `--component` 选择 vendor 时才执行局部生命周期

#### Scenario: 多 vendor Package 选择不明确

- **WHEN** Package 含多个 vendor component，且 run 未提供 `--component`
- **THEN** 命令失败并列出可选 component

### Requirement: 显式 action SHALL 是无 shell 展开的 argv

`PACKAGE["actions"]` MAY 定义 `build`、`deploy`、`run`、`debug`、`log`，每个值 MUST 是非空字符串数组。
App 清单的顶层 `actions` SHALL 使用相同契约。CLI SHALL 直接以 argv 执行 action，并 SHALL 把 `--` 后的
参数追加到 argv；字符串命令、未知 action、空 argv 或非字符串元素 SHALL 在执行前被拒绝。build action
MUST 在构建容器内执行，其余 action MUST 在宿主机资源目录中执行。CLI SHALL 提供
`FLANGE_SOURCE_DIR` 与 `FLANGE_TARGET_DIR`；显式 build action MUST 把需要发布的产物写入
`FLANGE_TARGET_DIR`，标准 vendor fallback 则由既有流水线自动写入该目录。

#### Scenario: 参数按 argv 原样追加

- **WHEN** `run` action 为 `["./run.sh", "--mode", "safe"]`，用户追加 `-- --port 9000`
- **THEN** 执行 argv 为 `./run.sh --mode safe --port 9000`
- **AND** 任一参数均不经过 shell 插值或 eval

#### Scenario: 拒绝 shell 字符串 action

- **WHEN** action 值为字符串 `"./run.sh; reboot"`
- **THEN** 清单加载失败且 action 不被执行

### Requirement: 设备选择 SHALL 无歧义

App 与 Package 的 deploy/run/debug/log SHALL 支持 `--serial <adb-serial>`。未指定 serial 且恰有一台
状态为 `device` 的设备时 SHALL 自动选择；没有可用设备或存在多台可用设备时 SHALL 在执行变更前失败。

#### Scenario: 多设备未指定 serial

- **WHEN** ADB 列出两台状态为 `device` 的设备且命令未传 `--serial`
- **THEN** 命令失败并列出设备 serial
- **AND** 不向任何设备部署或启动程序

### Requirement: 默认 debug 与 log SHALL 匹配 App 运行类型

在没有显式 action 时，service App 的 log SHALL 通过 ADB 调用 `journalctl -u <unit>` 并默认 follow；
debug variant 下 exec App SHALL 通过目标机 GDB 的 `--args` 启动，service App SHALL attach 其当前
MainPID。release variant 或无法推断运行对象时 SHALL 拒绝默认 debug，并提示使用 debug variant 或显式 action。

#### Scenario: 跟随 service 日志

- **WHEN** 对 unit 为 `demo.service` 的 App 执行 `flange app log demo`
- **THEN** CLI 在所选设备执行 `journalctl -u demo.service --no-pager -f`

#### Scenario: release target 拒绝默认 GDB

- **WHEN** 当前 variant 为 release 且 App 没有 debug action
- **THEN** `flange app debug demo` 在启动 GDB 前失败并提示选择 debug variant
