## Why

当前 ProjectSpec.md 和 build-system-design.md 中，kernel、uboot、rootfs、image 四个组件目录各只有一个 `BUILD.bazel`，平台差异全部通过 `select()` 在单个文件中处理。随着支持平台增多（Rockchip、Allwinner、Qualcomm 等），`select()` 会急剧膨胀且难以维护。同时，不同平台的 bootloader 构建流程差异巨大（Rockchip 用 U-Boot，Qualcomm 用 ABL/XBL），现有的 `uboot/` 命名无法准确覆盖所有场景。

## What Changes

- **组件目录按平台分子目录**：kernel、bootloader、image 目录下按平台（rockchip/allwinner/qualcomm）建立子目录，每个子目录有独立的 `BUILD.bazel` 和平台特有的构建脚本、补丁
- **`uboot/` 重命名为 `bootloader/`**：容纳 U-Boot、ABL/XBL 等不同 bootloader 方案
- **rootfs 保持扁平**：rootfs 跨平台差异小（主要是 arch 不同），不拆分子目录，差异通过 `FINAL_CONFIG` 传入
- **顶层 alias + select() 路由**：组件顶层 `BUILD.bazel` 使用 `alias` + `select()` 路由到对应平台子目录，每新增平台只需加一行
- **板级资源通过 filegroup 导出**：板级补丁、DTS 等文件放在 `board/<name>/patches/` 下，由 `board/<name>/BUILD.bazel` 导出 `filegroup`，组件规则通过 `deps` 引用
- **platform/ 退化为纯配置声明**：`platform/` 目录只保留配置值（repo URL、defconfig、包列表等），不再存放补丁文件等数据资源
- **更新 ProjectSpec.md 目录结构**：同步更新规格文档中的目录结构约定
- **更新 build-system-design.md**：同步更新构建系统设计文档中的目录结构和相关描述

## 非目标

- 不实现具体的构建规则（`.bzl`）——本提案只涉及目录结构和文档更新
- 不新增平台支持——只为现有设计的平台（Rockchip、Allwinner、Qualcomm）预留目录结构
- 不修改配置层（`platform/`、`board/`）的 `.bzl` 配置文件内容
- 不修改 `build/` 下的自定义 Bazel 规则
- 不涉及 rootfs 和 apps 目录的结构变更

## Capabilities

### New Capabilities
- `component-platform-layout`: 组件目录（kernel/bootloader/image）按平台分子目录的工程结构设计，包括目录组织、路由方式、资源归属规则

### Modified Capabilities
<!-- 无现有 spec 需要修改 -->

## Impact

- **ProjectSpec.md**：第 9 节目录结构约定需要更新
- **docs/build-system-design.md**：第 5.2 节组件 target 结构、第 7 节目录结构需要更新
- **CLAUDE.md**：如有引用 `uboot/` 的地方需改为 `bootloader/`
