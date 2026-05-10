## ADDED Requirements

### Requirement: AmlogicFlashStrategy 注册到 FlashStrategy 工厂

`builder/flash.py` 必须（SHALL）实现 `AmlogicFlashStrategy(FlashStrategy)` 类并把它注册到 `_FLASH_STRATEGIES["amlogic"]`，使 `get_flash_strategy("amlogic")` 返回该策略实例。

#### Scenario: amlogic 平台获得正确的 flash 策略

- **WHEN** `get_flash_strategy("amlogic")` 被调用
- **THEN** 返回 `AmlogicFlashStrategy` 实例
- **AND** 该实例继承自 `FlashStrategy` 抽象基类

#### Scenario: 不影响其他平台策略

- **WHEN** 加载 `_FLASH_STRATEGIES`
- **THEN** 仍然包含 `"rockchip"` → `RockchipFlashStrategy`
- **AND** 仍然包含 `"allwinnera733"` → `AllwinnerA733FlashStrategy`

### Requirement: AmlogicFlashStrategy 两段式 USB Burning 流程

`AmlogicFlashStrategy.pre_flash()` 必须（SHALL）调用 `pyamlboot` 把 target 目录下的 `bootloader/u-boot.bin.sd.bin` 推入 SoC DDR；u-boot 进入 fastboot 模式后，主 flash 流程必须（SHALL）通过 host 端 `fastboot` 工具写入各分区。整个过程 host 端依赖：`pyamlboot`（pip 安装或 git submodule）+ `android-tools-fastboot`（Ubuntu apt 包），不得（MUST NOT）依赖 vendor 闭源工具。

#### Scenario: pre_flash 阶段调用 pyamlboot

- **WHEN** `AmlogicFlashStrategy.pre_flash(tool, target_dir, config, device)` 被调用
- **AND** 板已按住 KEY1 上电，进入 MaskROM (USB device 1b8e:c003)
- **THEN** 实现调用 `pyamlboot` 把 `target_dir/bootloader/u-boot.bin.sd.bin` 推入 SoC DDR
- **AND** SoC 接收完整 u-boot 镜像后自动跳转到 BL2 → BL31 → u-boot proper
- **AND** u-boot 在 host 端注册为 fastboot 设备

#### Scenario: 主 flash 阶段写入分区

- **WHEN** pre_flash 成功，u-boot 在 host 端注册为 fastboot 设备
- **AND** `AmlogicFlashStrategy.flash()` 主流程被调用
- **THEN** host 端 `fastboot` 命令依次执行：
  - `fastboot flash bootloader target/bootloader/u-boot.bin.sd.bin`（写入 eMMC boot0 hw 分区）
  - `fastboot flash boot target/boot.img`
  - `fastboot flash recovery target/recovery.img`（若存在）
  - `fastboot flash rootfs target/rootfs.img`
  - `fastboot reboot`

#### Scenario: 不依赖 vendor 闭源工具

- **WHEN** 在干净环境实现 `flange flash khadas-vim3l-default-debug`
- **THEN** host 端依赖仅有 `pyamlboot`（MIT）与 `android-tools-fastboot`（Apache 2.0）
- **AND** 不得（MUST NOT）依赖 Amlogic SDK 内 `update.exe` / `Aml_USB_Burn_Tool.exe` 等闭源工具

### Requirement: AmlogicFlashStrategy 配置生成

`AmlogicFlashStrategy.generate_pre_flash_config(config)` 必须（SHALL）返回声明 pyamlboot 推送的 u-boot 镜像路径与目标 USB 设备 vid/pid 的 `PreFlashConfig` 对象，使 `flash-config.json` 包含足够信息让 `flange flash` 在干净 host 上端到端执行。

#### Scenario: 生成 amlogic flash-config

- **WHEN** 生成 khadas-vim3l 的 flash-config.json
- **THEN** `AmlogicFlashStrategy.generate_pre_flash_config(config)` 返回的 `PreFlashConfig` 包含 `download_boot` 字段指向 `bootloader/u-boot.bin.sd.bin`（或等价键，用于 pre_flash 阶段定位 u-boot 镜像）
- **AND** flash-config.json 中含有 amlogic MaskROM USB 设备 vid/pid（`1b8e:c003`）以便 host 端检测板进入 MaskROM

#### Scenario: 配置生成无平台硬编码

- **WHEN** `FlashConfigGenerator.generate(config)` 处理 amlogic 平台
- **THEN** 通过 `get_flash_strategy("amlogic").generate_pre_flash_config(config)` 获取 pre_flash 配置
- **AND** `FlashConfigGenerator` 自身不得（MUST NOT）出现 `if platform == "amlogic"` 分支

### Requirement: eMMC boot0 hw 分区写入

`AmlogicFlashStrategy` 写入 `bootloader` 分区时必须（SHALL）通过 fastboot 协议把数据落到 eMMC 硬件 boot0 分区（mmc0 partition 1，offset 0x200）；不得（MUST NOT）写到 user area。这是 Amlogic BootROM 的硬性要求 —— BootROM 上电后只读 hw boot0 分区。

#### Scenario: bootloader 写入 hw boot0

- **WHEN** `fastboot flash bootloader u-boot.bin.sd.bin` 被执行
- **AND** u-boot 端 `BOOTLOADER_PARTITION` 配置（来自 mainline `khadas-vim3l_defconfig`）指向 mmc0 hw boot0
- **THEN** 数据落到 eMMC partition 1（hw boot0）的 offset 0x200
- **AND** 重启后 BootROM 能从 hw boot0 加载 BL2

#### Scenario: 其余分区写入 user area GPT

- **WHEN** `fastboot flash boot/recovery/rootfs` 被执行
- **THEN** 数据写入 eMMC user area（partition 0）的 GPT 中对应分区
- **AND** GPT 必须（SHALL）由前一次 `fastboot flash gpt`（或 fastboot OEM 命令等价机制）已建立
