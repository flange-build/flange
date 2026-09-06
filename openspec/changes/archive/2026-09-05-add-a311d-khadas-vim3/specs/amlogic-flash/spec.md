## MODIFIED Requirements

### Requirement: AmlogicFlashStrategy 两段式 USB Burning 流程

`AmlogicFlashStrategy.pre_flash()` 必须（SHALL）调用 `pyamlboot` 把 target 目录下的裸 FIP
`bootloader/u-boot.bin` 推入 SoC DDR；不得（MUST NOT）推送前置 block-1 header 的 SD 格式
`u-boot.bin.sd.bin`。U-Boot 进入 fastboot 后，主 flash 流程必须（SHALL）通过 host 端 `fastboot` 写入各分区，
其中 bootloader 使用 SD 格式并落到 eMMC hardware boot0。host 端只依赖 `pyamlboot`、
`libusb` 与 `android-tools-fastboot`，不得（MUST NOT）依赖 vendor 闭源刷写工具。

#### Scenario: 按板卡流程进入 MaskROM 后调用 pyamlboot

- **WHEN** 目标板已按自身板卡文档进入 MaskROM（USB device `1b8e:c003`）
- **THEN** pre_flash 调用 pyamlboot 把 `target_dir/bootloader/u-boot.bin` 推入 SoC DDR
- **AND** SoC 接收完整镜像后跳转到 BL2 → BL31 → U-Boot proper
- **AND** U-Boot 在 host 端注册为 fastboot 设备

#### Scenario: VIM3 系列使用 TST 三击流程

- **WHEN** Khadas VIM3 或 VIM3L 通过推荐的 TST（Terry's Smart Tweezers，无镊子升级模式）进入 MaskROM
- **THEN** 用户连接 USB-C 后在两秒内快速按 Function 键三次并立即松开
- **AND** 流程不得要求用户把 Function 键保持到刷写或重启阶段

#### Scenario: 主 flash 阶段写入分区

- **WHEN** pre_flash 成功且 U-Boot 已注册为 fastboot 设备
- **THEN** host 依次写入 `target_dir/bootloader/u-boot.bin.sd.bin`、`target_dir/boot/boot.img`、
  可选的 `target_dir/recovery/recovery.img` 与 `target_dir/rootfs/rootfs.img`
- **AND** 最后执行 `fastboot reboot`

#### Scenario: 不依赖 vendor 闭源工具

- **WHEN** 在干净环境执行任意 Amlogic board 的 `flange flash`
- **THEN** host 端依赖仅有 `pyamlboot`、`libusb` 与 `android-tools-fastboot`
- **AND** 不得（MUST NOT）依赖 Amlogic SDK 的闭源 USB Burning 工具

### Requirement: eMMC boot0 hw 分区写入

`AmlogicFlashStrategy` 写入 `bootloader` 时必须（SHALL）通过 fastboot 把数据落到板级
`CONFIG_FASTBOOT_FLASH_MMC_DEV` 指定 eMMC 的 hardware boot0（partition 1，offset `0x200`），不得
（MUST NOT）写到 user area。MMC 序号属于板级存储拓扑，不得在共享 flash strategy 中硬编码；当前 VIM3 与
VIM3L 的 U-Boot 都枚举 eMMC 为 `mmc2`。

#### Scenario: VIM3 bootloader 写入 mmc2 boot0

- **WHEN** `fastboot flash bootloader u-boot.bin.sd.bin` 被执行
- **AND** VIM3 板级 fragment 声明 `CONFIG_FASTBOOT_FLASH_MMC_DEV=2`
- **AND** `CONFIG_FASTBOOT_MMC_BOOT1_NAME="bootloader"`
- **THEN** 数据落到 `mmc2` partition 1（hardware boot0）的 offset `0x200`
- **AND** 重启后 BootROM 能从 hardware boot0 加载 BL2

#### Scenario: 其余分区写入 user area GPT

- **WHEN** `fastboot flash boot/recovery/rootfs` 被执行
- **THEN** 数据写入同一 eMMC user area（partition 0）的 GPT 对应分区
- **AND** GPT 已由前一次 `fastboot oem format` 按设备实际容量建立
