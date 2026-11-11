# luckfox-pico-pro-max

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list luckfox-pico-pro-max` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Luckfox Pico Pro (RV1106G2 128MB) / Max (RV1106G3 256MB) 单板计算机，Cortex-A7 @ 1.1GHz，256MB SPI NAND（Winbond W25N02KV），板载内置百兆以太网 PHY（rk630phy）、USB 2.0 OTG、用户工作指示灯。本仓库内置 `default` 产品使用 Ubuntu Base；Alpine Linux（musl + apk + OpenRC）由外部发行版层提供。
下列完整构建、刷写、网络和 musl App 结果属于外部 Alpine 目标，不代表 Ubuntu 产品完成同等验收。

## 配置与产物

| 项 | 值 |
|---|---|
| SoC | Rockchip RV1106（ARMv7 / Cortex-A7，userspace=armhf，kernel/bootloader=arm） |
| 启动介质 | 256MB SPI NAND（2048B page，128KB PEB），GPT 分区表 |
| Bootloader | U-Boot（`rv1106_defconfig` + `rv1106-optee.config`，`CONFIG_EFI_PARTITION: 'y'`） |
| 内核 | Linux 6.1.115+（`rv1106g-luckfox-pico-pro-max.dts`，vendor FIT `boot.img`） |
| 根文件系统 | UBI 卷 `ubi0:rootfs`（mtd3，223MB），Alpine Linux（musl + apk + OpenRC）或 Ubuntu Base |
| 调试通道 | USB gadget（FunctionFS adbd + usbmoded），串口 `ttyFIQ0`，以太网 SSH |

## 实机验收结果

2026-11-09 至 11-10，在 RV1106G3 Max、W25N02KV 256MB SPI NAND 上完成外部 Alpine 目标验证。
基线为 Alpine 3.24.4、musl 1.2.6、apk 3.0.9、OpenRC；镜像包含 124 个 APK，解包约 72 MB，UBI 约 20 MB。
没有 systemd/dpkg/apt。外部层与 SDK 不随此仓库发布，接入约定见[多层工作区](../layers.md)。

- **启动与控制台**：U-Boot 解析 SPI NAND 上的 GPT 分区表，加载 vendor FIT boot.img；Linux 内核启动，板载工作灯以 heartbeat 双闪指示内核运行。
- **存储**：UBI 驱动正确挂载 223MB rootfs 分区并以 UBIFS 启动系统。
- **以太网**：百兆以太网（内置 FEPHY）自动协商 100Mbps/Full，通过 DHCP 获取网络地址，SSH 服务可用。
- **USB 调试（ADB）**：OpenRC 下 usbmoded 管理 DWC3 peripheral，正确拉起 adbd，实机稳定枚举。
- **App 运行时**：通过 `flange app` 成功构建、部署并运行 C++ / musl / zlib 测试程序（`musl-check`）；使用 armv7 musl SDK 和 Clang 21，动态加载器为 `/lib/ld-musl-armhf.so.1`。

## 启动约束

SPI NAND 的 page 为 2048 B、PEB 为 128 KiB；GPT 中 idbloader、uboot、boot、rootfs 的起始扇区分别为
`0x40`、`0x4000`、`0x8000`、`0x10000`。U-Boot 必须开启 EFI_PARTITION，SPL 的下一阶段偏移为 `0x4000`。
当前板级供电将 vdd_arm 设为 900 mV，移除高于 1104 MHz 的 OPP；不得直接套用其他 RV1106 板的电压/频率表。
