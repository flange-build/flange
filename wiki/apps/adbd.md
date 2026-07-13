---
title: adbd
type: app
status: stable
sources:
  - components/app/adbd/app.yaml
  - components/app/adbd/bin/adbd-arm64
  - components/app/adbd/conf/usbdevice.conf
  - components/app/adbd/scripts/usbdevice
  - components/app/adbd/systemd/usbdevice.service
  - components/app/adbd/udev/61-usbdevice.rules
  - components/board/atk-rk3506b/overlay/etc/modules-load.d/flange-usbgadget.conf
related:
  - "[[recoveryctl]]"
  - "[[recovery 系统]]"
  - "[[atk-rk3506b]]"
updated: 2026-07-14
---

## TL;DR

USB ADB gadget 服务，可运行于 normal 或 recovery rootfs，提供 host ↔ device 调试通道。支持 DWC2/DWC3 与模块化 ConfigFS gadget；[[atk-rk3506b]] 已验证断电冷启动后自动绑定并可 `adb shell`。

## 关键设计要点

- **app.yaml 类型**：`type: service`，`arch: [aarch64, armhf]`，`capabilities: [usb-gadget, adb-debug]`
- **二进制**：预编译 `bin/adbd-arm64` / `bin/adbd-armhf`，无编译步骤
- **systemd unit**：`usbdevice.service`（`Type: forking`）要求 `sys-kernel-config.mount`，并排在 `systemd-modules-load.service` 之后；入口 `/usr/sbin/usbdevice start` 负责启动 adbd
- **udev 规则**：`61-usbdevice.rules` 监听 `android_usb` 状态变化，触发 `usbdevice update`
- **配置文件**：`/etc/usbdevice.conf`（conffiles，升级不覆盖）；板级 overlay 覆盖 VID/PID；默认 `USB_FUNCS=adb`，序列号取自 cpuinfo
- **USB gadget 依赖**：`usbdevice` 在 configfs 创建 gadget group、挂载 functionfs、等待 `ep1` 后写 UDC；函数顺序由内核要求排列
- **模块化内核自愈**：板级 `modules-load.d` 冷启动加载 `phy-rockchip-inno-usb2`、`dwc2`、`usb_f_fs`；脚本若未看到 `usb_gadget`，会幂等 `modprobe usb_f_fs` 并给出明确错误
- **最小 rootfs**：`fuser` 仅用于占用诊断/清理；未安装 `psmisc` 时安全降级，不阻断 gadget 初始化
- **与 normal rootfs 差异**：recovery rootfs 默认启用；normal rootfs 取决于板级配置

## 关键代码位置

- [scripts/usbdevice](../../components/app/adbd/scripts/usbdevice) — gadget 编排（start / stop / update）
- [conf/usbdevice.conf](../../components/app/adbd/conf/usbdevice.conf) — 默认配置，板级 overlay 覆盖
- [systemd/usbdevice.service](../../components/app/adbd/systemd/usbdevice.service) — systemd unit
- [udev/61-usbdevice.rules](../../components/app/adbd/udev/61-usbdevice.rules) — udev 触发

## 易踩坑

- UDC 已绑定时写 `idProduct` 触发软断开，与 udev 形成无限触发循环；`update` 动作会跳过此写入
- adbd 须先打开 `ep1`，`usbdevice` 轮询 `/proc/<pid>/fd/` 确认后才写 UDC
- **UDC bind 竞态**：脚本写 UDC 后立即 read-back；不一致则退出 1，由 systemd 以 2 秒间隔有界重试。持续失败应检查 controller `dr_mode`/role、VBUS/ID、PHY 与 dmesg，不能把所有 DWC2/DWC3 故障都归因于 USB-C PD
