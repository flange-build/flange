# amlogic-flash Specification

## Purpose
Amlogic 平台 USB Burning 刷写契约。`AmlogicFlashStrategy` 在 pre_flash 阶段用 `pyamlboot` 把 u-boot 推到 SoC DDR；u-boot 在 `board_late_init` 暴露 `${boot_source}` env var（mainline meson 共用代码），fragment 的 PREBOOT 检测 `boot_source=usb` 自动进 fastboot gadget。host 端 `fastboot oem format` 按真实 eMMC 容量重建 GPT，然后 `fastboot flash bootloader` 路由到 mmc{N} hw boot0（u-boot `CONFIG_FASTBOOT_MMC_BOOT_SUPPORT` + `MMC_BOOT1_NAME="bootloader"` 命名），`flash boot/rootfs` 写 user area GPT 分区。整个 flow 无需接串口。
## Requirements
### Requirement: AmlogicFlashStrategy 注册到 FlashStrategy 工厂

`builder/flash/strategy.py` 必须（SHALL）实现 `AmlogicFlashStrategy(FlashStrategy)` 类并把它注册到 `_FLASH_STRATEGIES["amlogic"]`，使 `get_flash_strategy("amlogic")` 返回该策略实例。

#### Scenario: amlogic 平台获得正确的 flash 策略

- **WHEN** `get_flash_strategy("amlogic")` 被调用
- **THEN** 返回 `AmlogicFlashStrategy` 实例
- **AND** 该实例继承自 `FlashStrategy` 抽象基类

#### Scenario: 不影响其他平台策略

- **WHEN** 加载 `_FLASH_STRATEGIES`
- **THEN** 仍然包含 `"rockchip"` → `RockchipFlashStrategy`
- **AND** 仍然包含 `"allwinnera733"` → `AllwinnerA733FlashStrategy`

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

### Requirement: AmlogicFlashStrategy 配置生成

`AmlogicFlashStrategy.generate_pre_flash_config(config)` 必须（SHALL）返回声明 pyamlboot 推送的 u-boot 镜像路径与目标 USB 设备 vid/pid 的 `PreFlashConfig` 对象，使 `flash-config.json` 包含足够信息让 `flange flash` 在干净 host 上端到端执行。

#### Scenario: 生成 amlogic flash-config

- **WHEN** 生成 khadas-vim3l 的 flash-config.json
- **THEN** `AmlogicFlashStrategy.generate_pre_flash_config(config)` 返回的 `PreFlashConfig` 包含 `download_boot` 字段指向裸 FIP `bootloader/u-boot.bin`（用于 pre_flash 阶段 boot-g12.py 定位 u-boot 镜像；非 SD 格式 `.sd.bin`）
- **AND** flash-config.json 中含有 amlogic MaskROM USB 设备 vid/pid（`1b8e:c003`）以便 host 端检测板进入 MaskROM

#### Scenario: 配置生成无平台硬编码

- **WHEN** `FlashConfigGenerator.generate(config)` 处理 amlogic 平台
- **THEN** 通过 `get_flash_strategy("amlogic").generate_pre_flash_config(config)` 获取 pre_flash 配置
- **AND** `FlashConfigGenerator` 自身不得（MUST NOT）出现 `if platform == "amlogic"` 分支

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

### Requirement: macOS pyenv 刷写入口 SHALL 解析为真实脚本

macOS 的 Amlogic 刷写在 PATH 命中 pyenv shim 时 SHALL 按当前 pyenv 环境解析真实可执行入口，再传递动态库搜索路径并启动；MUST NOT 在设置 DYLD 环境后执行该 Shell shim。入口无法解析时 MUST 在设备传输前报告可操作错误。

#### Scenario: pyenv 安装的 pyamlboot

- **WHEN** boot-g12.py 来自当前 pyenv root 的 shims 目录
- **THEN** 使用 pyenv which 返回的真实入口执行 USB 引导，保留 Homebrew libusb 搜索环境

#### Scenario: 普通安装入口

- **WHEN** PATH 命中普通 boot-g12.py 脚本
- **THEN** 不要求额外查询或安装 pyenv

#### Scenario: 解析失败

- **WHEN** pyenv 不可用、解析超时或返回无效入口
- **THEN** 在设备等待或写入前返回明确错误，不继续执行 shim

### Requirement: fastboot 写入前 SHALL 完成有界就绪握手

Amlogic 的 `pre_flash` SHALL 在 30 秒总时限内完成 USB 枚举及只读 `getvar version` 握手，每个探测子进程最多等待 5 秒且不得超出剩余总时限。新上传 U-Boot 和复用已有 fastboot 设备 SHALL 经过相同检查，`--no-wait` MUST NOT 跳过该检查。只有唯一设备成功返回版本响应后，GPT、分区和重启命令才 SHALL 被允许，并通过 `-s` 绑定该序列号。

#### Scenario: USB 模式切换延迟或首次握手无响应
- **WHEN** pyamlboot 已结束，但设备尚未枚举或首次只读握手超时
- **THEN** 系统回收超时的探测进程，在剩余时限内通过新进程重试只读探测
- **AND** 握手成功后才执行一次 GPT 写入

#### Scenario: 已在 fastboot 模式
- **WHEN** 初始检测识别到 fastboot 设备
- **THEN** 系统跳过 pyamlboot 上传，但仍验证只读握手后再写入

#### Scenario: 未就绪或设备不唯一
- **WHEN** 总时限内没有成功的版本响应，或枚举到多台 fastboot 设备
- **THEN** 系统报告明确错误，MUST NOT 执行 GPT、分区或重启命令

### Requirement: GPT 写入 SHALL 有超时且不得自动重放

`fastboot oem format` SHALL 最多等待 30 秒。超时或失败时系统 MUST 停止后续分区写入，MUST NOT 自动重试这个持久写入命令；超时错误 SHALL 明确设备端执行结果未知，并提供检查连接和重新进入刷写模式的提示。

#### Scenario: GPT 命令无响应
- **WHEN** `oem format` 超过 30 秒未结束
- **THEN** 系统结束并回收宿主机命令进程，报告超时与结果未知
- **AND** 不重放 GPT、不写入后续分区、不重启设备
