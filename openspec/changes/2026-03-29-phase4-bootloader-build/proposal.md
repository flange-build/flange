## Why

flange 已完成 Docker 构建环境（Phase 0）、交叉编译工具链（Phase 1）、三层配置继承体系（Phase 2）和内核构建（Phase 3）。当前可以构建内核镜像，但嵌入式系统启动还需要 Bootloader（引导加载程序）。Bootloader 是启动链的第一环——没有它，内核无法被加载执行。本阶段将实现 Rockchip 平台的 Bootloader 构建规则，使 `bazel build //bootloader --config=radxa-zero3w` 能完成 U-Boot 编译并产出 idbloader.img 和 u-boot.itb。

## What Changes

- 新增 `build/bootloader_source.bzl`：repository rule，从 git 仓库浅克隆 U-Boot 源码
- 新增 `build/bootloader_build.bzl`：自定义 Bazel 规则 `bootloader_build`，采用框架+策略架构封装 Bootloader 完整构建流程
- 新增 `bootloader/BUILD.bazel`：顶层 alias + `select()` 路由，按平台 `config_setting` 分发
- 新增 `bootloader/rockchip/BUILD.bazel`：Rockchip 平台 Bootloader 构建实例化
- 新增 `bootloader/rockchip/build.sh`：Rockchip 平台构建策略脚本，调用 U-Boot make 并使用 rkbin 的 `boot_merger` 工具生成 idbloader.img
- 修改 `build/extensions.bzl`：新增 `bootloader_sources` module extension（U-Boot 源码）和 `rkbin_source` repository rule（Rockchip 固件仓库，平台级共享）
- 修改 `platform/rockchip/config.bzl`：新增 rkbin 仓库配置（repo、branch）
- 修改 `platform/rockchip/rk3566/config.bzl`：新增 rkbin INI 前缀配置
- 修改 `board/radxa-zero3w/board.bzl`：补充 bootloader defconfig
- 修改 `MODULE.bazel`：注册 bootloader_sources 和 rkbin_source extension

## 非目标

- **不实现 `//bootloader:flash` 刷写**：刷写功能属于 Phase 6（镜像打包+刷写），本阶段只产出构建产物
- **不支持 Rockchip 以外的平台**：Allwinner、Qualcomm 等平台的 Bootloader 构建在后续按需添加
- **不自编译 ATF**：使用 rkbin 预编译的 bl31.elf，不从源码编译 ARM Trusted Firmware
- **不实现增量编译优化**：首版实现以正确性为优先

## Capabilities

### New Capabilities
- `bootloader-build-rule`: 自定义 Bazel 规则，封装 Bootloader 的完整构建流程（源码拉取、补丁应用、配置、交叉编译、固件打包），支持可选的 firmware_src 输入以适配不同平台
- `bootloader-rockchip`: Rockchip 平台的 Bootloader 构建实现，使用 rkbin 预编译固件（bl31.elf）和打包工具（boot_merger），通过 INI 配置驱动产出 idbloader.img + u-boot.itb
- `bootloader-select-routing`: Bootloader 组件顶层 `select()` 路由，按平台 `config_setting` 分发到对应子目录

### Modified Capabilities
- `component-platform-layout`: 新增 bootloader 组件目录，进一步验证"顶层 alias + select() 路由"模式

## Impact

- **新增目录**：`bootloader/`、`bootloader/rockchip/`
- **新增构建规则**：`build/bootloader_build.bzl`、`build/bootloader_source.bzl`
- **修改配置层**：platform/rockchip 新增 rkbin 配置，rk3566 新增 ini_prefix，board 补充 defconfig
- **依赖 Phase 2**：使用 `config_registry.bzl` 的 `get_board_config()` 获取配置参数
- **依赖 Phase 1**：使用 `//toolchain:aarch64_linux` 交叉编译工具链
- **外部依赖**：需要网络访问 git 仓库拉取 U-Boot 源码和 rkbin 仓库
