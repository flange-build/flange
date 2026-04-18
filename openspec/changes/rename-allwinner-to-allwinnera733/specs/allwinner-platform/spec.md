## REMOVED Requirements

### Requirement: Allwinner 内核构建支持 BSP 集成
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 内核构建支持 BSP 集成"（含共享仓库引用）。

### Requirement: Allwinner 内核多步 Defconfig 合并
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 内核多步 Defconfig 合并"。

### Requirement: Allwinner 内核编译产物
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 内核编译产物"。

### Requirement: Allwinner Bootloader 预编译固件模式
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 Bootloader 预编译固件模式"。

### Requirement: Allwinner Boot 分区组装
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 Boot 分区组装"。

### Requirement: Allwinner Rootfs 构建
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 Rootfs 构建"。

### Requirement: Allwinner 整盘镜像组装
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 整盘镜像组装"。

### Requirement: Allwinner 平台配置三层继承
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。三层继承结构保留，改由新 capability 的"A733 平台配置三层继承"定义。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 平台配置三层继承"；`board` 与 `SOC` 中的 `platform` 字段从 `"allwinner"` 改为 `"allwinnera733"`。

### Requirement: Allwinner 平台默认启用 adbd 调试通道
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 平台默认启用 adbd 调试通道"。

### Requirement: Allwinner 内核 USB gadget 保证
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 内核 USB gadget 保证"。

### Requirement: A7Z 板级 USB gadget 配置
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。板级配置内容本身不变，迁移至新 capability 下。
**Migration**: 参见 `allwinnera733-platform` 中的"A7Z 板级 USB gadget 配置"。

### Requirement: Allwinner 直接使用 linux-a733 原始 patches
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。内容在新 capability 中保留（类名随之改为 `AllwinnerA733KernelBuilder`）。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 直接使用 linux-a733 原始 patches"。

### Requirement: Allwinner bootloader 复用 u-boot-aw2501 命名仓库
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-platform` 替代。内容在新 capability 中保留（类名随之改为 `AllwinnerA733BootloaderBuilder`）。
**Migration**: 参见 `allwinnera733-platform` 中的"A733 bootloader 复用 u-boot-aw2501 命名仓库"。
