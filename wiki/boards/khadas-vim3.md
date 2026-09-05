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
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list khadas-vim3` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Khadas VIM3 使用 Amlogic A311D（G12B，2×Cortex-A53 + 4×Cortex-A73），复用现有 Amlogic
mainline 构建和 pyamlboot → fastboot（快速刷写协议）链路。软件配置与构建输入已验证，实板启动、V14 DRAM
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
`fastboot oem format` 并刷写 bootloader/boot/rootfs。

## 板级数据

- `dtso/vim3-spidev-spicc1.dtso`：默认启用 SPICC1；用户态设备编号以实机枚举为准。
- `overlay/etc/hostname`：主机名 `khadas-vim3`。
- `overlay/etc/usbdevice.conf`：ADB gadget 使用 AOSP VID `0x18d1`。
- `overlay/etc/modules-load.d/flange-usbgadget.conf`：在 adbd 初始化前加载 `libcomposite`。
- 不添加 `btattach` service：mainline DTS 已声明 Bluetooth serdev 子节点。

## 实板验收边界

- VIM3 V14 调整过 DRAM 配置；旧 FIP blob 可能无法启动，必须以目标硬件实刷确认。
- PCIe 与 USB3 由板载 MCU mux，当前不强制选择任一路径。
- NPU、VPU、PCIe/USB3 切换和 SPI NOR 启动不在本变更范围；不得据此页宣称已支持。

参考：[U-Boot VIM3 文档](https://docs.u-boot.org/en/v2024.10/board/amlogic/khadas-vim3.html)、
[Linux v6.12 VIM3 DTS](https://github.com/torvalds/linux/blob/v6.12/arch/arm64/boot/dts/amlogic/meson-g12b-a311d-khadas-vim3.dts)、
[Khadas V14 说明](https://docs.khadas.com/products/sbc/vim3/troubleshooting/vim3-v14)。
