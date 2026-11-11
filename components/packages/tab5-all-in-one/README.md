# Tab5 USB 复合终端

用一根 USB-C 线将 M5Stack Tab5（ESP32-P4）接到 Linux 主机，提供 GUD（通用 USB 显示）、
HID（人机接口）键盘与触摸、UAC1（USB 音频）和 UVC（USB 视频）摄像头。
Linux 使用内核已有的 gud、usbhid/hid-multitouch、snd-usb-audio 和 uvcvideo 驱动。

## 使用入口

1. 按[固件指南](firmware/README.md)准备 ESP-IDF、构建并烧录 Tab5。
2. 在 Linux 目标的 `kernel.config` 中确认 `CONFIG_DRM_GUD`、`CONFIG_USB_HID`、
   `CONFIG_HID_MULTITOUCH`、`CONFIG_SND_USB_AUDIO`、`CONFIG_USB_VIDEO_CLASS` 及其依赖已启用。
   需要调整时通过 `flange build` 构建匹配的内核与 rootfs。
3. 将 Tab5 USB-C 接到 Linux Host 端口，按固件指南检查显示、输入、声卡和视频设备。
   X11 用法见 [GUD 显示](../../../docs/hardware/gud-display.md)。

本目录存放独立 ESP-IDF 固件，**没有 `package.py` 注册清单或自动烧录动作**。
当前 flange Docker 不包含 ESP 工具链，固件通过独立 ESP-IDF 环境构建；
不能把 `flange package build tab5-all-in-one` 当作已集成的入口。

## 能力与验证边界

| 功能 | 当前实现 | 实际验证范围 |
| --- | --- | --- |
| GUD 显示 | 640×360 RGB565，LZ4/脏矩形，PPA 放大旋转到 720×1280 | ILI9881C 面板、Linux console 出图通过；ST7123 仅编译 |
| 键盘 | Tab5 Keyboard，Normal 模式转换 6KRO 报告 | 输入与组合键通过；不支持 BIOS boot keyboard 协议 |
| 触摸 | GT911，声明最多 5 点 | 三指与四角坐标通过；四/五指未实测 |
| 音频 | 16 kHz 单声道 S16_LE，硬件支持全双工 | 播放、录音及硬件音量分别通过；长时同时收发未测 |
| 摄像头 | SC202CS → ISP → PPA → JPEG，MJPEG 640×360 / 10 fps | 旧管线出图与 AE 通过；当前 ISP 对齐实现只完成宿主测试和构建 |

当前 ISP 的 gamma、降噪、锐化、LSC、CCM、硬件 AE/AWB、直方图及环境亮度模型的参数和限制，
统一见[相机参考](firmware/CAMERA.md)。2026-08-21 的记录为 9 组共 3258 个宿主用例及两档 clean build 通过，
不能据此声明当前 ISP 画质已实机验收。

USB-C 是 **12 Mbps 全速口**；摄像头、音频和显示共用带宽。
摄像头启用后 GUD 可用带宽下降约三分之一是预算估算，尚无整机帧率实测。
五项同时运行的长期稳定性、音频时钟漂移、LZ4/脏矩形定量性能均未完成验收。

同类 ESP32-S3 设备见 [Cardputer](../cardputer-all-in-one/README.md)。
