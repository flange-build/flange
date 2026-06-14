# Cardputer USB 一线通（显示 + 音频 + 键盘）可行性与设计

- **日期**：2026-06-14
- **状态**：设计已确认，待实施
- **组件**：`components/packages/cardputer-all-in-one`

## 1. 目标

用一根 USB-C 线，把 **M5Stack Cardputer（ESP32-S3）作为 USB 设备**接到 **flange 嵌入式 Linux 板（USB 主机）**，让 Cardputer 同时充当：

- **USB 显示屏**（标准 DRM 设备 `/dev/dri/cardN`）
- **USB 麦克风** + **USB 扬声器**（标准 ALSA 声卡）
- **USB 键盘**（标准输入设备 `/dev/input/eventN`）

即一根线承载 **电源 + 显示 + 音频双向 + 键盘输入**，构成一个完整的「USB 瘦终端」（thin client）。

### 已确认的范围决策

| 维度 | 决策 |
|------|------|
| 用途 | 完整 USB 瘦终端（显示 + 键盘 HID + 音频双向）|
| 音频规格 | 语音级双向，mono 16 kHz / 16 bit（匹配 Cardputer 小扬声器 + 单声麦）|
| 显示传输 | **方案 A：GUD（Generic USB Display），全 mainline，Linux 侧零自定义驱动** |
| 固件边界 | 源码托管在 `firmware/`，**容器外**用 `idf.py` 构建/刷写；flange 不编译固件 |
| 固件栈 | ESP-IDF + TinyUSB（Arduino 的 TinyUSB 未编译音频类，排除）|

## 2. 核心判断

**可行（绿灯）。** 两个关键认知重塑了方案：

### 2.1 「USB 显示屏」对应 mainline 的 GUD，不是 tinydrm

`tinydrm`/`panel-mipi-dbi-spi` 是给**直连 SoC 的 SPI 屏**用的；USB 显示屏在 mainline 里对应的是 **GUD（Generic USB Display，`drivers/gpu/drm/gud/`）**。GUD 作者正是 tinydrm 与 panel-mipi-dbi 的 Noralf Trønnes —— 可理解为「tinydrm 的 USB 版」。

- **Linux（host）侧零自定义驱动**：仅需 `CONFIG_DRM_GUD=m`，直接出 `/dev/dri/cardN`。
- 专为**微控制器小屏 + 受限带宽**设计：自带 **LZ4 压缩 + 脏矩形（damage）增量刷新**。
- 音频侧同理：**UAC + mainline `snd-usb-audio`**；键盘走 **USB HID + usbhid**，host 侧全部零自定义驱动。

→ **真正的工作量几乎全在 Cardputer 固件侧**，Linux 侧只是内核配置 + 一个 flange 组件。

### 2.2 带宽天花板：ESP32-S3 是 Full Speed（12 Mbit/s）

ESP32-S3 的 USB-OTG 仅 Full Speed。这是整个一线通的带宽上限，显示与音频共享它。240×135 屏极小（满帧约 63 KB），瘦终端 + 语音音频的组合远在天花板之下。

### 2.3 已核实的外部事实

- **GUD 在 FS 微控制器上已被验证**：Stephen Bates 用 RP2040（同为 FS）与 STM32H723 实现过 GUD 设备；RP2040 版 320×240×16bpp 跑到 ~10 fps。我们的屏像素数仅为其 ~42%，且仅语音音频，余量更宽。
- **无现成 ESP32 GUD 设备固件**：现存实现为 Linux gadget（Pi Zero）、RP2040(PIO)、STM32H7 → ESP32-S3 需移植/实现 GUD 设备协议（**主风险**，但有参考实现可对照）。
- **固件必须 ESP-IDF**：arduino-esp32 的 TinyUSB 未编译音频类（`CFG_TUD_AUDIO` 关），只有 ESP-IDF 直连 TinyUSB 才有 UAC；复合设备（vendor+HID+audio）ESP-IDF 支持。

## 3. 架构

```
┌─────────────────────────────┐      一根 USB-C（一线通）       ┌───────────────────────────────┐
│  嵌入式 Linux（USB HOST）    │◄════ 电源+显示+音频+键盘 ════►│  M5Stack Cardputer（USB DEV） │
│  flange 板，如 RK/A733/Q6A   │                               │  ESP32-S3  USB-OTG  FS 12Mb/s │
│                             │   ┌── 一个 USB 复合设备 ──┐     │  ESP-IDF + TinyUSB            │
│  mainline 内核（零自定义驱动）│◄──┤ IF0 Vendor(GUD) bulk OUT│◄──│ GUD 设备协议→ST7789 blit(SPI) │
│   drm/gud  → /dev/dri/cardN │◄─►┤ IF1/2 UAC mono16k 收+发 │◄─►│ PDM 麦 ↔ I2S 扬声(NS4168)     │
│   snd-usb-audio → ALSA card │◄──┤ IF3 HID 键盘 int IN     │◄──│ 矩阵键盘扫描                  │
│   usbhid  → /dev/input/event│   └─────────────────────────┘   │ 240×135 ST7789 TFT           │
└─────────────────────────────┘                                 └───────────────────────────────┘
```

