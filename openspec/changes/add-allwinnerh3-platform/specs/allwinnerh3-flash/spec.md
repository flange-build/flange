## ADDED Requirements

### Requirement: H3 Flash 策略注册
`AllwinnerH3FlashStrategy` 必须（SHALL）注册到 `_FLASH_STRATEGIES` 中，使 `get_flash_strategy("allwinnerh3")` 返回正确的策略实例。

#### Scenario: 策略获取
- **WHEN** 调用 `get_flash_strategy("allwinnerh3")`
- **THEN** 返回 `AllwinnerH3FlashStrategy` 实例

### Requirement: H3 SD 卡 dd 刷写
`AllwinnerH3FlashStrategy` 的 `flash_all()` 必须（SHALL）支持将 raw.img 通过 dd 写入 SD 卡设备。

#### Scenario: flash_all 执行
- **WHEN** 对 `allwinnerh3` 平台执行 `flash_all()`
- **THEN** 执行 `dd if=raw.img of=<device> bs=4M status=progress conv=fsync`，将整盘镜像写入目标设备

#### Scenario: flash_raw 执行
- **WHEN** 对 `allwinnerh3` 平台执行 `flash_raw("/dev/sdX")`
- **THEN** 执行 dd 整盘刷写并同步

### Requirement: H3 分区镜像映射
`AllwinnerH3FlashStrategy.partition_image_map()` 必须（SHALL）返回 `allwinnerh3` 平台分区名到镜像路径的正确映射。

#### Scenario: 映射内容
- **WHEN** 调用 `partition_image_map()`
- **THEN** 返回包含 `spl → bootloader/u-boot-sunxi-with-spl.bin`, `boot → boot/boot.img`, `rootfs → rootfs/rootfs.img` 的映射

### Requirement: H3 无 pre_flash 步骤
`AllwinnerH3FlashStrategy.pre_flash()` 在 SD 卡模式下必须（SHALL）为空操作（no-op），不执行任何上传或准备动作。

#### Scenario: pre_flash 空操作
- **WHEN** 对 `allwinnerh3` 平台执行 `pre_flash()`
- **THEN** 不执行任何操作，直接返回

### Requirement: H3 设备检测
`AllwinnerH3FlashStrategy` 必须（SHALL）提供设备检测方法。SD 卡模式下，设备检测可为简单的路径存在性检查。

#### Scenario: SD 卡设备检测
- **WHEN** 调用 `detect_device()`
- **THEN** 返回 `None`（SD 卡模式不依赖 USB 设备自动检测，需用户显式指定设备路径）
