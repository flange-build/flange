# cli-envsetup Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase7-cli-scaffold. Update Purpose after archive.
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
`lunch` 函数 SHALL 自动扫描 `board/*/board.bzl` 列出可用板子，展示编号菜单让用户选择。选择后设置 `FLANGE_BOARD` 环境变量。

#### Scenario: 交互式选择
- **WHEN** 执行 `lunch`（无参数）
- **THEN** 显示编号列表（如 `1. radxa-zero3w`），用户输入编号后设置 `FLANGE_BOARD`

#### Scenario: 直接指定板子
- **WHEN** 执行 `lunch radxa-zero3w`
- **THEN** 直接设置 `FLANGE_BOARD=radxa-zero3w`，不显示菜单

#### Scenario: 指定无效板子
- **WHEN** 执行 `lunch nonexistent-board`
- **THEN** 输出错误信息提示板子不存在，列出可用选项

### Requirement: 前置检查
`flange` 命令 SHALL 在执行子命令前检查必要条件：`FLANGE_BOARD` 已设置、Docker daemon 在运行。

#### Scenario: 未执行 lunch
- **WHEN** 未执行 `lunch` 直接运行 `flange build`
- **THEN** 输出错误信息提示先执行 `lunch`

#### Scenario: Docker 未运行
- **WHEN** Docker daemon 未启动时运行 `flange build`
- **THEN** 输出错误信息提示启动 Docker

