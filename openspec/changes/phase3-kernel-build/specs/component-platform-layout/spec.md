## ADDED Requirements

### Requirement: 组件平台子目录包含平台构建脚本
按平台分子目录的组件（kernel、bootloader、image）的每个平台子目录 SHALL 包含一个平台构建脚本（如 `build.sh`），封装该平台特有的构建逻辑。构建脚本通过 `build_script` 属性被框架 rule 引用。

#### Scenario: Rockchip 内核包含平台构建脚本
- **WHEN** 查看 `kernel/rockchip/` 目录
- **THEN** 包含 `build.sh`，封装 Rockchip 内核的 make 命令、ARCH/CROSS_COMPILE 参数等平台特有逻辑

#### Scenario: 新增平台需创建构建脚本
- **WHEN** 需要新增 Allwinner 平台的 kernel 支持
- **THEN** 在 `kernel/allwinner/` 中创建 `build.sh`，包含 Allwinner 特有的编译流程（如 `make zImage`、sunxi 特有的后处理步骤）

### Requirement: 框架规则禁止硬编码平台参数
`build/` 目录下的自定义 Bazel 规则（`.bzl` 文件）MUST NOT 包含平台特有的硬编码值，包括但不限于：架构名（arm64、arm、riscv）、交叉编译前缀（aarch64-linux-gnu-）、镜像格式（Image、zImage）、厂商名（rockchip）。所有平台差异 SHALL 通过 rule 属性或策略脚本注入。

#### Scenario: 审查框架规则无平台硬编码
- **WHEN** 审查 `build/kernel_build.bzl` 的源码
- **THEN** 不包含任何架构、工具链前缀、厂商名等平台特有字符串

#### Scenario: 审查框架规则适用于 32-bit ARM
- **WHEN** 假设需要支持 `ARCH=arm`、`CROSS_COMPILE=arm-linux-gnueabihf-`、`make zImage` 的平台
- **THEN** 无需修改 `build/kernel_build.bzl`，只需提供对应的平台构建脚本

## MODIFIED Requirements

### Requirement: 顶层 alias + select() 路由
每个按平台分子目录的组件（kernel、bootloader、image）的顶层 `BUILD.bazel` SHALL 使用 Bazel `alias` + `select()` 路由到对应平台子目录的实现 target。对于首个实现的 kernel 组件，`select()` SHALL 包含 Rockchip 平台的映射，并使用 `no_match_error` 提供未配置平台时的错误提示。

#### Scenario: 用户构建 kernel 时自动路由到正确平台
- **WHEN** 当前配置为 Rockchip 平台，执行 `bazel build //kernel`
- **THEN** 实际构建 `//kernel/rockchip` target

#### Scenario: 新增平台只需在顶层加一行
- **WHEN** 需要新增 Amlogic 平台的 kernel 支持
- **THEN** 只需在 `kernel/BUILD.bazel` 的 `select()` 中增加一行 `"//build:platform_amlogic": "//kernel/amlogic"`

#### Scenario: 未配置平台时给出明确错误
- **WHEN** 执行 `bazel build //kernel` 但未设置 `--define=platform=...`
- **THEN** Bazel 报错，提示需要通过 `--config=<board>` 指定目标板

### Requirement: 板级资源通过 filegroup 导出
板级补丁、DTS 等数据文件 SHALL 存放在 `board/<name>/patches/` 目录下，由 `board/<name>/BUILD.bazel` 通过 `filegroup` 导出，组件构建规则通过 `deps` 引用。

#### Scenario: 板级内核补丁通过 filegroup 提供
- **WHEN** rk3588-evb 板子有特有的内核补丁
- **THEN** 补丁文件位于 `board/rk3588-evb/patches/kernel/`，由 `board/rk3588-evb/BUILD.bazel` 导出名为 `kernel_patches` 的 `filegroup`

#### Scenario: 组件构建规则引用板级补丁
- **WHEN** `kernel/rockchip/BUILD.bazel` 需要应用板级补丁
- **THEN** 通过 `board_patches` 属性引用 `//board/<name>:kernel_patches` filegroup
