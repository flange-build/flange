## ADDED Requirements

### Requirement: bootloader_build rule 采用框架+策略脚本架构
`build/bootloader_build.bzl` SHALL 提供 `bootloader_build` rule，采用框架+策略分离架构。rule 本身（框架）负责源码生命周期管理（重置/补丁应用）和构建产物收集，实际的编译和打包命令由平台提供的 `build_script`（策略）执行。rule MUST NOT 硬编码任何平台特有参数（如 ARCH、CROSS_COMPILE、boot_merger 等）。

#### Scenario: bootloader_build rule 声明正确的属性
- **WHEN** 查看 `bootloader_build` rule 的 attrs 定义
- **THEN** 包含 `bootloader_src`（Label，必选）、`build_script`（Label，必选）、`firmware_src`（Label，可选）、`defconfig`（string，必选）、`platform_patches`（label_list）、`board_patches`（label_list）

#### Scenario: bootloader_build rule 不包含平台硬编码
- **WHEN** 审查 `build/bootloader_build.bzl` 的 `_bootloader_build_impl` 函数
- **THEN** 不存在 `ARCH=`、`CROSS_COMPILE=`、`aarch64`、`arm64`、`boot_merger`、`rkbin` 等平台特有字符串

### Requirement: firmware_src 作为可选输入
`bootloader_build` rule SHALL 支持可选的 `firmware_src` 属性（`attr.label(default = None)`），用于传入平台特有的固件仓库（如 Rockchip 的 rkbin）。框架 SHALL 在 `firmware_src` 非空时设置 `FIRMWARE_DIR` 环境变量，为空时 `FIRMWARE_DIR` 设为空字符串。

#### Scenario: 传入 firmware_src 时设置 FIRMWARE_DIR
- **WHEN** `bootloader_build` 实例化时指定了 `firmware_src = "@rkbin_rockchip//:src"`
- **THEN** 构建脚本可通过 `$FIRMWARE_DIR` 访问 rkbin 仓库的根目录路径

#### Scenario: 未传入 firmware_src 时 FIRMWARE_DIR 为空
- **WHEN** `bootloader_build` 实例化时未指定 `firmware_src`
- **THEN** `$FIRMWARE_DIR` 设为空字符串，构建脚本可据此判断是否有固件仓库可用

### Requirement: 平台构建脚本通过环境变量契约通信
`bootloader_build` rule SHALL 通过环境变量向平台构建脚本传递输入，脚本 SHALL 通过设置环境变量声明构建产出路径。

**框架 → 脚本（输入）：**
- `BOOTLOADER_DIR` — U-Boot 源码目录（已 cd 进入，已应用补丁）
- `BOOTLOADER_DEFCONFIG` — U-Boot defconfig 名称
- `BOOTLOADER_JOBS` — make 并行任务数
- `FIRMWARE_DIR` — 固件仓库路径（可能为空）
- `RKBIN_INI_PREFIX` — rkbin INI 文件前缀（可能为空）

**脚本 → 框架（输出）：**
- `BOOTLOADER_IMG` — bootloader.img 绝对路径（FIT image，含 U-Boot + BL31 + DTB）
- `BOOTLOADER_IDBLOADER` — idbloader.img 绝对路径（IDB 格式，含 DDR + SPL，用于磁盘启动）
- `BOOTLOADER_MINILOADER` — miniloader.bin 绝对路径（MiniLoader 格式，用于 USB 上传）

#### Scenario: 平台脚本接收环境变量
- **WHEN** `bootloader_build` 框架调用 `bootloader/rockchip/build.sh`
- **THEN** 脚本可通过 `$BOOTLOADER_DIR`、`$BOOTLOADER_DEFCONFIG`、`$FIRMWARE_DIR` 等环境变量获取构建参数

#### Scenario: 平台脚本声明产出路径
- **WHEN** 平台脚本执行完毕
- **THEN** `$BOOTLOADER_IMG`、`$BOOTLOADER_IDBLOADER` 和 `$BOOTLOADER_MINILOADER` 指向有效的产出文件，框架据此收集产物

### Requirement: 持久化构建目录支持增量编译
`bootloader_build` rule SHALL 使用基于 target 名称的稳定构建目录，通过 `git reset --hard HEAD` 重置源码（保留 `.o` 等编译中间产物），实现增量编译。复用与 `kernel_build` 相同的机制。

#### Scenario: 增量构建保留编译产物
- **WHEN** 构建目录已存在（含 `.git`）
- **THEN** 执行 `git reset --hard HEAD` 重置源码变更，但 `.o` 文件、`.config` 等编译中间产物被保留

### Requirement: 构建 action 使用 run_shell 并禁用沙箱
`bootloader_build` rule 的构建 action SHALL 使用 `ctx.actions.run_shell` 执行，并设置 `execution_requirements = {"no-sandbox": "1", "no-remote": "1"}`。

#### Scenario: 构建 action 在非沙箱环境执行
- **WHEN** Bazel 执行 `bootloader_build` 的构建 action
- **THEN** action 使用 `no-sandbox` 和 `no-remote` execution requirements
