## Why

flange 当前仅支持 Rockchip 平台（RK3566）。框架的配置注册表、构建引擎产物映射、刷写系统中存在 Rockchip 硬编码，无法直接扩展到其他芯片平台。

需要添加 Allwinner A733 (sun60iw2p1) 平台支持，目标板为 Radxa Cubie A7Z — 一块 $15 起售的超紧凑 SBC（65×30mm），搭载 2×A76 + 6×A55 八核 CPU、3 TOPS NPU、WiFi 6。这是 flange 验证多平台架构能力的第一步。

## What Changes

### 框架重构（消除 Rockchip 硬编码）
- `config/registry.py`：将硬编码的 `_PLATFORM_CONFIGS` / `_SOC_CONFIGS` 映射表改为自动发现 `platform/*/config.py` 和 `platform/*/soc/*/config.py`
- `builder/engine.py`：将硬编码的 `_ARTIFACT_NAMES` 移至各平台定义，engine 通过平台接口获取产物映射
- `builder/flash.py`：`FlashConfigGenerator.generate()` 中 `if platform == "rockchip"` 的 pre_flash 逻辑改为策略方法，由各平台 FlashStrategy 自行声明

### 新增 Allwinner 平台
- `builder/platforms/allwinner/`：实现 kernel、bootloader、boot、rootfs、image 五个构建器
- `platform/allwinner/config.py`：Allwinner 平台公共配置
- `platform/allwinner/a733/config.py`：A733 SoC 配置（分区表、内核/bootloader 仓库、boot 参数）
- `board/radxa-cubie-a7z/config.py`：Radxa Cubie A7Z 板级配置

### Allwinner 内核构建
- 内核源码为 `radxa/kernel` (allwinner-aiot-linux-5.15) + `radxa/allwinner-bsp` (BSP 驱动/DTSI)
- BSP 集成到内核树的 `bsp/` 目录（内核 Makefile 已内置 `drivers-y += bsp/`）
- DTS 来自外部 device 仓库，构建前复制到内核 DTS 目录
- Defconfig 为 `defconfig` + `radxa.config` 两步合并

### Allwinner Bootloader（预编译固件模式）
- 创建 Allwinner 固件仓库（类似 Rockchip 的 rkbin），存放预编译的 boot0 + boot_package.fex
- `AllwinnerBootloaderBuilder` 从固件仓库拉取预编译产物，不从源码构建
- boot0 是 Allwinner 专有 SPL，boot_package.fex 是 U-Boot + BL31 + SCP 的打包体

### Allwinner Flash 策略
- 新增 `AllwinnerFlashStrategy`，支持 SD 卡 dd 刷写
- SD 卡布局：boot0@sector256, boot_package@sector24576, boot 分区, rootfs 分区

## 非目标

- **不从源码构建 Allwinner bootloader**：boot0、U-Boot、SCP 等构建需要 4+ 专有子模块和特殊工具链（Linaro ARM 7.2.1 + RISC-V），复杂度极高且产物变化频率低，采用预编译固件方案
- **不支持 UFS/eMMC 刷写**：首阶段仅支持 SD 卡部署，USB FEL 模式和 UFS 刷写留待后续
- **不修改 Rockchip 平台行为**：重构仅消除硬编码，不改变 Rockchip 构建/刷写的功能和产物

## Capabilities

### New Capabilities
- `allwinner-platform`: Allwinner 芯片平台构建支持，包含内核（BSP 集成模式）、bootloader（预编译固件模式）、boot 分区、rootfs、整盘镜像组装
- `allwinner-flash`: Allwinner 平台 SD 卡刷写策略
- `platform-abstraction`: 平台抽象层重构，消除硬编码使框架真正支持多平台扩展

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

### 代码影响
- `config/registry.py`：自动发现逻辑替换硬编码映射表
- `builder/engine.py`：`_ARTIFACT_NAMES` 提取为平台接口
- `builder/flash.py`：`FlashConfigGenerator` 消除平台硬编码
- `builder/platforms/`：新增 `allwinner/` 目录（5 个构建器模块）
- `platform/`：新增 `allwinner/` 目录（平台配置 + SoC 配置）
- `board/`：新增 `radxa-cubie-a7z/` 目录

### 依赖
- Allwinner 预编译固件仓库（需创建，托管 boot0 + boot_package.fex 二进制）
- 内核源码: `radxa/kernel` (allwinner-aiot-linux-5.15)
- BSP 源码: `radxa/allwinner-bsp` (cubie-aiot-v1.4.6)
- Device 配置: `radxa/allwinner-device` (device-a733-v1.4.6)

### Docker 环境
- 现有 aarch64-linux-gnu 交叉编译工具链可复用，无需新增
