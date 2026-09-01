# cli-envsetup Specification

## Purpose

定义 `envsetup.sh` 的环境初始化契约：source 之后提供什么、`lunch` 如何交互式选择目标、以及各子命令执行前必须通过哪些前置检查。
## Requirements
### Requirement: envsetup.sh 初始化开发环境
项目根目录 SHALL 提供 `envsetup.sh`，通过 `source envsetup.sh` 注入 `lunch` 和 `flange` 函数到当前 shell session。脚本 SHALL 设置 `FLANGE_DIR` 环境变量指向项目根目录。

#### Scenario: source 后函数可用
- **WHEN** 在项目根目录执行 `source envsetup.sh`
- **THEN** `lunch` 和 `flange` 命令可用，`FLANGE_DIR` 指向项目根目录

#### Scenario: 非项目目录 source
- **WHEN** 在任意目录执行 `source /path/to/flange/envsetup.sh`
- **THEN** `FLANGE_DIR` 正确指向 envsetup.sh 所在目录

### Requirement: lunch 交互式板级选择

`lunch` 无参数且标准输入输出为 TTY 时 SHALL 进入层级选择界面；用户选定后
SHALL 设置 `FLANGE_BOARD` / `FLANGE_PRODUCT` / `FLANGE_VARIANT` 并写入
`.flange/current_config`。

层级 SHALL 为 平台 → SoC → 板 → product → variant，末级即一个完整目标。
层级来自板级配置的自动发现，MUST NOT 触发完整配置求值 —— 求值单个目标约
1.3 秒，挂在导航上会让每次按键都卡住。

停留在末级目标上时 SHALL 显示该目标的配置表（身份、架构、内核、bootloader、
存储与分区、rootfs、功能开关、刷写）。配置求值 SHALL 在后台进行并缓存，
加载期间 SHALL 显示占位而不阻塞导航。

`lunch <board>-<product>-<variant>` 与 `--product=` / `--variant=` 的行为
保持不变。

#### Scenario: 层级浏览并选中

- **WHEN** 执行 `lunch`（无参数，TTY）
- **THEN** 显示可展开的层级树，用户下钻到某个 variant 并确认
- **AND** 该目标被设置为当前目标并持久化

#### Scenario: 末级目标显示配置表

- **WHEN** 光标停留在某个 variant 上
- **THEN** 显示该目标的配置表
- **AND** 求值期间显示加载占位，导航不被阻塞

#### Scenario: 打开时定位到当前目标

- **WHEN** 已选过目标后再次执行 `lunch`
- **THEN** 树自动展开到该目标并把光标置于其上

#### Scenario: 取消不改变当前目标

- **WHEN** 在界面中取消
- **THEN** `FLANGE_BOARD` / `FLANGE_PRODUCT` / `FLANGE_VARIANT` 保持原值

#### Scenario: 非 TTY 回退

- **WHEN** 在管道、CI 等非 TTY 环境执行 `lunch`，或显式传入 `--no-tui`
- **THEN** 回退到编号列表，行为与既有实现一致

#### Scenario: 直接指定完整目标

- **WHEN** 执行 `lunch radxa-rock5b-desktop-debug`
- **THEN** 直接设置三个变量，不进入界面

#### Scenario: 指定无效目标

- **WHEN** 执行 `lunch nonexistent-board`
- **THEN** 输出错误并列出可用目标

### Requirement: 前置检查
`flange` 命令 SHALL 在执行子命令前检查必要条件：`FLANGE_BOARD` 已设置、Docker daemon 在运行。

#### Scenario: 未执行 lunch
- **WHEN** 未执行 `lunch` 直接运行 `flange build`
- **THEN** 输出错误信息提示先执行 `lunch`

#### Scenario: Docker 未运行
- **WHEN** Docker daemon 未启动时运行 `flange build`
- **THEN** 输出错误信息提示启动 Docker

