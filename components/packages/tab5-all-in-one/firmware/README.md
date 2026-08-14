# Tab5 AIO 固件（ESP32-P4）

M5Stack Tab5 作为 **USB 设备**，让嵌入式 Linux 主机把它当成一块标准 DRM 显示器
（mainline `gud` 驱动，`/dev/dri/cardN`）。host 送来的 **640×360 RGB565** 帧经 ESP32-P4 的
PPA（Pixel Processing Accelerator，像素处理加速器）**2× 放大 + 90° 旋转**，铺满板载的
720×1280 MIPI-DSI 面板。同一个复合设备上还带 **HID 键盘**（Tab5 Keyboard）与
**HID 多点触摸**（GT911，与键盘共用同一个 HID 接口、靠 Report ID 区分）与
**UAC1 全双工音频**（ES8388 出喇叭 / ES7210 双麦录音，16 kHz 单声道，
带**播放音量/静音的硬件控制**，✅ **播放与录音均已实机验证**，见下文）；
后续阶段追加 UVC 摄像头。

> ESP-IDF 项目，**容器外**构建（flange 的 Docker 无 ESP 工具链）。

## 能力

- USB 复合设备，**VID/PID = `16d0:10a9`**（mainline `gud` 绑定的固定 modalias，**不可更改**）。
  - **IF0 Vendor(GUD) 显示**：GUD 设备协议最小子集，单 connector / 单模式 **640×360** /
    **RGB565**，支持 LZ4 压缩与 dirty rectangle（脏矩形）；收 host 帧（SET_BUFFER + bulk OUT）
    →（可选 LZ4 解压）→ PPA 缩放旋转 → DPI 帧缓冲 → 面板。
  - **IF1 HID 键盘 + 多点触摸**：一个接口、一条中断 IN 端点，靠 Report ID 区分 ——
    **RID 1 = 键盘**（Tab5 Keyboard 经独立 I2C 总线读行列事件，自建 6KRO 状态机上报）、
    **RID 2 = digitizer**（GT911 电容触摸，最多 5 点绝对坐标）。
    详见下文「HID 键盘」与「HID 多点触摸」。
  - **IF2/IF3/IF4 UAC1 音频**（无条件编译，默认构建就带）：
    一个 AudioControl + 两个 AudioStreaming（播放 OUT / 录音 IN），
    由 IAD 成组，host 侧走 mainline `snd-usb-audio`，零自定义驱动。
    **16 kHz / 单声道 / S16_LE，两个方向同参数**（全双工的 I2S TX/RX 共用 BCLK 与 WS）。
    播放经 ES8388 出板载喇叭，录音取 ES7210 的两只麦混成单声道。
    播放链上带一个 **Feature Unit（Mute + Volume）**，主机的音量键与 `alsamixer`
    直接调 **ES8388 的硬件音量**（不是主机软件音量）。详见下文「UAC1 全双工音频」。
  - 设备描述符为 Misc/IAD 复合设备，为后续 UVC 预留。
