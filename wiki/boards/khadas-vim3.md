---
title: khadas-vim3
type: board
status: wip
sources:
  - builder/platforms/amlogic/bootloader.py
  - builder/flash/strategy.py
  - components/board/khadas-vim3/config.jsonnet
  - components/board/khadas-vim3/patches/bootloader/flange_fastboot.config
  - components/board/khadas-vim3/dtso/vim3-spidev-spicc1.dtso
  - components/board/khadas-vim3/dtso/vim3-fan-led.dtso
  - components/board/khadas-vim3/overlay/etc/hostname
  - components/board/khadas-vim3/overlay/etc/modules-load.d/flange-usbgadget.conf
  - components/board/khadas-vim3/overlay/etc/usbdevice.conf
  - components/platform/amlogic/config.jsonnet
  - components/platform/amlogic/a311d/config.jsonnet
  - components/config/khadas-vim3-common.libsonnet
  - openspec/changes/archive/2026-09-05-add-a311d-khadas-vim3/design.md
  - docs/first-steps.md
related:
  - "[[khadas-vim3l]]"
  - "[[amlogic 平台]]"
  - "[[USB 线刷协议]]"
updated: 2026-09-06
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list khadas-vim3` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Khadas VIM3 使用 Amlogic A311D（G12B，2×Cortex-A53 + 4×Cortex-A73），复用现有 Amlogic
mainline 构建和 pyamlboot → fastboot（快速刷写协议）链路。软件配置、构建输入及实板 U-Boot 进入 fastboot 已验证；完整系统启动、V14 DRAM
（Dynamic Random-Access Memory，动态随机存取存储器）兼容性和外设状态待验收。

## target

```bash
lunch khadas-vim3-default-debug
lunch khadas-vim3-default-release
lunch khadas-vim3-desktop-debug
lunch khadas-vim3-desktop-release
```

## 关键配置

| 项 | 值 |
|---|---|
| U-Boot | mainline v2024.10，`khadas-vim3_defconfig + flange_fastboot.config` |
| Linux | mainline v6.12，arm64 generic `defconfig` |
| DTB | `amlogic/meson-g12b-a311d-khadas-vim3` |
| FIP（Firmware Image Package，固件镜像包） | `amlogic-boot-fip/khadas-vim3/` + `aml_encrypt_g12b` |
| 串口 | UART_AO，`console=ttyAML0,115200n8` |
| 存储 | eMMC 为 U-Boot `mmc2`；bootloader 写 hardware boot0，boot/rootfs 写 user-area GPT |
| Wi-Fi/BT | AP6398S（BCM4359），复用 VIM3L 的 fenix 三件套；BT 由 DTS serdev 自动绑定 |

VIM3 与 VIM3L 共用 `meson-khadas-vim3.dtsi`，因此 eMMC、SDIO Wi-Fi、UART BT、GbE、MCU、USB 和
40-pin header 基线相同。不能共用的是 SoC DTB、U-Boot defconfig、FIP board 目录与加密工具；VIM3L 的
SM1/G12A blob 不可用于 VIM3/G12B。

## 刷写

先连接 USB-C；在两秒内快速按 Function 键三次并立即松开。确认 host 看到 MaskROM
（掩膜只读存储器启动模式）`1b8e:c003` 后执行：

```bash
flange flash
```

现有 `AmlogicFlashStrategy` 会用 `boot-g12.py` 推裸 FIP，U-Boot fragment 自动进入 fastboot，随后执行
唯一设备枚举及 `getvar version` 只读握手。看到“fastboot 已就绪”后才执行
`fastboot oem format` 并刷写 bootloader/boot/rootfs；后续命令绑定该设备的序列号。

2026-09-05 的现场反馈：MacBook 使用 USB-C to USB-C 线时，旧流程首次调用在 `oem format`
等待，中断后重试恢复；用户确认其他连接方式未触发同一现象。串口已进入 U-Boot fastboot，
`crq->brequest:0x0` 为 USB 状态请求的普通打印，不能据此判定协议就绪。
当前宿主机流程以最长 30 秒的枚举与握手取代固定 3 秒休眠，单次探测最多 5 秒，
GPT 写入另有 30 秒超时。自动恢复与停止写入边界已通过模拟测试，C-to-C 冷启动首刷仍待实机复测。
具体状态与恢复步骤见[开发指南](../../docs/development-guide.md#amlogic-首次-usb-刷写)。

## 板级数据

- `dtso/vim3-spidev-spicc1.dtso`：默认启用 SPICC1；用户态设备编号以实机枚举为准。
- `dtso/vim3-fan-led.dtso`：默认启用三档风扇温控、白灯心跳与红灯运行常亮。
- `overlay/etc/hostname`：主机名 `khadas-vim3`。
- `overlay/etc/usbdevice.conf`：ADB gadget 使用 AOSP VID `0x18d1`。
- `overlay/etc/modules-load.d/flange-usbgadget.conf`：在 adbd 初始化前加载 `libcomposite`。
- 不添加 `btattach` service：mainline DTS 已声明 Bluetooth serdev 子节点。

## 风扇与 LED

主线 Linux v6.12 使用 MCU（微控制器）风扇驱动和 thermal（温控）子系统。MCU 位于 I2C AO 的
`0x18`，风扇接口提供 0（停转）/1（低）/2（中）/3（高）四种状态，不提供 RPM 转速反馈。
本板配置把驱动及其依赖内建，四个 target 使用相同策略：

| CPU 升温温度点 | 请求档位 | 降温退出温度点 |
|---|---|---|
| 50°C | 1（低速） | 45°C |
| 60°C | 2（中速） | 55°C |
| 70°C | 3（高速） | 65°C |

5°C 回差用于避免在阈值附近反复切换；实际降档由 `step_wise` 在后续采样中完成，多个有效温度点取最高请求档位。
上游 85°C CPU 降频、95°C hot 与 110°C critical 保护保持不变。温度策略在
`vim3-fan-led.dtso` 中可调整，修改后重建 boot。

在板上查询驱动与温度，不固定 `cooling_deviceN` / `thermal_zoneN` 编号：

```sh
for dev in /sys/class/thermal/cooling_device*; do
    [ "$(cat "$dev/type")" = khadas-mcu-fan ] || continue
    printf '%s: 当前档位=' "$dev"
    cat "$dev/cur_state"
    printf '最大档位='
    cat "$dev/max_state"
