## ADDED Requirements

### Requirement: H3 平台启用 recovery 子系统
`allwinnerh3` 平台必须（SHALL）启用 `recovery.enabled=True`，提供与 Rockchip/A733 平台对等的 USB ADB 在线维护能力（`recoveryctl` + `flange recovery` 系列命令）。

#### Scenario: recovery 已启用
- **WHEN** 读取 `components/platform/allwinnerh3/config.py` 的 `recovery` 字段
- **THEN** `recovery.enabled == True`

#### Scenario: recovery 分区存在
- **WHEN** 读取 `allwinnerh3` 平台 SoC 层 `partitions.entries`
- **THEN** 存在名为 `recovery` 的 ext4 分区条目，位于 `boot` 分区之后、`rootfs` 分区之前

### Requirement: H3 recovery 进入机制为 U-Boot env-only（无内核 reboot-mode driver 依赖）
由于 H3 芯片无 RTC IP、无对应 BSP/mainline reboot-mode driver，`allwinnerh3` 平台必须（SHALL）通过 `recoveryctl recovery --persistent`（`fw_setenv flange_boot_once=recovery`）作为进入 recovery 的唯一路径，不依赖 `reboot(2)` 参数触发的内核 boot-reason 寄存器机制。

#### Scenario: 进入 recovery 使用 persistent 模式
- **WHEN** 用户在 H3 设备的 normal 系统上执行 `recoveryctl recovery --persistent`
- **THEN** `fw_setenv flange_boot_once recovery` 成功写入 U-Boot env
- **AND** 设备重启后由 U-Boot 读取该 env 并进入 `/extlinux/recovery.conf`

#### Scenario: 默认（非 persistent）命令在 H3 上不生效
- **WHEN** 用户执行不带 `--persistent` 的 `recoveryctl recovery`
- **THEN** 由于 H3 无内核 reboot-mode driver 消费该 reboot 参数，设备重启后仍进入 normal 系统（此为已知平台限制，非缺陷）

### Requirement: H3 U-Boot 在 board_late_init 中消费 flange_boot_once
`allwinnerh3` 平台的 U-Boot 补丁必须（SHALL）在 mainline `board/sunxi/board.c` 的 `board_late_init()` 中读取 `flange_boot_once` env，命中 `"recovery"` 时清空该 env、`saveenv` 持久化，并将 `boot_syslinux_conf` env 设为 `extlinux/recovery.conf`；未命中时保持 mainline 默认值 `extlinux/extlinux.conf`。

#### Scenario: 一次性进入 recovery
- **WHEN** U-Boot 启动时 `flange_boot_once` env 值为 `"recovery"`
- **THEN** `board_late_init()` 清空该 env 并 `saveenv`
- **AND** `boot_syslinux_conf` 被设为 `extlinux/recovery.conf`
- **AND** 后续 `sysboot` 读取 `/extlinux/recovery.conf` 而非 `extlinux.conf`

#### Scenario: 清理失败时不进入 recovery
- **WHEN** `env_set(NULL)` 或 `saveenv` 失败
- **THEN** 本次不设置 `boot_syslinux_conf` 为 recovery.conf，避免清理失败导致反复进入 recovery

#### Scenario: 默认读取 normal 配置
- **WHEN** `flange_boot_once` 未设置或值非 `"recovery"`
- **THEN** `boot_syslinux_conf` 保持 mainline 默认值 `extlinux/extlinux.conf`

### Requirement: H3 U-Boot env 持久化存储
`allwinnerh3` 平台的 `nanopi_neo_defconfig` 必须（SHALL）配置 `CONFIG_ENV_IS_IN_MMC=y` 并关闭 `CONFIG_ENV_IS_IN_FAT`（mainline sunxi 默认值），使用未覆盖的 sunxi 默认 `ENV_OFFSET=0xF0000`/`ENV_SIZE=0x10000`，该区间（sector 1920–2047）位于 `spl` raw 分区结束处与首个数据分区（`boot`，sector 2048）开始处之间的天然空隙内，不与其余分区/固件区域重叠。

#### Scenario: env 配置生效
- **WHEN** 执行 `allwinnerh3` 平台的 bootloader 构建
- **THEN** 最终 `.config` 中 `CONFIG_ENV_IS_IN_MMC=y`
- **AND** `CONFIG_ENV_IS_IN_FAT` 未启用

#### Scenario: env 区间与分区表不冲突
- **WHEN** 读取 `allwinnerh3` 平台分区表
- **THEN** `spl` 分区结束扇区（16 + 1904 = 1920）不晚于 U-Boot env 起始扇区（0xF0000 / 512 = 1920）
- **AND** env 结束扇区（1920 + 128 = 2048）不晚于 `boot` 分区起始扇区（2048）

### Requirement: H3 rootfs 提供 fw_env.config
`allwinnerh3` 平台的 normal 与 recovery rootfs 均必须（SHALL）安装 `/etc/fw_env.config`，声明与决策 7 一致的设备路径、offset、size，使 `fw_setenv`/`fw_printenv` 可正确定位 U-Boot env 存储区域。

#### Scenario: fw_env.config 内容正确
- **WHEN** 读取 `allwinnerh3` 平台 rootfs 中的 `/etc/fw_env.config`
- **THEN** 内容包含正确的块设备路径、`0xF0000` offset、`0x10000` size

### Requirement: H3 USB gadget 支持（MUSB peripheral + configfs）
`allwinnerh3` 平台的内核配置必须（SHALL）启用 `CONFIG_USB_MUSB_HDRC`、`CONFIG_USB_MUSB_SUNXI` 及其依赖（`CONFIG_EXTCON`、`CONFIG_NOP_USB_XCEIV`、`CONFIG_PHY_SUN4I_USB`），以及 USB gadget 框架（`CONFIG_USB_GADGET`、`CONFIG_CONFIGFS_FS`、`CONFIG_USB_CONFIGFS`、`CONFIG_USB_CONFIGFS_F_FS`），使 NanoPi NEO 的 micro USB 口（mainline dts 已声明 `dr_mode="peripheral"`）可运行 USB gadget（ADB）。

#### Scenario: 内核配置包含 MUSB 与 gadget 选项
- **WHEN** 执行 `allwinnerh3` 平台的内核构建
- **THEN** 最终 `.config` 中 `CONFIG_USB_MUSB_HDRC=y`、`CONFIG_USB_MUSB_SUNXI=y`、`CONFIG_USB_GADGET=y`、`CONFIG_USB_CONFIGFS=y`、`CONFIG_USB_CONFIGFS_F_FS=y` 均成立

#### Scenario: rootfs 提供 USB gadget 配置
- **WHEN** 读取 `components/board/nanopi-neo/overlay/etc/usbdevice.conf`
- **THEN** `USB_VENDOR_ID=0x1f3a`（Allwinner 官方 VID）
- **AND** `USB_FUNCS=adb`

### Requirement: H3 recovery 镜像构建
`AllwinnerH3RecoveryBuilder` 必须（SHALL）复用 `RecoveryBuilder` 基类的全部通用能力（两阶段构建、overlay、kernel modules 安装），不做平台特化覆盖，与 Rockchip/A733 平台的薄子类模式一致。

#### Scenario: recovery 构建产物
- **WHEN** 执行 `allwinnerh3` 平台的 `flange build recovery`
- **THEN** 输出 `recovery/recovery.img`（ext4，label=recovery）
