# cardputer-all-in-one

用一根 USB-C 线，把 **M5Stack Cardputer（ESP32-S3）** 接到 flange 嵌入式 Linux 主机，让它当一个「USB 瘦终端」：USB 显示屏 + USB 麦/扬声器 + USB 键盘，全走 mainline 驱动（host 侧零自定义驱动）。

## 两侧分工

| 侧 | 内容 | 构建 |
|----|------|------|
| **Cardputer 固件** | `firmware/`（ESP-IDF + TinyUSB）—— GUD 显示 / UAC 音频 / HID 键盘 | **容器外** `idf.py`（见 `firmware/README.md`）|
| **Linux 组件** | 目标内核需启用 `CONFIG_DRM_GUD` / `CONFIG_SND_USB_AUDIO` / `CONFIG_USB_HID` | `flange build` |

Linux 侧零自定义驱动：显示用 **GUD**（Generic USB Display，`drivers/gpu/drm/gud`）、音频用 **UAC + snd-usb-audio**、键盘用 **USB HID**。

## 状态

- ✅ **GUD 显示链路打通** —— Cardputer 枚举为 `16d0:10a9`，host `gud` 出 `/dev/dri/cardN`，RGB565/LZ4 与脏矩形收帧上 ST7789。
- ✅ **HID 键盘** —— 74HC138 矩阵扫描 → HID usage 映射上报，与 GUD 同一复合设备，host 出 `/dev/input/eventN`。
- ✅ **UAC1 扬声器** —— mono 16 kHz / 16 bit USB OUT → I2S NS4168，host 由 `snd-usb-audio` 提供 ALSA playback PCM。
- ✅ **UAC1 麦克风** —— PDM SPM1423 → mono 16 kHz / 16 bit USB IN，和扬声器按最后启动优先半双工切换。
- ✅ **ATK-RK3506B host 支持** —— 启用 GUD、`usbhid`、`snd-usb-audio`，rootfs 提供 `evtest` 和 `alsa-utils`。
其他 Linux 板卡需单独核对内核与外设；本目录没有 `package.py` 清单，固件未集成 flange 自动烧录。

完整构建、接线和接口说明见[固件指南](firmware/README.md)。

## 文档

- [固件指南](firmware/README.md)
- [GUD 显示用法](../../../docs/hardware/gud-display.md)
