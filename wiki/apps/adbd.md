---
title: adbd
type: app
status: stable
sources:
  - components/app/adbd/app.yaml
  - components/app/adbd/conf/usbdevice.conf
  - components/app/adbd/scripts/usbdevice
  - components/app/adbd/systemd/usbdevice.service
  - components/app/adbd/udev/61-usbdevice.rules
related:
  - "[[recoveryctl]]"
  - "[[recovery 系统]]"
  - "[[atk-rk3506b]]"
updated: 2026-08-24
---

## TL;DR

USB ADB gadget 服务，可运行在 normal 或 recovery rootfs。它用 ConfigFS 组装 gadget、挂载 FunctionFS，等 adbd 打开 `ep1` 后再绑定 UDC，适配 DWC2/DWC3 和模块化 gadget 内核。

## 自愈路径

- `usbdevice.service` 的 `start` 启动 adbd，`reload` 执行幂等的 `usbdevice update`。
- udev 监听 `android_usb change` 和 `udc add|change`，通过
  `systemctl --no-block reload usbdevice.service` 异步触发更新。不在 udev worker 中直接启动 adbd，避免事件结束时进程被清理。
- UDC 绑定后立即 read-back；不一致则退出 1，systemd 以 2 秒间隔有界重试。

## 边界

`/etc/usbdevice.conf` 是 conffile，板级可覆盖 VID/PID；默认只启用 ADB。持续绑定失败时应查 controller `dr_mode`/role、VBUS/ID、PHY 和 dmesg，不能把所有 DWC2/DWC3 故障都归因于 USB-C PD。
