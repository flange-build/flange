## ADDED Requirements

### Requirement: kernel_build rule 采用框架+策略脚本架构
`build/kernel_build.bzl` SHALL 提供 `kernel_build` rule，采用框架+策略分离架构。rule 本身（框架）负责源码生命周期管理（克隆/增量重置/补丁应用）和构建产物收集，实际的编译命令由平台提供的 `build_script`（策略）执行。rule MUST NOT 硬编码任何平台特有参数（如 ARCH、CROSS_COMPILE、镜像格式等）。

#### Scenario: kernel_build rule 声明正确的属性
- **WHEN** 查看 `kernel_build` rule 的 attrs 定义
- **THEN** 包含 `kernel_src`（Label）、`build_script`（Label，平台构建脚本）、`image_name`（string）、`defconfig`（string）、`dts`（string）、`dts_dir`（string）、`platform_patches`（label_list）、`board_patches`（label_list）

#### Scenario: kernel_build rule 不包含平台硬编码
- **WHEN** 审查 `build/kernel_build.bzl` 的 `_kernel_build_impl` 函数
- **THEN** 不存在 `ARCH=`、`CROSS_COMPILE=`、`aarch64`、`arm64` 等平台特有字符串

### Requirement: 平台构建脚本通过环境变量契约通信
`kernel_build` rule SHALL 通过环境变量向平台构建脚本传递输入，脚本 SHALL 通过设置环境变量声明构建产出路径。框架与策略之间的契约如下：

**框架 → 脚本（输入）：**
- `KERNEL_DIR` — 内核源码目录（已 cd 进入，已应用补丁）
- `KERNEL_DEFCONFIG` — defconfig 名称
- `KERNEL_DTS` — DTS 文件名（不含扩展名）
- `KERNEL_DTS_DIR` — DTS 子目录名

**脚本 → 框架（输出）：**
- `KERNEL_IMAGE` — 内核镜像文件绝对路径
- `KERNEL_DTB` — DTB 文件绝对路径

#### Scenario: 平台脚本接收环境变量
- **WHEN** `kernel_build` 框架调用 `kernel/rockchip/build.sh`
- **THEN** 脚本可通过 `$KERNEL_DIR`、`$KERNEL_DEFCONFIG` 等环境变量获取构建参数

#### Scenario: 平台脚本声明产出路径
- **WHEN** 平台脚本执行完毕
- **THEN** `$KERNEL_IMAGE` 和 `$KERNEL_DTB` 指向有效的产出文件，框架据此收集产物

### Requirement: 持久化构建目录支持增量编译
`kernel_build` rule SHALL 使用基于 target 名称的稳定构建目录（如 `_kernel_build_<name>`），而非临时目录。首次构建时复制源码，后续构建时通过 `git checkout -f . && git clean -fd` 重置源码（保留 `.o` 等编译中间产物），实现 kbuild 增量编译。

#### Scenario: 首次构建复制源码
- **WHEN** 构建目录不存在
- **THEN** 执行 `cp -a` 复制完整源码到构建目录

#### Scenario: 增量构建保留编译产物
- **WHEN** 构建目录已存在（含 `.git`）
- **THEN** 执行 `git checkout -f . && git clean -fd` 重置源码变更，但 `.o` 文件、`.config` 等编译中间产物被保留，kbuild 根据时间戳判断增量编译范围

### Requirement: 构建 action 使用 run_shell 并禁用沙箱
`kernel_build` rule 的构建 action SHALL 使用 `ctx.actions.run_shell` 执行，并设置 `execution_requirements = {"no-sandbox": "1"}`，以支持内核构建系统对可写源码树和持久化构建目录的需求。

#### Scenario: 构建 action 在非沙箱环境执行
- **WHEN** Bazel 执行 `kernel_build` 的构建 action
- **THEN** action 在非沙箱模式下运行，可访问持久化构建目录

### Requirement: 补丁按序应用
`kernel_build` rule SHALL 先应用平台补丁（`platform_patches`），再应用板级补丁（`board_patches`）。补丁按文件名字母序排列，使用 `git apply` 或 `patch -p1` 应用。

#### Scenario: 平台补丁先于板级补丁应用
- **WHEN** 同时存在平台补丁和板级补丁
- **THEN** 平台补丁先被应用，板级补丁后被应用

#### Scenario: 无补丁时正常构建
- **WHEN** 平台补丁和板级补丁均为空
- **THEN** 跳过补丁步骤，直接调用平台构建脚本

### Requirement: kernel_source repository rule 拉取内核源码
`build/kernel_source.bzl` SHALL 提供 `kernel_source` repository rule，从 git 仓库浅克隆（`--depth=1`）指定分支的内核源码，并生成 `BUILD.bazel` 将源码导出为 `filegroup`。

#### Scenario: repository rule 执行浅克隆
- **WHEN** Bazel 拉取内核源码仓库
- **THEN** 使用 `git clone --depth=1 --branch=<branch> <remote>` 执行浅克隆

#### Scenario: 源码仅导出 Makefile 作为依赖标记
- **WHEN** 查看生成的 `BUILD.bazel`
- **THEN** filegroup 仅包含 `src/Makefile`，避免对内核源码树执行 glob 导致的性能问题

### Requirement: module extension 注册内核源码仓库
`build/extensions.bzl` SHALL 提供 `kernel_sources` module extension，接受 board 名称作为参数，从 `config_registry` 读取板级配置，调用 `kernel_source` repository rule 注册对应的内核源码仓库。

#### Scenario: 通过 MODULE.bazel 注册内核源码
- **WHEN** 在 `MODULE.bazel` 中声明 `kernel_sources.source(board = "radxa-zero3w")`
- **THEN** 创建名为 `kernel_src_radxa_zero3w` 的外部仓库，包含该板子的内核源码

#### Scenario: module extension 从 config_registry 读取配置
- **WHEN** module extension 处理 board 名称
- **THEN** 通过 `get_board_config()` 获取内核 repo URL 和 branch，无需在 MODULE.bazel 中重复声明
