---
title: orangepi-5-plus
type: board
status: wip
sources:
  - components/board/orangepi-5-plus/config.py
  - components/board/orangepi-5-plus/overlay/etc/hostname
  - components/board/orangepi-5-plus/overlay/etc/usbdevice.conf
  - components/board/orangepi-5-plus/overlay/usr/lib/firmware/goodix_911_cfg.bin
  - components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso
  - components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso
  - components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg
  - components/platform/rockchip/rk3588/config.py
related:
  - "[[radxa-rock5b]]"
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[新增板级支持]]"
updated: 2026-05-18
---

## TL;DR

OrangePi 5 Plus，RK3588，项目第二块 RK3588 板。首版落地：eMMC + UART2 + SSH + M.2 E-Key RTL8852BE WiFi/BT，逐字段复用 [[radxa-rock5b]] 模板。第二批：30-pin DSI FPC 接 HX8399-A 1080×1920 portrait 4-lane MIPI DSI 面板 + GT911 5-point 电容触摸（软件落地完成，实机点屏验收 pending）。第三批：板载 HDMI IN 口启用（一句 overlay 翻 `hdmirx_ctrler.status` 即可，driver 已 in-tree）。HDMI TX / NPU / NVMe / 板载 AP6275P / 双 2.5G NIC 显式配置 / PWM 风扇 / RGB LED 不在范围（RTL8125 走 r8169 主线驱动零配置自动 probe）。

## product / variant

```
lunch orangepi-5-plus-default-debug
lunch orangepi-5-plus-default-release
```

## 与 ROCK 5B 差异

| 项 | 值 |
|---|---|
| DTB | `rk3588-orangepi-5-plus`（rkr5.1 已含） |
| hostname | `orangepi-5-plus` |
| 板私有 dtso | `rk3588-orangepi-5-plus-hx8399a-gt911.dtbo`（DSI 屏 + 触摸）+ `rk3588-orangepi-5-plus-hdmirx-enable.dtbo`（HDMI IN 启用），均默认应用 |

其余（u-boot 仓 + `next-dev-v2026.01` + generic `rk3588_defconfig`、kernel `linux-6.1-stan-rkr5.1` + panthor fragment、mali-csf firmware、rockchip-mpp 多媒体栈、5 分区布局、RTL8852BE OOT 链路、UART2 1500000 console、mkimage_chip=rk3588）沿用 SoC 层与 ROCK 5B。

## WiFi / BT

逐字段等价 [[radxa-rock5b]]：rkwifibt OOT 编 `8852be.ko`，BT 走 in-tree btusb + 板私有 firmware 拷 `rtl8852bu_fw.bin` / `rtl8852bu_config.bin` 到 `/lib/firmware/rtl_bt/`。

## DSI 屏 + 触摸（HX8399-A + GT911）

30-pin DSI FPC 接 HX8399-A 1080×1920 portrait 4-lane MIPI DSI 面板 + GT911 5-point 电容触摸（**软件落地完成，实机验收 pending**）。接线复用 vendor `rk3588-orangepi-5-plus-lcd.dtsi`：panel reset GPIO2_C1 / VCC_LCD EN GPIO1_D2 / backlight `&backlight_1` PWM / touch i2c7@0x14 INT GPIO2_B2(rising) RST GPIO2_B5。

- Panel 走 BSP `panel-simple.c` 的 `simple-panel-dsi` + `panel-init-sequence` 路径——LCD 厂 init `.c` 与 dts 字节流 1:1 对应（16 cmd / 319 字节）。零 driver / 零 kernel patch
- Touch 走 mainline `goodix.c`（compatible `"goodix,gt911"`）；与 vendor `gt9xx` (`"goodix,gt9xx"`) 不撞。启动 `request_firmware("goodix_911_cfg.bin")` 拉 186B cfg（= `GOODIX_CONFIG_911_LENGTH`）
- cfg blob 走 `overlay/usr/lib/firmware/`（不走 `+extra_firmware`，那是 vendor 仓库 source 接口、非 board-local 接口；现有 `_install_overlays` cp -a 机制覆盖此场景）。**走 `usr/lib` 不走 `lib`**：ubuntu-base rootfs 已 usrmerge，根 `/lib` 是 symlink → `/usr/lib`，`cp -a` 不能用目录覆盖 non-directory，所以 board overlay 必须从 usrmerge 后路径起手
- VOP3 → DSI1 路由独立于 HDMI VP0/VP1，双显可并存
- dtso 全 `&label{}` fragment，规避 [[orangepi-cm4]] 屏适配撤回 change 的根级裸节点 → `FDT_ERR_BADOVERLAY` 坑
- `MIPI_DSI_MODE_EOT_PACKET` 旧宏 BSP 6.1 头文件已删，本案选择"不引用"走默认发 EOT（与 [[rp-pro-rk3568-h]] 的 `0002-...-eot-packet-compat.patch` 不同选择——那板 25+ LCD dtsi 引用旧名绕不开 patch，本板从零写 dtso 主动规避）

详见 `docs/superpowers/specs/2026-05-18-orangepi-5-plus-hx8399a-gt911-design.md`（设计 + 风险）与同名 `plans/` 实施计划。

## HDMI RX (HDMI IN)

板载 HDMI IN 口走 SoC `hdmirx_ctrler@fdee0000`（compatible `rockchip,rk3588-hdmirx-ctrler`）。BSP 三层默认 disabled：

```
rk3588.dtsi:541                          status="disabled"  # SoC 层
rk3588-orangepi-5-plus.dtsi:395          status="disabled"  # 板 dtsi（还写齐了 HPD/det-gpio/pinctrl）
rk3588-orangepi-5-plus.dts:323-325       status="disabled"  # 板 dts（最终显式重申）
```

driver `CONFIG_VIDEO_ROCKCHIP_HDMIRX=y` / `CONFIG_VIDEO_ROCKCHIP_HDMIRX_CLASS=y` 已在 argon `rockchip_linux_defconfig` 编入 vmlinuz——驱动就绪、节点配置就绪，仅差 status。

本板做法：`rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 一句 `&hdmirx_ctrler { status = "okay"; };`，默认应用。HPD/det-gpio/pinctrl 等属性留给板 dtsi（single source of truth）。

`hdmiin-sound` 节点（dtsi:85-95）无 status 字段 → 默认 okay，codec 指 `<&hdmirx_ctrler 0>`，controller 起来后 audio 自动跟随。

Rollback：板上 `/boot/extlinux/extlinux.conf` 删 fdtoverlays 行内 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 一项，重启即恢复 disabled，不影响 DSI 屏 overlay。

实机验收 pending（adb 探测期间 `/sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status` 仍是 `disabled`，待重刷镜像后验 `/dev/video*` 出现）。
