# rockchip-orangepi-cm4 Specification

## Purpose
TBD - created by archiving change orangepi-cm4-bringup-wifi-and-npu-fix. Update Purpose after archive.
## Requirements
### Requirement: orangepi-cm4 部署 AP6256 WiFi/BT 固件

`orangepi-cm4` board 的 `BOARD["rootfs"]["+extra_firmware"]` MUST 声明从 `radxa-pkg/radxa-firmware` 仓的 `lib/firmware/` 子目录拉以下三个 AP6256（Broadcom BCM4345C5 chipset）固件文件到 rootfs 的 `/lib/firmware/`：

- `brcm/fw_bcm43456c5_ag.bin`（WiFi 主固件，Rockchip bcmdhd `CONFIG_BCMDHD_AUTO_SELECT` 走 chip-id 拼名后实际加载文件）
- `brcm/nvram_ap6256.txt`（NVRAM 校准参数）
- `brcm/BCM4345C5.hcd`（Bluetooth patchram）

extra_firmware 条目的 `source` 字段 MUST 缺省（即 `"repo"`），由 `SourceManager.ensure_extra_firmware` 独立 clone 到 `.build/sources/extra-firmware/radxa/`。

#### Scenario: rootfs 镜像含 AP6256 三件套

- **WHEN** 构建 `orangepi-cm4-default-release` 的 rootfs 组件并 mount 产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43456c5_ag.bin` 存在且非空
- **AND** `/lib/firmware/brcm/nvram_ap6256.txt` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4345C5.hcd` 存在且非空

#### Scenario: 实机首启 WiFi 接口出现

- **WHEN** 把构建出的镜像刷入实机
- **THEN** `ip link` 输出包含 `wlan0`
- **AND** `dmesg` 不包含 `Direct firmware load for /brcm/fw_bcm43456c5_ag.bin failed` 类错误

#### Scenario: 实机首启 BT HCI 接口出现

- **WHEN** 把构建出的镜像刷入实机
- **THEN** `hciconfig -a` 输出包含 `hci0`
- **AND** `dmesg` 不包含 `Failed to load Broadcom firmware file (-2)` 类错误

### Requirement: orangepi-cm4 修复 bcmdhd 固件搜索路径

`components/board/orangepi-cm4/patches/kernel/` MUST 包含一条 patch 启用 Rockchip bcmdhd 驱动的 `FW_AMPAK_PATH="brcm"`，修改 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 中 `CONFIG_BCMDHD_AUTO_SELECT && CONFIG_BCMDHD_REQUEST_FW` 分支下的对应行（取消默认注释并把 `ampak` 改为 `brcm`）。

未应用该 patch 时，bcmdhd `dhd_conf_add_filepath()` 拼出的固件名为 `/fw_bcm43456c5_ag.bin`（缺 `brcm/` 前缀），即使固件文件正确部署也会因路径不匹配而 `request_firmware` 失败。

#### Scenario: patch 落地后 bcmdhd 加载固件路径正确

- **WHEN** kernel 构建期应用该 patch 并在实机加载 bcmdhd 模块
- **THEN** `dmesg` 出现 bcmdhd 从 `/lib/firmware/brcm/fw_bcm43456c5_ag.bin` 加载固件的痕迹（或至少不出现 `firmware loading failed` 类错误）

### Requirement: orangepi-cm4 修复 bootargs 与 extlinux 协作

