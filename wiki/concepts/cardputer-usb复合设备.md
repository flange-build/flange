---
title: Cardputer USB 复合设备
type: concept
status: stable
sources:
  - components/board/atk-rk3506b/config.jsonnet
  - components/packages/cardputer-all-in-one/README.md
  - docs/boards/atk-rk3506b.md
  - openspec/specs/rockchip-atk-rk3506b/spec.md
  - openspec/changes/archive/2026-07-15-add-rk3506b-atk-rk3506b/evidence/rk3506b-hardware-acceptance.md
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[atk-rk3506b]]"
  - "[[GUD 屏作 X11 显示]]"
updated: 2026-09-05
---

> 阅读前提：先确认[板卡配置与硬件范围](../boards/index.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；历史排障记录不代表全部目标已验收。
> 当前构建入口见[开发指南](../../docs/development-guide.md)，新增驱动/配置见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

Cardputer `16d0:10a9` 是 GUD（Generic USB Display，通用 USB 显示）、HID 键盘与
UAC1（USB Audio Class 1，USB 音频类）组成的复合设备。[[atk-rk3506b]] 的 USB1 Host
可自动绑定三个 class driver，并把它作为掌上 TTY console、输入设备和音频终端使用。

## Host 契约

| interface | 功能 | Linux driver |
|---|---|---|
| 0 | 240×135 GUD | `gud` |
| 1/2/3 | AudioControl、扬声器、麦克风 | `snd-usb-audio` |
| 4 | HID Boot Keyboard | `usbhid` |

板级 kernel 启用 `CONFIG_DRM_GUD=y`、`CONFIG_USB_HID=m` 与
`CONFIG_SND_USB_AUDIO=m`；`console=tty1 fbcon=map:1` 将 TTY 映射到 GUD framebuffer。
rootfs 提供 `evtest` 和 `alsa-utils`。414 MiB UBI 的 debug 包集保留
`gdb`/`strace`/`tcpdump`，不安装约 40 MiB 的 `valgrind`。

## 实机验收

2026-07-15 ADB 验证三个 driver 自动绑定，HID 输入和 GUD TTY 正常。ALSA 将 UAC1
枚举为 mono、16000 Hz、S16_LE 的 playback/capture PCM；`speaker-test`、5 秒录音和
回放均通过，用户确认扬声器与麦克风实际声音正常。固件音频为半双工，播录应顺序执行。

来源范围：早期页面引用的 `tests/config/test_atk_rk3506b.py` 已不在当前树中；
本页实机结果来自上方日期及 sources 中保留的硬件验收记录，不把该历史测试路径作为当前验证证据。
