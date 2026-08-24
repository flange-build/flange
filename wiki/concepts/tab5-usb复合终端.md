---
title: Tab5 USB 复合终端
type: concept
status: wip
sources:
  - components/packages/tab5-all-in-one/README.md
  - components/packages/tab5-all-in-one/firmware/README.md
related:
  - "[[Cardputer USB 复合设备]]"
  - "[[GUD 屏作 X11 显示]]"
updated: 2026-08-24
---

## TL;DR

M5Stack Tab5（ESP32-P4）通过一根 USB-C 线向 Linux 主机提供 GUD 显示、HID 键盘与五点触摸、UAC1 全双工音频和 UVC 摄像头。设备使用 `16d0:10a9`，Linux 主机侧全部复用 mainline driver，不需专用内核模块。

## 当前能力

- GUD 把 640×360 RGB565 画面经 PPA 放大、旋转到 720×1280 MIPI-DSI 面板。
- 键盘与 GT911 触摸共用 HID 接口；音频为 16 kHz/单声道/S16_LE。
- SC202CS 经 CSI/ISP/PPA/JPEG 输出 MJPEG 640×360@10 fps，`uvcvideo` 已有真实画面验证。
- 五项功能均分别上板通过；同时全开 10 分钟、GUD 帧率与音频时钟漂移仍未验收。

## ISP 现状与边界

当前代码是自研 T0–T13 管线；短暂接入官方 `esp_ipa` 后出现
`HP_SYS_HP_WDT_RESET`，已回退。T0–T13 的宿主机测试已通过，但整轮 ISP 对齐未上板，不应把仿真结果当成画质验收。USB-C 只有 12 Mbps 全速带宽，UVC 打开后显示变慢是物理上限。

固件使用 ESP-IDF v6.0.2 在 Docker 外构建；P4 rev 1.x 与 rev 3.x 不能共用同一份固件。