- **Host 侧**：flange 板当 USB 主机，加载三个 mainline 驱动（`drm/gud`、`snd-usb-audio`、`usbhid`）、零自定义代码。对 Linux 应用而言，Cardputer 就是「一块小显示器 + USB 耳麦 + USB 键盘」。
- **Device 侧**：ESP32-S3 跑**一个** TinyUSB 复合设备、4 个功能。
- **电源**：USB-C 从 host 取 5V 给 Cardputer 供电。前提是 host 板有真正的 USB 主机口且供电足够（flange 板基本都有）。

### 3.1 USB 复合描述符布局

| 功能 | 类 | 接口数 | 端点 | 用途 | 方向（相对 host）|
|------|----|------|------|------|------|
| GUD | Vendor | 1 | bulk OUT + EP0 ctrl | 帧缓冲 + GUD 命令 | OUT |
| 音频 | Audio (UAC1) | 3（1 AC + 2 AS）| iso OUT / iso IN | 扬声器(下行) / 麦(上行) | OUT + IN |
| 键盘 | HID | 1 | int IN | 键盘 | IN |

> 表中是**逻辑功能**，非最终 `bInterfaceNumber`。UAC1 需 1 个 AudioControl + 2 个 AudioStreaming 接口，故实际接口数为 1(GUD) + 3(UAC) + 1(HID) = 5，编号在手写描述符时统一排定（IAD 把 UAC 的 3 个接口分组）。

- 端点合计 1 bulk OUT + 1 iso OUT + 1 iso IN + 1 int IN，在 ESP32-S3 OTG 的 6 IN/6 OUT 之内；EP0 共用控制（GUD 大量走控制传输）。
- **手写复合描述符**（不用 Espressif 高层 UAC 组件），让四个功能共享同一 config；UAC 用 IAD 分组。
- 选 **UAC1**：FS 下最简、mono 16k 绰绰有余，UAC2 在此无收益。
- **GUD 绑定**：drm/gud 绑定到 vendor-specific 接口，再用 GUD 描述符控制请求确认能力；IF0 暴露为 vendor 类并应答 GUD 的 descriptor/connector/format 请求（精确 subclass/请求码实现期照 `notro/gud` 协议钉死）。

### 3.2 带宽预算（可行性核心）

FS 理论 12 Mbit/s = 1.5 MB/s；扣协议开销后实际可用 ~1.0–1.1 MB/s。

| 负载 | 占用 | 占比 |
|------|------|------|
| 音频 mono16k 双向 | 64 KB/s | ~6% |
| HID 键盘 | 几字节/按键 | <1% |
| **显示（剩余）** | **~0.95 MB/s** | **~94%** |

- 满帧 240×135×16bpp = **63.3 KB**，即便不压缩也 ~15 fps；LZ4 对文本/UI（3–8×）后余量很大。
- 真实负载只改小块（光标、一行文字、一个控件），GUD 脏矩形只发改动区 → 一次终端刷新几 KB → 亚帧延迟，手感跟手。
- RP2040 先例折算到我们尺寸 ≈ 24 fps 满帧（还没算 LZ4/脏矩形）。
- **唯一会让 FS 变痛的是全屏视频/动画**，而瘦终端 + 语音音频的选择正好避开。

## 4. Cardputer 固件设计（ESP-IDF + TinyUSB，FreeRTOS 多任务）

| 模块 | 职责 |
|------|------|
| `usb_descriptors.c` | 手写复合 config：IAD 分组 UAC(IF1+2)、Vendor/GUD(IF0)、HID(IF3)；device 描述符走 misc/IAD 类 |
| `gud_device.{c,h}` | GUD 设备协议状态机：响应控制请求（descriptor/connector/format/properties/SET_STATE…）、bulk OUT 收帧、LZ4 解压、维护帧缓冲、推脏矩形给显示任务。单 connector / 单 240×135 / RGB565 |
| `display_st7789.c` | 用 ESP-IDF 内置 `esp_lcd` ST7789 驱动 + DMA；按脏矩形设 CASET/RASET 窗口推像素（含 Cardputer 面板列/行偏移）|
| `uac_audio.c` | UAC1 回调：iso OUT(扬声)→环形缓冲→I2S TX 给 NS4168；I2S PDM RX 读 SPM1423 麦→环形缓冲→iso IN(麦)。16k/mono/16bit |
| `hid_keyboard.c` | 扫描矩阵键盘（74HC138 列选 + GPIO 行）+ Fn 层 → HID usage code，变化即 report |
| `app_main.c` | 初始化帧缓冲、起 TinyUSB；建 usb / display / audio / keyboard 任务 |

**内存**：M5StampS3(ESP32-S3FN8) 大概率无 PSRAM；63 KB 帧缓冲 + LZ4 scratch + DMA 缓冲放内部 512 KB SRAM 够用，双缓冲(~126 KB)要算预算。**实测确认模组是否带 PSRAM**。

