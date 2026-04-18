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

### 平台级 adbd 使能
- `platform/allwinner/config.py` 的 `custom_packages` 加入 `"adbd"`，与 Rockchip 平台对齐，使所有 Allwinner 板默认具备 adb 调试通道
- `AllwinnerKernelBuilder` 新增 `_write_usb_gadget_override()`，生成 `usb_gadget.config` fragment 并追加到 defconfig 合并尾部，强制 `USB_GADGET=y` / `USB_CONFIGFS=y` / `USB_CONFIGFS_F_FS=y` / `CONFIGFS_FS=y`——因 `radxa.config` 将 `USB_CONFIGFS` 降为模块，不叠加 override 会导致 `usbdevice.service` 启动前必须 modprobe
- `board/radxa-cubie-a7z/overlay/etc/usbdevice.conf` 提供 A733 平台 USB gadget 参数（VID=`0x1f3a` Allwinner Technology，USB_GROUP=`sunxi`，PID 映射表）

## 非目标

- **不从源码构建 Allwinner bootloader**：boot0、U-Boot、SCP 等构建需要 4+ 专有子模块和特殊工具链（Linaro ARM 7.2.1 + RISC-V），复杂度极高且产物变化频率低，采用预编译固件方案
- **不支持 UFS/eMMC 刷写**：首阶段仅支持 SD 卡部署，USB FEL 模式和 UFS 刷写留待后续
- **不修改 Rockchip 平台行为**：重构仅消除硬编码，不改变 Rockchip 构建/刷写的功能和产物

## Capabilities

### New Capabilities
- `allwinner-platform`: Allwinner 芯片平台构建支持，包含内核（BSP 集成模式、USB gadget override）、bootloader（预编译固件模式）、boot 分区、rootfs（含默认 adbd 调试通道）、整盘镜像组装
- `allwinner-flash`: Allwinner 平台 SD 卡刷写策略
- `platform-abstraction`: 平台抽象层重构，消除硬编码使框架真正支持多平台扩展

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

### 代码影响
- `config/registry.py`：自动发现逻辑替换硬编码映射表
- `builder/engine.py`：`_ARTIFACT_NAMES` 提取为平台接口
- `builder/flash.py`：`FlashConfigGenerator` 消除平台硬编码
- `builder/platforms/`：新增 `allwinner/` 目录（5 个构建器模块，`kernel.py` 含 USB gadget override）
- `platform/`：新增 `allwinner/` 目录（平台配置含 `custom_packages: ["adbd"]`、SoC 配置 defconfig 列表追加 `usb_gadget.config`）
- `board/`：新增 `radxa-cubie-a7z/` 目录（含 `overlay/etc/usbdevice.conf` 提供 A733 USB gadget 参数）

### 依赖
- Allwinner 预编译固件仓库（需创建，托管 boot0 + boot_package.fex 二进制）
- 内核源码: `radxa/kernel` (allwinner-aiot-linux-5.15)
- BSP 源码: `radxa/allwinner-bsp` (cubie-aiot-v1.4.6)
- Device 配置: `radxa/allwinner-device` (device-a733-v1.4.6)

### Docker 环境
- 现有 aarch64-linux-gnu 交叉编译工具链可复用，无需新增
