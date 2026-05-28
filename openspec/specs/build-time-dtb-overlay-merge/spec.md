# build-time-dtb-overlay-merge Specification

## Purpose
TBD - created by archiving change add-q6a-meizu-e3-panel. Update Purpose after archive.
## Requirements
### Requirement: 构建期 fdtoverlay 合并能力

flange 平台 MAY 在不支持运行时 DT overlay 的启动链（典型如 grub-with-dtb + EDK2 UEFI）上启用「构建期 fdtoverlay 合并」，把按 [[extlinux-dtb-overlays]] 四源契约声明的 `boot.package_overlays`（package overlay 源；vendor/board/in-tree 三源在 v1 不强制纳入）与 base dtb 经 `fdtoverlay` 工具合并为单 dtb 文件，覆盖式写入 rootfs `/boot/<dtb>.dtb`。该能力 MUST 满足：

- **触发条件**：仅在 `config["boot"]["package_overlays"]` 非空时启用合并分支；为空时 MUST 走 base dtb 直拷路径，与未启用本能力前**字节等价**。
- **执行位置**：合并 MUST 在 rootfs 装内核 dtb 那一刻执行（即原 `cp base.dtb → rootfs/boot/<dtb>.dtb` 改为 `fdtoverlay base + dtbo... → rootfs/boot/<dtb>.dtb`）；MUST NOT 把 merged dtb 放到 ESP 等其他位置（GRUB 经 rootfs 分区 `/boot/<dtb>.dtb` 加载）。
- **输入与查找**：合并 MUST 以 `target/device-tree-overlay/overlays/` 下的 `.dtbo` 文件为源（即既有 [[hardware-feature-packages]] `devicetree` component 的产物路径），按 `config["boot"]["package_overlays"]` 列表顺序传给 `fdtoverlay`。
- **基础 dtb 前提**：base dtb MUST 含 `__symbols__` 节点；由内核构建侧显式启用（典型如 QCLINUX BSP 经 `DTC_FLAGS_<dtb>=-@` cmdline override 给目标 dtb 加 `-@`，因 vendor BSP 仅对 `base-dtb-y` 列出的 dtb 默认带 `-@`，普通 `dtb-y` 不带）。本能力**不在合并阶段重复校验**——若缺失，`fdtoverlay` 退出码非零并将 stderr 上报，构建失败信息 MUST 不被吞。
- **依赖关系**：`device-tree-overlay` 组件 MUST 是 rootfs 组件的依赖（写入 `builder/cache.py:DEPENDENCY_GRAPH`），保证合并阶段 `.dtbo` 已就绪。
- **工具来源**：`fdtoverlay` 来自 `device-tree-compiler` 包（dtc 同源），构建 Docker 镜像已含，MUST NOT 引入新 host 工具依赖。

#### Scenario: 无 package overlay 时字节等价

- **WHEN** lunch 一个未启用任何 `packages` 的 board（例如 `radxa-dragon-q6a-default-debug`），构建 rootfs
- **THEN** rootfs `/boot/<dtb>.dtb` 内容与未启用本能力前**字节等价**（直拷 base dtb）
- **AND** 构建过程 MUST NOT 调用 `fdtoverlay`

#### Scenario: 启用 package overlay 时合并并落入 rootfs

- **WHEN** lunch 一个启用 `packages` 且包内声明 `devicetree` component 的 board（例如 `radxa-dragon-q6a-meizu-e3-bringup-debug`），构建 rootfs
- **THEN** rootfs `/boot/<dtb>.dtb` 是 `fdtoverlay` 合并 base dtb 与所有 `boot.package_overlays` 列出的 `.dtbo` 之后的产物
- **AND** GRUB `grub.cfg` 不变（仍是 `devicetree /boot/<dtb>.dtb` 一行），UEFI/GRUB 启动加载该 merged dtb 即生效 overlay 注入的节点

#### Scenario: rootfs 依赖 device-tree-overlay

- **WHEN** 检视 `builder/cache.py:DEPENDENCY_GRAPH`
- **THEN** `"rootfs"` 的依赖列表 MUST 包含 `"device-tree-overlay"`
- **AND** 构建拓扑保证 rootfs 阶段执行前所有 `.dtbo` 已编译到 `target/device-tree-overlay/overlays/`

#### Scenario: fdtoverlay 失败被显式上报

- **WHEN** base dtb 缺 `__symbols__` 或某 `.dtbo` `__fixups__` 无法解析，`fdtoverlay` 退出码非零
- **THEN** rootfs 构建失败
- **AND** `fdtoverlay` 的 stderr 信息原样向上呈现（不被吞），便于排错（首选检查 `dtc -O dts <dtb>` 是否含 `__symbols__` 节点）

### Requirement: 与既有运行时 overlay 路径互不冲突

构建期合并能力 MUST 与 [[extlinux-dtb-overlays]] 定义的运行时 overlay 路径并存——`vendor_overlays` / `board_overlays` / `dtb_overlays` / `package_overlays` 四源声明、basename 去重、`default_overlays ⊆ 四源并集` 等既有约束 MUST 不被本能力修改。两种应用路径 MUST 由各平台 boot/rootfs 组件**择一**采用：U-Boot/extlinux 世界（rockchip/allwinner/amlogic）继续 fdtoverlays= 行运行时叠加；grub-with-dtb 世界（首例 qualcommqcs6490）采用本能力的构建期合并。

#### Scenario: 既有 U-Boot 平台不受影响

- **WHEN** 对 rockchip / allwinner / amlogic 平台 board build
- **THEN** 各自的 boot 组件继续按 [[extlinux-dtb-overlays]] 写 extlinux.conf `fdtoverlays=` 行
- **AND** rootfs `/boot/` 下 base dtb 保持未合并状态（运行时由 U-Boot 叠加）
- **AND** 本能力的合并分支不被触发

#### Scenario: 四源契约本身不被改动

- **WHEN** 检视 [[extlinux-dtb-overlays]] capability 的 requirement
- **THEN** 关于 `boot.vendor_overlays` / `boot.board_overlays` / `boot.dtb_overlays` / package overlay 四源的声明形式、basename 去重、`default_overlays ⊆ 并集` 等约束 MUST 不被本变更修改
- **AND** 本能力 spec 仅定义「合并应用方式」，不重定义四源声明语义

