## Why

flange 尚不支持基于 Qualcomm SC8280XP（Snapdragon 8cx Gen 3）的 Radxa Dragon Q8B，无法为该板生成可写入 UFS 的 Ubuntu 系统镜像。Armbian 与 Radxa 已提供可工作的内核、Device Tree（设备树）、固件和 UEFI 启动资料，可在现有 Qualcomm UEFI/EDL 流水线上增量接入。

## What Changes

- 新增 `qualcommsc8280xp` 平台入口与 `sc8280xp` SoC 配置，复用现有 Qualcomm UEFI/GRUB、rootfs、GPT 镜像和 EDL 构建策略。
- 新增 `radxa-dragon-q8b` 板级配置，使用 Radxa `linux-7.0.11` 内核与 `sc8280xp-radxa-dragon-q8b.dtb`。
- 按 Armbian 实现安装 SC8280XP 的 ADSP/CDSP/SLPI/VPU 等固件与必要用户态包。
- 使用 Radxa 预编 SPI UEFI 固件包，并生成适用于 4096 字节扇区 UFS 的 ESP + rootfs 整盘镜像。
- 让共享 GRUB 菜单标题从配置读取板名，避免继续写死 Dragon Q6A。
- 新增最小配置测试，覆盖平台/SoC 自动发现、lunch target 和关键构建字段。

## Capabilities

### New Capabilities

- `qualcommsc8280xp-radxa-dragon-q8b`：定义 SC8280XP 平台、Radxa Dragon Q8B 板级配置、UEFI/GRUB 启动、UFS 镜像、EDL 刷写与板级固件契约。

### Modified Capabilities

无。

## Impact

- 新增 `components/platform/qualcommsc8280xp/`、`components/board/radxa-dragon-q8b/` 与对应平台构建入口。
- 复用 `builder/platforms/qualcommqcs6490/` 的现有构建器，并在 `builder/flash.py` 注册新平台到既有 Qualcomm EDL 策略。
- 外部输入包括 `radxa/kernel@linux-7.0.11`、`radxa-pkg/radxa-firmware` 与 Radxa Dragon Q8B 预编 SPI 固件包。
- 新增 lunch target：`radxa-dragon-q8b-default-{debug,release}`。

## 非目标

- 不重构或重命名既有 `qualcommqcs6490` 平台。
- 不从源码编译 XBL、EDK2、TZ 等 Qualcomm 签名启动固件。
- 不实现 ACPI、systemd-boot、运行时 DT overlay（设备树覆盖）或 recovery。
- 不承诺未经实板验证的 Wi-Fi、蓝牙地址生成、HDMI 热插拔增强和音频 UCM 定制；这些在基础启动与 UFS 路径验证后按需追加。