done
for zone in /sys/class/thermal/thermal_zone*; do
    printf '%s ' "$(cat "$zone/type")"
    cat "$zone/temp"
done
```

温度单位为千分之一摄氏度。应能看到 `khadas-mcu-fan` 且 `max_state=3`；实际风扇需连接板载风扇座。
直接写 `cur_state` 只适合短时调试，会被自动温控覆盖；无需安装 `fan.sh` 或写 I2C 寄存器。
[Khadas 官方风扇说明](https://docs.khadas.com/products/sbc/vim3/add-ons/cooling-fan)也区分了主线 thermal 与下游 `/sys/class/fan` 接口。

LED（发光二极管）沿用主线名称：白灯 `/sys/class/leds/white:status` 连接 GPIOAO_4，默认 `heartbeat`；
红灯 `/sys/class/leds/red:status` 连接 TCA6408 扩展器 GPIO5，默认 `default-on`。它们表示 Linux 运行状态，
不表示 MCU 或 BootROM 阶段的电源状态。板上用 root 权限执行：

```sh
# 查看当前触发器（方括号中为当前值）。
cat /sys/class/leds/white:status/trigger
cat /sys/class/leds/red:status/trigger
# 熄灭红灯需同时退出触发器并写入亮度。
echo none > /sys/class/leds/red:status/trigger
echo 0 > /sys/class/leds/red:status/brightness
# 恢复默认灯效。
echo default-on > /sys/class/leds/red:status/trigger
echo heartbeat > /sys/class/leds/white:status/trigger
```

部署前运行 `flange --target khadas-vim3-default-debug build boot`，将包含新 Image 与两个默认 overlay 的 boot
产物部署到对应目标；不需要重刷 bootloader。适配验证覆盖编译、配置和 DTB 合并。

2026-09-06 实板验证：CPU 模拟温度输入已验证自动三档及降温回差，用户确认风扇实际起转和
低、中、高速变化；测试后已清除模拟温度并恢复真实温度控制。尚未做实际加热压力测试或 RPM 测量。
红灯常亮与关闭已确认。白灯虽已配置 heartbeat，且强制常亮时 GPIO 读回为高，但实物未亮，
关闭红灯后仍未亮；根因未定位，用户决定暂缓排查，不计为白灯实板验收通过。

## 实板验收边界

- VIM3 V14 调整过 DRAM 配置；旧 FIP blob 可能无法启动，必须以目标硬件实刷确认。
- PCIe 与 USB3 由板载 MCU mux，当前不强制选择任一路径。
- NPU、VPU、PCIe/USB3 切换和 SPI NOR 启动不在本变更范围；不得据此页宣称已支持。

参考：[U-Boot VIM3 文档](https://docs.u-boot.org/en/v2024.10/board/amlogic/khadas-vim3.html)、
[Linux v6.12 VIM3 DTS](https://github.com/torvalds/linux/blob/v6.12/arch/arm64/boot/dts/amlogic/meson-g12b-a311d-khadas-vim3.dts)、
[Khadas V14 说明](https://docs.khadas.com/products/sbc/vim3/troubleshooting/vim3-v14)。