`components/board/orangepi-cm4/patches/kernel/` MUST 包含一条 patch 修正 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4.dtsi` 中的 `chosen.bootargs`，作两处修改：

1. 删除硬编码的 `root=PARTUUID=614e0000-0000`——u-boot 的 `bootargs_add_dtb_dtbo + env_update` 会把 DTB chosen.bootargs 合并到 extlinux APPEND 上，覆盖 flange normal / recovery 双 extlinux label 选择的 root=，导致 recovery 切换失效。
2. 追加 `firmware_class.path=/lib/firmware`——作为板级合理默认，与 `extra_firmware` 落点对齐，覆盖 dtsi 上游遗留的 Android 风格路径假设。

保留 `earlycon=uart8250,mmio32,0xfe660000` / `console=ttyFIQ0` / `rw rootwait`，仅作上述两处必要调整。

#### Scenario: patch 落地后 recovery 切换可用

- **WHEN** 在实机执行 `recoveryctl reboot recovery`（或等价方式触发 recovery 一次性引导）后重启
- **THEN** u-boot 进入 recovery extlinux label，kernel 启动后 `cat /proc/cmdline` 的 `root=` 指向 recovery 分区而非 dtsi 中删除的 PARTUUID
- **AND** 下一次正常重启回到 normal label，`root=` 指回 normal 分区

#### Scenario: firmware_class.path 兜底生效

- **WHEN** kernel 首启后内核态 `request_firmware` 加载任意固件
- **THEN** `cat /proc/cmdline` 含 `firmware_class.path=/lib/firmware`
- **AND** 即使驱动自身未显式指定固件路径，加载器也从 `/lib/firmware/` 查找

### Requirement: orangepi-cm4 禁用不可用 NPU

`components/board/orangepi-cm4/patches/kernel/` MUST 包含一条 patch 修正 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4.dtsi` 中的 NPU 节点状态：

1. `&rknpu` MUST 设置为 `status = "disabled"`。
2. `&rknpu_mmu` MUST 设置为 `status = "disabled"`。

该 patch 用于撤销 `rk3566-orangepi-cm4.dtsi` 对 `rk356x.dtsi` 默认 disabled 状态的 override，避免 `rknpu_mmu` probe 期间通过 `__genpd_dev_pm_attach` 拉起 NPU power domain，并在 PMU `npu` ack 不返回时触发 BSP `panic_on_set_idle`。

#### Scenario: patch 落地后 rknpu 与 rknpu_mmu 均为 disabled

- **WHEN** kernel 构建期应用 board 私有 kernel patch
- **THEN** `rk3566-orangepi-cm4.dtsi` 中 `&rknpu` 的 `status` 为 `"disabled"`
- **AND** `rk3566-orangepi-cm4.dtsi` 中 `&rknpu_mmu` 的 `status` 为 `"disabled"`

#### Scenario: 实机首启不再因 NPU power domain panic

- **WHEN** 把构建出的镜像刷入 Orange Pi CM4 实机并启动
- **THEN** 启动日志不再出现 `failed to get ack on domain 'npu'`
- **AND** 启动日志不再出现 `Kernel panic - not syncing: panic_on_set_idle set ...`
- **AND** 系统继续启动到 rootfs

### Requirement: orangepi-cm4 不修改 rk3566-orangepi-cm4-base.dts 且本轮不启用 DSI

`components/board/orangepi-cm4/config.jsonnet` 的 `BOARD["kernel"]["dts"]` MUST 保持 `"rk3566-orangepi-cm4-base"`，本 change MUST NOT 修改 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4-base.dts` 的内容（保持为 `rk3566-orangepi-cm4.dtsi` 的空壳）。

`components/board/orangepi-cm4/` MUST NOT 包含任何 board overlay（`dtso/` 目录不应存在）；`boot.overlays.board` 与 `boot.overlays.enabled` MUST 为空，让 `dsi1` 等显示链路节点维持 dtsi 默认 disabled。屏适配由独立后续 change 推进。

#### Scenario: base.dts 保持空壳

- **WHEN** 在 `.build/sources/kernel/orangepi-cm4/` 检查 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4-base.dts`
- **THEN** 文件内容除版权 header 与 `/dts-v1/;` 外只有一行 `#include "rk3566-orangepi-cm4.dtsi"`，与上游 dtsi tarball 一致（不被本 board 任何 patch 修改）

#### Scenario: 本轮不交付任何 DSI 屏 overlay

