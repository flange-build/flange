# cross-compile-toolchain Specification

## Purpose

定义 flange 如何为目标架构选择交叉编译工具链：架构从哪里声明、工具链前缀
如何推导、以及组件与 App 两侧如何共用同一份推导。

## Requirements

### Requirement: 目标架构由 canonical 配置声明

配置 MUST 在 `architecture` 下分别声明 `userspace`、`kernel`、`bootloader`
三个架构 —— 它们并不总是相同（Amlogic 的 bootloader 有 32 位阶段，而
kernel 是 arm64）。访问 MUST 通过 `builder.config.canonical` 的访问器，
这些访问器不提供默认值：缺字段直接 KeyError，而不是静默拿到 aarch64。

#### Scenario: 三个架构分别声明
- **WHEN** 板级配置声明 `architecture.kernel = "arm64"` 与 `architecture.bootloader = "arm"`
- **THEN** kernel 与 bootloader 各自按自己的架构选择工具链

#### Scenario: 缺失架构字段
- **WHEN** 配置未声明 `architecture.userspace`
- **THEN** `userspace_arch()` 抛 KeyError，而不是回退到某个默认架构

### Requirement: 工具链前缀由架构推导

App 构建 SHALL 按目标架构推导 `CROSS_COMPILE` 前缀，覆盖 aarch64、armhf、
riscv64 与原生 x86_64 / i386（前缀为空）。未覆盖的架构 SHALL 有明确行为，
不得静默产出宿主机架构的二进制。

#### Scenario: aarch64 目标
- **WHEN** App 的目标架构为 aarch64
- **THEN** 构建命令中的 `CROSS_COMPILE=aarch64-linux-gnu-`

#### Scenario: armhf 目标
- **WHEN** App 的目标架构为 armhf
- **THEN** 构建命令中的 `CROSS_COMPILE=arm-linux-gnueabihf-`

#### Scenario: 原生架构
- **WHEN** App 的目标架构为 x86_64
- **THEN** `CROSS_COMPILE` 为空，使用宿主机工具链

### Requirement: 组件构建统一经 make 封装传入工具链

`ComponentBuilder.make()` SHALL 是组件调用 make 的唯一入口，由它统一拼接
`ARCH=` 与 `CROSS_COMPILE=`。各组件 SHALL NOT 自行拼装 make 命令行 ——
分散拼装是"某个平台忘了传 CROSS_COMPILE、静默编出宿主机二进制"的来源。

#### Scenario: 组件传入架构与前缀
- **WHEN** kernel 组件调用 `self.make(src, ["Image"], arch="arm64", cross="aarch64-linux-gnu-")`
- **THEN** 实际执行的命令包含 `ARCH=arm64` 与 `CROSS_COMPILE=aarch64-linux-gnu-`

#### Scenario: 并行度默认值
- **WHEN** 调用 `make()` 未指定 jobs
- **THEN** 使用宿主 CPU 数留出余量后的并行度，且至少为 1

### Requirement: 工具链由构建容器提供

交叉编译器 SHALL 由构建容器预装（见 `docker-build-env`），构建过程
SHALL NOT 在构建期下载或安装工具链。

#### Scenario: 容器内工具链可用
- **WHEN** 在构建容器内执行 `aarch64-linux-gnu-gcc --version`
- **THEN** 输出 GCC 版本信息
