## Why

当前 Cardputer 固件已作为 GUD 显示器与 HID 键盘工作，但尚不能接收 Linux 主机的音频播放流，
无法完成“一根 USB-C 线同时承载显示、键盘和声音”的阶段目标。需要先落地低带宽、标准驱动可识别的
UAC1（USB Audio Class 1，USB 音频类 1）单声道扬声器下行链路。

## What Changes

- 在现有 GUD + HID USB 复合设备中增加 UAC1 AudioControl 与扬声器 AudioStreaming 接口。
- 支持 Linux `snd-usb-audio` 通过 isochronous OUT 端点发送 mono 16 kHz / 16 bit PCM。
- 增加音频接收缓冲与 I2S 扬声器输出模块，驱动 Cardputer 板载 NS4168 功放。
- 处理扬声器数据 GPIO 与 UART0 日志引脚冲突，确保音频启用时不会争用 GPIO43。
- 补充 firmware 构建、枚举、ALSA 播放和故障排查文档。

## Capabilities

### New Capabilities

- `cardputer-usb-uac-speaker`: 定义 Cardputer firmware 的 UAC1 扬声器枚举、音频格式、数据传输和板载播放行为。

### Modified Capabilities

无。

## Impact

- 影响 `components/packages/cardputer-all-in-one/firmware/main/` 下 USB 描述符、启动编排与新增音频模块。
- 调整 `firmware/sdkconfig.defaults` 中 TinyUSB Audio 类配置及固件中文文档。
- USB 产品仍使用 GUD 绑定要求的 `16d0:10a9`，Linux 侧继续使用 mainline `snd-usb-audio`，不引入自定义 host 驱动。
- firmware 仍在宿主机 ESP-IDF 环境构建，不纳入 flange Docker 构建。

## 非目标

- 不在本变更实现 UAC 麦克风上行、立体声或高采样率音频。
- 不修改 Linux 内核驱动、flange 平台构建规则或 GUD/HID 功能行为。
- 不解决全双工音频、自动增益、回声消除或音量持久化。
