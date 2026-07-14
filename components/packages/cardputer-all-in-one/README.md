# cardputer-all-in-one

用一根 USB-C 线，把 **M5Stack Cardputer（ESP32-S3）** 接到 flange 嵌入式 Linux 主机，让它当一个「USB 瘦终端」：USB 显示屏 + USB 麦/扬声器 + USB 键盘，全走 mainline 驱动（host 侧零自定义驱动）。

## 两侧分工

| 侧 | 内容 | 构建 |
|----|------|------|
| **Cardputer 固件** | `firmware/`（ESP-IDF + TinyUSB）—— GUD 显示 / UAC 音频 / HID 键盘 | **容器外** `idf.py`（见 `firmware/README.md`）|
| **Linux 组件** | 内核 config fragment（`CONFIG_DRM_GUD` / `SND_USB_AUDIO` / `USB_HID`）+ udev/文档 | `flange build`（P4 阶段落地）|

Linux 侧零自定义驱动：显示用 **GUD**（Generic USB Display，`drivers/gpu/drm/gud`）、音频用 **UAC + snd-usb-audio**、键盘用 **USB HID**。

## 状态

- ✅ **GUD 显示链路打通** —— Cardputer 枚举为 `16d0:10a9`，host `gud` 出 `/dev/dri/cardN`，未压缩 RGB565 收帧上 ST7789。
- ✅ **HID 键盘** —— 74HC138 矩阵扫描 → HID usage 映射上报，与 GUD 同一复合设备，host 出 `/dev/input/eventN`。
- ✅ **UAC1 扬声器** —— mono 16 kHz / 16 bit USB OUT → I2S NS4168，host 由 `snd-usb-audio` 提供 ALSA playback PCM。
- ⏳ UAC 麦克风（GPIO43 与扬声器 WS 共用，需半双工设计）/ LZ4+脏矩形 / Linux flange 组件 / flash 集成。

详见 `firmware/README.md`。

## 文档

- 设计/可行性：`docs/superpowers/specs/2026-06-14-cardputer-usb-all-in-one-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-14-cardputer-usb-all-in-one-p0-gud-display.md`（GUD 显示）、`docs/superpowers/plans/2026-06-17-cardputer-usb-hid-keyboard.md`（HID 键盘）
- 固件细节与构建/烧录/验证：`firmware/README.md`
