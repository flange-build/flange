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
related:
  - "[[recoveryctl]]"
  - "[[recovery 系统]]"
updated: 2026-04-26
---

## TL;DR

USB ADB 服务，运行于 recovery rootfs，提供 host ↔ device 通道；[[recoveryctl]] 依赖此通道接收宿主机指令。

## 关键设计要点

- **app.yaml 类型**：`type: service`，`arch: [aarch64, armhf]`，`capabilities: [usb-gadget, adb-debug]`
- **二进制**：预编译 `bin/adbd-arm64` / `bin/adbd-armhf`，无编译步骤
- **systemd unit**：`usbdevice.service`（`Type: forking`，`WantedBy: sysinit.target`）；入口 `/usr/sbin/usbdevice start` 负责启动 adbd
- **udev 规则**：`61-usbdevice.rules` 监听 `android_usb` 状态变化，触发 `usbdevice update`
- **配置文件**：`/etc/usbdevice.conf`（conffiles，升级不覆盖）；板级 overlay 覆盖 VID/PID；默认 `USB_FUNCS=adb`，序列号取自 cpuinfo
- **USB gadget 依赖**：`usbdevice` 在 configfs 创建 gadget group、挂载 functionfs、等待 `ep1` 后写 UDC；函数顺序由内核要求排列
- **与 normal rootfs 差异**：recovery rootfs 默认启用；normal rootfs 取决于板级配置

## 关键代码位置

- [scripts/usbdevice](../../components/app/adbd/scripts/usbdevice) — gadget 编排（start / stop / update）
- [conf/usbdevice.conf](../../components/app/adbd/conf/usbdevice.conf) — 默认配置，板级 overlay 覆盖
- [systemd/usbdevice.service](../../components/app/adbd/systemd/usbdevice.service) — systemd unit
- [udev/61-usbdevice.rules](../../components/app/adbd/udev/61-usbdevice.rules) — udev 触发

## 易踩坑

- UDC 已绑定时写 `idProduct` 触发软断开，与 udev 形成无限触发循环；`update` 动作会跳过此写入
- adbd 须先打开 `ep1`，`usbdevice` 轮询 `/proc/<pid>/fd/` 确认后才写 UDC
- **UDC bind 早于 dwc3 ready 的 race**：RK3588 等带 USB-C PD 控制器（如 fusb302 在 i2c-6）的板，dwc3 (`fc000000.usb`) 必须等 Type-C 角色协商完成才能接收 gadget binding。`usbdevice.service` 在 sysinit 阶段拉起，若此时 PD 协商未完成，写 sysfs `UDC` attr 会被 kernel 抛 `-19 (ENODEV)`、`udc fc000000.usb: failed to start rockchip` 一行 dmesg。修法：脚本在 `Writing UDC=` 后 read-back 校验 UDC attr 是否真的接受 controller name，失败 exit 1；service unit `Restart=on-failure RestartSec=2 StartLimitBurst=5 StartLimitIntervalSec=30`，2 秒后 cold restart。typically 一两次重试就能成功；30s 后若仍失败认为是硬件真问题（USB cable 断 / hub 异常）systemd 停止重试
