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

`lunch` SHALL 从 `components/board/*/config.jsonnet` 自动发现可用板子，
枚举出 `<board>-<product>-<variant>` 目标供选择。选定后 SHALL 设置
`FLANGE_BOARD` / `FLANGE_PRODUCT` / `FLANGE_VARIANT` 三个环境变量，并写入
`.flange/current_config`。

#### Scenario: 交互式选择
- **WHEN** 执行 `lunch`（无参数）
- **THEN** 展示可选目标供用户选定
- **AND** 三个环境变量与状态文件一并更新

#### Scenario: 直接指定完整目标
- **WHEN** 执行 `lunch radxa-rock5b-desktop-debug`
- **THEN** 直接设置三个变量，不进入交互

#### Scenario: 仅替换 product 或 variant
- **WHEN** 已有当前目标时执行 `lunch --variant=release`
- **THEN** 保留 board 与 product，只替换 variant

#### Scenario: 指定无效目标
- **WHEN** 执行 `lunch nonexistent-board`
- **THEN** 输出错误信息，并列出可用目标

### Requirement: 前置检查
`flange` 命令 SHALL 在执行子命令前检查必要条件：`FLANGE_BOARD` 已设置、Docker daemon 在运行。

#### Scenario: 未执行 lunch
- **WHEN** 未执行 `lunch` 直接运行 `flange build`
- **THEN** 输出错误信息提示先执行 `lunch`

#### Scenario: Docker 未运行
- **WHEN** Docker daemon 未启动时运行 `flange build`
- **THEN** 输出错误信息提示启动 Docker

