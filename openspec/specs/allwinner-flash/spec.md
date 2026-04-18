# allwinner-flash Specification

## Purpose
TBD - created by archiving change add-allwinner-a733-platform. Update Purpose after archive.
## Requirements
### Requirement: Allwinner Flash 策略注册
`AllwinnerFlashStrategy` 必须（SHALL）注册到 `_FLASH_STRATEGIES` 中，使 `get_flash_strategy("allwinner")` 返回正确的策略实例。

#### Scenario: 策略获取
- **WHEN** 调用 `get_flash_strategy("allwinner")`
- **THEN** 返回 `AllwinnerFlashStrategy` 实例

### Requirement: Allwinner SD 卡 dd 刷写
`AllwinnerFlashStrategy` 的 `flash_all()` 必须（SHALL）支持将 raw.img 通过 dd 写入 SD 卡设备。

#### Scenario: flash_all 执行
- **WHEN** 对 Allwinner 平台执行 `flash_all()`
- **THEN** 执行 `dd if=raw.img of=<device> bs=4M status=progress conv=fsync`，将整盘镜像写入目标设备

#### Scenario: flash_raw 执行
- **WHEN** 对 Allwinner 平台执行 `flash_raw("/dev/sdX")`
- **THEN** 执行 dd 整盘刷写并同步

### Requirement: Allwinner 分区镜像映射
`AllwinnerFlashStrategy.partition_image_map()` 必须（SHALL）返回 Allwinner 平台分区名到镜像路径的正确映射。

#### Scenario: 映射内容
- **WHEN** 调用 `partition_image_map()`
- **THEN** 返回包含 `boot0 → bootloader/boot0_sdcard.bin`, `boot_package → bootloader/boot_package.fex`, `boot → boot/boot.img`, `rootfs → rootfs/rootfs.img` 的映射

### Requirement: Allwinner 设备检测
`AllwinnerFlashStrategy` 必须（SHALL）提供设备检测方法。首阶段 SD 卡模式下，设备检测可为简单的路径存在性检查。

#### Scenario: SD 卡设备检测
- **WHEN** 调用 `detect_device()` 且无 USB FEL 设备
- **THEN** 返回 `None`（SD 卡模式不依赖 USB 设备检测）

### Requirement: Allwinner 无 pre_flash 步骤
`AllwinnerFlashStrategy.pre_flash()` 在 SD 卡模式下必须（SHALL）为空操作（no-op），不执行任何上传或准备动作。

#### Scenario: pre_flash 空操作
- **WHEN** 对 Allwinner 平台执行 `pre_flash()`
- **THEN** 不执行任何操作，直接返回

