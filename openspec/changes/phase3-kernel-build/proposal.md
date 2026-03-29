## Why

flange 已完成 Docker 构建环境（Phase 0）、交叉编译工具链（Phase 1）和三层配置继承体系（Phase 2）。当前具备了交叉编译能力和板级配置查询能力，但还不能构建任何实际的嵌入式组件。内核是嵌入式系统最核心的组件之一，也是项目"内核快速验证通道"核心目标的基础。本阶段将实现 Rockchip 平台的内核构建规则，使 `bazel build //kernel --config=radxa-zero3w` 能完成从源码拉取、补丁应用、defconfig 配置到交叉编译的完整流程，产出可用的 Image 和 DTB 文件。

## What Changes

- 新增 `kernel/BUILD.bazel`：顶层 alias + `select()` 路由，按 `config_setting` 分发到平台子目录
- 新增 `kernel/rockchip/BUILD.bazel`：Rockchip 平台内核构建实现，调用自定义 Bazel 规则
- 新增 `build/kernel_build.bzl`：自定义 Bazel 规则 `kernel_build`，封装内核源码拉取、补丁应用、defconfig 配置、交叉编译的完整流程
- 新增 `build/git_repository.bzl`：自定义 repository rule，从 git 仓库拉取内核源码并缓存
- 利用 Phase 2 的 `config_registry` 获取板级配置（repo URL、branch、defconfig、DTS 名称），驱动内核构建参数

## 非目标

- **不实现内核模块单独编译**：本阶段只构建完整内核镜像，不支持 out-of-tree 内核模块
- **不实现 `//kernel:flash` 刷写**：刷写功能属于 Phase 6（镜像打包+刷写），本阶段只产出构建产物
- **不支持 Rockchip 以外的平台**：Allwinner、Qualcomm 等平台的内核构建在后续按需添加
- **不实现增量编译优化**：首版实现以正确性为优先，增量编译优化后续迭代

## Capabilities

### New Capabilities
- `kernel-build-rule`: 自定义 Bazel 规则，封装 Linux 内核的完整构建流程（源码拉取、补丁应用、配置、交叉编译）
- `kernel-rockchip`: Rockchip 平台的内核构建实现，使用 `kernel_build` 规则和平台/板级配置产出 Image + DTB
- `kernel-select-routing`: 内核组件顶层 `select()` 路由，按平台 `config_setting` 分发到对应子目录

### Modified Capabilities
- `component-platform-layout`: 新增 kernel 组件目录的实际实现，验证"顶层 alias + select() 路由"模式

## Impact

- **新增目录**：`kernel/`、`kernel/rockchip/`
- **新增构建规则**：`build/kernel_build.bzl`、`build/git_repository.bzl`
- **依赖 Phase 2**：使用 `config_registry.bzl` 的 `get_board_config()` 获取内核构建参数
- **依赖 Phase 1**：使用 `//toolchain:aarch64_linux` 交叉编译工具链
- **外部依赖**：需要网络访问 git 仓库拉取内核源码
