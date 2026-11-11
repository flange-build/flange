# 显示与外设专题

先按板卡确认接口、电源、管脚和产品配置，再选择对应说明。

| 场景 | 使用文档 |
| --- | --- |
| 构建期或 U-Boot 运行期叠加设备树 | [设备树覆盖](device-tree-overlays.md) |
| 内核外置 Wi-Fi、触摸和背光驱动 | [外置模块](kernel-modules.md) |
| 魅族 E3 MIPI-DSI 屏 | [E3 功能包](meizu-e3-panel.md) |
| A7A sec_ts 触摸重启/失联 | [供电欠压结论](a7a-touch-power.md) |
| Cubie A7Z ST7789V2 SPI 屏 | [Cubie A7Z](../boards/radxa-cubie-a7z.md) |
| ROCK 5C Lite ST7789VM LCD HAT | [ROCK 5C Lite](../boards/radxa-rock5c-lite.md) |
| Orange Pi 5 Plus DSI/GT911/HDMI RX | [Orange Pi 5 Plus](../boards/orangepi-5-plus.md) |
| USB GUD 屏接入 X11 | [GUD 显示](gud-display.md) |
| Cardputer 显示、键盘和半双工音频 | [Cardputer 固件](../../components/packages/cardputer-all-in-one/README.md) |
| Tab5 显示、键盘、触摸、音频和摄像头 | [Tab5 固件](../../components/packages/tab5-all-in-one/README.md) |
| GNOME/Weston 与 GPU | [桌面](desktop.md)、[A733 图形边界](a733-graphics.md) |
| NPU 推理 | [RKNN](rknn.md) |
| 蓝牙音箱与采集 | [蓝牙音频](bluetooth-audio.md) |

SPI panel-mipi-dbi 的初始化文本由构建器转换为固件；文件名来自设备 compatible，
不能只更改文件名而不改设备树。reset 极性、面板偏移、MADCTL 和像素格式按具体屏幕确认。
旧的 fbtft 与用户态 spidev 显示实验已由上述 DRM 方案替代。

PicoCalc 迁移评估未形成仓库内的固件实现，不在当前支持范围。
