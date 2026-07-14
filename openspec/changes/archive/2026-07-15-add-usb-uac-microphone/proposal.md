## Why

当前 Cardputer firmware 仅向 Linux host 暴露 UAC1 扬声器，板载 SPM1423 数字麦克风无法作为标准
ALSA capture PCM 使用。补齐 UAC1 麦克风后，Cardputer 才能作为无需自定义音频驱动的双向 USB 音频终端。

## What Changes

- 在现有 UAC1 Audio Function 中增加 mono 16 kHz / 16 bit isochronous IN 录音流。
- 使用 ESP32-S3 I2S PDM RX 从 GPIO46 采集 SPM1423 数据，并通过 TinyUSB Audio IN FIFO 上传。
- 对共享 GPIO43 的麦克风 PDM CLK 与扬声器 I2S WS 实施半双工仲裁，保证任一时刻只有一个方向驱动该引脚。
- 保持现有 GUD、UAC1 扬声器和 HID 功能及其 endpoint 不变。
- 更新中文文档，增加 Linux ALSA 枚举、录音和半双工限制说明。

## Capabilities

### New Capabilities

- `cardputer-usb-uac-microphone`: 定义 Cardputer UAC1 麦克风枚举、PDM 采集、USB Audio IN 传输及与扬声器的半双工仲裁行为。

### Modified Capabilities

无。

## Impact

- 影响 `components/packages/cardputer-all-in-one/firmware/main/` 下的 USB 描述符、TinyUSB 配置、音频模块和引脚定义。
- 不新增外部依赖，继续使用已锁定的 esp_tinyusb、TinyUSB 和 ESP-IDF I2S driver。
- Linux host 继续使用 mainline `snd-usb-audio`，新增 ALSA capture PCM。
- GPIO43 仍不可用于 UART0 console，并新增播放与录音不能同时进行的运行时约束。

## 非目标

- 不支持 full-duplex（全双工）播放与录音。
- 不增加采样率切换、立体声、硬件增益、静音或回声消除。
- 不实现应用层语音识别、录音文件保存或网络音频传输。
- 不在本变更中归档尚待实机验证的 UAC1 扬声器变更。
