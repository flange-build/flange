> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

Phase 0 已搭建 Docker 构建容器（Ubuntu 24.04），其中包含 `aarch64-linux-gnu-gcc` 13.3.0 交叉编译器。但 Bazel 默认使用宿主机（x86_64）的本地编译器，要产出 aarch64 二进制需要显式注册 CC toolchain 并通过 `--platforms` 激活。

MVP 经验（build-system-design.md §8.5）已确认：需要 `toolchain/` 目录，包含 `cc_toolchain_config.bzl`（工具路径）和 `BUILD.bazel`（toolchain 注册）。

## Goals / Non-Goals

**Goals:**
- 注册 aarch64-linux-gnu CC toolchain，使 Bazel 能交叉编译 C/C++ 代码
- 定义 aarch64 linux platform，与 toolchain 通过约束匹配
- 提供 `.bazelrc` 快捷配置 `--config=aarch64`
- 验证：编译简单 C 程序产出 aarch64 ELF

**Non-Goals:**
- 不支持多架构（仅 aarch64）
- 不引入 Bazel rules_cc 之外的第三方规则
- 不配置 sysroot（使用容器内系统安装的交叉编译工具链 include/lib 路径）

## Decisions

### D1: 使用 Bazel 内置 cc_toolchain API

使用 `cc_common.create_cc_toolchain_config_info` 配置工具链，不引入第三方 toolchain 规则（如 `toolchains_llvm`）。

**为什么？** 容器内已安装 GCC 交叉编译器，直接声明路径最简单。第三方规则会增加依赖和复杂度，在当前阶段不需要。

### D2: 工具路径使用绝对路径

在 `cc_toolchain_config.bzl` 中使用 `/usr/bin/aarch64-linux-gnu-*` 绝对路径。

**为什么？** 这些工具在 Docker 容器内位置固定（由 apt 安装），不存在路径变化问题。容器就是构建环境的约束边界。

### D3: platform 定义放在 toolchain/ 目录

将 `platform(name = "aarch64_linux")` 放在 `toolchain/BUILD.bazel` 中，而非单独的 `platform/` 目录。

**为什么？** 设计文档的 `platform/` 目录是配置层（.bzl 配置文件），不是 Bazel platform() 定义。Bazel platform 与 toolchain 强相关，放在一起更内聚。后续阶段 2 建立配置体系时，`config/` 目录下的 `config_setting` 会引用这里定义的约束。

### D4: .bazelrc 配置映射

在 `.bazelrc` 中添加 `build:aarch64 --platforms=//toolchain:aarch64_linux`，使用户可通过 `--config=aarch64` 快捷切换。

**为什么？** 后续 CLI 脚手架（flange build）会自动拼接此参数，但在 CLI 就绪前，开发者可直接使用 `--config=aarch64`。

## Risks / Trade-offs

- **[风险] cxx_builtin_include_directories 路径可能不完整**：交叉编译器的 include 目录路径需要精确匹配容器内实际路径，否则头文件找不到 → 缓解：通过 `aarch64-linux-gnu-gcc -E -x c - -v < /dev/null` 查询实际路径
- **[风险] Bazel 8 API 变化**：`cc_common.create_cc_toolchain_config_info` 在 Bazel 8 可能有 API 变化 → 缓解：验证阶段发现问题后调整
- **[取舍] 绝对路径 vs sysroot**：绝对路径绑定容器环境，无法在容器外使用 → 可接受，设计要求所有构建在容器内完成