## 5. Linux 侧 flange 组件（最轻的一侧）

仿 `components/packages/meizu-e3-panel` 的 `package.py` 模式，本组件贡献：

- **内核 config fragment**（`kernel/cardputer-usb.config`）：`CONFIG_DRM_GUD=m`（连带 Kconfig select 的 KMS helper / GEM shmem / LZ4 压缩）、`CONFIG_SND_USB_AUDIO=m`、`CONFIG_USB_HID` / `CONFIG_HID_GENERIC`；USB 主机控制器各平台一般已开。
- **（可选）overlay**：udev 规则给 card/声卡命名、示例 weston/getty 单元。
- **文档**：接线、配对、带宽。

平台无关——任何带 USB 主机口的 flange 板在 lunch 配置里启用即可。瘦终端的「消费侧」（在 `/dev/dri/cardN` 上跑 getty/weston + 默认 ALSA 走 USB 声卡 + 键盘 input）作为后续 app。

## 6. 仓库布局 + 构建/刷写

```
components/packages/cardputer-all-in-one/
├── package.py                  # flange Linux 组件
├── kernel/cardputer-usb.config # DRM_GUD / SND_USB_AUDIO / USB_HID …
├── overlay/                    # （可选）udev、示例 weston/getty 单元
├── firmware/                   # ESP-IDF 项目（容器外构建，flange 仅托管）
│   ├── CMakeLists.txt
│   ├── sdkconfig.defaults      # TinyUSB / CFG_TUD_AUDIO+VENDOR+HID / native USB
│   ├── partitions.csv
│   └── main/{app_main,usb_descriptors,gud_device,display_st7789,uac_audio,hid_keyboard}.c
├── docs/                       # 接线/带宽/USB 描述符/配对
└── README.md
```

**固件（容器外）**：
```
cd components/packages/cardputer-all-in-one/firmware
get_idf_551 && idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

**Linux 侧**：`flange build` 把 config fragment 合进内核、组件文件落 rootfs；目标板插上 Cardputer 即枚举出 card / 声卡 / 键盘。

## 7. 风险

1. **GUD 设备协议移植（主风险）**：无 ESP32 现成实现，照 `notro/gud` 协议 + RP2040/STM32 参考写。先做最小子集（单 connector / 单模式 / 可先不上 LZ4）让 host 绑定出图，再加 LZ4 + 脏矩形。
2. **四合一复合描述符**：Espressif 高层 UAC 组件独占配置 → 手写描述符走底层 tinyusb；IAD 分组、端点编号、bInterfaceNumber 要排对。
3. **USB-Serial-JTAG 冲突**：TinyUSB 接管 native USB(GPIO19/20) 后，原 USB-C 上的串口控制台/自动下载可能不可用 → BOOT 键进下载模式刷写，**log 走 UART0**。
4. **无 PSRAM**：见 §4 内存预算；需实测确认。
5. **UAC iso + GUD bulk FS 下共存**：iso 预留后 bulk 拿剩余，TinyUSB FIFO/端点分配要调；语音级占用低，风险小。
6. **键盘 Fn 层映射**：Cardputer 矩阵键盘 + Fn 组合到 HID usage 的映射需逐键核对。

## 8. 分期（每个任务 ≤ ~2h，符合项目约定）

- **P0 PoC**：固件只做 GUD（无压缩/单模式）出图 + host `modetest`/`kmscube` 验证一线出画面 → 证明链路。
- **P1**：UAC 扬声器(下行)→`aplay`；再加麦(上行)→`arecord`。
- **P2**：HID 键盘 →`evtest`。
- **P3**：LZ4 + 脏矩形，实测帧率/延迟；四合一稳定性。
- **P4**：Linux 侧 flange 组件（config + udev + 示例单元），`flange build` 一键出镜像。
- **P5（可选）**：`flange flash` 封装 esptool 刷 Cardputer；瘦终端体验整合（getty/weston on card + 默认 ALSA + 键盘）。

## 9. 非目标

- 不追视频/动画级帧率（FS 物理限制；要的话 ESP32-P4 HS 另案）。
- 不做立体声/hi-fi 音频（硬件 + 带宽，本案语音级）。
- 不在 flange Docker 里编固件（无工具链，容器外 idf.py）。
- 不改 GUD/UAC/HID mainline 驱动（全用上游，零自定义内核驱动）。
- 不做 Cardputer 电池独立运行（一线通取 host 5V）。

## 10. 参考

- GUD 驱动与设备实现：<https://github.com/notro/gud>（协议、Pi Zero gadget、buildroot 板级）
- GUD 合入 Linux 5.13：<https://www.phoronix.com/news/Generic-USB-Display-GUD-5.13>
- ESP-IDF USB Device（TinyUSB 复合设备）：<https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/usb_device.html>
- ESP-IoT-Solution TinyUSB 指南（UAC / 复合设备）：<https://docs.espressif.com/projects/esp-iot-solution/en/latest/usb/usb_overview/tinyusb_guide.html>
