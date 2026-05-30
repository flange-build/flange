## ADDED Requirements

### Requirement: Radxa Zero macOS host 刷写验收

Radxa Zero 的 Amlogic 刷写流程必须（SHALL）支持用户确认的 macOS host 环境。
host 端必须能使用 `fastboot`、`boot-g12.py`、Python `pyusb` 与 `libusb` 完成
MaskROM → U-Boot fastboot → eMMC 分区写入流程。

#### Scenario: macOS host 工具预检通过

- **WHEN** 在 macOS host 上执行 Radxa Zero 刷写前预检
- **THEN** `which fastboot` 返回可执行路径
- **AND** `which boot-g12.py` 返回可执行路径
- **AND** `python3 -c "import usb"` 成功退出
- **AND** `brew --prefix libusb` 返回 Homebrew libusb 安装路径

#### Scenario: macOS 检测 Radxa Zero MaskROM

- **WHEN** Radxa Zero 1.5 按住 MaskROM 按键并通过 USB 连接 macOS host
- **THEN** Amlogic flash 策略可通过 macOS USB 栈检测到 `1b8e:c003`
- **AND** 检测失败时错误信息提示检查 USB 连接、按键时序与 libusb/pyusb 环境

### Requirement: Radxa Zero eMMC fastboot 刷写

Radxa Zero 的 `flange flash` 必须（SHALL）通过现有 Amlogic 两段式流程刷写 8GB
eMMC：pre_flash 阶段按 `flash-config.json.pre_flash.download_boot` 指向的
pyamlboot 兼容镜像启动 U-Boot，fastboot 阶段写入 bootloader、boot 与 rootfs。

#### Scenario: pre_flash 使用 flash-config 声明的 download_boot

- **WHEN** 生成 `radxa-zero-default-debug` 的 `flash-config.json`
- **THEN** `pre_flash.download_boot` 指向 target 目录内存在的 U-Boot/FIP 引导镜像
- **AND** `AmlogicFlashStrategy.pre_flash()` 使用该字段构造 `boot-g12.py` 命令
- **AND** 策略不得（MUST NOT）在代码中为 Radxa Zero 硬编码另一条引导镜像路径

#### Scenario: fastboot 不刷写 recovery

- **WHEN** `recovery.enabled == False`
- **AND** 执行 `flange flash`
- **THEN** fastboot 写入命令包含 `bootloader`
- **AND** fastboot 写入命令包含 `boot`
- **AND** fastboot 写入命令包含 `rootfs`
- **AND** fastboot 写入命令不包含 `recovery`

#### Scenario: bootloader 写入 eMMC hw boot0

- **WHEN** fastboot 阶段执行 `fastboot flash bootloader <image>`
- **THEN** U-Boot fastboot 配置将 `bootloader` 路由到 eMMC hw boot0
- **AND** 重启后 Amlogic BootROM 能从 eMMC 启动 BL2

#### Scenario: user area GPT 与 rootfs grow 匹配 8GB eMMC

- **WHEN** fastboot 阶段执行 GPT 格式化或等价分区表写入
- **THEN** user area GPT 至少包含 `boot` 与 `rootfs` 分区
- **AND** `rootfs` 分区占用剩余空间或支持首启扩展到 8GB eMMC 的可用容量
