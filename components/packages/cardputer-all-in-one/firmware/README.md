# Cardputer AIO 固件（ESP32-S3）

M5Stack Cardputer 作为 **USB 设备**，让嵌入式 Linux 主机把它当成一块标准 DRM 显示器
（mainline `gud` 驱动，`/dev/dri/cardN`）+ UAC1（USB Audio Class 1，USB 音频类 1）扬声器
（mainline `snd-usb-audio`）+ USB 键盘（mainline `usbhid`，`/dev/input/eventN`），同处一个 USB 复合设备。

> ESP-IDF 项目，**容器外**构建（flange 的 Docker 无 ESP 工具链）。

## 能力

- USB 复合设备，**VID/PID = `16d0:10a9`**（mainline `gud` 绑定的固定 ID）。
  - **IF0 Vendor(GUD) 显示**：GUD 设备协议最小子集，单 connector / 单模式 **240×135** / **RGB565**（未压缩）；收 host 帧（SET_BUFFER + bulk OUT）→ blit 到板载 ST7789。
  - **IF1 AudioControl + IF2 AudioStreaming**：UAC1 mono 16 kHz / 16 bit / `S16_LE`，host 的
    isochronous OUT 音频经 I2S（BCLK=GPIO41、DOUT=GPIO42、WS=GPIO43）送到板载 NS4168。
  - **IF3 HID 键盘**：扫描 74HC138 矩阵键盘（列选 GPIO{8,9,11}/行 GPIO{13,15,3,4,5,6,7}）→ 映射为 HID usage（含 Shift/Ctrl/Alt/Opt 修饰 + Fn 层 F1-12/方向/Esc/Del）→ 中断 IN 上报。
- 协议头 `main/gud_protocol.h` 从内核 6.8 `include/drm/gud.h` vendor（Dual MIT/GPL）；键盘引脚/键值表照搬 M5Cardputer 库。

尚未实现（后续阶段）：UAC 麦克风上行、LZ4/脏矩形。麦克风 PDM clock 与扬声器 WS 共用 GPIO43，
双向音频需要另行设计半双工切换。

## 构建 / 烧录

```bash
get_idf_551                       # 激活宿主机 ESP-IDF 5.5.1
idf.py set-target esp32s3         # 首次
idf.py build
```

**烧录要点：固件用 TinyUSB 接管了 native USB(GPIO19/20)，普通自动复位下载不可用**，需手动进 ROM 下载模式：

1. **按住 G0(BOOT)** 同时插 USB-C / 复位，松开 → 下载模式（host `lsusb` 见 `303a:1001`）。
2. `idf.py -p /dev/ttyACM0 flash`（端口以实际为准）。
3. 拔插一次 USB-C 正常上电启动 → 枚举为 `16d0:10a9`。

## 日志与 GPIO43

native USB 归 TinyUSB 后，USB-C 上的串口控制台失效；板载扬声器又将 GPIO43 用作 I2S WS，
因此 firmware 默认设置 `CONFIG_ESP_CONSOLE_NONE=y`，不再启用 UART0 控制台。需要调试时使用 JTAG
debugger，或在本地 sdkconfig 中把 UART TX 临时改到未占用 GPIO；不得恢复 GPIO43 上的 UART0 TX。

## Host 侧验证（主机需 mainline `gud`，内核 ≥5.13，发行版一般自带 `CONFIG_DRM_GUD=m`）

```bash
lsusb | grep 16d0                      # 16d0:10a9
sudo dmesg | grep -iE "gud|drm"        # [drm] Initialized gud ... + /dev/dri/cardN
ls /dev/dri/
sudo apt-get install -y libdrm-tests   # 若无 modetest
modetest -M gud                        # 列出 connector + 240x135 模式
modetest -M gud -s <connector_id>:240x135   # 送测试图上屏
```

实时内容（GStreamer，kmssink 直驱 GUD 卡）：

```bash
# 注意：modetest -s 与 kmssink 都需 DRM master，二选一（先停掉另一个）
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=240,height=135 ! \
  kmssink driver-name=gud connector-id=<id> force-modesetting=true
```

键盘（HID）：
```bash
cat /proc/bus/input/devices | grep -B1 -A5 -i "16d0\|Cardputer"   # 找 eventN
sudo evtest /dev/input/eventN     # 在 Cardputer 上打字，看 KEY_* 事件
```

扬声器（UAC1）：

```bash
cat /proc/asound/cards             # 找 Cardputer 对应 card 编号
aplay -l                           # 应出现一个 USB Audio playback device
aplay -D hw:<card>,0 --dump-hw-params -f S16_LE -c 1 -r 16000 /dev/zero
speaker-test -D hw:<card>,0 -F S16_LE -c 1 -r 16000 -t sine -f 1000
```

`--dump-hw-params` 应报告 `FORMAT: S16_LE`、`CHANNELS: 1`、`RATE: 16000`。连续运行最后一条命令
10 分钟，确认无周期性爆音、停声或 USB 重新枚举；同时重复 `modetest -M gud` 和 `evtest` 做复合回归。

## 板级显示参数（`main/display_st7789.c`，按真机实测确定）

| 项 | 值 | 说明 |
|----|----|------|
| `rgb_ele_order` | `BGR` | Cardputer 面板红蓝顺序 |
| `invert_color` | `true` | ST7789 需反色 |
| `swap_xy` / `mirror` | `true` / `(true,false)` | 旋转 180° |
| `set_gap` | `(40, 52)` | 240×135 GRAM 偏移 |
| 软件 G/B 对调 | 收帧后 blit 前 | 实测净管道为 G/B 通道互换，软件再换一次抵消 |

> 上述是 Cardputer 这块屏 + 当前 GUD 字节路径联合实测的结果；换屏/换路径需重新校。

## 文件

| 文件 | 职责 |
|------|------|
| `main/app_main.c` | 初始化 + TinyUSB 安装 + 编排 |
| `main/usb_descriptors.{c,h}` | USB 复合描述符数据（GUD + UAC1 speaker + HID）+ HID 回调 |
| `main/tinyusb_config/tusb_config.h` | 在 esp_tinyusb 默认配置上开启并定参 TinyUSB Audio class |
| `main/gud_protocol.h` | GUD 协议定义（vendor 自内核 6.8）|
| `main/gud_device.{c,h}` | GUD 控制协议状态机 + 收帧上屏 |
| `main/display_st7789.{c,h}` | ST7789 显示 HAL（esp_lcd）|
| `main/uac_audio.{c,h}` | UAC1 控制回调 + USB FIFO → I2S/NS4168 扬声器链路 |
| `main/hid_keyboard.{c,h}` | 74HC138 矩阵扫描 + 键值→HID usage 映射上报 |
| `main/cardputer_kbd_map.h` | 键盘引脚/坐标/X_map（源自 M5Cardputer 库）|
| `main/cardputer_pins.h` | 显示等板级 GPIO / 尺寸常量 |

设计与路线：见仓库 `docs/superpowers/specs/2026-06-14-cardputer-usb-all-in-one-design.md` 与 `docs/superpowers/plans/`。