- **WHEN** 检查 `components/board/orangepi-cm4/`
- **THEN** 不存在 `dtso/` 子目录
- **AND** 合并后 FINAL_CONFIG 的 `boot.overlays.board` 与 `boot.overlays.enabled` 均为空（保持 SoC / platform 默认）

#### Scenario: 默认首启 DSI 链路保持沉默

- **WHEN** 默认 extlinux 配置启动 `orangepi-cm4-default-release`
- **THEN** 启动日志不出现 `dw-mipi-dsi-rockchip fe070000.dsi` 相关 probe 与 defer 信息
- **AND** kernel 正常启动到 rootfs，HDMI 出图链路（vop2 + HDMI）不受影响

### Requirement: orangepi-cm4 提供 HAL 与 RT-Thread AMP product

`orangepi-cm4` board 配置 MUST 声明 `default`、`amp`、`amp-rtt` 三个 product。`amp` product SHALL
启用 HAL 模式 AMP 固件；`amp-rtt` product SHALL 启用 RT-Thread 模式 AMP 固件。两个 AMP product
MUST 复用 RK3566 SoC 层的 `amp.memory`，并 MUST 使用 product 作用域配置启用 AMP，不能改变
`default` product 的 dts、分区表、bootloader AMP 选项或 CPU 数量。

两个 AMP product MUST 满足以下配置约束：

- `amp.enabled` 为 `true`
- `amp.mode` 分别为 `hal` / `rt-thread`
- `amp.app` 分别指向 Orange Pi CM4 专用 UART7 HAL / RT-Thread AMP app
- `bootloader.defconfig` 追加 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- `kernel.defconfig` 追加 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- `kernel.device_tree.name` 选择 Orange Pi CM4 专用 AMP dts
- `partitions` 在 `recovery` 与 `rootfs` 之间包含非 raw 的 `amp` ext4 分区，且 `rootfs` 仍为
  `remaining`

#### Scenario: HAL AMP product 配置解析正确