- 协议头 `main/gud_protocol.h` 从内核 6.8 `include/drm/gud.h` vendor（Dual MIT/GPL）；
  面板 init 序列与 DSI/DPI 参数复刻自 esp-bsp `bsp/m5stack_tab5`（Apache-2.0）；
  待机画面用的点阵字体 `main/font8x16.h` vendor 自 [Spleen](https://github.com/fcambus/spleen)
  8×16（BSD-2-Clause，见下文「待机画面」）。

## 硬件与工具链

| 项 | 值 |
|----|----|
| 主控 | **ESP32-P4 rev v1.0**（实测 esptool 报 `revision v1.0`） |
| PSRAM | 32 MB HEX(16 线) @ 200 MHz（实测启动日志 `Found 32MB PSRAM device`） |
| Flash | 16 MB，`partitions.csv` 的 factory 分区 4 MB |
| 工具链 | **ESP-IDF v6.0.2**（宿主机 `~/esp/esp-idf`） |

```bash
. $HOME/esp/esp-idf/export.sh     # .zshrc 里的等价别名是 get_idf
```

### ⚠️ P4 芯片版本是互斥的，不能运行时兼容

`sdkconfig.defaults` 显式写了：

```
CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y
CONFIG_ESP32P4_REV_MIN_100=y
```

IDF v6.0 默认最低支持 **v3.1**，不改这两项会在烧录时直接被拒绝：
`requires chip revision in range [v3.1 - v3.99]`。

IDF Kconfig 原文：rev < 3.0 与 >= 3.0「硬件差异巨大、互不兼容」（*mutually exclusive*）。
即本固件编译为支持 v0.x/v1.x 后就**跑不了 v3.x 的 P4**，这与双面板批次不同 —— **无法运行时兼容**。
若日后遇到换成 v3.x 芯片的 Tab5 批次，只能另出一份固件
（改 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=n` + `CONFIG_ESP32P4_REV_MIN_301`）。

## 构建 / 烧录

```bash
. $HOME/esp/esp-idf/export.sh
idf.py set-target esp32p4         # 首次
idf.py build
```

**开箱即用**：`sdkconfig.defaults` 已经把所有必需项写全（芯片版本、控制台、PSRAM、
分区表、TinyUSB 类计数、codec 裁剪），`rm -f sdkconfig && idf.py build` 直接产出
**GUD + HID + UAC1 音频**的可用固件，不需要任何旁路 conf 文件。
唯一的可选项是排障用的 `CONFIG_AIO_DEBUG_CDC`（默认关，见「日志」一节）。

> ⚠️ 改过 `main/Kconfig.projbuild` 之后**必须连 build 目录一起删**
> （`idf.py fullclean` 或 `rm -rf build sdkconfig`），否则 `sdkconfig.h` 不重新生成，
> 新配置项在 C 里报 `undeclared`。同理 `SDKCONFIG_DEFAULTS` 会留在 CMake 缓存里，
> 换过一次就得显式再传一次。

**烧录要点：TinyUSB 接管全速 PHY 后 USB-Serial/JTAG 失效，自动复位下载不可用**，
需手动进 ROM 下载模式：

1. **按住 BOOT(G35)** 同时插 USB-C / 复位，松开 → ROM 下载模式；
2. `idf.py -p <口> flash`（端口以实际为准）；
3. 拔插一次 USB-C 正常上电启动 → 枚举为 `16d0:10a9`。

## 日志

**UART0 = TX G37 / RX G38**（引到 M5-Bus），115200 8N1。

与 Cardputer 不同，Tab5 的 UART0 不与显示/音频争引脚，因此 `CONFIG_ESP_CONSOLE_UART_DEFAULT=y`，
**保留了完整的串口控制台**。USB-C 上的串口失效后，这里是唯一的现场证据来源，调试时先接它。

### 可选：USB CDC 调试串口（默认关闭）

**默认状态下这块板现场没有任何可用串口。** UART0 只在 M5-Bus 排针上（要外接 USB-TTL），
而 USB-C 上的 USB-Serial/JTAG 被有意关掉了 —— TinyUSB 必须独占那条 FSLS PHY（见上一节）。
两者都不满足时，所有 `ESP_LOG*` 在现场等于不存在。

开关是 **menuconfig → Tab5 All-in-One → `CONFIG_AIO_DEBUG_CDC`**（默认 n）：

```bash
idf.py menuconfig      # 打开 CONFIG_AIO_DEBUG_CDC
idf.py build flash monitor
```

打开后复合设备上会多出一个 CDC ACM 接口，`ESP_LOG*` / `stdout` 改从 USB-C 出来，
`idf.py monitor` 直接可看，**不用接 USB-TTL**。它自己会 `select` 出
`CONFIG_TINYUSB_CDC_ENABLED`，不需要也**不应该**手动去开那一项。

代码侧一律走 `#if CONFIG_AIO_DEBUG_CDC` / `#if CONFIG_TINYUSB_CDC_ENABLED` 条件编译
（`usb_descriptors.{c,h}` 的接口/端点/描述符，`app_main.c` 的 `tinyusb_cdcacm_init()` +
`tinyusb_console_init()` + 主循环里每 10 秒复读一次的 `codec_audio_report()`）。
`_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN)` 在两档下都成立：
**默认档（GUD + HID + 音频）241 字节 / 5 接口，调试档 300 字节 / 7 接口**。

也可以直接在 `sdkconfig.defaults` 末尾把 `#CONFIG_AIO_DEBUG_CDC=y` 那一行的注释取消，
再 `rm -f sdkconfig && idf.py build`（`sdkconfig.defaults` 只在生成 `sdkconfig` 时读一次）。

#### ⚠️ 代价：让出 GUD 的 IN 端点 + 借走 UVC 预留的 `0x84`

| 用途 | 正常档 | 调试档 |
|---|---|---|
| vendor(GUD) | OUT `0x01` / IN `0x81` | OUT `0x01`（**没有 IN**） |
| HID（键盘 + 触摸） | IN `0x82` | IN `0x82` |
| UAC 录音 | IN `0x83` | IN `0x83` |
| UVC 预留 | IN `0x84` | —（借给 CDC 通知） |
| CDC 通知 / 数据 | — | IN `0x84` / OUT `0x03` + IN `0x81` |

**去掉 vendor 的 IN 端点为什么安全**：mainline `drivers/gpu/drm/gud/gud_drv.c` 的
`gud_probe()` 只调一次 `usb_find_bulk_out_endpoint()`，全驱动没有
`usb_find_bulk_in_endpoint` / `usb_rcvbulkpipe` —— GUD 协议是「EP0 控制请求 +
bulk OUT 送像素」的单向结构；本固件 `gud_device.c` 也只有 rx 侧，从不调
`tud_vendor_write()`。TinyUSB 的 `vendord_open()` 按描述符里实际出现的端点逐条 open
（`vendor_device.c:296-332`），只有 OUT 时就只开 `rx_stream`。
`0x81` 一直是 `TUD_VENDOR_DESCRIPTOR` 顺带声明的、**从未通过流量**的端点。

FIFO 不是瓶颈：256 words 依次扣 EP0 16 + HID 16 + 音频 IN 9 + CDC 通知 16 +
CDC 数据 IN 16 = 73，余 183 ≫ RX FIFO 所需的 62 words；IN 端点连 EP0 共 5 条，
恰好等于 `ep_in_count`，`dcd_dwc2.c` 的 `TU_ASSERT(allocated_epin_count < ep_in_count)`
每一步都成立。（此处曾按「vendor/CDC 数据各 32」记，那是假设 bulk IN 开了双缓冲；
实测 `_tud_cfg.bm_double_buffered` 保持默认 0，`tud_configure()` 从未被调用，故各 16。）

> ⚠️ **直接开 `CONFIG_TINYUSB_CDC_ENABLED` 仍然是编译期错误。**
> esp_tinyusb 默认给 CDC 的端点就是 `0x83`/`0x84`，与 UAC 录音、UVC 预留直接撞号，
> 而且不让出 vendor 的 IN 就会超编 —— `dcd_dwc2` 超编时**一个字都不打**，
> 症状是某个接口静默不工作。`usb_descriptors.h` 的 `#error` 会把你导向
> `CONFIG_AIO_DEBUG_CDC`，那一档已经把端点号重排好了。

**这是排障设施，不是产品特性。** 定位完就关掉 —— 它占着留给 UVC 的 `0x84`。

#### ⚠️ 开机早期的日志会丢

`tinyusb_console_init()` 之后 `stdout` 写进 CDC 的 TX 环形缓冲，这些字节要等 host 侧真的打开
`ttyACM*` 并开始读才会流出去。从上电到你敲下 `idf.py monitor` 之间的日志，超出缓冲的部分被覆盖丢弃。
**看不到最前面几行是正常现象，不是 bug。** 要抓上电阶段（`board_power` / `display_init` 那一段）
仍然只能接 UART0。

## ⚠️ 必须显式选全速端口

Tab5 的 USB-C 接在 P4 的 **USB1P1 全速 PHY（GPIO24/25，12 Mbps）** 上；
480 Mbps 的高速 PHY（`USB2_OTG_D±`）接的是 **USB-A 母座**。

而 `esp_tinyusb` 2.2.1 在 ESP32-P4 上把 `TINYUSB_DEFAULT_CONFIG()` 展开成 **HIGH_SPEED**。
用默认值会去驱动错的那条 PHY —— **USB-C 永远枚举不出来，且没有任何报错**。
所以 `app_main.c` 里写的是：

```c
tinyusb_config_t tusb_cfg = TINYUSB_CONFIG_FULL_SPEED(NULL, NULL);
```

### ⚠️ 还要关掉次级控制台，否则 USB-C 上出来的是 CDC ACM

**选对端口只是第一步。** P4 只有一条 FS/LS PHY（`SOC_USB_FSLS_PHY_NUM = 1`），
**USB-Serial/JTAG 与 OTG1.1 共用它**。谁先占住谁赢。

IDF 的 `ESP_CONSOLE_SECONDARY` **默认就是 `USB_SERIAL_JTAG`**，它会 select 出
`ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED` → `USJ_ENABLE_USB_SERIAL_JTAG`，
于是 USJ 外设开机即启用并占住 PHY，TinyUSB 再怎么 `usb_new_phy()` 也抢不过来。

**只设 `CONFIG_ESP_CONSOLE_UART_DEFAULT=y` 是不够的** —— 那只管主控制台，
次级是另一个独立选项。所以 `sdkconfig.defaults` 里必须还有：

```
CONFIG_ESP_CONSOLE_SECONDARY_NONE=y
CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=n
```

**症状**：host 侧 `dmesg` 只见

```
cdc_acm 1-1.1:1.0: ttyACM0: USB ACM device
```

`lsusb` 里根本没有 `16d0:10a9`，屏幕待机画面正常、UART 日志也正常打出
`TinyUSB Driver installed on port 0` —— 固件一切「看起来正常」，只是 PHY 不归它。

> 这两项只影响**应用**阶段。bootloader 阶段 USJ 仍然启用，按住 BOOT 进下载模式照常能烧录
> （IDF Kconfig 原文即如此说明）。

### 端点预算（后续阶段会用满）

P4 全速控制器（tinyusb `dwc2_esp32.h`）：`ep_count = 7`、`ep_in_count = 5`（含 EP0）、
FIFO 256 words（1 KB），即**最多 4 条可用 IN 端点**。

当前已用 **3 条 IN 端点**：vendor(`0x81`) + HID(`0x82`) + UAC 录音(`0x83`)，**余 1 条**。
`0x84` 是留给 UVC 视频流的最后一条，**不得占用** —— 这也是音频坚决不用显式反馈端点的原因
（见下文「UAC1 全双工音频」）。

正因为一开始就知道会用满，**触摸与键盘才合并在同一个 HID 接口**上、用 Report ID 区分
（RID 1 键盘 / RID 2 digitizer），触摸没有新增任何端点（见下文「HID 多点触摸」）。

| 端点 | 归属 | 类型 |
|---|---|---|
| `0x01` / `0x81` | vendor(GUD) | bulk OUT / IN |
| `0x82` | HID（键盘 + 触摸） | 中断 IN |
| `0x02` | UAC 播放 | 等时 OUT（adaptive） |
| `0x83` | UAC 录音 | 等时 IN（asynchronous） |
| `0x84` | **预留给 UVC** | — |

> 要 USB 日志串口请开 **`CONFIG_AIO_DEBUG_CDC`**（排障档）：它让出 vendor(GUD) 的 IN
> 端点 `0x81`（GUD 只用 bulk OUT）并借走 `0x84`，把 CDC 塞进这张表。直接开
> `CONFIG_TINYUSB_CDC_ENABLED` 仍是编译期 `#error`。见下文「日志」章节。

## 显示

### 为什么是 640×360

USB-C 只有 12 Mbps 全速：720p RGB565 整帧 1.84 MB，整屏刷新约 1.8 秒，交互不可用。
640×360 整帧 460 KB，且相对面板恰为**整数 2 倍**，硬件放大无插值伪影。

GUD descriptor 因此只对 host 声明**单一模式 640×360 / RGB565**，标记 `PREFERRED`，
并声明 `GUD_COMPRESSION_LZ4`（host 逐帧择优，压缩与未压缩两条收帧路径都要处理）。

### 流水线

```
host ──(bulk OUT, 可选 LZ4)──▶ 640×360 RGB565 (PSRAM)
                                 │
                                 ▼  PPA SRM 单次操作
                          scale 2.0 + rotate 90°
                                 │
                                 ▼
                    DPI 帧缓冲: 720×1280 RGB565 (PSRAM)
                                 │
                                 ▼  MIPI-DSI 2 lane @ 1000 Mbps
                              面板（DSI PHY 供电 = 内部 LDO_VO3 @ 2500 mV）
```

PPA 是 SRM（Scale-Rotate-Mirror）引擎，`scale_x/scale_y` 与 `rotation_angle` 在**一次操作里
同时生效**，不需要两遍搬运 —— 这是选 PPA 而非软件缩放的核心理由。

### 方向标定：`DISPLAY_ROT_CCW90 = 1`（已实机标定）

`display_dsi.c` 里的这个宏决定旋转方向（`1` = 90° CCW，`0` = 270° CCW，两者相差 180°）。
**实机验证取值为 `1`**（标定当时的判据是四象限自检图的红色象限横持时落在左上角）。

自检图已换成待机画面，**现在的判据是文字方向**：横持时 `NO SIGNAL` 正着可读即正确，
上下颠倒就是取值反了。这比原来的色块**更灵敏** —— 文字方向一眼可辨，
色块得对照记忆哪个角该是红的。

> ⚠️ 「画面铺满全屏」**验不出方向** —— 两个分支都产生 (0,0) 起的 720×1280 输出，
> 差别只在内容转了 180°。判据必须是内容本身（待机画面的文字方向），不是有没有黑边。

坐标映射（`DISPLAY_ROT_CCW90 = 1`）：

```
panel_x = y * 2
panel_y = PANEL_H - (x + w) * 2      /* x 轴反向 */
```

`display_blit()` 的**输入契约是紧凑排列**的 `w×h` 个 RGB565（stride = w，无 padding），
与 `gud_device.c` 收帧后的样子一致（脏矩形数据从缓冲偏移 0 起连续存放）；
`x/y` 只用于算输出落点，不参与输入寻址。整帧 (0,0,640,360) 时紧凑解读与
「整帧基址 + 偏移」解读恰好重合，所以**只有非整帧的脏矩形能区分二者**。

### 不做 byteswap

`BSP_LCD_BIGENDIAN = 0`、`COLOR_SPACE = RGB` ⇒ DSI/DPI 链路按小端 RGB565 直接取用。
Cardputer 上为抵消 ST7789 4-line SPI 字节序而加的 per-pixel `bswap16` 在这里**必须删除**，
留着会把颜色搞反。

### CPU 直写帧缓冲后必须 cache 回写

P4 的 DMA 不侦听 cache，DPI 帧缓冲是 `SPIRAM | DMA` 分配的：CPU 改完不回写，
末尾若干行可能还脏在 L2 里没落盘，表现为**屏幕底部杂色带**。
`display_dsi.c` 的 `frame_buffer_flush()` 负责这件事。

走 PPA 的路径**不用管** —— `ppa_srm.c` 自己在提交 DMA 事务前做了输入 C2M 回写与
输出 M2C invalidate。

### 背光点亮时机

背光 GPIO 在 `board_power_init()` 里配好但**保持熄灭**，直到 `display_init()` 全部初始化
成功后才由 `board_backlight(true)` 点亮。不变式是「背光亮 ⟺ 面板正在输出有效视频」——
195 条面板 init 命令要跑几十到上百毫秒，提前点亮会在开机时闪一下白屏/杂讯。

### 待机画面（`NO SIGNAL`）

开机后 host 还没送帧时屏上显示的是一幅**产品化的 NO SIGNAL 画面**（`display_standby_screen()`），
不是自检图 —— 早期那张「四象限彩块 + 中央黑方块」是 bring-up 期用来标定旋转方向、
验证 PPA 变换的，使命已完成。

```
              ┌──────────┐        显示器线框（下巴上一颗琥珀电源灯）
              └────┬─────┘
                 ──┴──

               NO SIGNAL          3×（24×48），琥珀 #F0A030
          Waiting for USB host…   2×（16×32），浅灰 #C8CDD4，末尾三点循环
      ───────────────────────     分隔线 #2A2F38
       M5Stack Tab5  |  USB Display          1×（8×16），暗灰 #8A929C
       640 x 360 RGB565  |  USB 16d0:10a9
```

- 背景 `#0F1115`（不刺眼、也不是纯黑，便于与「面板没输出」区分）。RGB565 是有损的，
  `standby_screen.c` 的配色表逐项注明了设计值与转换后实际显示的值。
- **收到第一帧 GUD 后永久停止绘制**，之后完全由 host 内容接管。停止条件是
  `gud_device_has_frame()`（`gud_device.c` 里 blit 成功后置位的一个 `volatile bool`）。
  这是硬要求：GUD 是脏矩形刷新的，被待机画面盖掉的一小块，host 未必会再画一次。
- 等待点动画每 500ms 一步，**只重画点所在的 48×32 那一小块**（3 KB 紧凑缓冲 + 局部
  `display_blit()`），不重画 460 KB 整屏 —— 整屏搬运既浪费也可能挤占 USB 收帧时序。
  它同时替代了此前用来证明「固件还活着」的诊断心跳。动画任务停下后 `vTaskDelete(NULL)` 退出。
- ⚠️ 动画任务让 PPA 有了**第二个提交者**（另一个是 TinyUSB 收帧），故 PPA client 的
  `max_pending_trans_num` 从 1 提到 2。池子空了时 `ppa_do_scale_rotate_mirror()`
  不等待、直接返回 `ESP_FAIL`，落在 GUD 侧就是 host 的一块脏矩形永远不上屏
  （脏矩形不会自动重发）—— 窗口很窄，但代价不对称。
- **它仍然验证着旋转方向**，而且比四象限彩块更灵敏：文字上下颠倒/镜像一眼可辨，
  说明 `DISPLAY_ROT_CCW90` 取值错了（见上「方向标定」）。

文案一律**英文**：显示器 OSD 的通用惯例（`NO SIGNAL`），且中文点阵要带整个 CJK 字库，
几十上百 KB flash，对一块开机三秒就被 host 覆盖的画面完全不划算。

#### 字体

`main/font8x16.h` = [Spleen](https://github.com/fcambus/spleen) 2.2.0 的 `spleen-8x16.bdf`，
**BSD-2-Clause**，© 2018-2026 Frederic Cambus。工程刻意不引 LVGL，字体渲染是自己的
100 行绘制原语（填充矩形 / 线框 / 整数倍放大画字符串，全在 `standby_screen.c`，不外露）。

提取是**机械的**（照 `panel_init_data.h` / `tab5_kbd_map.h` 的先例，不手抄）：按
`STARTCHAR..ENDCHAR` 切块 → 只取 `ENCODING` 落在 `0x20`–`0x7E` 的 95 个字形 → 断言其
`BBX 8 16 0 -4` 与 8×16 cell 一致 → 把 `BITMAP` 的 16 行十六进制原样搬下来 = 1520 字节。
整份字库有 1001 个字形（含 Unicode 区），带进来纯属浪费 flash。位布局与源 BDF 一致：
每行 1 字节，**bit7 是最左像素**。

#### 宿主机版式预览

绘制原语与版式被抽成零依赖纯函数（`main/standby_screen.{c,h}`，只需要 `tab5_pins.h` 的
`GUD_W/GUD_H`），因此可以在宿主机上渲染成 PPM 肉眼验收 ——「文字越界 / 两行叠一起 /
颜色算反」这类问题，在这里发现比烧一轮板便宜得多：

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -I../main test_standby_screen.c ../main/standby_screen.c \
    -o /tmp/test_standby && /tmp/test_standby /tmp/standby.ppm   # 参数可选，给了才导预览
```

35 个用例覆盖越界哨兵、行带占用（元素之间的空隙必须真的是空的）、左右 8px 边距、
标题与正文的颜色层次、点动画各相位的单调性与钳位。**改版式后务必重跑。**

## 面板批次

Tab5 随批次装两种面板，**同一份固件都支持**，型号在运行时由内部 I2C 探测决定：

| 探到的地址 | 判定 |
|---|---|
| `0x55` | **ST7123**（显示触控一体） |
| `0x14` | **GT911** 触摸 ⇒ 面板为 **ILI9881C** |

DPI 时序（两者只有像素时钟与 porch 不同，见 `display_dsi.c` 的 `s_panel_timings`）：

| 面板 | dpi_clk | hbp / hpw / hfp | vbp / vpw / vfp |
|---|---|---|---|
| ILI9881C | 60 MHz | 140 / 40 / 40 | 20 / 4 / 20 |
| ST7123 | 70 MHz | 40 / 2 / 40 | 8 / 2 / 220 |

- **开发用机是 ILI9881C 批次**（实测扫到 0x14、无 0x55），面板 ID 实测 `0x98 / 0x81 / 0x5c`。
- ⚠️ **必须传 esp-bsp 的定制 init 序列**（`main/panel_init_data.h`，vendor 自 esp-bsp，
  Apache-2.0）。用面板驱动组件内置的默认序列，实机表现为**竖纹 + 四角暗角 + 颜色错乱**。
- ⚠️ **ST7123 路径未经实机验证**（只编译不执行，固件启动时会打一条 warning 说明）。
  且上游 esp-bsp 的 ST7123 init 数据有两条 `data_size` 多算 1 字节
  （`0xA3` 声明 40、实际 39；`0xE8` 声明 15、实际 14），会让驱动越界读 1 字节 ——
  该路径出问题时这是**首要怀疑对象**。我们逐字节原样搬运了上游数据，没有就地"修正"，
  以便将来与 esp-bsp 逐行 diff。

## 实测 I2C 设备表（内部总线 SDA = G31 / SCL = G32）

| 地址 | 器件 |
|---|---|
| 0x10 | ES8388 音频 codec |
| 0x14 | GT911 触摸 |
| 0x32 | RX8130CE RTC |
| 0x40 | ES7210 麦克风前端 |
| 0x41 | INA226 电量监测 |
| 0x43 / 0x44 | PI4IOE5V6408 IO 扩展 ×2 |
| 0x68 | BMI270 IMU |

`0x43` 是 PI4IOE5V6408-1，本固件用它的 `LCD_EN`(pin4) / `TOUCH_EN`(pin5) 给面板与触摸上电。

> Tab5 Keyboard 在**另一条** I2C 上：SDA = G0 / SCL = G1 / INT = G50，地址 `0x6D`，
> 由 `kbd_i2c.c` 自己持有 `I2C_NUM_1`（本表这条内部总线是 `I2C_NUM_0`）。详见「HID 键盘」。

## Host 侧验证（主机需 mainline `gud`，内核 ≥ 5.13，发行版一般自带 `CONFIG_DRM_GUD=m`）

```bash
lsusb | grep 16d0                      # 16d0:10a9
sudo dmesg | grep -iE "gud|drm"        # [drm] Initialized gud ... + /dev/dri/cardN
ls /dev/dri/
sudo apt-get install -y libdrm-tests   # 若无 modetest
modetest -M gud                        # 列出 connector + 640x360 模式
modetest -M gud -s <connector_id>:640x360   # 送测试图上屏
```

实时内容（GStreamer，kmssink 直驱 GUD 卡；会产生大量脏矩形与 LZ4 压缩帧）：

```bash
# 注意：modetest -s 与 kmssink 都需 DRM master，二选一（先停掉另一个）
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=640,height=360 ! \
  kmssink driver-name=gud connector-id=<id> force-modesetting=true
```

固件侧对照：UART 日志里 `LZ4 解压失败` 与 `ppa srm 失败` 均应为 0 条。
开机的**待机画面**（`NO SIGNAL`，见上「显示 / 待机画面」）被 host 画面覆盖、
等待点动画随之停下（日志打一条 `待机画面停止绘制，屏幕交给 host`），这一变化本身即是
GUD 打通的证据；若开机就黑屏、连待机画面都没有，则可据此区分「显示坏了」与「GUD 没送帧」。

## 帧率

**待实测** —— Task 4（GUD 出图）与 Task 5（脏矩形 + LZ4）的实机验证尚未完成，
此处不填任何数字，以免把估算当成实测。

测法（两个场景各记一个数）：

- **场景 A（帧率下限）**：上面的 `videotestsrc` 全屏动态内容，几乎每帧都是整帧脏区，
  用 `GST_DEBUG=kmssink:5` 或在固件侧统计 `display_blit()` 次数/秒；
- **场景 B（实际体感）**：把文本终端绑到 GUD 卡后跑 vim/htop，记录打字与滚动的跟手程度
  （「打字无感延迟 / 滚动可见撕裂」这类描述），这才是「USB 瘦终端」的真实使用场景。

## 资源占用（实测，`idf.py size`）

| 项 | 值 |
|---|---|
| Flash | 356,466 字节（约 348 KB），占 4 MB factory 分区 **9%** |
| 内部 DIRAM | 95,694 字节（**16.6%**），剩余约 470 KB |
| 镜像总大小 | 442,336 字节（`.bin` 另有 padding） |

播放音量控制（Feature Unit + 换算 + 两个控制请求回调）的增量：**Flash +502 / DIRAM +4**
（相对不带音量控制的 355,964 / 95,690）。DIRAM 那 4 字节就是 `s_vol_q8` 与 `s_vol_muted`。

UAC1 音频的增量：**Flash +77,608 / DIRAM +4,370**（相对不带音频的 275,062 / 91,228）。
Flash 那一大笔几乎全在三个新链接进来的库上，与我们自己的代码无关：
`esp_driver_i2s` 22.9 KB（STD/PDM/TDM 三种模式一起编）+ `esp_codec_dev` 16.2 KB
+ `esp_hal_i2s` 5.4 KB，其余是 TinyUSB 的 audio class。
`esp_codec_dev` 已经在 `sdkconfig.defaults` 里裁到**只剩 ES8388 与 ES7210 两颗**，
其余八颗 codec 不编。9% 的占用离 4 MB 分区还很远，本阶段不做进一步瘦身。

大块缓冲全在 PSRAM，不占内部 RAM：GUD 收帧缓冲共约 900 KB（未压缩帧与压缩帧各一份，
每份 `640×360×2` = 460,800 字节），DPI 帧缓冲 1.84 MB。
待机画面另临时占一份 460,800 字节，blit 完即释放；等待点动画常驻 3 KB（`48×32×2`），
收到第一帧后一并释放。字体 1520 字节在 flash（`.rodata`）。

> ⚠️ **DIRAM 总量是 576,464 字节（约 563 KB）** —— 对着 `build/tab5_aio.map` 的
> Memory Configuration 核实过：`sram_low 0x4ff00000 / 0x2cbd0` + `sram_high 0x4ff40000 / 0x60000`。
> 这个布局是 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` 带来的：IDF 的
> `components/esp_system/ld/esp32p4/memory.ld.in` 对两档芯片用**完全不同的 SRAM 布局** ——
> rev ≥3.0 是一整块 `sram_seg`（`0x4FF00000 + L2_CACHE_SIZE` 到 `0x4FFAEFC0`），
> rev <3.0 拆成 `sram_low` + `sram_high` 两段。
>
> 但按本工程的 `CONFIG_CACHE_L2_CACHE_SIZE=0x20000` 算，rev ≥3.0 档位是
> `0x4FF20000`–`0x4FFAEFC0` = 585,664 字节，**只比当前多 9,200 字节（约 9 KB）**。
> 也就是说：**翻 Kconfig 换档位换不回什么内存**，内部 RAM 不够时只能从别处省，
> 不要指望改芯片版本档位解决。
>
> **后续阶段（UAC 音频 / UVC 摄像头）的内部 RAM 预算要按剩余 ~474 KB 算，不能按 563 KB。**
> DMA 缓冲往往必须在内部 RAM，这条约束比看上去紧。

## HID 键盘

**实机验证通过**：键盘输入在 GUD 显示的 Linux console 上正常。

Tab5 Keyboard 是**独立的 STM32F030 I2C 从机**，地址 `0x6D`，挂在 **SDA=G0 / SCL=G1**，
与内部 I2C（G31/G32，见上）**物理分离**，故 `kbd_i2c.c` 自建一条 `i2c_master_bus`，
用 `I2C_NUM_1`（`I2C_NUM_0` 已被 `board_power` 的内部总线占用）。中断线 **G50，低有效**
（键盘固件拉低表示事件队列非空）→ ESP 侧配上拉 + 下降沿触发。矩阵 **5 行 × 14 列 = 70 键**。

> **键盘与触摸都是可选外设，缺席不拦启动。** Tab5 Keyboard 是可拆配件（2×5 排针），
> 不接底座时 `i2c_master_probe(0x6D)` 必然失败；触摸控制器也随面板批次而异。
> 故 `app_main.c` 对 `kbd_start()` / `touch_start()` **不用 `ESP_ERROR_CHECK`**，
> 失败只打一条 **WARNING** 后继续启动 —— 日志里看到
> `键盘不可用(...)，继续启动` 属正常现象，不是故障。
> 反之 `board_power` / `display` / `gud_device` / TinyUSB 仍是 `ESP_ERROR_CHECK`：
> 那些是核心链路，起不来就没有任何可用形态。

### 寄存器表

取自官方固件 `user_i2c_reg.h`，不是照协议图猜的：

| 地址 | 名称 | 说明 |
|---|---|---|
| `0x00` | INTR_CONFIG | bit0 普通模式中断使能 / bit1 HID / bit2 字符，默认 `0x07` |
| `0x01` | INTR_STATUS | 同位布局；写 0 释放中断信号并清状态 |
| `0x02` | EVENT_NUM | 当前模式队列长度 0~32；读一次事件自动减 1；**写 0 清空队列并释放中断**（已从官方 `user_i2c_callback.c:149-159` 核实：`event_fifo_reset()` + `int_disable()`） |
| `0x03` | RGB_BRIGHTNESS | 0~100，默认 20 |
| `0x10` | KEYBOARD_MODE | 0 = Normal / 1 = HID / 2 = Character，默认 0 |
| `0x11` | RGB_MODE | 0 绑定 / 1 自定义 |
| `0x20` | KEY_EVENT | Normal 模式事件，1 字节：bit7 = 按下(1)/释放(0)，bit[6:4] = 行(0~4)，bit[3:0] = 列(0~13)；队列空读回 `0xFF` |
| `0x30` | HID_EVENT | 2 字节（本实现不用） |
| `0x40` / `0x50` | CHAR_EVENT_LENGTH / CHAR_EVENT | 字符模式（本实现不用） |
| `0x60`–`0x67` | RGB_VALUE | RGB1_B/G/R、RGB2_B/G/R |
| `0xFD` | IAP_UPDATE | 固件升级入口 |
| `0xFE` | FIRMWARE_VERSION | 只读 |
| `0xFF` | I2C_ADDRESS | 读写，改后立即生效并存 Flash |

> ⚠️ **协议图容易读错**：图里最后一行标的 `0xF0` 是**块基址**，Version / Address 分别在
> 该行的 E / F 列，即绝对地址是 `0xFE` / `0xFF`。照图按 `0xF0` 读会读到别的东西。
>
> ⚠️ **`0xFD` 是固件升级（IAP）入口，协议图上没画**。误写会把键盘刷成砖，
> `kbd_i2c.c` 永不触碰这个地址。

### 为什么不用键盘自带的 HID 模式

读 M5 官方固件 `user_keyboard_handle.c` 确认两个硬伤：
1. 修饰键（Ctrl / Alt / Sym / Aa）被标记 `special_key`，不进事件队列 —— host 永远看不到
   「单独按住 Ctrl」；
2. 按下推 `{modifier, keycode}`、松开推 `{modifier, 0}`，一次只能表达一个键。

对「Linux 终端」这个用途，组合键与按住状态都是刚需，故用 Normal 模式（寄存器 `0x10` 写 0）
自建 6KRO 状态机，不用官方 HID 模式（寄存器 `0x30`）。

### 两个上游语义陷阱

行列 → HID usage 的映射表 vendor 自官方固件 `key_value_map`（`tab5_kbd_map.h`，MIT），
但直接照抄语义会踩两个坑：

1. **底行字母 `z x c v b n m` 的 `firstModifierMask` 是 `KEY_MOD_LSHIFT`**
   （第 0–3 行字母都是 `KEY_MOD_RESERVED`）。官方 `convert_to_hid()` 的小写分支根本不读
   这个字段（只用运行时 `modifier_mask`），无声地绕过了它。**任何无条件取
   `firstModifierMask` 的实现都会让整个底行打出大写**。本实现对字母基础层硬写
   `mod = 0`（`kbd_translate.c`）。
2. **Aa 必须被 Ctrl/Alt 门控**（官方是 `aa_flag && !ctrl_state && !alt_state`）。漏掉的话，
   按住 Aa 时 `Ctrl+C` 会变成 `Ctrl+Shift+C` —— 终端里前者是 SIGINT、后者通常是「复制」，
   **症状（Ctrl+C 中断不了程序）极难联想到键盘层逻辑**。门控用的 ctrl/alt 状态必须取自
   `s_pressed`（当前按下集合），不能取正在累加的 `modifier`（那时还没算完）。

另外一个容易搞混但不是「陷阱」的点：**Sym / Aa 不作为 Shift 上报**。官方表里它们的
`firstKeyCode` 都是 `KEY_LEFTSHIFT`，但物理键盘上标「!」的键，其基础层本身就是
`Shift+1` —— Sym 是切到第二层，不是 Shift；若把 Sym 当 Shift 上报，符号会全错。

### 分层规则

Sym(3,0) / Aa(3,1) 是本地层键，不上报；查表得到的 usage 落在 `0xE0~0xE7`（HID 修饰键区间）
时转成 modifier 位、不占 keycode 槽（Ctrl/Alt 由此自动处理）；Sym 按住且
`key_modifier_flag` 置位时用第二层；Aa 生效（且未按 Ctrl/Alt）时字母键用第二层（大写）。
超过 6 个非修饰键同时按下时静默丢弃 —— 有意选择，70 键小键盘上同时按 7 个键属误触。

### USB 侧

IF1 = HID（`EPNUM_HID = 0x82`，vendor 用 `0x81`），`bInterval = 10`（ms）。
**报告描述符带 Report ID**（`HID_RID_KEYBOARD = 1`）—— P4 全速控制器最多 4 条可用
IN 端点（见上），UAC/UVC 会用满，所以触摸与键盘共用本接口，以 **RID 2 = digitizer**
追加（已落地，见下文「HID 多点触摸」）。

> ⚠️ **`bInterfaceProtocol` 已从 `HID_ITF_PROTOCOL_KEYBOARD` 改成 `HID_ITF_PROTOCOL_NONE`**
> （随触摸一并落地）。传 `KEYBOARD` 会把 `bInterfaceSubClass` 一并设为 BOOT，即宣称支持
> boot keyboard，而 **boot 协议的报告格式不允许 Report ID** —— 本接口现在同时承载
> 键盘(RID 1)与 digitizer(RID 2)、必须靠 Report ID 区分，继续声明 BOOT 就是在说谎。
> **代价**：BIOS/UEFI/GRUB 这类只会 `SET_PROTOCOL(boot)` 的早期环境不再能把它当键盘用
> （记录在此免得日后有人报「BIOS 里打不了字」）。Linux `usbhid` 默认走 report 协议，
> 日常零影响 —— 改完实机复验：键盘仍枚举为**独立的 input 设备**
> （`flange Tab5 USB Terminal Keyboard`），见下文「HID 多点触摸 / Host 侧验证」。

`tud_hid_set_report_cb` 是空实现，即**不同步 host 的 CapsLock 等 LED 状态**（本阶段有意）。

### 端点忙的处理

`tud_hid_ready()` 为假时若直接丢弃报告，同一批排空产生的多条报告只有第一条发得出去；
**丢掉「释放」那条就是终端里的卡键/字符自动重复，且现象极像硬件故障**。实现改为最多等
20ms 让端点腾空（`kbd_i2c.c` 的 `kbd_build_and_report()`），仍失败时 `ESP_LOGW`。

> ⚠️ 并**不能**用「一批只发最终状态」来规避 —— 批次里若同时有 press-A 和 release-A，
> 合并后这次按键会整个消失，必须逐条发。

### 宿主机回归测试

分层逻辑被抽成零依赖纯函数 `kbd_translate.c`（`kbd_i2c.c` 只管 I2C 与 USB 上报），
`firmware/test/test_kbd_translate.c` **直接编译真实源码**而非复制体，16 个用例覆盖
两个上游陷阱与 Sym/Aa 组合。不引入任何测试框架，也不挂进 IDF 构建：

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -I../main test_kbd_translate.c ../main/kbd_translate.c -o /tmp/t && /tmp/t
```

**改动分层逻辑后务必重跑。**

### Host 侧验证

```bash
lsusb -v -d 16d0:10a9 | grep -A5 HID
cat /proc/bus/input/devices
sudo evtest /dev/input/eventN
```

## HID 多点触摸（GT911）

**实机验证通过**：host 侧 `hid-multitouch` 绑定，**多点触摸可用（实测三指同时接触）**，
键盘仍是独立的 input 设备。⚠️ **四角坐标标定尚未验证**，见本章末「待验项」。

GT911 与 IO 扩展 / codec / IMU 同挂**内部 I2C**（SDA=G31 / SCL=G32），所以 `touch_hid.c`
直接复用 `board_i2c_bus()` 的总线句柄，**不像键盘那样自建总线**；触摸电源使能在
PI4IOE5V6408-1(`0x43`) 的 PIN5，`board_power_init()` 已拉高。上报走键盘那条 HID
接口(IF1)与端点，用 **Report ID 2** 区分。20ms 轮询，不用中断（理由见下）。

> 触摸与键盘一样是**可选外设，缺席不拦启动** —— `touch_start()` 失败只打 WARNING，
> 详见上文「HID 键盘」开头那段说明。

### ⚠️⚠️ TP_INT 上的上拉电阻 —— 这块板最大的坑

**Tab5 v1 硬件（ILI9881C + GT911）在 TP_INT（G23）上有一颗到 3V3 的上拉电阻，它会压住
GT911 不出坐标。** I2C 读得到产品 ID、`esp_lcd_touch_new_i2c_gt911()` 一路返回 `ESP_OK`、
轮询任务也在跑，但状态寄存器 `0x814E` 的 buffer-ready 位(bit7)永远不置起 ——
**现象是完全静默**：设备在、驱动在、`evtest` 里一个事件都没有。

解法要**两句、缺一不可**（`touch_start()` 开头）：

1. 把 G23 `gpio_config()` 成 **OUTPUT** 并 `gpio_set_level(..., 0)` **主动驱动到低**，
   压住那颗外部上拉；且必须在 `esp_lcd_touch_new_i2c_gt911()` **之前**做；
2. 同时把 `tp_cfg.int_gpio_num` 填成 **`GPIO_NUM_NC`**。

**只做第 1 句无效** —— GT911 驱动会在初始化里把这个脚重新 `gpio_config()` 成
INPUT + NEGEDGE，刚驱动的低电平立刻被抹掉，等于没修。代价是放弃中断驱动触摸的可能，
本来也没用上（我们是 20ms 轮询）。

这不是猜测：官方 esp-bsp `bsp/m5stack_tab5/src/bsp_display.c` 的 `bsp_touch_new()` 在
`board_version == 1` 分支专门做了这两件事，注释原文 *"there is resistor to 3V3 on
interrupt pin which is blocking GT911 touch"*。我们此前只逐项对照了 BSP 里 `tp_cfg` 的
**初始化列表**（那部分确实相同），漏看了紧随其后的这两行 GPIO 操作，于是原样复现了这个
「上游已知并已修」的坑。**排查时若见触摸完全静默，先查这里，别再怀疑 I2C** ——
`esp_lcd_touch_new_i2c_gt911()` 结尾会无条件读产品 ID(`0x8140`) 与配置版本(`0x8047`)，
它返回 `ESP_OK` 本身就已经证明 I2C 通、地址对。

> **拉低不影响 I2C 地址**：GT911 只在**上电/复位瞬间**按 INT 电平 latch 地址
> （高⇒`0x14`、低⇒`0x5D`），那一刻由板上那颗上拉决定为高；此处拉低发生在
> `board_power_init()` 拉起 TOUCH_EN 之后很久（中间还隔着 195 条面板 init 命令），
> 地址早已锁定。
>
> 万一将来换批次硬件复发，Plan B 是补 M5 官方的显式复位时序（脉冲 IO 扩展 P5），
> 但**顺序写反会更坏**：必须「先拉高 INT → 脉冲 P5 → 等 100ms → 再执行 INT 拉低」；
> 若在 INT 已被拉低之后才脉冲 P5，GT911 会 latch 成 `0x5D`，连 I2C 都不再应答。
> 详见 `touch_hid.c` 里 `touch_start()` 开头的长注释。

### ⚠️ I2C 地址是 `0x14`，不是驱动默认的 `0x5D`

GT911 的**默认**地址是 `0x5D`，`0x14` 是**备用**地址 —— Tab5 用的正是 `0x14`。
组件的 `ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG()` 宏填的是 `0x5D`，且只校验传入值合法、
**不会自动探测**（它那段地址选择流程还要求有 rst 引脚，Tab5 没有，直接被跳过）。
所以必须显式改写：

```c
io_cfg.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP;   /* = 0x14 */
```

不改就一定探不到。顺带：`display_dsi.c` 的面板批次探测正是靠 `i2c_master_probe(0x14)`
命中才选的 ILI9881C 分支，这个地址是实测无疑的（见上文「面板批次」）。

### 坐标反变换（`touch_map.c`）

触摸控制器按**面板原生 720×1280 竖向**出数，而 host 画的是 640×360 横向内容 ——
两者必须落到同一可视坐标系，否则点哪儿指针跑到别处。方向三 flag
（`swap_xy` / `mirror_x` / `mirror_y`）**全填 0，这不是待标定的占位值，是官方 BSP 的取值**
（esp-bsp 的 `tp_cfg` 初始化列表与此逐项相同）。

反变换与 `display_blit()` 在 `DISPLAY_ROT_CCW90 = 1` 下的正变换**互逆**：

```
正：GUD gy ↦ panel x ∈ [2·gy, 2·gy+2)
    GUD gx ↦ panel y ∈ [1280−2·gx−2, 1280−2·gx)

反：gud_x = (PANEL_H − 1 − panel_y) / GUD_SCALE     /* 0..639 */
    gud_y =  panel_x                / GUD_SCALE     /* 0..359 */
```

边界自检：`gud(0,0)` ↔ `panel(0,1279)`、`gud(639,359)` ↔ `panel(718,0)`。

再归一化成 HID 逻辑值 `[0, TOUCH_HID_LOGICAL_MAX]`（**32767**），让报告描述符与 GUD
分辨率解耦 —— 换分辨率只改调用方传的 `gud_max`，描述符不动。取 32767 而非 65535 是因为
**Logical Maximum 在 HID 里是有符号量**，超过 32767 就得用更宽的编码并小心正负。

两处容易写错、且现象极难反推的地方，就地钉死在 `touch_map.c` 的注释里：

- **必须先钳入参**：`panel_y` 超过 `PANEL_H-1` 时 `PANEL_H-1-panel_y` 是负数（整型提升后
  有符号），除完再转 `uint16_t` 会绕成一个巨大值 —— 光钳结果救不回来；
- **归一化的中间积显式用 `uint32_t`**：`639 × 32767 = 20,938,113` 早已超出 `uint16_t`
  与 `int16_t`，不要依赖「int 至少 32 位」。

#### 宿主机回归测试（32 用例）

反变换被抽成零依赖纯函数（照 `kbd_translate.c` 的先例），`test/test_touch_map.c`
**直接编译真实源码**而非复制体：

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -I../main test_touch_map.c ../main/touch_map.c -o /tmp/t && /tmp/t
# → OK (32 cases)
```

用例覆盖四角、正中、越界钳位、**与显示正变换的往返一致性**，以及
`touch_report_fill()` 的两条不变量（`contact_count` 恒等于 `tip=1` 的 slot 数、
非活跃 slot 整体清零）。「几个触点装进几个 slot、多出来的怎么办」这类错误在实机上
只表现为「多指时坐标错位或干脆没反应」，从现象反推极难，放到宿主机上钉死几乎零成本。
**改算式或报告布局后务必重跑。**

### 报告描述符：四个不写清楚就会被静默坑掉的点

TinyUSB 没有现成的 digitizer 描述符宏（只有 keyboard/mouse/consumer/gamepad），
`AIO_HID_REPORT_DESC_TOUCH` 按 HID Usage Tables 的 Digitizers 页(0x0D)手写。
负载 `sizeof(touch_report_t)` = **31 字节** = 5 × 6 字节 contact + 1 字节 Contact Count；
单个 contact 是 `Tip Switch 1 bit + 7 bit 常量填充 + Contact Identifier 8 bit + 绝对 X/Y 各 16 bit`。

1. **活跃触点必须紧挨着排在报告最前面、不留空洞**，不能按 `contact_id` 去占固定 slot。
   Linux `hid-multitouch` 的默认 class 带 `MT_QUIRK_CONTACT_CNT_ACCURATE`：它**只看前
   `contact_count` 个 slot**，其余直接不处理（靠 `input_mt_sync_frame` 释放）。中间留空洞的话，
   **空洞后面的真实触点会被整个丢弃**。`touch_report_fill()` 因此负责压实，并把未使用的
   slot 整体清零。
2. **`TOUCH_CONTACTS_MAX`（= 5）三处共用同一个常量**：① 报告描述符（展开几份 contact
   collection、Contact Count 的 Logical Maximum）；② `touch_report_t` 的 slot 数；
   ③ `tud_hid_get_report_cb()` 里 Contact Count Maximum 那份 Feature 报告的应答值。
   各写各的，host 解出来的触点数与报告实际长度对不上，**症状是坐标全乱**。
   `usb_descriptors.c` 与 `touch_map.h` 各有一条 `_Static_assert` 把描述符展开次数与
   结构体尺寸钉在一起，改数量时漏改会在编译期炸掉，而不是等到实机坐标乱跳。
3. **Contact Identifier 的 Logical Maximum 255 必须用 2 字节编码**
   （`HID_LOGICAL_MAX_N(255, 2)`）：HID 的 logical min/max 是**有符号**量，
   单字节 `0xFF` 会被解析成 **−1**。
4. **X/Y 用 Generic Desktop 页的 X/Y，不是 Digitizer 页** —— `hid-input` / `hid-multitouch`
   只认这一组来生成 `ABS_MT_POSITION_X/Y`。⚠️ 用完必须 `HID_USAGE_PAGE(DIGITIZER)` **切回去**：
   Usage Page 是 **Global** item，会一直生效到下次改写，不切回来的话下一份 contact 的
   Usage(Finger)/Usage(Tip Switch) 与段尾的 Contact Count 全被解析成 Desktop 页里同号的
   usage，**整份描述符报废**。

此外 **Contact Count Maximum 是 `Feature` 报告、不是 Input**：`hid-multitouch` 在 probe 时会
主动 `GET_REPORT(Feature, RID 2)` 读它来决定分配几个 MT slot，STALL 或返回空会让它退回默认值。
应答实现在 `tud_hid_get_report_cb()` 里，就一个字节 —— 多点能不能真正生效就差它
（⚠️ buffer 里**不要**再写 Report ID，TinyUSB 已经替我们写进第一字节并把指针后移了）。

> 键盘(RID 1)与触摸在同一个 HID 接口上，因此**整个接口会归 `hid-multitouch` 管**。
> 这不影响键盘：`mt_input_mapping()` 对 `application == GenericDesktop/Keyboard` 的字段
> 直接返回 0，退回 `hid-input` 的默认处理 —— 实机上键盘依然是一个**独立的 input 设备**。

### 上报策略

- **`contact_id` 取触摸控制器给的 `track_id`**，不用数组下标：同一根手指按住期间 `track_id`
  不变，host 靠它把帧与帧之间的触点连成轨迹（→ `ABS_MT_TRACKING_ID`）。若改用下标，
  中间某根手指抬起时后面的手指会集体「换 id」，host 看成瞬移。
- **状态没变就不发**：20ms 轮询下按住不放会每帧产生一条相同报告，白占与键盘共用的端点带宽。
  坐标是状态量不是边沿，host 记住最后一条即可。比较直接对整个 packed 结构体 `memcmp`。
- **端点忙时最多等 20ms**（写法与 `kbd_build_and_report()` 一致）。直接丢弃的话，
  丢掉的若正好是 `contact_count = 0` 那条「全部抬起」，**host 就一直认为手指还按着**
  —— 与键盘的卡键同源。
- **只有真发出去了才记进 `last_rpt`**：否则「状态没变就不发」会把一次失败的发送**永久固化**
  （手指已离开屏幕、不会再产生新状态）。发送失败保持 `last_rpt` 不动，下一轮自然重试。

### Host 侧验证（`evtest`）

复合设备会出**两个** input 设备，先按名字挑对：

```bash
lsusb | grep 16d0                     # 16d0:10a9
sudo evtest                           # 不带参数：列出所有 event 设备及名字，按编号选
```

- `flange Tab5 USB Terminal **Keyboard**` —— 键盘那份（RID 1）；
- `flange Tab5 USB Terminal` —— **触摸这份**（RID 2），名字里没有 `Keyboard`。

也可以直接查驱动绑没绑对：

```bash
grep -B2 -A4 "Tab5" /proc/bus/input/devices          # 看 Name / Handlers=eventN
ls -l /sys/bus/hid/devices/*16D0*10A9*/driver        # → .../drivers/hid-multitouch
```

**实机验证结论**（在 `khadas-vim3l`（arm64）上用 `evtest`）：

- 设备枚举为 `bus 0x3 vendor 0x16d0 product 0x10a9`，名为 `flange Tab5 USB Terminal`；
- **`hid-multitouch` 正常绑定**，且**键盘仍是独立的 input 设备**
  （`flange Tab5 USB Terminal Keyboard`）—— 共用一个 HID 接口不冲突。
  ⓘ 这条是**推断**而非直接观察：上面那条查 `/sys/bus/hid/.../driver` 的命令当时没跑，
  依据是能力表里出现了 `ABS_MT_SLOT` —— 该轴由 `input_mt_init_slots()` 创建，
  HID 栈里只有 `hid-multitouch` 会调它，`hid-generic` 不会；
- 能力表含 `ABS_MT_SLOT`（**Max 4**）、`ABS_MT_POSITION_X` / `ABS_MT_POSITION_Y`
  （均 **Max 32767**），属性含 `INPUT_PROP_DIRECT`（直接式触摸屏，不是触摸板）；
- `ABS_MT_SLOT` 的 **Max 4**（= `TOUCH_CONTACTS_MAX` − 1 = 5 − 1）恰好证明
  **Contact Count Maximum 那份 Feature 报告被内核读到了** —— 没读到的话这里会是
  `hid-multitouch` 的默认值 10；
- **实测三指同时接触**，分别落在 slot 0 / 1 / 2，各有独立且稳定的 `ABS_MT_TRACKING_ID`，
  坐标各自独立更新。

> ⚠️ **不要把这写成「5 点全部验证通过」**：实测只观察到 3 指同时接触，**4 / 5 指未验证**。
> 描述符与报告结构声明的是 5 点，且 GT911 本身按 `CONFIG_ESP_LCD_TOUCH_MAX_POINTS = 5` 上报。

### ✅ 四角坐标标定（已实机验证）

依次点屏幕**横持视角**的四个角，X 与 Y **各自都能跑到接近 0 与接近 32767**
（`evtest` 里看 `ABS_MT_POSITION_X` / `ABS_MT_POSITION_Y` 的取值范围）——
标定通过，`touch_map.c` 的反变换与轴向都是对的。

> ⓘ 曾有一次抓取里所有触点的 Y 都落在满量程的 **78%–99%**，一度疑似 Y 轴映射有问题。
> 实测四角标定正常 ⇒ 那就是当时手指本来就点在画面下方那一带。再遇到类似的偏态分布，
> 先按四角标定复核，别直接怀疑映射。

## UAC1 全双工音频（ES8388 播放 + ES7210 双麦录音）

### ✅ 状态：播放与录音均已实机验证

**已实机确认**：主机把它枚举成 UAC1 声卡，`speaker-test` / `aplay` 从板载喇叭**出声**，
`arecord` 录到的**声音正常**，**播放音量控制（Feature Unit）也已实机验证通过**，
同时 GUD 显示、键盘、触摸均无回归。
音频因此改为**无条件编译**，所有排障旋钮已删除（见下面「排障经验」）。

> ⚠️ **未验证的部分，别写成已验证**：
> - 全双工**同时**收发的长时间稳定性（实测是分别验证播放与录音）；
> - 与 GUD / HID 并跑时对帧率的影响（音频每毫秒一次 DMA + 一次 USB ISO 传输）；
> - 音质与时钟漂移 —— 本设备**没有反馈端点**（理由见下文），长时间连续播放是否
>   出现爆音、断续或缓慢的相位漂移，尚无实测数据。

### 排障过程留档（三刀二分 + 根因）

这一节保留的是**结论与证据**，不是操作手册：当时用来切刀的四个 Kconfig 旋钮
（`AIO_AUDIO_MODE` / `AIO_AUDIO_FULL_STAGE` / `AIO_AUDIO_I2S_GPIO` /
`AIO_USJ_RELEASE_PHY_PADS`）已经**全部删除**，正文里提到它们只是在复述当时的实验条件。

原始现象：加上音频之后，主机侧不但没出录音设备，**连已实机验证的 GUD 显示也枚举不出来了**；
退回 `31275803` 之前即恢复。主机侧 dmesg（`2f7a6502` 实测，即**已含**「数据泵补延时 +
优先级降到 4」那次修复）：

```
221.388  usb 1-1.2: USB disconnect, device number 5      ← app 接管，TinyUSB 上电
221.731  usb 1-1.2: device descriptor read/64, error -32
223.101  usb 1-1.2: Device not responding to setup address.
224.010  usb 1-1-port2: unable to enumerate USB device
```

读法：D+ 已拉起（主机看得到设备），但 EP0 一个控制传输都不应答；且之后**再没出现过**
bootloader 阶段的 `cdc_acm ttyACM0` ⇒ 设备既没崩也没复位，是「活着但 EP0 不应答」。
这条否定证据下面反复用到。

### ⚠️ 排障经验（这轮最贵的三条）

1. **分档旋钮的残留配置会静默改变行为，而日志表现得像真实故障。**
   清理前的最后一轮里，`CONFIG_AIO_AUDIO_FULL_STAGE=2` 留在了 `sdkconfig` 里
   （stage 2 的定义就是「只做到 `es8388_init()` 为止」，`es7210_init()` 根本不执行）。
   于是自检打出 `录音 ES7210=未运行 probe=未运行 卡在=未开始` —— 我们对着一条
   **压根没跑过的代码路径**查了一整轮「ES7210 故障」，而 ES7210 从头到尾都是好的。
   教训：**分阶段旋钮只该在一次排障会话里存在，定位完立刻删掉**；真要保留，
   自检日志必须把「当前档位」本身也打出来，否则「没跑」与「跑了但失败」
   在现场无法区分。（快照里把「未运行」与真实错误码分开是对的，但那只解决了一半 ——
   人还得知道**为什么**没运行。）
2. **没查源码就写进注释的机理，会把后面几次烧板全带偏。** 见下面「历史：一度写在
   这里的错误机理」。
3. **现场没有串口时，先把日志通道做出来再排障。** `CONFIG_AIO_DEBUG_CDC` 这一档
   （拿 GUD 那条从未通过流量的 IN 端点换一条 USB CDC 串口）本该是第一步而不是第五步。

### ✅ 二分第一刀（已实测）：描述符无罪

当时的 `DESC_ONLY` 档（描述符原样带音频，但**不启动 codec**）实测结果：
**GUD 显示正常，且主机成功枚举出 UAC 设备**。

于是这一整片候选根因**被排除**：描述符内容、接口号、端点号、DWC2 的 FIFO 预算、
TinyUSB 音频类驱动本身（`audiod_init` / `audiod_open` / `CFG_TUD_AUDIO_*`）——
这些在 `DESC_ONLY` 下全都在跑，而且跑得好好的。

完整档与 `DESC_ONLY` 的差值只剩「编译 `codec_audio.c` + 调用它」，
**根因 100% 在 `codec_audio.c` 的运行时**。

### 二分第二刀：按启动步骤分级（`codec_audio_start()` 的五个动作）

当时的 `AIO_AUDIO_FULL_STAGE`（0–5）把启动切成五级，一次烧板切一刀，
判据只有一条：GUD 还出不出图（现场没串口）。

| 值 | 跑到哪一步为止 | 这一级挂掉 ⇒ 根因是 |
|---|---|---|
| `0` | **只起数据泵**，codec/I2S 一个字都不碰 | 数据泵对 `tud_audio_*` 的调用本身 |
| `1` | `i2s_full_duplex_init()`：建通道 + 配 G26~G30 + 时钟 | I2S 外设 / 引脚 / 时钟 bring-up |
| `2` | `+ es8388_init()`：I2C `0x10` 寄存器序列 + TX 通道使能 | ES8388 那段 I2C，或 TX 通道使能 |
| `3` | `+ es7210_init()`：I2C `0x40` 寄存器序列 + RX 通道使能 | ES7210 那段 I2C，或 RX 通道使能 |
| `4` | `+ board_speaker_enable(true)`：功放上电（**不起数据泵**） | 功放上电（电流/电源，软件之外） |
| `5` | `+ 数据泵任务`（= 完整行为） | 数据泵的稳态运行 |

**实测结果：`4` 挂、`2` 挂** ⇒ 数据泵、功放上电、ES7210 全部洗清，
根因落在 `1`（`i2s_full_duplex_init()`）或 `2`（`es8388_init()`）—— 与最终结论一致。

> ⚠️ 这把刀也是**代价最大的一把**：它留在 `sdkconfig` 里的残值后来伪造了一次
> 「ES7210 故障」，见上面「排障经验」第 1 条。旋钮已删除。

### ✅ 二分第三刀（已实测）：罪就是那两个焊盘

当时的 `AIO_AUDIO_I2S_GPIO=NO_USB_PADS` 档（**整套音频照跑**，只把 G26/G27 从
`i2s_std_config_t.gpio_cfg` 里换成 `I2S_GPIO_UNUSED`）：

> **GUD 显示正常、声卡枚举、麦克风也枚举出来了。只是没有声音、麦克风也没电平。**

没声音是预期的（DOUT 与 BCLK 确实没接出去）。这一档把剩下的候选根因一次洗清：
I2S 外设 / 时钟 / GDMA、codec I2C 序列、`esp_codec_dev`、数据泵、UAC 描述符、端点、FIFO
**全部无罪** —— 只要碰 G26/G27 就死。附带结论：最初「麦克风枚举不出来」不是独立 bug，
是同一根因的连带现象。

### 🎯 根因（已坐实）：**配 G26/G27 会顺手关掉 USB-C 的焊盘**

一句话：**这不是「两个驱动器抢一个焊盘」的模拟问题，是一次寄存器误伤。**

`esp_hal_gpio/esp32p4/include/hal/gpio_ll.h:676-686`：

```c
static inline void gpio_ll_func_sel(gpio_dev_t *hw, uint8_t gpio_num, uint32_t func)
{
    // Disable USB PHY configuration if pins (24, 25) (26, 27) needs to select an IOMUX function
    // P4 has two internal PHYs connecting to USJ and USB_WRAP(OTG1.1) separately.
    // We only consider the default connection here: PHY0 -> USJ, PHY1 -> USB_OTG
    if (gpio_num == 24 || gpio_num == 25)      USB_SERIAL_JTAG.conf0.usb_pad_enable = 0;
    else if (gpio_num == 26 || gpio_num == 27) USB_WRAP.otg_conf.usb_pad_enable = 0;
    IO_MUX.gpio[gpio_num].mcu_sel = func;
}
```

注释里那句 **"We only consider the default connection here"** 就是引信 ——
`route_fsls_phy0_to_otg()` 恰恰把那个默认映射对调了。完整调用链：

```
i2s_channel_init_std_mode()
  → i2s_gpio_check_and_set()                  esp_driver_i2s/i2s_common.c:920
    → gpio_func_sel(26/27, PIN_FUNC_GPIO)     esp_driver_gpio/src/gpio.c:1128
      → gpio_ll_func_sel()
        → USB_WRAP.otg_conf.usb_pad_enable = 0
          → 换过 PHY 后这一位管的是 PHY0 = G24/G25 = **USB-C**
```

`usb_pad_enable` 是**跟着 mux 走的**（否则 `usb_new_phy()` 置位 USB_WRAP 那一位之后
USB-C 根本不会通）。所以 G26/G27 上自始至终只有 I2S 一个驱动器，PHY1 的焊盘从未打开。

症状也对得上：G25(D+) 的复位状态是「输入禁用 + 上拉使能」，焊盘关掉后 D+ 仍浮在高位
⇒ 主机看得到设备，但收发器已死 ⇒ EP0 一个控制传输都不应答，CPU 不复位。

**为什么 esp-bsp / M5Stack 自己的固件不会踩到**：Tab5 的 PHY1 上根本没接 USB 连接器
（原理图 U1 pin 55/56 的网名就是 `I2S_DIN_MOSI_GPIO26` / `I2S_SCLK_GPIO27`），
而 `bsp/m5stack_tab5/src/bsp_usb.c` 走的是 `usb_host_install()`，在 P4 上解析成
**高速控制器 + UTMI PHY**（独立焊盘），从不碰 G24~G27。esp-bsp 全仓库对
`usb_phy` / `usb_wrap` / `phy_sel` / `pad_enable` 零命中，也没有任何 example 同时开
音频与 USB。P4 官方 errata 13 条里也没有 USB/GPIO 相关项。**我们是第一个在这块板上
把全速 OTG 换到 PHY0 的**。

### 🔧 修法（已实现，无需任何 Kconfig 开关）

见 `main/app_main.c`，两步：

1. **`codec_audio_init()`（I2S + 两颗 codec）排到 `tinyusb_driver_install()` 之前。**
   误伤发生时 USB 还没连主机；随后 install 内部的 `usb_new_phy()` →
   `usb_wrap_hal_init()` → `usb_wrap_ll_phy_set_defaults()` 会把 `usb_pad_enable`
   置回 1（`esp_hal_usb/usb_wrap_hal.c:11-19`）。**没有「已枚举设备被短暂拔掉」的窗口** ——
   反过来（音频在后）主机会看到一次 disconnect，GUD/HID 全部重来。
   为此 `route_fsls_phy0_to_otg()` 里提前打开了 USB_WRAP 的总线时钟
   （启动阶段 `esp_perip_clk_init()` 把它关了，对被门控外设写寄存器在 P4 上是总线错误）。
2. **install 之后跑 `otg_fsls_pads_repair()`** —— 幂等兜底，三个动作：
   `usb_pad_enable = 1`（**确认必需**，误伤的就是这一位）、
   `pad_pull_override = 0`（**保险**，防同族的 `gpio_ll_pullup_dis(G27)` 拿掉 D+ 上拉）、
   G26/G27 驱动能力从 `usb_phy.c` 抬的 CAP_3(40mA) 回默认 CAP_2(20mA)。
   它还会把进入时读到的 `usb_pad_enable` 打进日志，作为机理的现场证据。

> ⚠️ 千万别顺手去调低 **G24/G25** 的驱动能力：`usb_phy.c:309-313` 写死了 26/27、
> 从不碰 24/25，USB-C 能工作全靠这两个脚复位值本来就是 3(40mA)（TRM 第 9 章引脚表）。

> ⓘ `LP_SYS.usb_ctrl` 的 `sw_hw_usb_phy_sel` / `sw_usb_phy_sel` 在公开 TRM 里是
> **reserved**，TRM 只文档化了 eFuse 那条静态换法。我们用的是未公开的运行时路径 ——
> 能用（实机已验），但别指望 IDF 的其它部分知道我们换过。
> 另注：`usb_wrap_ll_phy_select()` 在 v5.4.3 / v5.5.1 及更早版本有 switch 漏 `break`
> 的 bug，`phy_idx=0` 是静默空操作（espressif/esp-idf#17831 修）；本工程用的 IDF v6.0
> 已含 `break`，不受影响。

### 历史：一度写在这里的**错误**机理（保留作教训）

**ESP32-P4 内部全速(FSLS) PHY 的 D−/D+ 是复用到 GPIO 上的**：

| PHY | D− | D+ | Tab5 上是谁 |
|---|---|---|---|
| PHY0 | **G24** | **G25** | USB-C（bootloader 的 USJ 与 app 的 TinyUSB 都在这里） |
| PHY1 | **G26** | **G27** | **正好是本板的 I2S DOUT 与 BCLK** |

依据（IDF v6.0 源码逐条可查，**不是推测**）：

```
components/soc/esp32p4/register/hw_ver1/soc/io_mux_reg.h:167-176
    #define USB_INT_PHY0_DM_GPIO_NUM  24      #define USB_INT_PHY0_DP_GPIO_NUM  25
    #define USB_INT_PHY1_DM_GPIO_NUM  26      #define USB_INT_PHY1_DP_GPIO_NUM  27

components/esp_hal_usb/esp32p4/usb_dwc_periph.c:31-34
    static const usb_internal_phy_io_t internal_phy_io = { .dp = 27, .dm = 26 };
  ——挂在 usb_dwc_info.controllers[1]（Full-Speed USB-DWC，即 TinyUSB 用的那个）上

components/esp_hw_support/usb_phy/usb_phy.c:308-313（注释是 IDF 原文）
    // For FSLS PHY that shares pads with GPIO peripheral, we must set drive capability to 3 (40mA)
    gpio_ll_set_drive_capability(..., internal_phy_io->dm /* G26 */, GPIO_DRIVE_CAP_3);
    gpio_ll_set_drive_capability(..., internal_phy_io->dp /* G27 */, GPIO_DRIVE_CAP_3);
```

而 `main/tab5_pins.h`：`PIN_I2S_DOUT = 26`、`PIN_I2S_SCLK(BCLK) = 27`。

**关键的一环是 `route_fsls_phy0_to_otg()` 换 PHY 是双向的**：OTG1.1 拿到
PHY0(G24/G25) 的同时，**USJ 被换到了 PHY1(G26/G27)**（见 `usb_wrap_ll_phy_select()`
的注释：`sw_usb_phy_sel = true` ⇒ *"USJ mapped to USB FSLS PHY 1"*）。
而 USJ 从 bootloader 起就是使能的（dmesg 里 `219.231` 那条 `cdc_acm` 就是它），
`CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=n` 只让**应用**不再初始化它，
**并不会关掉它已经使能的 PHY 焊盘**。

于是 `i2s_channel_init_std_mode()` 一配 G26/G27，那两个焊盘上就同时有
**USB PHY 的模拟驱动器**和 **I2S 的数字推挽输出**（驱动能力还刚被 `usb_phy.c`
抬到 CAP_3 = 40 mA）。

**这条推断已被证伪**：`CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=n` 时，IDF 在 `app_main`
之前就已经清掉了 `USB_SERIAL_JTAG.conf0.usb_pad_enable` 并门控了 USJ 的时钟 ——

```
esp_system/port/soc/esp32p4/clk.c:238-242 → esp_hal_clock/esp32p4/clk_gate_ll.h:330-336
    REG_CLR_BIT(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_USB_PAD_ENABLE);
    REG_CLR_BIT(HP_SYS_CLKRST_SOC_CLK_CTRL2_REG, ..._USB_DEVICE_APB_CLK_EN);
```

所以 PHY1 的焊盘从来没被打开过，G26/G27 上只有 I2S 一个驱动器。
顺带被证伪的还有一个候选修法：「排障时再显式调一次
`usb_serial_jtag_ll_phy_enable_pad(false)` 把焊盘让给 I2S」——**空操作**，
还多余地把 USJ 的 APB 与 48M 时钟又打开一次；它的 Kconfig 开关
（`AIO_USJ_RELEASE_PHY_PADS`）已随清理删除，别再实现第二遍。

教训：「USB 还占着焊盘」听起来天经地义，但没查 IDF 的启动路径就写进注释，
把后续三次烧板引到了错的方向。真正的机理见上面「根因（已坐实）」一节。

### ✅ 修法已实机验证

带真实引脚（G26/G27）的完整音频 + GUD + HID 一起烧上去：

| 现象 | 结论 |
|---|---|
| GUD 出图 **且** 主机出声卡 **且** 喇叭有声音、录音正常 | ✅ 实测就是这一行 —— 修法成立，排障旋钮已全部删除 |

**后手（留给日后）**：`gpio_ll_func_sel()` 的误伤是**每次**配脚都会发生的，
如果哪天有人在装完 TinyUSB 之后再动 G26/G27，`otg_fsls_pads_repair()` 就得跟着挪到那次配脚之后
（它进入时读到的 `usb_pad_enable` 会打进日志，正是用来发现这件事的）。
更彻底的做法是**绕开 `gpio_func_sel()`**：给 I2S 传 `I2S_GPIO_UNUSED`，自己写
`IO_MUX.gpio[26/27].mcu_sel = PIN_FUNC_GPIO` + `esp_rom_gpio_connect_out_signal()`，
把 IDF 那条副作用整个跳过。
**不能走的路**：不换 PHY —— USB-C 物理接在 G24/G25 上，全速 OTG 必须用 PHY0；
eFuse 换法也没用，IDF 的 `gpio_ll_func_sel()` 仍按写死的映射误伤。

### 已排除的候选（静态验算，非推测）

**数据泵在枚举完成前调 `tud_audio_*` 不会有事。** TinyUSB 0.21.0 的
`class/audio/audio_device.c` 里，三个 API 的第一行都是同一条守卫：

```c
uint16_t tud_audio_n_write(...)         { TU_VERIFY(func_id < CFG_TUD_AUDIO && _audiod_fct[func_id].p_desc != NULL); ... }  // :501
uint16_t tud_audio_n_read(...)          { TU_VERIFY(... p_desc != NULL); ... }                                              // :449
bool     tud_audio_n_clear_ep_in_ff(...){ TU_VERIFY(... p_desc != NULL); ... }                                              // :506
```

`p_desc` 只在 `audiod_open()`（即 `SET_CONFIGURATION` 解析描述符时）才被赋值，
而 `audiod_reset()`（:793，每次总线复位都会调）用 `tu_memclr(audio, ITF_MEM_RESET_SIZE)`
把它清回 `NULL`。所以在 host 完成 `SET_CONFIGURATION` 之前，这三个调用是**纯空操作**：
不解引用未初始化的 FIFO、不取任何锁（`TU_VERIFY` 只是 `if (!cond) return 0/false`，
不是 `assert`），也不会碰 TinyUSB 的任何内部状态。软件 FIFO 的缓冲区本身是
`.bss` 里的静态数组，`audiod_init()`（:677，`tud_init()` 里调）就已经 `tu_fifo_config()` 好了。

**「panic / 看门狗把板子打挂」这一整类不成立。** 本工程 `sdkconfig` 里
`CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT=y` 且 `CONFIG_ESP_SYSTEM_PANIC_REBOOT_DELAY_SECONDS=0`，
`CONFIG_ESP_INT_WDT=y`（300 ms，触发即 panic）。也就是说：**任何** panic、断言失败、
栈溢出、或连续 300 ms 关中断/跨核死锁，结果都是**立即复位**。而复位后 bootloader
阶段的 USB-Serial/JTAG 会重新枚举成 `cdc_acm ... ttyACM0`——实测 dmesg 里
`221.388` 那次 disconnect 之后**再没出现过**。所以设备既没崩也没复位，
它是「活着但 EP0 不应答」。（`CONFIG_ESP_TASK_WDT_PANIC` 未开，任务看门狗只告警。）

**内存不是根因。** 带音频的默认档实测 `idf.py size`：DIRAM 用 95690 / 576464 字节（16.6%），
**内部 RAM 还剩 480 KB**。而且 `codec_audio_init()` / `codec_audio_start()` 里每一条分配失败路径
（`i2s_new_channel` / `audio_codec_new_*` / `esp_codec_dev_new` / `xTaskCreate`）
都是 `ESP_RETURN_ON_*` 返回错误码 → 数据泵根本不会被创建 → USB 一侧毫发无损。

**`codec_audio_start()` 里没有可能永不返回的调用。** 逐个查过：

- I2C（与触摸共用 `board_i2c_bus()`）：`esp_codec_dev` 的
  `platform/audio_codec_ctrl_i2c.c` 把 `DEFAULT_I2C_TRANS_TIMEOUT` 定为 **100 ms**，
  每次 `i2c_master_transmit[_receive]()` 都带这个超时；IDF 的 `i2c_master` 驱动
  自带总线互斥锁，与 20 ms 轮询的触摸任务之间**不会互相破坏、也不会死等**
  （两边都是有限超时 + 只在一处取锁，构不成循环等待）。
- `esp_codec_dev` 的 I2S 互斥锁：`DEFAULT_WAIT_TIMEOUT` = **1000 ms**，同样有限。
- `i2s_channel_init_std_mode()` / `i2s_channel_enable()`：纯寄存器与 DMA 配置，不阻塞。

**而且即便它真的永不返回也不要紧**：`codec_audio_start()` 跑在 `app_main`（CPU0）里，
`app_main` 之后只有 `while (1) vTaskDelay(1000)`；而 TinyUSB 的任务是
`xTaskCreatePinnedToCore(..., prio 5, xCoreID = TINYUSB_DEFAULT_TASK_AFFINITY)`，
多核构建下 **`TINYUSB_DEFAULT_TASK_AFFINITY = 1`，即钉在 CPU1**
（`espressif__esp_tinyusb/include/tinyusb_default_config.h:70-85`）。
数据泵是 `xTaskCreate`（不钉核）、优先级 **4**，低于 TinyUSB 的 5，
**在任何一个核上都抢不过它**——这也说明 `2f7a6502` 那次「优先级 5→4」不可能是解药，
与实测一致。

### 已排除的候选（续：时钟 / 电源域 / GDMA，源码验算）

**I2S 不碰任何 USB 也在用的 PLL。** `I2S_CLK_SRC_DEFAULT` 在 P4 上不是 PLL：
`esp_hal_i2s/esp32p4/include/hal/i2s_ll.h:46-51` 里
`#if HAL_CONFIG(CHIP_SUPPORT_MIN_REV) >= 300` 才是 `I2S_CLK_SRC_PLL_160M`，
否则 `I2S_LL_DEFAULT_CLK_SRC = I2S_CLK_SRC_XTAL`（注释原文：*"No PLL clock source
before version 3, use XTAL as default"*）。本固件是 `CONFIG_ESP32P4_REV_MIN_100`，
**走的就是 XTAL 40 MHz 分频**（MCLK 4.096 MHz = 40 MHz ÷ 9.765625，靠 I2S 自己的
小数分频器）。APLL 也没被碰：`i2s_common.c` / `i2s_std.c` 里 `periph_rtc_apll_acquire()`
的每一处都由 `clk_src == I2S_CLK_SRC_APLL` 守着。

**没有共享寄存器被误改。** 逐个字对过 `HP_SYS_CLKRST`：

| 寄存器（32 位字） | I2S bring-up 会写 | 同字里有没有 USB 位 |
|---|---|---|
| `soc_clk_ctrl1` | `reg_ahb_pdma_sys_clk_en`（GDMA） | **有**：`reg_usb_otg11_sys_clk_en` |
| `soc_clk_ctrl2` | `reg_i2s0_apb_clk_en` | **有**：`reg_usb_device_apb_clk_en`（USJ） |
| `peri_clk_ctrl11/12/13` | I2S0 rx/tx 分频与源选择 | 无 |
| `hp_rst_en0/1/2` | `reg_rst_en_gdma` / `reg_rst_en_i2s0_apb` | 无 |

前两行虽然同字，但两边写的都是**位域读改写**（读活寄存器 → 改一位 → 写回），
顺序执行时互不破坏；而 USB 侧的写发生在 `tinyusb_driver_install()`（TinyUSB 任务，
CPU1），I2S 侧发生在之后的 `app_main`（CPU0），**不存在并发**。

> ⓘ 顺带发现一个 IDF 的潜在缺陷（与本 bug 无关，仅记录）：
> `esp_hal_usb/usb_wrap_hal.c:14-15` 调的是**下划线版**
> `_usb_wrap_ll_enable_bus_clock()` / `_usb_wrap_ll_reset_register()`，即
> **没有**套 `PERIPH_RCC_ATOMIC()`，而同文件 LL 头里白纸黑字写着
> *"…are shared registers, so this function must be used in an atomic way"*。
> 本工程里因为不并发所以没踩到。

**GDMA 通道也不是被抢走的。** P4 的全速 OTG 核是 slave-only（不吃 GDMA），
`usb_dwc_info.controllers[1]` 也没有任何 DMA 相关字段。

### 已排除的候选（续：USB 侧，`DESC_ONLY` 实测已复核这一整片）

**FIFO 与 IN 端点预算不是根因。** 按 `dcd_dwc2.c` 的 `dfifo_alloc()` 逐步验算
（rhport 0 = FS，`ep_count=7` / `ep_in_count=5` / `otg_dfifo_depth=256`，
`calc_device_grxfsiz(mps,n) = 13+1+2*(mps/4+1)+2n`）：

> ⚠️ **可分配量是 242 words，不是 256。** `dcd_dwc2.c:260-263` 在 DMA 模式下先扣
> `2 × ep_count = 14` words 作 EPInfo。本工程 `CONFIG_TINYUSB_MODE_DMA=y`（esp_tinyusb
> 的 `tusb_config.h:106` 据此定义 `CFG_TUD_DWC2_DMA_ENABLE 1`），而 P4 的
> `OTG11_ARCHITECTURE = 2` = `GHWCFG2_ARCH_INTERNAL_DMA`，两个条件都成立
> ⇒ `dma_device_enabled()` 为**真**。
> 本节此前记作「FS 核 slave-only、不扣 EPInfo」，**那是错的**，少算了 14 words。
> 音频阶段余量充裕所以没出事，但 UVC 的包大小是按这个数定的，务必用 242。

| 步骤 | 端点 | mps | `grxfsiz` | `dfifo_top` | `allocated_epin_count` | 断言 |
|---|---|---|---|---|---|---|
| `dfifo_device_init` | — | — | **62** | **242** | 0 | — |
| 同上，EP0 IN | `0x80` | 64 | 62 | **226** | **1** | `0<5` ✅ / `242≥16+62` ✅ |
| `vendord_open` | `0x01` OUT | 64 | 62（`new_sz=62`，不涨） | 226 | 1 | ✅ |
| `vendord_open` | `0x81` IN | 64 | 62 | **210** | **2** | `1<5` ✅ / `226≥16+62` ✅ |
| `hidd_open` | `0x82` IN | 64 | 62 | **194** | **3** | `2<5` ✅ / `210≥16+62` ✅ |
| `audiod_open` | `0x83` IN | 36 | 62 | **185** | **4** | `3<5` ✅ / `194≥9+62` ✅ |
| `audiod_open` | `0x02` OUT | 36 | 62（`new_sz=48<62`，不涨） | 185 | 4 | ✅ |

余量 185−62 = **123 words（492 字节）**，IN 端点 4 条 ≤ 5。**没有任何一条断言接近失败**，
但这 123 words 就是 UVC 的 ISO IN 能拿到的全部空间。
而且 `handle_bus_reset()` 与 `dcd_edpt_close_all()` 都会把 `allocated_epin_count`
清零并重跑 `dfifo_device_init()`，多次总线复位/重设配置不会累加。

再者，音频的两次分配走的是 `usbd_edpt_iso_alloc()`，`audiod_open()` **忽略其返回值**——
即便失败也不会让 `SET_CONFIGURATION` 失败；而音频接口排在 vendor/HID **之后**打开，
在机制上不可能反过来害 GUD 打不开端点。

**端点号 `0x02`(OUT) 与 `0x82`(IN) 共号也不是根因（就源码而言）。** `dcd_dwc2.c` 与
`usbd.c` 的所有端点状态都按 `[epnum][dir]` 索引：`dwc2->ep[dir][epnum]`、
`xfer_status[epnum][dir]`、`_usbd_dev.ep_status[epnum][dir]`、
`daintmsk` 的 IN/OUT 各占一半位、`depctl.tx_fifo_num = epnum` 只对 IN 生效。
唯一只按 `epnum` 索引的是 `dfifo_alloc()` 里的 `bm_double_buffered & (1<<epnum)`，
而它默认为 0（`CFG_TUD_CONFIGURE_DWC2_DEFAULT`）且只影响 bulk IN 的 FIFO 加倍。
参照实现 cardputer 用的是 `0x03`/`0x84`（不共号），但**没有找到 dwc2 禁止共号的依据**。

**`esp_codec_dev` 与 IDF `esp_driver_i2s` 的初始化路径上没有 `ESP_ERROR_CHECK` /
`abort()` / `assert()`**（已 grep 全组件），`codec_audio.c` 自己也全是
`ESP_RETURN_ON_*`。所以「codec 初始化失败 → panic → 复位循环」这条具体路径不成立
——这与上面「dmesg 里再没出现过 bootloader 的 CDC ACM」那条实测证据互为印证。

**数据泵的忙循环也已被实机排除。** `2f7a6502` 已经给错误路径补了 `vTaskDelay(10ms)`、
并把优先级从 5 降到 4，而**那份失败的 dmesg 正是在 `2f7a6502` 上抓的**。
再加上上面那条「TinyUSB 任务钉在 CPU1、优先级 5」的分析，这条线索到此为止。

---

以下为音频功能本身的设计说明。

Tab5 作为 host 的 USB 声卡：播放 host → USB → ES8388 → 板载喇叭，录音 ES7210 双麦 → USB → host，
**两个方向同时可用**。host 侧走 mainline `snd-usb-audio`，零自定义驱动。

### 参数：16 kHz / 单声道 / S16_LE，两个方向同参数

**两个方向必须同采样率**，这不是选择题：全双工的 I2S TX/RX 共用 BCLK 与 WS，
采样率、位宽、slot 数三项都得一致。要让两个方向跑不同速率就得占两个 I2S 端口，
而 Tab5 的 SCLK/LRCK/MCLK 在物理上只有一组。

**为什么是 16 kHz 单声道 —— 是 FIFO 账定的，不是听感定的。** 全速控制器整块 FIFO 只有
256 words（1 KB），要同时装下共享 RX FIFO 与每条 IN 端点的 TX FIFO：

| 方案 | OUT 包 | RX FIFO | 音频 IN 的 TX FIFO | 合计已用 | 空闲（留给 UVC） |
|---|---|---|---|---|---|
| **16 kHz 单声道（本方案）** | 36 B | **62**（不涨） | 9 | **119** | **137 words = 548 B** ✅ |
| 32 kHz 单声道 / 16 kHz 立体声 | 68 B | 64 | 17 | 129 | 127 words |
| 48 kHz 单声道 | 100 B | 80 | 25 | 153 | 103 words |
| 48 kHz 立体声 | 196 B | 128 | 49 | 225 | **31 words** ❌ UVC 没位置 |

16 kHz 单声道有一个别的档位没有的性质：**OUT 包 36 B 小于 vendor 已有的 64 B，
共享 RX FIFO 一个 word 都不涨**，整个音频功能的 FIFO 代价只有录音那 9 words。
而 FIFO 不够时 `dfifo_alloc()` 只是 `TU_ASSERT` 返回 false，**默认日志等级下一个字都不打**。

**升级阶梯**：32 kHz 单声道与 16 kHz 立体声只多吃 10 words，属于「几乎免费」的档位；
48 kHz 立体声不可行。等 UVC 的可行性结论出来之后再抬。改的是 `usb_descriptors.h` 里
`UAC_SAMPLE_RATE` / `UAC_CHANNEL_COUNT` 两个常量。

### 为什么绝不用显式反馈端点

反馈端点会多占一条 IN，正好顶掉留给 UVC 的 `0x84`（见上「端点预算」）。
16 kHz 让这件事成立：`16000 % 1000 == 0` ⇒ 每个 USB 帧**恰好 16 个样本、没有小数包**，
adaptive（播放 OUT）与 asynchronous（录音 IN）就够用。若选 44 100 Hz，就得按 9/10 的比例
交替发 44 和 45 个样本并跟踪相位漂移 —— 那才是逼人上反馈端点的场景。

`tusb_config.h` 里 `CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP` 与 `..._INTERRUPT_EP` 都**显式写 0**，
不靠默认值。异步 IN 每帧发几个样本由 `CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL` 按软件 FIFO 水位
决定（标称 ±1），这就是「异步 IN 不需要反馈」的实现基础。

> ### ⚠️ 与之配对的静默陷阱：sync 字段绝不能填 0
>
> UAC1 的 ISO 端点描述符里，`bmAttributes` 的 sync 字段填 0（`TUSB_ISO_EP_ATT_NO_SYNC`）
> 会被 TinyUSB **当成一条反馈端点**（`audio_device.c` 的 UAC1 分支就是靠
> `sync == NO_SYNC` 来判定的），数据端点从此永远发不出去 —— 而枚举一切正常。
> `test/check_usb_desc.py` 有专门一条断言守着它，另一条守着 `bSynchAddress == 0`。

### I2S 全双工的硬性要求（写错了不报错，只出噪声）

1. **TX 与 RX 必须在同一个端口，且两次 `i2s_channel_init_std_mode()` 的 `i2s_std_config_t`
   要能 `memcmp` 相等** —— 驱动靠这个判定能否共享 BCLK/WS。`codec_audio.c` 的写法是
   **两次传同一个 `const` 局部变量的地址**，让「填得不一样」在结构上就不可能发生。
2. **不一致时 P4 不报错**：只打一条 **DEBUG 级**的 `"TX & RX on I2S0 are simplex"`
   就放行，所有函数照样返回 `ESP_OK`，然后两个方向各自去驱动 BCLK/WS —— 症状是噪声或全静音。
   本工程现场没有串口，那行字谁也看不见，所以改用**读寄存器**显式判定：
   `I2S0.tx_conf.sig_loopback`（就是 `i2s_ll_share_bck_ws()` 写的那一位）必须是 1，
   为 0 就返回错误码、拒绝启动音频（host 侧表现为「声卡在但全静音」）。
3. **两个通道必须在一次 `i2s_new_channel(&cfg, &tx, &rx)` 里同时要到** —— P4 的 I2S v2 上
   分两次建会失败。
4. **不能混 STD 与 TDM**（`mode_info` 结构体对不上，直接组不成全双工）。ES7210 只有 2 只麦，
   驱动本身也是「≥3 只麦才开 TDM」，走 STD 立体声 2 slot 正合适。
5. **不能用 `I2S_SLOT_MODE_MONO`**：它会把 `slot_mask` 设成只剩左声道，**MIC2 白装**。
   线上统一走立体声 2 slot，USB 侧的单声道由 `audio_frame.c` 的纯函数转换。

### codec 接法与两个陷阱

两颗芯片与 IO 扩展/触摸同挂内部 I2C(G31/G32)，`audio_codec_i2c_cfg_t.bus_handle` 正好吃
`board_i2c_bus()` 的现成句柄，**不新建 master** —— 与 `touch_hid.c` 同一处置。

> **⚠️ 陷阱一：8 bit / 7 bit 地址。** `esp_codec_dev` 的 `.addr` 收的是 **8 bit** 形式
> （驱动内部再 `>>1`），而 `i2c_master_probe()` 收 **7 bit**。`tab5_pins.h` 里两种形式
> **分开定名**（`ES8388_I2C_ADDR7 = 0x10` / `ADDR8 = 0x20`，`ES7210_I2C_ADDR7 = 0x40` / `ADDR8 = 0x80`）。
> 混用的症状是 codec 初始化失败，或把寄存器写到别的器件上 —— 而 I2C 写没有任何反馈。
>
> **⚠️ 陷阱二：`esp_codec_dev_close()` 不会关功放。** 关流时不自己拉低 `SPEAKER_EN`
> 就会残留导通，容易有关机 pop。本阶段音频一路常开、不做关流，但这条写在 `codec_audio.c` 的注释里。

### 喇叭功放：`0x43` 的 PIN1，且必须最后开

功放使能 = **`0x43` 那颗 PI4IOE5V6408 的 PIN1**（esp-bsp 的 `BSP_SPEAKER_EN`），
**与 LCD_EN(PIN4) / TOUCH_EN(PIN5) 是同一颗**。功放**没有独立 GPIO**
（esp-bsp 的 `BSP_POWER_AMP_IO = GPIO_NUM_NC`），所以 `es8388_codec_cfg_t.pa_pin` 填 −1，
驱动内建的 PA 控制变成空操作，由 `board_speaker_enable()` 自己驱动。

上电顺序**必须**是：

```
i2s_full_duplex_init()  →  esp8388_init()（含 esp_codec_dev_open：先静音、再解除静音）
                        →  vTaskDelay(50ms)（让 DAC 输出电平稳定）
                        →  board_speaker_enable(true)   ← 最后才导通功放
```

不变式：**功放导通 ⟺ ES8388 已配置完成且已解除静音**。`board_power_init()` 只把引脚配成
推挽输出并**保持 0**，与背光的处置同构（配好但不点亮，点亮归显示域）。

> ⚠️ **esp-bsp 自己的顺序是反的**（`bsp_audio.c` 先 `bsp_feature_enable(SPEAKER)` 再配 codec），
> 本工程**刻意不照抄**。这是从代码顺序**推出**的爆音风险，上游没有已报告的 Tab5 缺陷 ——
> 若实机没听到「啪」声，也**不要**把顺序改回去，代价只是 50 ms 开机时间。
>
> 关流时必须**反序**：先 `board_speaker_enable(false)` 再 `esp_codec_dev_close()`。

### 播放音量控制：Feature Unit → ES8388 硬件音量

主机的音量键与 `alsamixer` 直接调 **ES8388 的 DAC 音量寄存器**，不是让主机在送出前
把 PCM 乘一遍。这不是锦上添花：16 bit / 16 kHz 上主机每软件衰减 6 dB 就丢掉 1 bit
有效位，衰到常用的 −30 dB 时只剩 11 bit —— 这正是「真声卡」与「USB 喇叭」的分界线。

AudioControl 的播放链因此从 `ID1(USB 流) → ID2(喇叭)` 改成
**`ID1(USB 流) → ID5(Feature Unit) → ID2(喇叭)`**，Feature Unit 声明 **Mute + Volume**
两个控制、**只在 master 通道上**（`bmaControls[0] = 0x0003`，逐通道的 `bmaControls[1] = 0`）。
两边都声明的话，`snd-usb-audio` 会**各建一个同名 mixer 控件**，第二个被自动改名成
`PCM Playback Volume,1` —— alsamixer 里出现两根一模一样的滑块。本设备是单声道，
master 一根就够。**录音侧刻意不放 Feature Unit**（录音增益本阶段不做）。

改动落点：`usb_descriptors.c` 的 `UAC1_AUDIO_DESCRIPTOR`（`ID2` 的 `bSourceID` 1→5、
AC 头的 `wTotalLength` 52→63、配置描述符 230→241 字节），
`codec_audio.c` 的 `tud_audio_get_req_entity_cb` / `tud_audio_set_req_entity_cb`。
Unit ID 取 **5** 而非插进 1..4 中间：录音侧那条 AS 接口的 `bTerminalLink` 指着 ID4，
重编号会连带动到与本次改动无关的录音链；UAC1 只要求实体 ID 在功能内唯一。

> #### ⚠️ 本功能唯一真正难的地方：两套音量刻度的换算
>
> | | 单位 | 类型 | 特殊值 |
> |---|---|---|---|
> | UAC1（host 侧） | **1/256 dB** | **有符号 16 位**，线上小端 | `0x8000` = −∞ dB（静音） |
> | `esp_codec_dev_set_out_vol()` | **0..100 百分比** | 无符号整数 | `0` 会落到 **−96 dB** |
>
> `esp_codec_dev` 的默认曲线是 `vol 0..100 → −50..0 dB`（`esp_codec_dev.c` 的
> `_get_vol_db()`），但 `vol == 0` 有一条**单独的 −96 dB 分支**，不是曲线端点。
>
> 换算写错的表现极具误导性 ——「音量条能拖但声音不跟着变」「拖到一半突然静音」
> 「方向反了」，**全都长得像 codec 或 I2C 出了问题**，而这块板现场没有串口。
> 所以换算被抽成零依赖纯函数 `main/uac_volume.{c,h}`，配宿主机测试
> `test/test_uac_volume.c`（32 用例：端点双向往返、全量百分比往返、逐 q8 值扫单调性、
> `0x8000` 特殊值、越界钳位、以及 **`−50 dB = −12800 = 0xCE00` 这类负值的字节编码**）。
>
> **MIN / MAX / RES 的取值理由**：
>
> | | 值 | 理由 |
> |---|---|---|
> | MIN | **−50 dB**（`0xCE00`） | `esp_codec_dev` 默认曲线的**下端点**。ES8388 寄存器本身能到 −96 dB，但我们只能经百分比这个入口去够它 —— 声明得比曲线宽，下半段会全部钳到 `vol=0`，症状正是「拖到一半突然静音」 |
> | MAX | **0 dB** | 曲线上端点 = 满量程。>0 dB 是数字增益，只会削顶 |
> | RES | **0.5 dB**（`128`） | 真实步进，两侧正好对上：百分比只有 101 档、跨 50 dB ⇒ 每档 0.5 dB，而 ES8388 的 `DACCONTROL4/5` 步进也恰是 0.5 dB。声明 1 dB 白丢一半分辨率；声明更细则是撒谎，host 送来的中间值会被静默吞掉 |
>
> 于是本换算与 `esp_codec_dev` 默认曲线**逐点重合**（`q8 = −12800 + 128 × percent`），
> host 看到的 dB 就是 codec 真正被设成的 dB，没有第二层隐藏映射。
> 音量条拖到底（0%）时额外落进 `esp_codec_dev` 的 −96 dB 分支，即**底端就是静音** ——
> 这是有意接受的，比停在「还能听见」更符合预期，且 Mute 是另一条独立控制。

几个不那么显眼但会出事的点：

- **`GET_MIN` / `GET_MAX` / `GET_RES` 三条都必须应答**，不是可选项：`snd-usb-audio`
  在 probe 时就把它们读齐来建 mixer 控件，任何一条 STALL 都会让**整个音量控件被丢掉**
  —— 表现是「alsamixer 里根本没有这个通道」，而不是「音量不好用」。
- **`GET_CUR` 回报 host 送来的原值**（`s_vol_q8` 存的就是原值），不是换算再反换算的结果：
  后者会在四舍五入边界上让滑块自己弹一格。
- **开机音量经同一个换算算出来**（`UAC_VOL_DEFAULT_Q8` = −15 dB = 70%），不是硬写 70：
  否则 host 枚举后第一次 `GET_CUR` 读到的音量与硬件实际状态对不上，
  滑块显示一个值、实际是另一个值，随便动一下才「对上」。
- **只应答 master 通道（`wValue` 低字节 = 0）**，其余 STALL —— 应答一个描述符里没声明过
  的通道等于对 host 撒谎，症状会推迟到某个 host 真去读它时才出现。
- 两个回调里的 `esp_codec_dev_set_out_vol/mute()` 是 **I2C 写，跑在 TinyUSB 任务上下文**
  （控制传输数据阶段），每次几百微秒。音量是人手操作、频率极低，不值当为它引一套
  异步落盘机制；但**别把同样的写法搬到高频路径上**。

### 数据泵

一个任务、每 1 ms 一转，同时搬两个方向：

```
i2s_channel_read(rx)  →  stereo_to_mono  →  tud_audio_write()      （录音）
tud_audio_read()      →  mono_to_stereo  →  i2s_channel_write(tx)  （播放）
```

**节拍源是动态的 —— 谁阻塞成功谁就是节拍**，这是「播放与录音各自降级」在泵里的落点：

| 可用的方向 | 节拍源 | 说明 |
|---|---|---|
| 录音可用 | `i2s_channel_read()` | DMA 描述符正好是 1 ms 的样本数，读满即返回，比 `vTaskDelay(1)` 更贴合 USB 帧 |
| 只有播放 | `i2s_channel_write()` | DMA 排满时它阻塞，同样是 1 ms 一拍 |
| 都不可用 | `vTaskDelay(1)` | STAGE 0 反向验证档 |

> ⚠️ **RX 读失败绝不 `continue`**。早先的版本拿 `i2s_channel_read()` 当唯一节拍源、
> 读失败就跳过整轮，于是 ES7210 一挂、完好的 ES8388 也一声不出 —— 播放被录音挟持。
> 现在读失败只是把录音缓冲清零（向 host 上报静音）并计一次数，播放照走。
> 一整轮谁都没阻塞成功时**必须**补一次 `vTaskDelay()`：那两个超时只在通道已
> RUNNING 时才真的阻塞，通道没使能时两个调用都立即返回错误，不补延时循环就退化成
> 不让出 CPU 的忙转，把同核的 idle 任务一起饿死 ——「音频没起来」会升级成「整块板子不正常」。

host 没选中某个方向时：播放侧**灌静音而不是停写**（I2S 时钟保持连续，ES8388 不会因为
BCLK 断续而「咔」一声）；录音侧清空软件 FIFO（否则下次打开会先放出一段陈旧音频）。

任务优先级 **4，低于** `TINYUSB_DEFAULT_TASK_PRIO`(5)。曾经取 5（同优先级），理由是
「绝大部分时间阻塞在 I2S 收发上」—— 那个前提在通道未进入 RUNNING 时不成立，
`i2s_channel_read()` 会立即返回错误而非阻塞满超时。USB 是这块板的命脉，
显示/键盘/触摸/音频全走它，任何情况下都不该被音频抢。欠载/溢出**只计数**，每 10 秒汇总一条
日志：1 kHz 的 `ESP_LOGW` 会自己把音频饿死，属于观测干扰被观测。

Cardputer 上那套 `AUDIO_MODE_SPEAKER/MICROPHONE` 三态仲裁**不移植** —— 那是因为它的扬声器 WS
与麦克风 PDM CLK 共用同一个 GPIO；Tab5 的 DOUT(G26)/DSIN(G28) 是两根脚，两个方向各自独立，
用两个 `volatile bool` 就够。

### 宿主机验证（烧板前必跑）

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -Werror -I../main test_audio_frame.c ../main/audio_frame.c \
   -o /tmp/ta && /tmp/ta                                   # → OK (13 cases)
cc -std=c11 -Wall -Wextra -Werror -I../main test_uac_volume.c ../main/uac_volume.c \
   -o /tmp/tv && /tmp/tv                                   # → OK (32 cases)

cd .. && . $HOME/esp/esp-idf/export.sh && idf.py build
python3 test/check_usb_desc.py build/tab5_aio.elf          # → 描述符树 + OK
```

`check_usb_desc.py` 从 ELF 里取出 `aio_desc_device` / `aio_desc_configuration` 的字节，
逐条断言并打印整棵描述符树。**这是本阶段唯一一道能在烧板前拦住错误的闸门** ——
手写描述符错一个字节的表现是「host 完全不认这个设备 / 不出 ALSA 节点」，
而现场没有串口可查；`TUD_AUDIO10_*` 宏只保证每条 item 的 `bLength`/tag 自洽，
**不校验** terminal ID 链、`wTotalLength`、`baInterfaceNr` 这些跨描述符引用。
它需要 `pyelftools`（IDF 的 python 环境自带），所以要先 `export.sh`。

断言覆盖：VID/PID 与 Misc/IAD 设备类、`wTotalLength` 与 `bNumInterfaces` 自洽、
IF0 仍是 vendor 类 / IF1 仍是 HID 类 / 三条老端点都还在、IAD 从 IF2 起覆盖 3 个接口、
AC 头的 `bcdADC`+`wTotalLength`+`baInterfaceNr`、终端 ID 链（1→5→2 播放 / 3→4 录音）、
播放侧 Feature Unit 的 `bUnitID`/`bSourceID`/`bControlSize`/`bLength` 与两个
`bmaControls`（master 必须是 Mute+Volume，逐通道那个必须为 0）、
两条 AS 各有 alt0 零带宽 + alt1 带端点、`bTerminalLink` 指向正确的终端、
两条 ISO 端点的包大小/间隔/sync 类型、**`bSynchAddress` 全为 0**、
**sync 字段全非 0**、IN 端点 ≤ 4 条且 `0x84` 未被占用、两份 Type I 格式描述符与预期参数一致。

音频是无条件编译的，所以**没有音频 IAD 本身就是一条失败**；唯一还会变的是
`CONFIG_AIO_DEBUG_CDC` 那一档，脚本按**描述符里 CDC IAD 的 `bFunctionClass`**
自动判定，不去读 `sdkconfig` —— 它只相信 ELF 里真正躺着的那串字节，这样才保得住
「独立第二意见」的性质。判定为调试档时它改为断言
**IF0 只剩 bulk OUT**（IN 端点没让干净会超编，而 `dcd_dwc2` 超编时一个字都不打）、
CDC 的 IAD/接口类/三条端点各就各位、且全部端点地址互不重复。

### Host 侧验证（上板后）

```bash
lsusb -v -d 16d0:10a9 | grep -A6 -iE "iad|audio|isochronous|synch"
cat /proc/asound/cards                  # 应出现 "Tab5 USB Terminal"
aplay -l && arecord -l                  # 各出现一个 USB Audio 设备
cat /proc/asound/card<N>/stream0        # Playback/Capture 两段：S16_LE / 1ch / 16000

# 播放
speaker-test -D hw:<N>,0 -F S16_LE -c 1 -r 16000 -t sine -f 1000 -l 3
aplay -D hw:<N>,0 --dump-hw-params -f S16_LE -c 1 -r 16000 /dev/zero
aplay -D hw:<N>,0 /usr/share/sounds/alsa/Front_Center.wav

# 录音
arecord -D hw:<N>,0 -f S16_LE -c 1 -r 16000 -d 10 /tmp/tab5.wav
sox /tmp/tab5.wav -n stat               # 安静时 RMS 低、说话时高；不能是全零或常数

# 全双工：两个终端同时跑上面的 speaker-test 与 arecord，两边都要正常
```

#### 播放音量控制（Feature Unit）

```bash
# 1) 控件存在：应出现 "PCM Playback Volume"（滑块）与 "PCM Playback Switch"（开关）
amixer -c <N> scontrols
amixer -c <N> sget PCM
#    期望：Limits: Playback 0 - 100 / dB range 从 -50.00dB 到 0.00dB / 有 [on|off]

# 2) 读写：一边放 speaker-test 一边改，声压必须**当场**跟着变
amixer -c <N> sset PCM 100%          # 满量程
amixer -c <N> sset PCM 20%           # 明显变轻
amixer -c <N> sset PCM toggle        # 静音 / 解除静音

# 3) 也可以直接按 dB 设，验证刻度对得上
amixer -c <N> -- sset PCM -15dB      # = 70%，即开机默认值

# 4) 交互式：alsamixer -c <N>，用 ↑↓ 拖 PCM，M 键切静音
alsamixer -c <N>

# 5) 桌面音量键：pactl list sinks 里选中该 sink 后按笔记本的音量加/减，
#    pactl get-sink-volume <sink> 与 amixer 读出的值要同步变化
```

**怎么确认改的是硬件音量而不是主机软件音量**（这是本功能唯一值得验的东西）：

1. **看 host 有没有在拧 PCM**：`amixer -c <N> sget PCM` 显示的是硬件控件本身；
   若它是 `[100%]` 而声音却很轻，那说明衰减发生在 PulseAudio/PipeWire 的软件混音里。
   `pactl list sinks | grep -i "volume\|flags"` 里出现 **`HW_VOLUME_CTRL`** 才是走硬件。
2. **看寄存器**（最硬的一条证据，需 `CONFIG_AIO_DEBUG_CDC=y`）：拖动音量后看
   `codec_audio_report()` 每 10 秒复读的那行 `ES8388 ... vol L/R=xx/xx` ——
   它读的是 `DACCONTROL4/5`，**必须跟着变**（值越大越轻，0x00 = 0 dB，步进 0.5 dB；
   70% ⇒ −15 dB ⇒ 0x1e）。静音时 `dacctl3` 的 bit2 置 1。
   若这两个寄存器纹丝不动而声音却变了，那就是主机在做软件音量。
3. **看设备侧的 USB 数据**：同一行日志里的 `usb_peak` 是 host 送来的 PCM 峰值。
   拖音量条时 `usb_peak` **不该变**（host 原样送出），变的只有 codec 寄存器。
   `usb_peak` 跟着音量条变 ⟹ host 在软件衰减 ⟹ Feature Unit 没被用上。

判据：`stream0` 里**不出现 `Sync Endpoint`**、`lsusb -v` 的两条 ISO 端点分别是
`Synch Type Adaptive` 与 `Synch Type Asynchronous`、`dmesg` 无 `snd-usb-audio` 报错、
无重新枚举，且 **GUD 显示 / 键盘 / 触摸全部不回归**。

> ⓘ host 侧需要 `CONFIG_SND_USB_AUDIO`（发行版一般自带 `snd-usb-audio.ko`）。
> 若 `lsusb` 看得到设备、`/proc/asound/cards` 却没有它且 `dmesg` 无音频相关行，
> 先 `modinfo snd-usb-audio` 确认模块存在 —— 那是 host 内核配置问题，不是固件缺陷。

### `CONFIG_AIO_DEBUG_CDC`：拿 GUD 的 IN 端点换一条 USB 日志串口

这块板现场没有可用串口：UART0 只在 M5-Bus 排针上（要外接 USB-TTL），
USB-Serial/JTAG 被 TinyUSB 收走。于是音频排障长期只能盲二分，每切一刀烧一次板。
`CONFIG_AIO_DEBUG_CDC`（menuconfig → Tab5 All-in-One）用一次**可逆的端点交换**
换来 `ESP_LOG*`：

| | 0x81 | 0x82 | 0x83 | 0x84 |
|---|---|---|---|---|
| 正常档 | vendor(GUD) | HID | UAC 录音 | 留给 UVC |
| **调试档** | **CDC 数据** | HID | UAC 录音 | **CDC 通知** |

**GUD 不需要 IN 端点** —— 这是这条路成立的全部依据：mainline
`drivers/gpu/drm/gud/gud_drv.c` 的 `gud_probe()` 只调一次
`usb_find_bulk_out_endpoint()`，全驱动没有 `usb_find_bulk_in_endpoint` /
`usb_rcvbulkpipe`（协议本身是「EP0 控制请求 + bulk OUT 送像素」的单向结构）；
本固件 `gud_device.c` 也只有 rx 侧，从不调 `tud_vendor_write()`。
TinyUSB 侧同样没问题：`vendord_open()` 按描述符里实际出现的端点逐条 open，
只有 OUT 时就只开 `rx_stream`（`vendor_device.c:296-332`）。
所以 `0x81` 一直是 `TUD_VENDOR_DESCRIPTOR` 顺带声明出来的、**从未通过流量**的端点。

FIFO 也够：256 words 的 dfifo 依次扣 EP0(16) + HID(16) + 音频 IN(9) +
CDC 通知(16) + CDC 数据 IN(16) = 73，余 183 ≫ `grxfsiz` 62；
IN 端点连 EP0 共 5 条，恰好等于 `ep_in_count`，`dcd_dwc2.c` 的
`TU_ASSERT(allocated_epin_count < ep_in_count)` 每一步都成立。

```bash
idf.py menuconfig      # Tab5 All-in-One → 打开 CONFIG_AIO_DEBUG_CDC
idf.py build flash monitor

# 或：取消 sdkconfig.defaults 末尾 `#CONFIG_AIO_DEBUG_CDC=y` 的注释，再
rm -f sdkconfig && idf.py build flash monitor
```

⚠️ **排障档，不是产品档**：它占了留给 UVC 的 `0x84`，4 条 IN 端点用满。
查完就关掉。GUD 显示 / 键盘 / 触摸 / 音频在这一档下全部照常工作。

#### 日志里该看哪几行

`codec_audio_init()` 必须跑在 `tinyusb_driver_install()` 之前（焊盘那个坑），
而 CDC 要等 install 之后才起得来 —— 也就是说**音频最关键的那几行日志天生打不出来**。
所以 `codec_audio.c` 把 init 阶段的每个判定记成静态快照，由 `codec_audio_report()`
在启动末尾补打一遍。

**复读只在本档下发生**：CDC 的 TX 环形缓冲会把 host 打开 `ttyACM` 之前的内容覆盖掉，
只打一遍现场大概率什么都看不到，所以 `app_main` 主循环里那次每 10 秒的复读被
`#if CONFIG_AIO_DEBUG_CDC` 圈住。默认档日志走 UART0（终端有回滚、不会被覆盖），
打一遍就够 —— 每轮复读要做十几次 I2C 寄存器回读，而那条内部总线还挂着触摸、
IO 扩展与 IMU，没必要长期占着。

```
codec_audio: [自检] I2S=ESP_OK duplex=1 | 播放 ES8388=ESP_OK open=ESP_OK | 录音 ES7210=ESP_OK open=ESP_OK | pa=1 pump=1
codec_audio: [自检] ES7210 probe(0x40)=ESP_OK 卡在=完成
codec_audio: [自检] ES8388 chippwr=00 dacpwr=3c dacctl3=00 vol L/R=1e/1e LOUT1/ROUT1=1e/1e LOUT2/ROUT2=00/00
codec_audio: [自检] ES7210 mic1gain=.. mic2gain=.. mic12pwr=..
codec_audio: [自检] 泵 帧=... spk_on=1 mic_on=0 usb_peak=8123 mic_peak=37
codec_audio: 10s 泵：spk_on=1 mic_on=0 usb_peak=8123 mic_peak=37 | TX 欠载 0 麦 FIFO 溢出 0 RX 读失败 0
```

⚠️ **播放与录音是两条互不牵连的链路**：第一行里 `播放 ES8388=…` 与
`录音 ES7210=…` 各报各的，一边失败另一边照常工作（ES7210 挂 ⇒ 录音上报静音、
播放正常；ES8388 挂 ⇒ 播放丢数据、录音正常）。只有 `I2S!=ESP_OK` 才两边一起放弃。

⚠️ 「没跑过」打成 **`未运行`**，绝不打成 `-1`：`ESP_FAIL` 与
`ESP_CODEC_DEV_DRV_ERR` **都等于 −1**，用 −1 当哨兵会让「那一步没跑」与
「那一步真的返回了 DRV_ERR」在日志里长得一模一样。

从上往下读，**第一条不对的就是根因**：

| 现象 | 结论 |
|---|---|
| `I2S!=ESP_OK` / `duplex=0` | I2S 没起来或没组成全双工（两次 `init_std_mode` 的 `std_cfg` 不相等）⇒ 两个方向都没戏，先修它 |
| `录音 ES7210` 非 `ESP_OK`，且 `probe(0x40)=ESP_OK` | 芯片在总线上、应答正常 ⇒ 罪在驱动侧，看 `卡在=` 那一句 |
| `probe(0x40)=ESP_ERR_NOT_FOUND` | 芯片**不应答** ⇒ 查供电(AUDIO_VDD)/走线，别再查驱动。地址本身已核实：原理图 U13 的 AD0/AD1 双双接 AGND ⇒ 7 bit `0x40` |
| `卡在=esp_codec_dev_open` | 罪在「拿 RX 去 reconfig 一条已经在跑的全双工 I2S」这一步，不是 codec 本身 |
| ES8388 寄存器全打成 `ffffffff` | 回读失败 ⇒ I2C 根本没通（地址 / 总线 / 上电） |
| `dacpwr!=3c` 或 `dacctl3` 的 bit2=1 | DAC 没上电 / 还在静音 |
| `pa=0` | 功放没导通（ES8388 没起来，或 IO 扩展写失败）。**与 ES7210 无关** |
| `pump=0` / `帧=0` | 数据泵任务没起来。帧数**无条件**递增，所以这条不再会被「RX 一直读不到」冒充 |
| `spk_on=0` | **host 从没把播放接口切到 alt 1** ⇒ 问题在主机侧（没选对声卡 / 没在放音），不在固件 |
| `spk_on=1` 但 `usb_peak=0` | host 选了接口却只送静音 |
| `usb_peak>0` 却仍没声 | 数字侧全通，问题在 codec 之后的模拟侧（音量 / 路由 / 功放 / 喇叭） |
| `RX 读失败` 一直在涨 | 只影响录音。数据泵的节拍源会自动落到 `i2s_channel_write()` 上，**播放不受连累** |

`mic_peak` 是**无条件**统计的（host 没开录音时也统计），所以它单独回答
「ES7210 到底有没有在往 DSIN 上送东西」。

#### 关掉调试档之后

不接 UART0 时，这一段仍然是盲的（自检快照只在启动时打一遍，且没有出口）。
三条缓解照旧成立：

1. codec 初始化失败只会让音频降级，但**描述符是静态的**，host 侧照样枚举出声卡
   —— 「有声卡但全静音」本身就是一条 host 侧信号；
2. 全双工是否成立由读寄存器显式判定，不靠日志；
3. 真要抓上电最早那一段（CDC 也抓不到），接 UART0(G37/G38)。


## 文件

| 文件 | 职责 |
|------|------|
| `main/app_main.c` | 编排：board_power → display → gud → TinyUSB 安装 |
| `main/usb_descriptors.{c,h}` | USB 复合描述符数据（IF0 GUD vendor + IF1 HID 键盘 RID1 / 多点触摸 RID2 + IF2-4 UAC1 音频 + IF5/6 CDC 排障串口，最后一段受 `CONFIG_AIO_DEBUG_CDC` 控制）、UAC 参数常量与端点账 |
| `main/gud_protocol.h` | GUD 协议定义（vendor 自内核 6.8） |
| `main/gud_device.{c,h}` | GUD 控制协议状态机 + 收帧（脏矩形累积 / LZ4 解压）→ `display_blit()` |
| `main/lz4.{c,h}` | 官方 LZ4 v1.9.4 参考实现（BSD-2-Clause），仅用 `LZ4_decompress_safe` |
| `main/display_dsi.{c,h}` | 显示 HAL：LDO + DSI + 面板探测/初始化 + PPA 缩放旋转 + 待机画面上屏/动画任务 + 背光点亮 |
| `main/standby_screen.{c,h}` | 待机画面（`NO SIGNAL`）的绘制原语与版式，零依赖纯函数（宿主机可渲染预览） |
| `main/font8x16.h` | Spleen 8×16 点阵字体，ASCII 0x20-0x7E（vendor 自 fcambus/spleen，BSD-2-Clause） |
| `test/test_standby_screen.c` | 待机画面宿主机回归测试 + PPM 版式预览（直接编译真实源码，非复制体） |
| `main/panel_init_data.h` | 两种批次的面板 init 命令序列（vendor 自 esp-bsp，Apache-2.0） |
| `main/board_power.{c,h}` | 内部 I2C 总线 + PI4IOE5V6408 上电时序 + 背光开关 + 喇叭功放开关 |
| `main/kbd_i2c.{c,h}` | 键盘 I2C 总线 + G50 中断 + 事件排空 + HID 上报（Normal 模式） |
| `main/kbd_translate.{c,h}` | 按下集合 → HID modifier/keycode 分层翻译，零依赖纯函数（宿主机可测） |
| `main/tab5_kbd_map.h` | 行列 → HID usage 映射表（vendor 自 M5 官方固件，MIT） |
| `test/test_kbd_translate.c` | `kbd_translate()` 宿主机回归测试（直接编译真实源码，非复制体） |
| `main/touch_hid.{c,h}` | GT911 初始化（INT 拉低 + 备用地址 `0x14`）+ 20ms 轮询 + digitizer 上报（RID 2） |
| `main/touch_map.{c,h}` | 面板坐标 → GUD 坐标反变换 + HID 归一化 + 报告装填，零依赖纯函数（宿主机可测） |
| `main/Kconfig.projbuild` | 只剩 `CONFIG_AIO_DEBUG_CDC`（默认 n，让出 GUD 的 IN 端点换 USB 日志串口）；音频无条件编译，排障旋钮已删除 |
| `main/codec_audio.{c,h}` | ES8388/ES7210 初始化 + I2S 全双工 + UAC 数据泵 + TinyUSB 音频类回调（含 Feature Unit 的音量/静音落到 ES8388 硬件）+ `codec_audio_report()` 开机自检快照 |
| `main/audio_frame.{c,h}` | USB 单声道 ↔ I2S 立体声转换，零依赖纯函数（宿主机可测） |
| `main/uac_volume.{c,h}` | UAC1 音量(有符号 1/256 dB) ↔ `esp_codec_dev` 百分比 的换算 + 线上小端编解码，零依赖纯函数（宿主机可测）；含 MIN/MAX/RES 取值理由 |
| `test/test_uac_volume.c` | 音量换算的宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tinyusb_config/tusb_config.h` | `include_next` esp_tinyusb 默认配置后追加 `CFG_TUD_AUDIO_*`（它没开放 Audio 类） |
| `test/test_touch_map.c` | 触摸坐标变换与报告装填的宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tab5_pins.h` | 板级 GPIO / 面板与 GUD 尺寸常量（含放大倍数的静态断言） |
| `sdkconfig.defaults` | 目标/PSRAM/分区/控制台/vendor 类、芯片版本互斥的说明，以及末尾默认注释掉的 CDC 调试串口开关 |
| `partitions.csv` | factory 分区 4 MB |
| `main/idf_component.yml` | 依赖精确锁版：esp_tinyusb / tinyusb / io_expander / 两个面板驱动 / esp_codec_dev |

设计与路线：见仓库
`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` 与
`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`。
