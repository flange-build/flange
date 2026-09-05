---
title: orangepi-5-plus
type: board
status: wip
sources:
  - components/board/orangepi-5-plus/config.jsonnet
  - components/board/orangepi-5-plus/overlay/etc/hostname
  - components/board/orangepi-5-plus/overlay/etc/usbdevice.conf
  - components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.bin
  - components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso
  - components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso
  - components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg
  - components/platform/rockchip/rk3588/config.jsonnet
  - docs/first-steps.md
related:
  - "[[radxa-rock5b]]"
  - "[[rockchip 平台]]"
  - "[[out-of-tree 模块]]"
  - "[[新增板级支持]]"
updated: 2026-09-05
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list orangepi-5-plus` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

OrangePi 5 Plus，RK3588，项目第二块 RK3588 板。首版落地：eMMC + UART2 + SSH + M.2 E-Key RTL8852BE WiFi/BT，逐字段复用 [[radxa-rock5b]] 模板。第二批：30-pin DSI FPC 接 HX8399-A 1080×1920 portrait 4-lane MIPI DSI 面板 + GT911 5-point 电容触摸（**实机已验**：DSI 屏出图 / 触摸 4 角与 weston 1:1 对齐）。第三批：板载 HDMI IN 口启用（一句 overlay 翻 `hdmirx_ctrler.status` 即可，driver 已 in-tree）。HDMI TX / NPU / NVMe / 板载 AP6275P / 双 2.5G NIC 显式配置 / PWM 风扇 / RGB LED 不在范围（RTL8125 走 r8169 主线驱动零配置自动 probe）。

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

30-pin DSI FPC 接 HX8399-A 1080×1920 portrait 4-lane MIPI DSI 面板 + GT911 5-point 电容触摸。接线复用 vendor `rk3588-orangepi-5-plus-lcd.dtsi`：panel reset GPIO2_C1 / VCC_LCD EN GPIO1_D2 / backlight `&backlight` PWM / touch i2c7@0x14 INT GPIO2_B2(rising) RST GPIO2_B5。

- Panel 走 BSP `panel-simple.c` 的 `simple-panel-dsi` + `panel-init-sequence` 路径——LCD 厂 init `.c` 与 dts 字节流 1:1 对应（16 cmd / 319 字节）。零 driver / 零 kernel patch
- Touch 走 mainline `goodix.c`（compatible `"goodix,gt911"`）；与 vendor `gt9xx` (`"goodix,gt9xx"`) 不撞。启动 `request_firmware("goodix_911_cfg.bin")` 拉 186B cfg（= `GOODIX_CONFIG_911_LENGTH`）
- cfg blob 当前由 `sources.goodix-911-cfg` 引用板级 `firmware/touch/`，经 `rootfs.extra_firmware` 安装。历史 overlay 方案使用 `usr/lib/firmware/` 是为避开 usrmerge 根 `/lib` symlink 的目录覆盖冲突；该约束仍值得保留，不能把旧文件落点当当前源码位置。
- VOP3 → DSI1 路由独立于 HDMI VP0/VP1，双显可并存
- dtso 全 `&label{}` fragment，规避 [[orangepi-cm4]] 屏适配撤回 change 的根级裸节点 → `FDT_ERR_BADOVERLAY` 坑
- `MIPI_DSI_MODE_EOT_PACKET` 旧宏 BSP 6.1 头文件已删，本案选择"不引用"走默认发 EOT
- **触摸坐标 transform**：chip 物理安装与 panel 原生方向 1:1（实机 evtest 抓四角推回 chip raw 验证），不需任何 swap/invert；overlay 设 `touchscreen-size-x=<1080>; touchscreen-size-y=<1920>;`，input absinfo 与 chip cfg 报告范围对齐

### 易踩坑

- **u-boot fdt_overlay_apply 不支持 delete marker**：`overlay_apply_node()` (lib/libfdt/fdt_overlay.c:550) 只 additive merge —— 对每个 property 调 `fdt_setprop()`（覆盖/新增），对 subnode 递归 add；完全没 `__delete_property__` / `__delete_node__` 处理。所以 overlay 的 `/delete-property/` / `/delete-node/` **不生效**：dtc 编 overlay 时直接把 delete 当 dts AST 时操作（不存在的属性自然就不写进 dtbo），u-boot apply 时 base 的同名属性原封不动。要删 vendor 注入的 boolean transform 只能走 kernel patch 或上游修源。本板早期写过 board kernel patch 删 vendor `touchscreen-inverted-x / touchscreen-swapped-x-y`，upstream argon `linux-6.1-stan-rkr5.1` commit `b173d7a80` 整段注释 vendor demo 节点后 patch 撤销

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

**Console 安静策略**：driver `rk_hdmirx.c:1685` 在无 HDMI 源时按 `v4l2_err`（KERN_ERR=3）刷 "HDMI pull out, return!"，cmdline `loglevel=4` 压不住。由 base rootfs `components/rootfs/overlay/etc/sysctl.d/10-console-quiet.conf` 设 `kernel.printk = 1 4 1 7` 在 systemd-sysctl 早期 apply 后只让 KERN_EMERG 上 console，kernel boot 期不受影响。该 sysctl 是 base rootfs 全板生效，本板 HDMI RX spam 是其首要受益者之一。
