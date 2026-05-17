---
title: orangepi-cm4
type: board
status: stable
sources:
  - components/board/orangepi-cm4/config.py
  - components/board/orangepi-cm4/patches/kernel/0001-dts-orangepi-cm4-bootargs-fix.patch
  - components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch
  - components/board/orangepi-cm4/patches/kernel/0003-dts-orangepi-cm4-disable-rknpu.patch
  - components/board/orangepi-cm4/overlay/etc/hostname
  - components/board/orangepi-cm4/overlay/etc/usbdevice.conf
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-05-17
---

## TL;DR

Orange Pi CM4，RK3566 计算模块。当前交付范围：**无屏可启动 + AP6256 WiFi/BT 即插即用**，禁用不可用 NPU。DSI 屏适配（实机用 Waveshare CM4-DISP-BASE-5A）尚未交付，单独立项推进。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。

```
lunch orangepi-cm4-default-debug
lunch orangepi-cm4-default-release
```

## 关键差异点

| 项 | 值 |
|---|---|
| DTB | `rk3566-orangepi-cm4-base`（保持空壳） |
| board overlay | 无（dsi1 维持 dtsi 默认 disabled） |
| kernel patches | `0001` bootargs、`0002` bcmdhd FW_AMPAK_PATH、`0003` disable rknpu |
| extra_firmware | radxa-firmware 仓拉 AP6256 三件套到 `/lib/firmware/brcm/` |
| bootloader | 使用平台/SoC 默认 commit |

## AP6256 WiFi/BT

固件三件套（BCM4345C5）：`fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt` / `BCM4345C5.hcd` → `/lib/firmware/brcm/`。配套两条 kernel patch：

- `0001` 改 `rk3566-orangepi-cm4.dtsi` chosen.bootargs：删硬编码 `root=PARTUUID`（避免覆盖 extlinux APPEND，断 normal/recovery 切换）、加 `firmware_class.path=/lib/firmware`。与 tspi-rk3566 0001 同因。
- `0002` 启用 bcmdhd `FW_AMPAK_PATH="brcm"`，让固件名拼出 `brcm/` 前缀。与 tspi-rk3566 0002 一字不差。

BT 仅做"硬件就绪 + patchram 到位"，未预装 bluez 等用户态包，应用层栈由产品方自取。

## NPU

`rk356x.dtsi` 默认禁用 `rknpu` / `rknpu_mmu`，但 Orange Pi CM4 dtsi 又改成 `okay`。实机日志显示 `rknpu_mmu` probe 拉起 NPU power domain 后，PMU 等不到 `npu` ack，会触发 BSP `panic_on_set_idle`。`0003` 把两处状态改回 `disabled`，优先保证默认镜像可启动。

## DSI 屏适配（未交付，单独立项）

实机底板是 Waveshare CM4-DISP-BASE-5A（5" DSI 屏），桥芯片 Chipone ICN6211 在 i2c1@0x2c，EN 板上拉死高无独立 reset GPIO。本轮 change（`orangepi-cm4-bringup-wifi-and-npu-fix`）尝试一次性带屏适配但实机不能正常启动，已撤回。详细踩坑见 `wiki/log.md` 2026-05-17 条目：

- dtsi 错抄的 RPi 7" panel 模板（`raspits_panel@45` / `raspits_touch_ft5426@38`）与实际 ICN6211 链路不匹配
- BSP `drm_mipi_dsi.c::mipi_dsi_remove_device_fn` 缺 `bus_type` 校验，DSI defer cleanup NULL deref（上游 commit `7977c539e9b1` 等价 fix 未合）
- `CONFIG_DRM_CHIPONE_ICN6211` 未启用，driver 编不进
- mainline ICN6211 driver 强制要求 `enable-gpios`，与本板硬件不符
- dtso 根级新增节点必须 `&{/} {}` 显式包成 fragment，否则 u-boot `FDT_ERR_BADOVERLAY`

未来开屏适配 change 时直接复用上述路标。

## overlay

`overlay/etc/hostname` + `overlay/etc/usbdevice.conf`，无额外定制内容。