- **WHEN** 解析 `orangepi-cm4-amp-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 为 `true`
- **AND** `amp.mode` 为 `hal`
- **AND** `amp.app` 指向 Orange Pi CM4 专用 UART7 HAL AMP app
- **AND** `kernel.device_tree.name` 为 Orange Pi CM4 专用 AMP dts
- **AND** `bootloader.defconfig` 同时包含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `kernel.defconfig` 同时包含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- **AND** `partitions.entries` 中 `amp` 分区位于 `recovery` 之后、`rootfs` 之前

#### Scenario: RT-Thread AMP product 配置解析正确

- **WHEN** 解析 `orangepi-cm4-amp-rtt-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 为 `true`
- **AND** `amp.mode` 为 `rt-thread`
- **AND** `amp.app` 指向 Orange Pi CM4 专用 UART7 RT-Thread AMP app
- **AND** `kernel.device_tree.name` 与 HAL AMP product 相同
- **AND** `bootloader.defconfig` 同时包含 `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `kernel.defconfig` 同时包含 `CONFIG_RPMSG_CHAR=y` 与 `CONFIG_RPMSG_CTRL=y`
- **AND** `partitions.entries` 中 `amp` 分区位于 `recovery` 之后、`rootfs` 之前

#### Scenario: default product 不受 AMP product 影响

- **WHEN** 解析 `orangepi-cm4-default-release` 的 FINAL_CONFIG
- **THEN** `amp.enabled` 不为 `true`
- **AND** `kernel.device_tree.name` 仍为 `rk3566-orangepi-cm4-base`
- **AND** `bootloader.defconfig` 不包含 `CONFIG_AMP=y` 或 `CONFIG_ROCKCHIP_AMP=y`
- **AND** `partitions.entries` 不包含 `amp` 分区

### Requirement: orangepi-cm4 AMP 从核 console 使用 40pin UART7_M2

Orange Pi CM4 AMP product 的从核 console MUST 使用 UART7_M2，而不是 RK356x AMP demo 默认的
UART4_M1。板级文档 MUST 说明 UART7_M2 的 40pin 接线：

- 40pin 15 脚：GPIO4_A2 / UART7_TX_M2
- 40pin 16 脚：GPIO4_A3 / UART7_RX_M2

Orange Pi CM4 专用 AMP dts MUST 把 `rockchip-amp` 的 console 相关 clock、pinctrl 与 IRQ 切到
UART7：

- clock 使用 `SCLK_UART7` / `PCLK_UART7`
- pinctrl 使用 `uart7m2_xfer`
- console IRQ 使用 `UART7_IRQn` / GIC INTID 155

HAL AMP app MUST 初始化 UART7_M2，baud rate MUST 保持 1500000。RT-Thread AMP app/BSP MUST
初始化 UART7_M2，console device MUST 为 `uart7`，baud rate MUST 保持 115200。

#### Scenario: 编出的 AMP dtb 选择 UART7_M2

- **WHEN** 构建 `orangepi-cm4-amp-release` 或 `orangepi-cm4-amp-rtt-release` 的 kernel 并反编译 dtb
- **THEN** `rockchip-amp` 的 clock 引用包含 `SCLK_UART7` 与 `PCLK_UART7`
- **AND** `rockchip-amp` 的 `pinctrl-0` 引用 `uart7m2_xfer`
- **AND** `rockchip-amp.amp-irqs` 包含 `UART7_IRQn` / INTID 155 路由到 cpu3
- **AND** `rockchip-amp.amp-irqs` 仍包含 `MBOX0_CH3_A2B_IRQn` / INTID 222 路由到 cpu3

#### Scenario: HAL AMP 从核通过 UART7_M2 输出日志

- **WHEN** 刷写并启动 `orangepi-cm4-amp-release`，并把 USB-TTL 接到 40pin 15/16
- **THEN** 从核 console 以 1500000 baud 输出 HAL AMP 启动日志
- **AND** 日志显示 rpmsg link-up 与 endpoint announce 成功

#### Scenario: RT-Thread AMP 从核通过 UART7_M2 输出日志

- **WHEN** 刷写并启动 `orangepi-cm4-amp-rtt-release`，并把 USB-TTL 接到 40pin 15/16
- **THEN** 从核 console 以 115200 baud 输出 RT-Thread AMP 启动日志
- **AND** 日志显示 rpmsg link-up 与 endpoint announce 成功

### Requirement: Orange Pi CM4 RT-Thread AMP 独占 UART7_M2 pinmux

`rk3568_amp_uart7_rtt_demo` 的 app `.config` MUST 显式关闭 `RT_USING_GMAC1`，因为
RK3568 GMAC1_M1 与 UART7_M2 共用 GPIO4_A2/A3，且 BSP 的 GMAC1 pinmux 初始化发生在
UART7 之后。app `.config` 还 MUST 关闭 `RT_USING_UART2`，避免 AMP 初始化 Linux
debug console。该约束 MUST 由配置回归测试覆盖，不能只依赖当前 BSP 默认值。

#### Scenario: 最终 iomux 不覆盖 UART7

- **WHEN** 构建 `orangepi-cm4-amp-rtt-debug`
- **THEN** 最终 `.config` 含 `# CONFIG_RT_USING_GMAC1 is not set`
- **AND** 最终 `.config` 含 `# CONFIG_RT_USING_UART2 is not set`
- **AND** `rt_hw_iomux_config` 在配置 UART7_M2 后不调用 GMAC1_M1 pinmux

#### Scenario: UART7 从复位开始输出

- **WHEN** 刷写并重启 Orange Pi CM4 RT-Thread AMP product
- **THEN** UART7_M2 在 Linux 应用 `uart7m2_xfer` 之前已可输出
- **AND** 能看到标准 RT-Thread banner、版本与 `cpu3 up` 日志
