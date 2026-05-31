# cross-compile-toolchain Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase1-cross-toolchain. Update Purpose after archive.
## Requirements
### Requirement: Bazel CC toolchain 注册 aarch64-linux-gnu
项目 SHALL 在 `toolchain/BUILD.bazel` 中定义 `cc_toolchain` 和 `toolchain`，声明 aarch64-linux-gnu 交叉编译工具链。工具链 SHALL 在 `MODULE.bazel` 中通过 `register_toolchains` 注册。

#### Scenario: toolchain 在 MODULE.bazel 中注册
- **WHEN** 查看 `MODULE.bazel` 文件
- **THEN** 包含 `register_toolchains("//toolchain:aarch64_linux_toolchain")`

#### Scenario: toolchain 定义包含完整工具路径
- **WHEN** 查看 `toolchain/cc_toolchain_config.bzl` 的工具声明
- **THEN** 包含 `gcc`、`g++`、`ar`、`ld`、`nm`、`objdump`、`strip` 等 aarch64-linux-gnu 前缀工具的路径

### Requirement: aarch64 linux platform 定义
项目 SHALL 在 `toolchain/BUILD.bazel` 中定义 `platform(name = "aarch64_linux")`，声明目标操作系统为 linux、目标 CPU 为 aarch64。

#### Scenario: platform 约束正确
- **WHEN** 查看 `toolchain/BUILD.bazel` 中的 platform 定义
- **THEN** `constraint_values` 包含 `@platforms//os:linux` 和 `@platforms//cpu:aarch64`

### Requirement: --config=aarch64 快捷配置
`.bazelrc` SHALL 保留 `build:aarch64` 配置，映射到 `--platforms=//toolchain:aarch64_linux`。板级配置（如 `--config=radxa-zero3w`）SHALL 复用此 platform 声明，而非重复定义。

#### Scenario: 使用 config 切换到交叉编译
- **WHEN** 在构建容器内执行 `bazel build --config=aarch64 //<target>`
- **THEN** Bazel 使用 aarch64-linux-gnu 工具链编译，产出 aarch64 二进制

#### Scenario: 板级配置复用 aarch64 platform
- **WHEN** 使用 `--config=radxa-zero3w` 构建
- **THEN** 构建使用 `//toolchain:aarch64_linux` platform，与 `--config=aarch64` 效果相同

### Requirement: 交叉编译产出 aarch64 ELF
使用已注册的 toolchain 编译 C 代码 SHALL 产出 aarch64 架构的 ELF 可执行文件。

#### Scenario: 编译简单 C 程序
- **WHEN** 在构建容器内执行 `bazel build --config=aarch64 //toolchain/test:hello`
- **THEN** 产出的二进制文件 `file` 命令输出包含 `ELF 64-bit LSB` 和 `ARM aarch64`

### Requirement: cc_toolchain_config 包含正确的 include 路径
`cc_toolchain_config.bzl` SHALL 在 `cxx_builtin_include_directories` 中声明容器内 aarch64-linux-gnu 交叉编译器的系统头文件路径。

#### Scenario: 包含标准库头文件可用
- **WHEN** 交叉编译一个包含 `#include <stdio.h>` 的 C 程序
- **THEN** 编译成功，无"头文件未找到"错误

