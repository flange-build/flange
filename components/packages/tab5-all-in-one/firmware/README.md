# Tab5 AIO 固件（ESP32-P4）

M5Stack Tab5 作为 **USB 设备**，让嵌入式 Linux 主机把它当成一块标准 DRM 显示器
（mainline `gud` 驱动，`/dev/dri/cardN`）。host 送来的 **640×360 RGB565** 帧经 ESP32-P4 的
PPA（Pixel Processing Accelerator，像素处理加速器）**2× 放大 + 90° 旋转**，铺满板载的
720×1280 MIPI-DSI 面板。同一个复合设备上还带 **HID 键盘**（Tab5 Keyboard）与
**HID 多点触摸**（GT911，与键盘共用同一个 HID 接口、靠 Report ID 区分）与
**UAC1 全双工音频**（ES8388 出喇叭 / ES7210 双麦录音，16 kHz 单声道，
带**播放音量/静音的硬件控制**，✅ **播放与录音均已实机验证**，见下文）
与 **UVC 摄像头**（SC202CS 经 MIPI-CSI + ISP + 硬件 JPEG，**MJPEG 640×360 @ 10 fps**，
✅ **出真实画面已实机验证**；⏳ 自动白平衡闭环未上板，见下文）。

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
  - **IF5/IF6 UVC 摄像头**：VideoControl（`bNumEndpoints = 0`）+ VideoStreaming
    （alt 0 零端点 / alt 1 一条 ISO IN `0x84` × 448 B），由 IAD 成组，
    host 侧走 mainline `uvcvideo`，零自定义驱动。**只声明一个格式/分辨率/帧率：
    MJPEG 640×360 @ 10 fps**。SC202CS → MIPI-CSI(RAW8 1280×720@30) → ISP 去马赛克
    → PPA ×0.5 → 硬件 JPEG(4:2:2)。**未打开时严格零占用**（alt 0 不预留带宽，
    固件侧连 CSI 都不启动）。详见下文「UVC 摄像头」。
  - 设备描述符为 Misc/IAD 复合设备。**4 条可用 IN 端点已全部用满。**
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

### ⚠️⚠️ ESP32-P4 rev <3.0 已知**不可用**的硬件功能

> **这个坑已经咬了四次**（烧录被拒 → CSI 桥 → JPEG 输入格式 → ISP 的 WBG），
> 所以单列一节集中记录。共同的症状模式是：**IDF 的例程、文档、头文件都写着有，
> 编译也过，运行时才报 `ESP_ERR_NOT_SUPPORTED`；更坏的是有些不报错，只是静默不生效。**
> 排查任何「照 IDF 例程写却不工作」的外设时，**先回来看这张表**。

机理是统一的：IDF 的 LL 层大量用 `#if HAL_CONFIG(CHIP_SUPPORT_MIN_REV) >= 300`
把功能圈起来，rev <3.0 编到的是 `#else` 分支 —— 有的分支是**空函数**（硬件上就没有那个块），
有的是运行时查芯片版本后返回错误。

| 功能 | rev <3.0 下的实际状态 | 出处与后果 |
|---|---|---|
| **烧录** | IDF v6.0 默认最低支持 **v3.1**，直接拒绝 | 不加 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` + `CONFIG_ESP32P4_REV_MIN_100=y` 就烧不进去（见上一节） |
| **CSI 桥的颜色转换** | ❌ **硬件上没有这个块** | `mipi_csi_ll.h:159/292` 那对 `#if ... >= 300`，`#else` 分支里桥的五个颜色模式 LL 函数**全是空实现**。而 `esp_cam_new_csi_ctlr()` 内部就会调 `s_csi_ctlr_format_conversion()`（`esp_cam_ctlr_csi.c:226`），只要 `input != output` 就在 `:604-608` 查版本并拒绝 ⇒ **`ESP_ERR_NOT_SUPPORTED`，连控制器都建不出来**。⇒ IDF 例程 `examples/peripherals/camera/mipi_isp_dsi` 那份 `RAW8→RGB565` 的 CSI 配置**只适用于 rev ≥3.0，不能照抄**。**解法：CSI 的 input/output 都填 RGB565（桥直通旁路），去马赛克整个交给 ISP** |
| **硬件 JPEG 编码器的 YUV420 / YUV444 输入** | ❌ 不支持 | `esp_driver_jpeg/jpeg_encode.c:186-198` 的 `#if !(CONFIG_ESP_REV_MIN_FULL < 300 && SOC_IS(ESP32P4))`。可用输入只剩 **RGB888 / RGB565 / GRAY / YUV422** ⇒ 本工程选 RGB565 输入（正好是 PPA 的输出色彩模式） |
| **ISP 的 WBG（白平衡增益）、BLC、crop** | ❌ 不可用（均要 rev ≥3.0） | ⇒ **白平衡只能改用 CCM**（色彩校正矩阵）来做，见下文「UVC 摄像头 / 白平衡」。官方标定的 `acc.blc = 16/255` 在本板没有任何 ISP 侧执行点 ⇒ 官方算法给出的 `IPA_METADATA_FLAGS_BLC` 只能忽略（处置与官方 `esp_video` 的 `#if ESP_VIDEO_ISP_DEVICE_BLC` 同构）。SC202CS 传感器自带 BLC（寄存器 `0x3902`，`0xc0` = 开）是另一条独立的路，本工程**只读不写**、把读数打进自检行。⏳ **基座实测值尚未取得** |
| **ISP 的 CCM** | ✅ 可用，但**系数上限 4.0** | rev <3.0 的 CCM 系数是 **2 位整数 + 10 位小数**；rev ≥3.0 才是 4 位整数 + 8 位小数（上限 16）。⚠️ **不要贴着 4.0 写**：驱动的范围检查是**闭区间** `[-4.0, +4.0]`（`isp_ccm.c:25-31`），而 S2.10 实际能表达的最大值是 `4095/1024 = 3.9990` ⇒ 恰好写 4.0 会**通过**驱动检查，然后在 HAL 里被 `saturation = true` **悄悄截断且不报错** —— 硬件里的矩阵与日志打出来的不是同一个。本工程把矩阵交给官方算法给出，下发时显式传 `.saturation = true`（越界饱和而不是整个拒绝：配失败 = 一点白平衡都没有，比略微不准坏得多） |
| **ISP 的 AWB 统计** | ✅ **可用** | 曾经误记为「有版本门」。实际 `isp_awb.c` 只有 **subwindow 子功能**要 rev ≥3.0，且那里只 `ESP_LOGW` 一条警告，不失败 |
| **ISP 的去马赛克 / `esp_isp_new_processor` / `enable`** | ✅ 可用，**一概无版本门** | `isp_ll.h:473-478`：把 ISP 输出设成 `ISP_COLOR_RGB565` 会顺手打开 `demosaic_en` |
| **ISP 的 LSC** | ✅ 可用，**已使用**（⏳ 未上板验证） | 版本门是 rev ≥ **1.00**（`isp_lsc.c:58`），而 `ESP_CHIP_REV_ABOVE(min, rev)` 展开成 `min <= rev`（`soc/chip_revision.h:31`）⇒ v1.0 恰好过。本工程已配：**273 格（21×13）× 4 通道**暗角修正表，档位与内容由官方 `esp_ipa` 经 `IPA_METADATA_FLAGS_LSC` 给出。两条顺序硬要求：`esp_isp_lsc_allocate_gain_array()` 要求 `lsc_fsm == INIT` ⇒ **必须排在 `esp_isp_lsc_enable()` 之前**；`esp_isp_lsc_configure()` 反而**没有** FSM 门 ⇒ 取流中可重配（按 CCT 换档依赖这一点） |

## 构建 / 烧录

```bash
. $HOME/esp/esp-idf/export.sh
idf.py set-target esp32p4         # 首次
idf.py build
```

**开箱即用**：`sdkconfig.defaults` 已经把所有必需项写全（芯片版本、控制台、PSRAM、
分区表、TinyUSB 类计数、codec 裁剪、`esp_cam_sensor` 只留 SC202CS 一个模式），
`rm -f sdkconfig && idf.py build` 直接产出
**GUD + HID + UAC1 音频 + UVC 摄像头**的可用固件，不需要任何旁路 conf 文件。
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
**默认档（GUD + HID + 音频 + UVC）384 字节 / 7 接口，
调试档（GUD + HID + UVC + CDC，无音频）259 字节 / 6 接口**。

也可以直接在 `sdkconfig.defaults` 末尾把 `#CONFIG_AIO_DEBUG_CDC=y` 那一行的注释取消，
再 `rm -f sdkconfig && idf.py build`（`sdkconfig.defaults` 只在生成 `sdkconfig` 时读一次）。

#### ⚠️ 代价：让出 GUD 的 IN 端点 + **整个音频功能不编译**

| 用途 | 正常档 | 调试档 |
|---|---|---|
| vendor(GUD) | OUT `0x01` / IN `0x81` | OUT `0x01`（**没有 IN**） |
| HID（键盘 + 触摸） | IN `0x82` | IN `0x82` |
| UAC 播放 / 录音 | OUT `0x02` / IN `0x83` | **整体不编译** |
| **UVC 视频流** | IN `0x84` | IN `0x84`（**同一条，不变**） |
| CDC 通知 / 数据 | — | IN `0x83` / OUT `0x03` + IN `0x81` |

> ⚠️ **这一档的代价在 UVC 落地后变了。** 它原先是「借走 UVC 预留的 `0x84`」——
> UVC 真的占上之后两者直接撞号，而这块板现场没有别的日志通道。
> 现在改成 **`AIO_HAS_AUDIO` 由 `CONFIG_AIO_DEBUG_CDC` 反相定义**：
> 开调试档 ⇒ `codec_audio.*` 整体不编译，腾出的那条 IN 端点给 CDC，
> **`0x84` 永久归 UVC、绝不出借** —— 因为摄像头 bring-up 恰恰是最需要日志的那一段。
> 编译期有 `#if CONFIG_AIO_DEBUG_CDC && AIO_HAS_AUDIO` 的 `#error` 守着。

**这一档下失去的能力**：

| 失去的 | 严重度 | 说明 |
|---|---|---|
| **全部音频**：喇叭播放、双麦录音、`alsamixer` 音量 | 高 | host 侧 `/proc/asound/cards` 里**没有**这块设备。ES8388/ES7210 不初始化，功放不导通 |
| vendor(GUD) 的 IN 端点 `0x81` | **无** | `drm/gud` 从不使用它（依据见下），显示照常 |
| 开机最早那几行日志 | 中 | CDC 的 TX 环形缓冲要等 host 打开 `ttyACM*` 才开始流 |
| 再加任何 USB 功能的余地 | — | 4 条 IN 用满 |

**保留的**：GUD 显示、HID 键盘、HID 多点触摸、**UVC 摄像头**。

> 💡 **有 USB-TTL 的话，优先接 UART0(G37/G38)**：零端点代价、能抓上电最早的日志、
> **默认档（音频在）也能用**。CDC 调试档是「手边只有一根 USB-C 线」时的替代品。

**去掉 vendor 的 IN 端点为什么安全**：mainline `drivers/gpu/drm/gud/gud_drv.c` 的
`gud_probe()` 只调一次 `usb_find_bulk_out_endpoint()`，全驱动没有
`usb_find_bulk_in_endpoint` / `usb_rcvbulkpipe` —— GUD 协议是「EP0 控制请求 +
bulk OUT 送像素」的单向结构；本固件 `gud_device.c` 也只有 rx 侧，从不调
`tud_vendor_write()`。TinyUSB 的 `vendord_open()` 按描述符里实际出现的端点逐条 open
（`vendor_device.c:296-332`），只有 OUT 时就只开 `rx_stream`。
`0x81` 一直是 `TUD_VENDOR_DESCRIPTOR` 顺带声明的、**从未通过流量**的端点。

FIFO 也够（**分母是 242 words 不是 256**，见「端点预算」）：RX 62 + EP0 16 +
`0x81` CDC 数据 IN 16 + `0x82` HID 16 + `0x83` CDC 通知 **2** + `0x84` UVC 112
= **已用 224，空闲 18** —— 比默认档（231 / 11）还宽裕 7 words。
IN 端点连 EP0 共 5 条，恰好等于 `ep_in_count`，`dcd_dwc2.c` 的
`TU_ASSERT(allocated_epin_count < ep_in_count)` 每一步都成立。

> 此处两处旧账已订正：① 曾按「vendor/CDC 数据各 32」记，那是假设 bulk IN 开了双缓冲，
> 实测 `_tud_cfg.bm_double_buffered` 保持默认 0、`tud_configure()` 从未被调用，故各 16；
> ② 曾把 **CDC 通知记成 16 words**，实际它的 `wMaxPacketSize` 是 **8** ⇒ `ceil(8/4) = 2 words`。
> 两处都只让余量更大，不影响任何结论。

> ⚠️ **直接开 `CONFIG_TINYUSB_CDC_ENABLED` 仍然是编译期错误。**
> esp_tinyusb 默认给 CDC 的端点就是 `0x83`/`0x84`，与 UAC 录音、UVC 预留直接撞号，
> 而且不让出 vendor 的 IN 就会超编 —— `dcd_dwc2` 超编时**一个字都不打**，
> 症状是某个接口静默不工作。`usb_descriptors.h` 的 `#error` 会把你导向
> `CONFIG_AIO_DEBUG_CDC`，那一档已经把端点号重排好了。

**这是排障设施，不是产品特性。** 定位完就关掉 —— 它让整个音频功能不编译。

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

### 端点预算（**已 4/4 用满**）

P4 全速控制器（tinyusb `dwc2_esp32.h`）：`ep_count = 7`、`ep_in_count = 5`（含 EP0），
即**最多 4 条可用 IN 端点**。UVC 落地后**四条全部用尽，不得再加任何 USB 功能**。

正因为一开始就知道会用满，**触摸与键盘才合并在同一个 HID 接口**上、用 Report ID 区分
（RID 1 键盘 / RID 2 digitizer），触摸没有新增任何端点（见下文「HID 多点触摸」）；
音频也**坚决不用显式反馈端点**（见下文「UAC1 全双工音频」）—— 那一条要留给 UVC，
**而 UVC 已经如约用上了它**。

| 端点 | 归属 | 类型 |
|---|---|---|
| `0x01` / `0x81` | vendor(GUD) | bulk OUT / IN |
| `0x82` | HID（键盘 + 触摸） | 中断 IN |
| `0x02` | UAC 播放 | 等时 OUT（adaptive） |
| `0x83` | UAC 录音 | 等时 IN（asynchronous） |
| `0x84` | **UVC 视频流**（448 B/帧） | 等时 IN（asynchronous） |

接口布局：IF0 vendor(GUD) / IF1 HID / IF2–IF4 UAC1 / **IF5–IF6 UVC**，
默认档 **7 接口 / 384 字节**配置描述符。

#### ⚠️ FIFO 可分配的是 **242 words，不是 256**

`dcd_dwc2.c` 的 `dfifo_device_init()` 在 **buffer DMA 模式**下先扣一笔：

```c
_dcd_data.dfifo_top = dwc2_controller->otg_dfifo_depth;   /* 256 */
if (is_dma) {
    _dcd_data.dfifo_top -= 2 * dwc2_controller->ep_count;  /* −2×7 = −14 */
}
```

`is_dma` 的两个条件本工程**都成立**：`CFG_TUD_DWC2_DMA_ENABLE=1`（由
`CONFIG_TINYUSB_MODE_DMA=y` 门控，默认值从未改过）、且 P4 OTG1.1 的
`ghwcfg2.arch == 2`（internal DMA）。⇒ **可分配上限 242 words。**

| 项 | wMaxPacketSize | words |
|---|---|---|
| RX FIFO（所有 OUT 共享） | 最大 OUT 包 = vendor 的 64 | 62 |
| EP0 IN | 64 | 16 |
| `0x81` vendor bulk IN | 64 | 16 |
| `0x82` HID 中断 IN | 64 | 16 |
| `0x83` UAC 录音 ISO IN | 36 | 9 |
| **`0x84` UVC 视频 ISO IN** | **448** | **112** |
| **合计 / 余量** | | **231 / 11** |

**为什么 UVC 端点取 448 而不取满 492**（余量原本是 `242 − 119 = 123` words）：

1. `dfifo_alloc()` 失败只是 `TU_ASSERT` 返回 false，**一个字都不打日志**；
2. 448 在 `is_dma` 真/假**两种假设下都装得下**（slave 模式余量 137 words）。
   取 492 则只在 DMA 模式下「碰巧够用」，有人改成 slave 模式就炸；
3. 代价只有 9% 带宽（446 vs 490 B/ms 有效载荷），而 640×360 @ 10 fps 上有
   1.5–2.6 倍余量，买得起。

**实测已证实这笔账**：`EP4 IN=112 words` 那一行在启动日志里如期出现，且
**枚举时就分配好了，不等 host 选 alt 1**（见下文「UVC 摄像头 / ISO FIFO 在
`SET_CONFIGURATION` 就分配」）。调试档另测到 224/242 与 242 的口径一致。

> 要 USB 日志串口请开 **`CONFIG_AIO_DEBUG_CDC`**（排障档）。⚠️ **它的语义已经变了** ——
> 现在是「**整个音频功能不编译**，换出一条 IN 端点给 CDC」，`0x84` **永久归 UVC、不再出借**。
> 有 USB-TTL 时**优先接 UART0(G37/G38)**：零端点代价、能抓上电最早的日志、默认档也能用。
> 直接开 `CONFIG_TINYUSB_CDC_ENABLED` 仍是编译期 `#error`。见下文「日志」章节。

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

**⏳ 待实测** —— 此处不填任何数字，以免把估算当成实测。

**测法已经写成可执行的规程**，见文末「**五项能力复合回归规程**」的步骤 A / B ——
它同时量三件事，不要拆开跑：

- **场景 A（帧率下限，摄像头关）**：`videotestsrc` 全屏动态内容（几乎每帧整帧脏区），
  用 `fpsdisplaysink` 读 average fps ⇒ `fps_A`；
- **场景 A′（帧率下限，摄像头开）**：同样的压测，同时跑 UVC ⇒ `fps_B`。
  **`fps_B / fps_A` 是「打开摄像头会让显示明显变慢（−33%）」那条推算唯一能被证实或
  证伪的地方**，期望 ≈ 0.67；
- **场景 B（实际体感）**：把文本终端绑到 GUD 卡后跑 vim/htop，记录打字与滚动的跟手程度
  （「打字无感延迟 / 滚动可见撕裂」这类描述），这才是「USB 瘦终端」的真实使用场景。

同一场里还要顺带确认 `LZ4 解压失败` / `ppa srm 失败` 均为 **0 条**（P0 欠账）。

## 资源占用（实测，`idf.py size` @ `c844d908`，IDF v6.0.2）

**默认档**（GUD + HID + UAC1 音频 + UVC 摄像头，7 接口）：

| 项 | 值 |
|---|---|
| Flash | **418,986** 字节（约 409 KB），占 4 MB factory 分区 **10%** |
| 内部 DIRAM | **97,260** 字节（**16.87%**），剩余 **479,204** 字节（约 468 KB） |
| 镜像总大小 | 505,534 字节（`.bin` 为 505,904，另有 padding） |

**UVC 调试档**（`CONFIG_AIO_DEBUG_CDC=y`：**没有音频**，GUD + HID + UVC + CDC，6 接口）：

| 项 | 值 |
|---|---|
| Flash | **352,018** 字节 |
| 内部 DIRAM | **95,980** 字节（**16.65%**），剩余 480,484 字节 |
| 镜像总大小 | 436,034 字节（`.bin` 为 436,400） |

> ⚠️ **调试档比默认档更小**（Flash −66,968），因为它把整个音频功能编译掉了 ——
> 音频那一笔本身就有 7 万多字节。**别拿它当「加了功能反而变小」的怪事看。**

**P4 阶段（UVC + 摄像头）的增量：Flash +62,520 / DIRAM +1,566**
（相对 P3 结束时的 356,466 / 95,694）。其中 CCM + AE 那次是 Flash +4,738 / DIRAM +80，
AWB 闭环那次是 Flash +1,772 / DIRAM +68，**PSRAM ±0** —— 大头是新链接进来的
`esp_driver_cam` / `esp_driver_isp` / `esp_driver_jpeg` 与 `esp_cam_sensor` 的寄存器表。
10% 的占用离 4 MB 分区还很远，不做进一步瘦身。

早先几个阶段的增量（保留作对照）：播放音量控制 **Flash +502 / DIRAM +4**；
UAC1 音频 **Flash +77,608 / DIRAM +4,370**（几乎全在三个新链接的库上：
`esp_driver_i2s` 22.9 KB + `esp_codec_dev` 16.2 KB + `esp_hal_i2s` 5.4 KB，
其余是 TinyUSB 的 audio class；`esp_codec_dev` 已裁到只剩 ES8388 与 ES7210 两颗）。

### PSRAM（大块缓冲全在这儿，不占内部 RAM）

| 用途 | 大小 |
|---|---|
| GUD 收帧缓冲（未压缩 + 压缩各一份，每份 `640×360×2`） | 2 × 460,800 = 921,600 |
| DPI 帧缓冲 `720×1280×2` | 1,843,200 |
| **CSI 帧缓冲 3 × `1280×720×2`** | **5,529,600** |
| **PPA 缩放输出 `640×360×2`**（cache line 对齐） | **460,800** |
| **JPEG 输出双缓冲 2 × `UVC_MAX_FRAME_BYTES`** | **131,072** |
| 合计 | 约 **8.5 MB** / 32 MB |

待机画面另临时占一份 460,800 字节，blit 完即释放；等待点动画常驻 3 KB（`48×32×2`），
收到第一帧后一并释放。字体 1520 字节在 flash（`.rodata`）。

> 摄像头那三项（≈6.1 MB）**即便没人打开摄像头也一直占着** —— 启动时一次建好，
> 为的是分配失败在开机日志里立刻可见。32 MB PSRAM 付得起，而**带宽代价为零**
> （alt 0 时不取流/不缩放/不编码），理由见「UVC 摄像头 / 不用时零占用」。

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
> **内部 RAM 预算要按剩余量算，不能按 563 KB。** 五项能力全部落地后**实测剩余
> 479,204 字节（约 468 KB）**，即 UAC 音频与 UVC 摄像头两个阶段合计只吃掉约 6 KB ——
> 大块缓冲全在 PSRAM（见「资源占用」）。DMA 缓冲往往必须在内部 RAM，
> 这条约束比看上去紧，但目前远未逼近。

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

> ⚠️ **本表的分母 256 已被 P4 阶段订正为 242**（buffer DMA 模式下 `dfifo_device_init()`
> 先扣 `2 × ep_count = 14`，见「端点预算」）。所以「空闲」那一列各减 14：
> 16 kHz 单声道实际余 **123 words = 492 B**。**结论一条没变** —— UVC 取 448 B（112 words）
> 仍然装得下，且 48 kHz 立体声那一档只会更装不下。

**升级阶梯**：32 kHz 单声道与 16 kHz 立体声只多吃 10 words，属于「几乎免费」的档位；
48 kHz 立体声不可行。改的是 `usb_descriptors.h` 里 `UAC_SAMPLE_RATE` /
`UAC_CHANNEL_COUNT` 两个常量。
⚠️ **但 UVC 已经落地并吃掉了 112 words，默认档实测只剩 11 words 空闲** ——
再抬采样率就会把 UVC 的 ISO 端点挤掉，**这条阶梯实际上已经关闭了**。

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

### `CONFIG_AIO_DEBUG_CDC`：拿 GUD 的 IN 端点 + **整个音频**换一条 USB 日志串口

这块板现场没有可用串口：UART0 只在 M5-Bus 排针上（要外接 USB-TTL），
USB-Serial/JTAG 被 TinyUSB 收走。于是音频排障长期只能盲二分，每切一刀烧一次板。
`CONFIG_AIO_DEBUG_CDC`（menuconfig → Tab5 All-in-One）用一次**可逆的交换**
换来 `ESP_LOG*`：

| | 0x81 | 0x82 | 0x83 | 0x84 |
|---|---|---|---|---|
| 正常档 | vendor(GUD) | HID | UAC 录音 | **UVC 视频流** |
| **调试档** | **CDC 数据** | HID | **CDC 通知** | **UVC 视频流（不变）** |

> ⚠️ **UVC 落地后这一档的代价变了。** 它原先借的正是 `0x84`，与 UVC 直接撞号。
> 现在改成**整个音频功能不编译**（`AIO_HAS_AUDIO` 由本项反相定义）来腾端点，
> **`0x84` 永久归 UVC** —— 因为摄像头 bring-up 恰恰是最需要日志的那一段，
> 「一开日志就没摄像头」是不能接受的。
> **这一档下 host 侧 `/proc/asound/cards` 里没有这块设备**，`aplay -l` / `arecord -l`
> 都不列它；GUD 显示 / HID 键盘 / HID 触摸 / **UVC 摄像头**照常。

**GUD 不需要 IN 端点** —— 这是这条路成立的全部依据：mainline
`drivers/gpu/drm/gud/gud_drv.c` 的 `gud_probe()` 只调一次
`usb_find_bulk_out_endpoint()`，全驱动没有 `usb_find_bulk_in_endpoint` /
`usb_rcvbulkpipe`（协议本身是「EP0 控制请求 + bulk OUT 送像素」的单向结构）；
本固件 `gud_device.c` 也只有 rx 侧，从不调 `tud_vendor_write()`。
TinyUSB 侧同样没问题：`vendord_open()` 按描述符里实际出现的端点逐条 open，
只有 OUT 时就只开 `rx_stream`（`vendor_device.c:296-332`）。
所以 `0x81` 一直是 `TUD_VENDOR_DESCRIPTOR` 顺带声明出来的、**从未通过流量**的端点。

FIFO 也够（分母 **242** words，见「端点预算」）：RX 62 + EP0 16 + CDC 数据 IN 16 +
HID 16 + CDC 通知 **2** + UVC 112 = **已用 224 / 空闲 18**，比默认档还宽裕 7 words；
IN 端点连 EP0 共 5 条，恰好等于 `ep_in_count`，`dcd_dwc2.c` 的
`TU_ASSERT(allocated_epin_count < ep_in_count)` 每一步都成立。

```bash
idf.py menuconfig      # Tab5 All-in-One → 打开 CONFIG_AIO_DEBUG_CDC
idf.py build flash monitor

# 或：取消 sdkconfig.defaults 末尾 `#CONFIG_AIO_DEBUG_CDC=y` 的注释，再
rm -f sdkconfig && idf.py build flash monitor
```

⚠️ **排障档，不是产品档**：它把**整个音频功能编译掉了**，4 条 IN 端点用满。
查完就关掉。GUD 显示 / 键盘 / 触摸 / **UVC 摄像头**在这一档下照常工作，**音频没有**。

💡 **有 USB-TTL 的话优先接 UART0(G37/G38)** —— 零端点代价、能抓上电最早的日志、
**默认档（音频在）也能用**。CDC 调试档是「手边只有一根 USB-C 线」时的替代品。

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


## UVC 摄像头（SC202CS + MIPI-CSI + ISP + 硬件 JPEG）

### 状态：取流链路已实机验证；**画质返工后（官方 `esp_ipa` 接管）一次都没烧过板**

| 项 | 状态 |
|---|---|
| UVC 链路（MJPEG **640×360 @ 10 fps**，ISO IN `0x84` × **448 B/帧**） | ✅ 实机：`ffplay` 出图、**零拒收**、每 10 秒精确 +100 帧、提交 == 完成、`payload=448` 未被缩水 |
| FIFO 分配 | ✅ 实机：`EP4 IN=112 words`，**枚举时即分配，不等 alt 1** |
| 硬件 JPEG 实时编码（RGB565 输入 / 4:2:2 / `CAM_JPEG_QUALITY = 70`） | ✅ 实机 |
| SC202CS 探测（SCCB `0x36`，PID `0xeb52`） | ✅ 实机 `detect=1` |
| MIPI-CSI + ISP 取流 1280×720 RAW8 → RGB565 | ✅ 实机：**30 fps 稳定**，抢缓冲 / 丢弃 / 取帧超时**全 0**，帧长 **1843200** 正确 |
| PPA ×0.5 缩小 + 接入 UVC | ✅ 实机：`ffplay` 出**真实摄像头画面** |

⛔ **画质那一层已经整体返工，返工后的固件一次都没有烧过板。**

返工（`a98886fb`，净删 6850 行）把此前那一整套**自研控制律**——AE 比例控制器、AWB 灰世界
与四道防护、CCT 估计、CCM 逐档插值与强度钳制、gamma 选档、`env.luma` 重建——连同
`cam_tune.{c,h}` / `cam_isp_map.{c,h}` / `cam_isp_cal.h` / `test/isp_cal_extract.py` /
两份宿主机测试**全部删除**，改由官方闭源算法库 `espressif/esp_ipa` 2.3.0 接管。
**本工程现在一行画质控制律都没有**，只剩「建统计 → 送统计 → 按 flag 把 blob 的
metadata 分发到 ISP 与传感器」这条消费侧管道。理由与教训见下文
「**依赖方向搞反的代价**」。

| 项 | 落点 | 状态 |
|---|---|---|
| 官方 `esp_ipa` pipeline（`ian → awb → agc → adn → acc → aen` 六个模块） | `cam_ipa.c` | ⏳ **已实现，未上板验证** |
| 官方标定 `sc202cs_default.json` **构建期**编成 `esp_video_ipa_config.c`（1055 行） | 构建系统 | ⏳ **已实现，未上板验证**（构建产物存在这一条已确认） |
| 三块 ISP 硬件统计（AE 5×5 / AWB 白点 / 直方图），**连续模式 + ISR 回调** | `camera_csi.c` | ⏳ **已实现，未上板验证** |
| IPA 节拍任务：AE 统计的 ISR 当节拍源 ⇒ **每帧一次 = 30 Hz**，带 100 ms 兜底 | `camera_csi.c` | ⏳ **已实现，未上板验证** |
| metadata 逐位分发（ISP 侧 7 组 + 传感器侧曝光/增益） | `cam_ipa.c` | ⏳ **已实现，未上板验证** |
| `CONFIG_AIO_CAM_IPA` 总开关（默认**开**） | `Kconfig.projbuild` | ⏳ **已实现，未上板验证** |
| IPA 任务栈余量（`CAM_IPA_TASK_STACK = 4096` 是**估的、不是量的**） | — | ⏳ **未测**，第一次烧板必看那一格 |
| 五项能力同跑 10 分钟的复合回归 | — | ⏳ **未做**（规程见文末） |
| 摄像头开着时 GUD 帧率的变化、PSRAM 带宽争用实测值 | — | ⏳ **未测**（观测设施已就位；采集时机就在复合回归里） |
| 脏矩形 / LZ4 的定量验证（P0 欠账） | — | ⏳ **未测**（同上） |
| UAC1 全双工长时稳定性、无反馈端点的时钟漂移（P3 欠账） | — | ⏳ **未测**（同上） |

> ⚠️ **返工前那条「AE 闭环已实机验证」不再适用** —— 被验证的那套控制律已经不在仓库里了。
> 上板验证清单也随之整个重写：现在要验的不是「我们的控制律收不收敛」，
> 而是「**官方算法在这块板上跑得对不对**」，判据简单得多，见下文「上板验证清单」。
>
> ⚠️ **`CONFIG_AIO_CAM_IPA = n` 不是「退回自研算法」** —— 那套东西已经删干净了。
> 关掉得到的是一个**最小可用状态**：CSI 取流 / 去马赛克 / PPA / JPEG / UVC 全部照常，
> 三块硬件统计也照常建、照常跑（自检行仍有数看），但**不建 pipeline、不下发任何 metadata**
> ⇒ 画面发绿 + 偏暗 + 四角暗角、曝光固定在模式表默认值上。用途只有一个：
> 把「画质不对」与「取流 / USB 不对」两类问题分开。
>
> ⓘ 历史上**唯一实机验证过的画质配置**是 `43288ae9`（对角阵 CCM `diag(1.7, 1, 1.55)` +
> 软件全帧均值 AE + 灰世界 AWB）。那套代码已被删除，**现在的开关组合里没有任何一档能退回它**；
> 真要做 A/B 对照只能 `git checkout 43288ae9 -- components/packages/tab5-all-in-one/firmware/`
> 单独烧一版。

### 管线全貌

```
SC202CS ──MIPI-CSI 1 lane @ 576 Mbps──▶ CSI host
  RAW8 1280×720 @30fps                     │
  SCCB 0x36（复用内部 I2C G31/G32）          ▼
  电源 = IO 扩展 0x43 的 PIN6              ISP：BF → LSC → 去马赛克 → CCM
                                            │    → gamma → SHARP → Color
                                            │   （BGGR，RAW8 → RGB565）
                                            ▼
                                        CSI 桥（**直通，不做颜色转换**）
                                            │
                                            ▼ DW-GDMA
                            1280×720 RGB565 = 1,843,200 B × 3 块（PSRAM）
                                            │
                                            ▼ PPA SRM  scale ×8/16（精确 0.5）
                                640×360 RGB565 = 460,800 B（PSRAM，**cache line 对齐**）
                                            │
                                            ▼ 硬件 JPEG 编码器（RGB565 in / 4:2:2 / q=70）
                                     ~20–35 KB JPEG × 2 块（双缓冲）
                                            │
                                            ▼ tud_video_n_frame_xfer()（一次提交整帧）
                            ISO IN 0x84，448 B/包（含 2 B 载荷头）@ 1 ms
                                            │
                                            ▼
                                host: uvcvideo → /dev/videoN
```

各段的代码落点：`camera_csi.{c,h}`（传感器 + CSI + ISP + **三块硬件统计** + **IPA 节拍任务**）、
`cam_ipa.{c,h}`（官方 `esp_ipa` 的**消费侧**：建 pipeline、送统计、按 flag 分发 metadata）、
`cam_jpeg.{c,h}`（PPA 缩放 + JPEG 编码）、`uvc_stream.{c,h}`（TinyUSB 类回调 + 帧泵）、
`cam_frame_stats.{c,h}`（帧统计纯函数，**纯观测、不参与任何控制**）。

### 为什么是 640×360 @ 10 fps —— 是**像素管线**定的，不是带宽定的

先把带宽账摆出来，因为结论与直觉相反：**640×480 在带宽上本来是够的**
（10 fps 每帧预算 44.6 KB，典型 MJPEG 4:2:2 中等质量 23–38 KB）。
做不到的原因是三条像素管线约束叠在一起：

1. **SC202CS 唯一可用的模式是 1280×720（16:9）** —— 它四个模式全是 RAW，
   1600×1200 的 1200 行超过 P4 ISP 的 1920×1080 输入上限，1600×900 裁不出 4:3；
2. **P4 的 ISP 没有缩放器** —— `esp_driver_isp` 下只有 `isp_crop.h`，只能裁不能缩；
3. **唯一的缩放器 PPA，缩放比粒度是 1/16**（系数是「整数位 + 4 位小数」）——
   `1280×720 → 640×360` 是精确的 8/16；而 640×480 要「裁 960×720 再乘 2/3」，
   **2/3 表达不出来**（最近的 11/16 给出 660×495）。

⇒ 640×360 是这条管线上唯一既精确、又不改变视野与宽高比的输出尺寸。附带三个好处：

- **与 GUD 显示模式同为 640×360**，整个包里只有一个分辨率要记；
- 像素数比 640×480 少 25% ⇒ JPEG 小 25% ⇒ 帧率余量大 25%；
- 640 与 360 **都整除 4:2:2 的 MCU（16×8）**，编码器不需要补边。
  （这也是选 4:2:2 而不是 4:2:0 的直接原因：4:2:0 的 MCU 是 16×16，360 不整除。
  代价是 4:2:0 大 20–25%，按现有余量付得起。）

10 fps ⇒ `interval_ms = 100`、`dwFrameInterval = 1,000,000`（100 ns 单位），
每帧传输耗时 = 帧字节 / 446 B/ms，20–35 KB ⇒ 45–78 ms，落在 100 ms 帧期内，
剩下的空档还给 GUD 的 bulk。

**只声明一个格式、一个帧、一个离散帧间隔** —— 不做多分辨率/多帧率协商。

### ⚠️ CSI 的 `input_data_color_type` 与 `output_data_color_type` **双双决定长度**

**这是本阶段最贵的一个坑，且它有两种表现：一种直接报错，一种静默给半帧。**

```c
.input_data_color_type  = CAM_CTLR_COLOR_RGB565,   /* ← 不是 RAW8！ */
.output_data_color_type = CAM_CTLR_COLOR_RGB565,
```

**为什么两个都填 RGB565（而不是照 IDF 例程写 RAW8 → RGB565）**：

- 本板 P4 是 **rev v1.0，CSI 桥的颜色转换硬件根本不存在**
  （`mipi_csi_ll.h` 那对 `#if ... >= 300` 的 `#else` 分支里，桥的五个颜色模式 LL 函数
  **全是空实现**）。而 `esp_cam_new_csi_ctlr()` 内部就会调
  `s_csi_ctlr_format_conversion()`（`esp_cam_ctlr_csi.c:226`），只要 `input != output`
  就在 `:604-608` 查芯片版本并拒绝 ⇒ **`ESP_ERR_NOT_SUPPORTED`，连控制器都建不出来**。
  实机第一次就死在这里。
- ⇒ **IDF 例程 `examples/peripherals/camera/mipi_isp_dsi` 那份 CSI 配置只适用于
  rev ≥3.0，不能照抄。** 解法是让 CSI 桥**直通**，去马赛克整个交给 ISP。

**这两个字段描述的是「桥搬运的数据」，不是「传感器发出的数据」**，而且**双双参与长度计算**：

| 字段 | 算什么 | 填 RGB565 | 若误填 RAW8 |
|---|---|---|---|
| `input_data_color_type` → `in_bpp` | `csi_transfer_size = h*v*in_bpp/64`，即 **DMA 实际搬多少字节** | 1,843,200 | **921,600（半帧）** |
| `output_data_color_type` → `out_bpp` | `fb_size_in_bytes = h*v*out_bpp/8`，即**帧缓冲大小与 `received_size`** | 1,843,200 | 1,843,200 |

⇒ 填 `RAW8/RGB565` 会**只搬半帧却声称收满**：`received_size` 正常、帧计数正常、
全帧亮度统计照样跟手，**从上层完全看不出来**。

固件对此有两道自证判据（都在自检行里）：

1. **帧长不符计数器** —— `received_size != CAM_FB_BYTES` 时这一帧**不交出去**
   （半帧冒充正常画面比没有帧更坏），计数与实收字节都进快照；
2. **下 1/8 亮度与全帧并排统计**，并自动判读：全帧见过光而下 1/8 全程为零
   ⇒ 打一条 `ERROR` 直接点名 `csi_cfg.input_data_color_type`。

> ⓘ CSI host 本身不配色彩格式（`mipi_csi_hal_init` 只设 lane/时钟，数据类型范围
> 写死 `0x12~0x2f`，已涵盖 RAW8 的 `0x2A`），所以改这两个字段**不影响 MIPI 收包**。

### ⚠️ ISP 在 CSI 桥**之前**，所以写进 PSRAM 的字节由 ISP 的输出格式定义

管线次序是 **CSI host → ISP → CSI 桥 → DW-GDMA → PSRAM**，而不是直觉上的
「CSI 收完再交给 ISP」。依据：`SOC_ISP_SHARE_CSI_BRG = 1`；`isp_core.c:92` 以
`BRG_USER_SHARE` 认领同一个桥，CSI 控制器以 `BRG_USER_CSI` 认领，
`mipi_csi_share_hw_ctrl.c` 允许这一对共存。

⇒ **是 ISP 吐 RGB565，桥只负责搬**，上一节那两个字段填 RGB565 才与实际一致。

ISP 配置：

```c
.clk_hz = 80 MHz,
.input_data_source      = ISP_INPUT_DATA_SOURCE_CSI,
.input_data_color_type  = ISP_COLOR_RAW8,      /* 这里才是传感器真正发的 RAW8 */
.output_data_color_type = ISP_COLOR_RGB565,    /* 会顺手打开 demosaic_en */
.bayer_order = COLOR_RAW_ELEMENT_ORDER_BGGR,
```

> ⚠️ **bayer order 要按名字抄，绝不能按数值抄**：
> `esp_cam_sensor_types.h` 是 `RGGB=0 … BGGR=3`，而 `hal/color_types.h` 是
> `BGGR=0 … RGGB=3`，**两套枚举的顺序恰好相反**。

> ⓘ 三块 1.84 MB 帧缓冲（`CAM_FB_COUNT = 3`）而不是双缓冲：`bk_buffer_dis = true`
> 时驱动没有内部备份缓冲，`on_get_new_trans` 回调**必须无条件拿得出一块空闲缓冲**，
> 返回空会让驱动走到 `assert(false)` 直接崩机 —— 而双缓冲的稳态空闲数恰好是 0。

### ⚠️ PPA 输出缓冲的**地址与长度都必须 cache line 对齐**

`ppa_srm.c:186-189` 对 `out.buffer` 与 `out.buffer_size` **两者都硬性检查**，
不过就直接 `ESP_ERR_INVALID_ARG`。**症状是「一帧都出不来」，而不是画面异常** ——
host 侧完全看不出这是内存对齐问题。

所以缩放输出缓冲用 `MALLOC_CAP_SPIRAM | MALLOC_CAP_CACHE_ALIGNED` 分配，
并在运行时再验一次长度可整除（460,800 = 128 × 3,600，天然对齐）。

> ⓘ **JPEG 编码器那一侧反而没有这个要求**（`jpeg_encode.c:250` 的 C2M 带
> `UNALIGNED` 标志），所以接 PPA 之前一直用普通 `malloc` 都没事 ——
> 这条限制是引入 PPA 才出现的，P4 计划里没写。
>
> ⓘ 但 **JPEG 的输出比特流缓冲另有一条**：`jpeg_encode.c:144` 检查 `bit_stream`
> 地址按 cache line 对齐，必须用 `jpeg_alloc_encoder_mem()` 分配，普通
> `heap_caps_malloc()` 过不了 —— 症状同样是「一帧都编不出来」。

### ⚠️ UVC 的 ISO FIFO 在 `SET_CONFIGURATION` 就分配了，**不等 alt 1，且失败静默**

> 这一条推翻了 P4 计划里「alt 1 才分配 FIFO」的说法，直接改变了排障方向。

逐行依据：

- `tusb_mcu.h:768-770` dwc2 没定义 `TUP_DCD_EDPT_CLOSE_API` ⇒ `TUP_DCD_EDPT_ISO_ALLOC` 成立；
- `video_device.c:1404-1422` 的 `videod_open()` 里就调 `usbd_edpt_iso_alloc()`；
- `dcd_dwc2.c:634-637` → `dfifo_alloc()`，**此刻**写下 `DIEPTXF4`；
- `video_device.c:866-871` 里 alt 1 只调 `usbd_edpt_iso_activate()` → `edpt_activate()`，
  那里只写 `DIEPCTL`，**一个字都不碰 FIFO**。

⇒ **`usbd_edpt_iso_alloc()` 的返回值 `video_device.c` 根本不检查，彻底静默。**

**所以症状是「提交涨、完成不涨」，而不是 `SET_INTERFACE` 被 STALL。**
判据是启动日志里 `FIFO: EP4 IN=112 words` 那一行**必须出现** —— 它不出现就是分配失败了。
实测两档都出现，默认档 `已用 231 / 空闲 11`，调试档 `已用 224 / 空闲 18`（分母都是 242）。

### ⚠️ `dwMaxVideoFrameBufferSize` 声明小了会让**每包缩水，且哪里都不报错**

TinyUSB 自己算 `dwMaxPayloadTransferSize`（`video_device.c:562-567`）：

```
payload = min( ceil(dwMaxVideoFrameSize / interval_ms) + 2 , CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE )
```

而 `dwMaxVideoFrameSize` 来自 host 的 COMMIT，`uvcvideo` 直接抄我们帧描述符里的
`dwMaxVideoFrameBufferSize`。**声明成 30000 的话 `30000/100 + 2 = 302 < 448`
⇒ 每个 ISO 包只发 302 字节，带宽白掉三分之一，而且哪里都不报错。**

⇒ `UVC_MAX_FRAME_BYTES = 65536`（`65536/100 + 2 = 658 > 448` ✅），三道守着：
`usb_descriptors.h` 的 `_Static_assert`、`check_usb_desc.py` 的断言、
以及自检行里把实际 `payload=` 打出来（**实测 448，未被缩水**）。

65536 同时是 JPEG 输出缓冲的大小 —— 用**同一个常量**；编码结果超限时走**可见的失败路径**
（丢帧 + 计数），**不截断**（截断的 JPEG 在 host 侧表现为绿色/灰色的下半屏，极难归因）。

### ⚠️ TinyUSB 上游 bug：三个 `*_FRM_MJPEG_DISC` 宏是坏的，本工程手写了替代

`TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC`（`video.h:656-660`）把变参**原样**摊进字节流，
却又按「每个变参占 4 字节」算 `bLength`：

- 传裸 `u32`（1 个变参）⇒ `bLength = 30`、`bFrameIntervalType = 1` 都对，
  但那个 u32 被截成**1 个字节**，实际只发 27 字节 ⇒ **整条描述符流从这里开始错位**；
- 传 `U32_TO_U8S_LE(interval)`（4 个变参）⇒ 字节数对了，
  但 `bLength` 变成 42、`bFrameIntervalType` 变成 4。

**两条路都错。** 这不是我们用错了：**三个 `*_DISC` 宏在全仓库（`src` 与 `examples`）
零调用者，上游从没跑过它们。** 本工程用手写的 `AIO_UVC_FRM_MJPEG_DISC1(...)` 替代，
精确产出 30 字节，`check_usb_desc.py` 有 `len(frm) == 26 + 4` 的断言钉住。

> ⓘ 用 `_DISC`（离散）而不是 `_CONT`（连续）的理由：`video_device.c:550-558` 在 host
> 把 `dwFrameInterval` 填 0（问默认值）时，对「`bFrameIntervalType > 1`」与
> 「连续区间 min != max」这两种情况会直接 `return true` 而**不填任何值**。

### ⚠️ `CFG_TUD_VIDEO` 与 `CFG_TUD_VIDEO_STREAMING` **必须同时定义**

`usbd.c:229` 只看 `#if CFG_TUD_VIDEO` 就把 videod 驱动挂进驱动表，
而 `video_device.c:30` 的编译门是 `#if (CFG_TUD_ENABLED && CFG_TUD_VIDEO && CFG_TUD_VIDEO_STREAMING)`。
**只定义前者 ⇒ 整个 `video_device.c` 编译成空文件 ⇒ 链接期缺 `videod_init` / `videod_deinit` /
`videod_reset` / `videod_open` / `videod_control_xfer_cb` / `videod_xfer_cb` 六个符号。**
`tusb_option.h` 只给了 `CFG_TUD_VIDEO` 的默认值 0，后者连默认值都没有。

三个宏都在 `main/tinyusb_config/tusb_config.h`，且 `usb_descriptors.c` 有
`_Static_assert` 守着两者都为 1、以及 `UVC_EP_SIZE == CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE`。

### ⚠️ `sc202cs.c:1167` 上游 off-by-one —— 增益下标会越界读

`MIN(u32_val, s_limited_abs_gain_index)` 在增益表里**没有任何一项超过**
`CONFIG_CAMERA_SC202CS_ABSOLUTE_GAIN_LIMIT` 时（**默认恰好如此**：表的最大值
`63008` == 上限 `63008`，`:1526-1532` 那个循环从不 `break`），
`s_limited_abs_gain_index` 停在 `ARRAY_SIZE` 上 —— 于是**下标 == 表长也被放行**，
`sc202cs_gain_map[表长]` 是一次**越界读**。

⇒ **不能指望传感器驱动兜底**，传进去的下标必须自己保证合法。
`cam_ipa.c` 的 `gain_to_index()` 因此只在**官方增益表内部**线性扫描、取「不超过目标的
最大一档」，下标天然落在 `[0, count − 1]`；表本身与表长都是开机时用
`esp_cam_sensor_query_para_desc()` 查来的，**一个数都不写死**。

### 白平衡：**用 CCM 替代 WBG**（硬件事实，与返工无关）

本板 P4 rev v1.0 的**硬件白平衡增益（WBG）有 rev ≥3.0 的版本门，用不了**
（`isp_wbg.c:30`），BLC（`isp_blc.c:30`）与 crop（`isp_crop.c:30`）同理。
而 **CCM（颜色校正矩阵）没有任何版本门** —— 它在去马赛克之后的 RGB 域上乘一个 3×3 矩阵，
而「逐通道增益」与「CCM」都是线性算子，可以合并成一个：

```
CCM' = CCM × diag(red_gain, 1, blue_gain)
```

**必须右乘**：WBG 在管线里位于 CCM 的**上游**，右乘才对应这个顺序。
反过来（先 CCM 再乘增益）等于把增益作用在已经混过色的通道上，那是另一件事。
官方 `esp_video` 在没有 WBG 的芯片上做的就是同一件事
（`esp_video_isp_device.c` 的 `isp_init_ccm_param()` 把 R/B 增益乘进第 0 / 2 列）——
**这是官方在 rev <3.0 上的降级路径，不是我们发明的绕法。**

- **系数绝对值上限 3.999** —— rev <3.0 的 CCM 定点是「符号 + 2 位整数 + 10 位小数」
  （`hal/isp_ll.h:138-144`；rev ≥3.0 才是 4 + 8），超范围
  `esp_isp_ccm_configure()` 直接 `ESP_ERR_INVALID_ARG`。
  `cam_ipa.c` 传 `.saturation = true`，让驱动在越界时**饱和**而不是整个拒绝：
  配失败等于**一点白平衡都没有**（画面整体发绿），比略微不准坏得多。
- 落点是 `cam_ipa.c` 的 `config_ccm()`。矩阵来自 blob 的 `IPA_METADATA_FLAGS_CCM`，
  `red_gain` / `blue_gain` 来自 `IPA_METADATA_FLAGS_RG` / `_BG`，
  三者任意一个变了就重算整个矩阵。**这三个数都不是我们算的。**

#### 为什么断定「整体发绿 = 白平衡缺失」而不是「bayer order 配错」

1. **物理必然** —— Bayer 阵列 50% 是绿像素、绿滤光片透过率也最高，
   而 RAW→RGB 只有 ISP 去马赛克一步，若没有任何一处对三通道施加不同增益
   （WBG 用不了、CCM 停在单位阵）⇒ 必然偏绿。**这正是 `CONFIG_AIO_CAM_IPA = n` 的预期画面。**
2. **bayer order 错的症状不是这个** —— 四种 order 的差别是 R 与 B 的位置，
   G 在四种 order 里都占对角线两格，所以配错的表现是**红蓝对调 + 棋盘格高频伪影**，
   不是整幅均匀偏绿。
3. **可证伪的现场判据**（烧板后按这个判）：看 `[自检] 帧内容` 那行的「通道均值 R.. G.. B..」
   —— `R < G > B` 且比例大体固定、与镜头对着什么无关 ⇒ 白平衡没生效
   （去看 `IPA：ISP 重配 CCM=` 与 `块状态 CCM=`）；
   拍**红色**物体时 `B > R` ⇒ 才轮到改 `camera_csi.c` 的 `bayer_order`。

### 画质：官方 `esp_ipa` 接管，**本工程一行控制律都不写**

#### ⚠️ 返工的由来：依赖方向搞反的代价

这是本工程迄今最贵的一个错误，写在这里是因为它属于「**前提没有回头验证**」这一类，
而不是某个算法写错了。

从 P4 计划阶段起，文档里一直写着一条判断：

> 「引 `esp_ipa` 会把 `esp_video` + `usb_host_uvc` + `esp_h264` 一起拖进来，
> 而本板 TinyUSB device 独占唯一一条 FSLS PHY，不能引入 USB **Host** 栈。」

**事实部分是对的**：`esp_video` 2.3.0 的 manifest 确实强制依赖
`usb_host_uvc` + `esp_h264` + `esp_ipa`，引它确实会把 USB Host 栈拖进来。
**错的是推论方向** —— 依赖是

```
esp_video ──▶ esp_ipa                  （esp_video 依赖 esp_ipa）
esp_ipa   ──▶ cmake_utilities + idf>=5.4  （esp_ipa 只依赖这两个，再无其他）
```

也就是说 **`esp_ipa` 完全可以单独引**，而且这正是「与官方 1:1」唯一可能的形式。
这条判断从计划阶段被写进文档、一路带到实施，中途**没有任何一步回头去读 `esp_ipa`
自己的 manifest**，于是自研了一整套本不该写的控制律 —— 约七八个提交的工作量作废。

**为什么不能自己写、必须 1:1**：官方标定数据与官方算法是**一对，不可拆**。
`sc202cs_default.json` 里那 19 档 CCM、9 档 LSC、4 档 gamma / 4 档锐化 / 7 档 BF、
25 个 AE 权重，全都是**按 `esp_ipa` 这套算法的行为**在实验室标出来的。
把这些数喂给另一套控制律，得到的不是「近似官方」，而是一个谁也没验证过的第三种东西。

> 教训一句话：**「A 会拖进 B」与「B 会拖进 A」是两件事**；
> 一条把整个方案定死的前提，代价小到只要读一个 manifest 就能验证时，
> 就应该在动手之前验证一次，而不是让它在文档里滚十几个提交。

#### 数据流

```
     ISP 硬件统计（camera_csi.c 建，连续模式 + ISR 回调）
       AE 5×5 ────┐   AWB 白点 ───┐   直方图 16 段 ───┐
                  │               │                   │
                  ▼               ▼                   ▼
            cam_fill_ipa_stats() 填成一份 esp_ipa_stats_t（只对真交付过数据的块置 flag）
                  │
                  ▼   cam_ipa_process()
            esp_ipa_pipeline_process()        ← 闭源 blob（libesp_ipa.a，约 210 KB）
                  │   输出 esp_ipa_metadata_t（flags 位表示哪些字段有效）
                  ▼   cam_ipa.c 的 dispatch() 逐位分发
        ISP 侧 ── BF / Demosaic / SHARP / Gamma / CCM(+RG,BG) / Color / LSC
        传感器侧 ─ 曝光 + 增益（ET 与 GN 同时置位 ⇒ GROUP_EXP_GAIN 一次性下发）
```

消费侧的每一段都对应 `esp_video/src/esp_video_isp_pipeline.c` 里的一个 `config_xxx()`
（那是官方自己的消费侧实现，开源约 1500 行，是「怎么用这个 blob」的唯一权威）。
**但不引 `esp_video` 组件本身** —— 见上文。

#### 标定数据：**构建期**编进固件，运行期不解析 JSON

| 项 | 内容 |
|---|---|
| 来源 | `managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/sc202cs_default.json`（Apache-2.0，**不在仓库里**，`idf.py build` 才拉下来） |
| 生成器 | `esp_ipa/tools/config/esp_ipa_config.py`，读 `ESP_IPA_JSON_CONFIG_FILE_PATH` 这个 build property |
| 产物 | `build/esp-idf/espressif__esp_ipa/esp_video_ipa_config.c`（**1055 行**） |
| 接通方式 | `esp_cam_sensor` 的 `project_include.cmake` 按 `CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_CONFIGURATION_FILE`（默认 `y`）自动设那个 property —— **我们一行 CMake 都没写** |
| 查表键 | `esp_ipa_pipeline_get_config("SC202CS")`，用 `strcmp` 比 JSON 的顶层键。⚠️ 必须逐字符相同，**不是**模式名 `MIPI_1lane_24Minput_RAW8_1280x720_30fps` |

JSON 里的六个算法模块（**顺序 = JSON 键序 = pipeline 执行序**）与它们带的标定量：

| 模块 | 管的事 | 标定量 |
|---|---|---|
| `ian` | 图像分析（`luma` / `color_temp` 两节） | 环境亮度与色温的模型参数 |
| `awb` | 自动白平衡 | 白点框 `range`（green / rg / bg）、`min_counted` 等 |
| `agc` | 自动曝光与增益 | `luma_adjust`（target 62、[56,64]、**25 个 AE 权重**）、`exposure`/`gain` 的 frame_delay 与最小步长、高/低光优先偏移、`anti_flicker` |
| `adn` | 自适应降噪 | **BF 7 档**、**Demosaic 4 档** |
| `acc` | 自适应颜色校正 | **CCM 19 档**（色温）、**LSC 9 档**（色温）、`saturation`、`blc` |
| `aen` | 自适应增强 | **gamma 4 档**、**锐化 4 档**、**对比度 4 档** |

⚠️ **`cam_isp_cal.h` / `test/isp_cal_extract.py` 那套「机械提取标定表到 C 头文件」的做法
已随返工删除。** 现在标定数据由官方生成器直接编译进固件，我们不碰它、也不再有第二份拷贝
（唯一的例外见下面「仍然自己维护的那 6 个数」）。

#### 三块硬件统计（`camera_csi.c`）

| 统计块 | 采样点 | 模式 | 交付给 | 建不起来时 |
|---|---|---|---|---|
| **AE** 5×5 分块亮度 | `AFTER_DEMOSAIC`（CCM **上游**） | **连续** + ISR 回调 | `agc` / `ian` | 曝光不再自适应，其余照常；**且整条 IPA 掉到 100 ms 兜底节拍** |
| **AWB** 白点累加（`counted` / `sum_r,g,b`） | `BEFORE_CCM` | **连续** + ISR 回调 | `awb` | 白平衡停在初值（画面保持一个固定偏色） |
| **HIST** 16 段直方图 | `ISP_HIST_SAMPLING_RGB`（demosaic 后、gamma 前） | **连续** + ISR 回调 | `ian` 的 `luma` | gamma 停在初值档 |
| **AF** | — | ❌ 不建 | — | SC202CS 定焦模组，没有 VCM |
| **AWB subwindow** 5×5 | — | ❌ rev <3.0 硬件没有 | — | 不置 `IPA_STATS_FLAGS_AWB_SUBWIN`，`awb_subwin[][]` 留零 |

三条不变式：

1. **只对真正交付过数据的块置 flag 位**（`cam_fill_ipa_stats()`）——
   置了位却给全 0，blob 会以为画面全黑、把曝光一路推到顶；
2. **三块统计全部只降级、不拦启动** —— 任何一块建不起来都只记错误码 + 打 warning，取流照常；
3. **AE / AWB 共用同一个 ISP 中断** ⇒ 两者的 `intr_priority` 必须与处理器一致（都写 0）。
   直方图的 `esp_isp_hist_config_t` **没有** `intr_priority` 字段，不存在这个坑。

#### 节奏：专用任务，**每帧一次 = 30 Hz**

| 项 | 值 | 为什么 |
|---|---|---|
| 任务 | `ipa`，优先级 **3**、栈 **4096 B** | 必须低于 TinyUSB / UVC 帧泵 / 触摸 / 键盘（5）与音频泵（4）：晚一拍只是 AE 多花 33 ms 收敛，而那几条晚一拍是用户看得见听得见的掉帧、爆音、丢触点。它还会做 I2C 写（下发曝光/增益），压在触摸之上更没道理 |
| 节拍源 | **AE 统计的 ISR**（`vTaskNotifyGiveFromISR`） | 三块统计里 AE 由 `AE_FDONE` 驱动、每帧必发一次，最可靠；`agc` 又是唯一每拍都消费输入的控制律 |
| 频率 | **≈30 Hz**（= 传感器帧率） | 官方 `esp_video` 的 `isp_task` 就是「一份统计一次 `process()`，不分频」 |
| 兜底 | `CAM_IPA_FALLBACK_MS = 100` | AE 统计断供时通知永远不来 ⇒ AWB/CCM/gamma/LSC 会一起冻在初值上，比返工前更差。超时也走一拍 = 降级成 10 Hz，而不是失效 |
| 不取流时 | `portMAX_DELAY` 无限期阻塞 | 「摄像头不取流时零影响」在本任务上的落点 |

⚠️ **`process()` 不许再加任何分频。** 官方算法内部自带帧延迟
（`agc.exposure.frame_delay = 3`）、最小步长（`gain.min_step = 0.03`）与迟滞
（`gamma.luma_min_step = 3.0`），而 `stats->seq` 每调一次涨一 —— blob 的 `frame_delay`
数的就是它。返工前把 `process()` 挂在 UVC 帧泵那 100 ms 的固定节拍上，只有 10 Hz，
**官方标定里所有按「帧」计的量统统被拉长三倍**，表现为 AE/AWB 收敛慢三倍。
这条已经在 `87ba6c95` 修掉了（专用任务 + AE ISR 节拍源），别再把它挂回帧泵。

⚠️ 栈 4096 是**估算**：把 `esp_ipa_stats_t`（≈624 B）提成文件级静态之后，
留给 blob 的浮点运算与 LSC 分发的余量应当够用 —— 但**没有量过**。
自检行的「栈余」（`uxTaskGetStackHighWaterMark`，IDF 返回字节）是唯一的直读依据，
**第一次烧板必看**，掉到 512 B 以下就把 `CAM_IPA_TASK_STACK` 加大。

#### metadata 逐位分发（`cam_ipa.c` 的 `dispatch()`）

| flag | 去哪 | 备注 |
|---|---|---|
| `BF` | `esp_isp_bf_configure` + 一次性 `enable` | `denoising_level` + 3×3 模板 |
| `DM` | `esp_isp_demosaic_configure` | ⚠️ **只 configure，不 enable**（已被 `output=RGB565` 隐式打开）；`grad_ratio` 是 2 整 + 4 小数 ⇒ 步长 1/16，**四舍五入**不截断 |
| `SH` | `esp_isp_sharpen_configure` + 一次性 `enable` | 两个系数是 3 整 + 5 小数 ⇒ 步长 1/32，同样四舍五入 |
| `GAMMA` | `esp_isp_gamma_configure` × R/G/B + 一次性 `enable` | 三个通道各有独立的 `IPA_GAMMA_FLAGS_*` 位，**按位判断**（官方 SC202CS 标定三通道同曲线，但那是数据的性质，不是契约） |
| `CCM` / `RG` / `BG` | `esp_isp_ccm_configure` + 一次性 `enable` | 三者任一变化都重算整个矩阵：`CCM × diag(rg, 1, bg)` |
| `BR` / `CN` / `ST` / `HUE` | `esp_isp_color_configure` + 一次性 `enable` | 四个字段在**同一个寄存器组**里 ⇒ **四位任一置起就重发整组**，没置起的沿用此刻的值。`128` 就是 `1.0×`（1 整 + 7 小数），blob 给的就是这个 `val` 的原值，**直接写、不换算** |
| `ET` / `GN` | 传感器 | µs → 行（`t_line = 1e9/(fps·vts)` ns）、增益倍率 → 表下标；**没变就不发**（省 I2C）；**两者都要改时必须 `ESP_CAM_SENSOR_GROUP_EXP_GAIN` 一次性下发**，否则会漏出一帧「新曝光 + 旧增益」，而 blob 下一拍恰好会把那一帧当成反馈 |
| `LSC` | `esp_isp_lsc_configure` + 一次性 `enable` | 增益数组 273 格 × 4 通道，`allocate` 必须在 `enable` **之前**（`lsc_fsm == INIT`）⇒ 放在 `cam_ipa_init()` 里；每次下发都比对 `lsc_gain_array_size == 驱动分配的格数`，不等直接记 `ESP_ERR_INVALID_SIZE` 而不是错位填 LUT |

**rev v1.0 忽略掉的那几位 —— 只记录进自检行，一个字都不写硬件：**

| flag | 为什么忽略 | 预期出现吗 |
|---|---|---|
| `BLC` | rev v1.0 的 ISP **没有 BLC 块**（`isp_blc.c` 的版本门要 rev ≥3.0，连符号都不会被链进来），而官方标定文件**带着 `acc.blc`**（model 0、stretch false、四通道偏移都是 16）⇒ blob 会稳定地置起这一位。处置与 `esp_video` 完全一致（它用 `#if ESP_VIDEO_ISP_DEVICE_BLC` 编译掉，我们用 `CAM_IPA_HAS_BLC`） | ✅ **预期会出现**，不是错误路径 |
| `AWB` | 这一位给的是**白点统计框**。而 `esp_isp_awb_controller` 的窗口/白点框**只能在创建控制器时给定**，blob 要等 pipeline 建好之后才可能给出 ⇒ 顺序上够不着 | 可能出现，忽略 |
| `SR` / `AF` / `FP` / `AETL` | 统计区域 / 自动对焦 / 对焦位置 / 传感器 AE 目标电平。SC202CS 是定焦模组，标定文件也**没有 `af` / `atc` 两节**（只有 `ian`/`awb`/`agc`/`adn`/`acc`/`aen` 六个） | ❌ **预期永远不出现**。真在自检行里看到，说明换过标定文件，回去重看 `dispatch()` 那段的假设 |

> ⚠️ 忽略 `BLC` 的代价是「黑电平基座 16/255 不被扣掉」—— 暗部略微发灰，
> 且这个基座会被 CCM 的负非对角项放大成轻微的品红黑位。传感器自身的 BLC（寄存器 `0x3902`）
> 能顶掉一部分，那是另一条独立的路；自检行会把 `0x3902` 的读值打出来
> （`0xc0` = 开着 ⇒ 基座 ≈0；`0x80` = 关着 ⇒ 基座 ≈16，与官方 `acc.blc` 吻合）。
> **本工程只读不写这个寄存器。**

#### 仍然自己维护的唯一标定量：AWB 白点框那 **6 个数**

`camera_csi.c` 建 AWB 控制器时必须给定白点筛选框，而它**只能在创建时给定**（见上）。
所以这 6 个数是**唯一**必须手抄进固件的官方标定量，直接照抄 `sc202cs_default.json` 的
`awb.range`：

```
green { min 98,     max 210 }
rg    { min 0.3801, max 0.879 }
bg    { min 0.2903, max 0.6587 }
```

驱动的亮度窗量纲是 `R+G+B`（`[0, 765]`），官方给的却是 green 的范围，换算式是官方桥接层
自己的 `lum = G × (1 + R/G + B/G)`：

```
lum_max = 210 × (1 + 0.8790 + 0.6587) = 532.9 → 533
lum_min =  98 × (1 + 0.3801 + 0.2903) = 163.7 → 164
```

> ⚠️ **改标定文件（换传感器 / 升 `esp_ipa` 版本）时这 6 个数要跟着改。**
> 这是本次返工留下的**唯一一处**「官方数据在两个地方各存一份」，别再增加第二处。
>
> ⓘ 现场验算的办法：自检行里的「平均G = Σg / 白点数」应当落回 `[98, 210]`。
>
> ⓘ 驱动把两个比值转成 2 整 + 8 小数的定点（**截断**），硬件实际用的框是
> `0.37890625~0.87890625` / `0.2890625~0.65625`，比写进去的略宽一点点 ——
> 方向安全（宁可多收几个边界像素）。

### ISP 对齐：与官方管线的逐级对照

> **口径**：官方 = Espressif `esp_video` + `esp_ipa` 2.3.0 + 标定文件 `sc202cs_default.json`。
> 官方管线的逻辑重建见
> `docs/superpowers/research/2026-08-19-esp32p4-official-isp-pipeline.md`（**关于官方的部分仍然有效**），
> 返工前的自身基线见 `…-our-isp-pipeline-audit.md`（**描述的是已删除的实现**），
> 已被返工推翻的实施计划见
> `docs/superpowers/plans/2026-08-21-tab5-isp-align-with-official.md`（**保留作历史记录**）。
>
> ⛔ **本章描述的配置一次都没有烧过板。** 上板测法与判据见「上板验证清单」。

#### 逐级对照表：官方 13 级 vs 我们配了哪些

| # | 级 | 域 | rev v1.0 | 官方配不配 | **我们** | 参数来自 |
|---|---|---|---|---|---|---|
| 1 | **BLC** 黑电平 | RAW | ❌ 不可用 | eco5 配 / eco4 不配 | ❌ 忽略 `IPA_METADATA_FLAGS_BLC`（传感器自带 BLC 只读不写） | — |
| 2 | **DPC** 坏点 | RAW | 寄存器有、**IDF 无 API** | 不配 | ❌ 不配 | — |
| 3 | **BF** 双边降噪 | RAW | ✅ | 配 | ✅ 按 `BF` flag 下发 | blob（`adn.bf` 7 档） |
| 4 | **LSC** 暗角 | RAW | ✅（门是 rev ≥ **1.0**） | 配 | ✅ 273 格 × 4 通道，按 `LSC` flag 下发 | blob（`acc.lsc` 9 档） |
| 5 | **Demosaic** | RAW→RGB | ✅ | 配 | ✅ 只 `configure` 不 `enable` | blob（`adn.demosaic` 4 档） |
| 6 | **Median** | RGB | 寄存器有、**无 API** | 不配 | ❌ 不配 | — |
| 7 | **CCM** | RGB 线性 | ✅ S2.10（±3.999） | 配 | ✅ `CCM × diag(rg,1,bg)`，饱和钳制交给驱动 | blob（`acc.ccm` 19 档 + AWB 增益） |
| 8 | **Gamma** | RGB | ✅ | 配（R/G/B 各 16 点折线） | ✅ 三通道各按位下发 | blob（`aen.gamma` 4 档） |
| 9 | **RGB2YUV** | — | ✅（复位即开） | 隐式 | ✅ 由输出格式隐式决定 | — |
| 10 | **SHARP** 锐化 | YUV(Y) | ✅ | 配 | ✅ 按 `SH` flag 下发 | blob（`aen.sharpen` 4 档） |
| 11 | **Color** 对比度/饱和度/色调/亮度 | YUV | ✅ | 配 | ✅ 四位合成**一次** configure | blob（`aen.contrast` / `acc.saturation`） |
| 12 | **YUV2RGB / YUV Limit** | — | ✅ | 隐式 | ✅ 由输出格式隐式决定 | — |
| 13 | **CROP** | 输出域 | ❌ 不可用 | 不配 | ❌ 不配（PPA 顶替） | — |
| — | **WBG** 白平衡增益 | RAW | ❌ 不可用 | 配（rev ≥3.0） | ❌ **折进 CCM 第 0/2 列**（官方 rev <3.0 同款降级） | — |

> ⚠️ 「**我们**」那一列的 ✅ 只表示「**代码里配了这一级**」，**不表示上板验证过** ——
> 返工后的固件一次都没烧过。上板怎么确认这一列，见「上板验证清单」阶段 4。

#### rev v1.0 的硬件限制清单（一切取舍的来源，**与返工无关，仍然成立**）

| 限制 | 后果 | 处置 |
|---|---|---|
| **无 WBG** | 白平衡没有 RAW 域执行点 | blob 的 `red_gain`/`blue_gain` 右乘进 CCM（官方同款降级） |
| **无 ISP BLC** | 官方 `acc.blc = 16` 无执行点 | 忽略 `BLC` 位（与 `esp_video` 的 `#if` 同构）；传感器自带 BLC 只读不写 |
| **CCM 是 S2.10（±3.999）** | 官方低色温档本身可能含 >4 的系数 | `.saturation = true`，越界饱和而不是整个拒绝 |
| **无 crop** | ISP 出不了 640×360 | PPA SRM ×0.5 顶替（本来就要用它做旋转） |
| **无 AWB subwindow** | 官方 5×5 分区投票做不了 | 只用主窗的 4 个累加值，不置 `AWB_SUBWIN` 位 |
| **无影子寄存器** | 参数写下去**立刻生效**，没有帧边界原子性 | 换光源时可能闪一下暗角（LSC 要写 273×2 条 LUT）—— **这是硬件限制，不是 bug**。blob 自带迟滞（`gamma.luma_min_step` 等）是唯一的缓解 |
| **CSI 桥无颜色转换** | `input_data_color_type != output_data_color_type` 直接 `ESP_ERR_NOT_SUPPORTED`，连控制器都建不出来 | CSI 两端都填 RGB565，去马赛克全交给 ISP |
| **JPEG 编码器不吃 YUV420/444** | 只能 4:2:2 | `cam_jpeg.c` 固定 4:2:2 |

#### 返工之后**仍然与官方不同**的地方

| 项 | 官方 | 我们 | 原因 |
|---|---|---|---|
| BLC | ISP BLC 写 `acc.blc` | 忽略该 flag | rev v1.0 无 ISP BLC |
| WBG | 独立 RAW 域增益块 | 折进 CCM 第 0/2 列 | rev v1.0 无 WBG（官方 rev <3.0 也这么降级） |
| AWB 子窗 | 5×5 分区投票 | 只有主窗 4 个累加值 | rev v1.0 无 subwindow |
| AWB 统计框 | 由 `IPA_METADATA_FLAGS_AWB` 动态下发 | 建控制器时静态给定（照抄官方 `awb.range`） | 控制器的框只能在创建时给 ⇒ 顺序上够不着 |
| 增益查表 | `esp_video` 用二分，**只在精确命中某一档时才 `break`** | 线性扫描取「不超过目标的最大一档」 | blob 给的是连续浮点倍率，精确命中是小概率事件 ⇒ 官方那条路在多数拍上会走完 `max_inter` 然后报 "failed to search target gain" 整个放弃。表长不过百余项，每拍一次线性扫描可忽略 |
| 曝光换算 | 走 V4L2 那层的 µs↔行 | 自己按 `t_line = 1e9/(fps·vts)` 算 | 不引 `esp_video` ⇒ 没有那一层 |
| IPA 调度 | `isp_task` 阻塞在统计 DMA 完成上 | 专用任务阻塞在 **AE 统计 ISR** 的任务通知上，另带 100 ms 兜底 | 官方三块统计装在同一个 meta buffer 里一起 DQ；我们是三个独立 ISR，必须挑一个当拍子 |
| 视频框架 | `esp_video`（V4L2） | 直接用 `esp_driver_cam` + `esp_driver_isp` | `esp_video` 强制拖进 USB **Host** 栈，违反 spec §8.1 |

#### 踩过的坑（每一条都咬过一次或差点咬；**与返工无关，仍然成立**）

1. **CSI 的颜色转换在 rev <3.0 上不存在。** `input != output` ⇒ 连控制器都建不出来
   （`ESP_ERR_NOT_SUPPORTED`）。IDF 例程 `mipi_isp_dsi` 那份 `RAW8→RGB565` 的 CSI 配置
   **只适用于 rev ≥3.0**。曾经实机死在这里一次。
2. **统计窗口不写就是 `bsize = 0`。** 现场表现是「25 块全 0」/「16 个 bin 全 0」——
   而全零窗**能通过**参数校验。⚠️ 两者口径还不同：AE 的窗按 `/5` 分块（写 `1280×720`，整除）；
   **AWB 的窗是把四个坐标原样写进 `lpoint`/`rpoint` 的闭区间 ⇒ 要写 `1279/719`**。
3. **`esp_isp_bf_configure(proc, NULL)` 是空指针解引用**（`else` 分支之后仍无条件求值
   `config->flags.update_once_configured`）。`sharpen` / `color` 同样的写法。
   **全程不许传 NULL**，要禁用请用编译开关。
4. **Demosaic 只 `configure`、不 `enable`** —— 它已被 `output = RGB565` 隐式打开
   （`isp_ll_set_output_data_color_format()` 顺手置了 `demosaic_en`），
   调 `enable` 会撞 FSM 门拿到 `ESP_ERR_INVALID_STATE`，让人误以为参数没配上。
5. **各 ISP 子块的 `enable` 都有 FSM 门，整个生命周期只能成功一次。**
   `cam_ipa.c` 用 `s_bf_en` / `s_sharp_en` / … 几个布尔记住「已经开过了」；
   `configure` 本身没有 FSM 门，取流中可随时重配（LSC 换档依赖这一点）。
6. **`intr_priority` 与处理器不一致时驱动返回的是布尔 `1`，不是 `esp_err_t`**
   （`ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, …)` 传的是比较结果）。
   自检行会打出一个 `esp_err_to_name()` 认不出的码，**别往别处查**。AE/AWB 与处理器全写 0。
7. **LSC 的分配顺序**：`esp_isp_lsc_allocate_gain_array()` 要求 `lsc_fsm == INIT`
   ⇒ 必须在 `enable` 之前 ⇒ 放在 `cam_ipa_init()` 里，而不是等 metadata 第一次给出 LSC。
8. **定点换算要「四舍五入 + 进位」，不能截断。** `grad_ratio`（1/16）与锐化系数（1/32）
   截断的话舍掉的小数会被位域**静默吞掉**（1.05 截成 1.0000 = −4.8%），
   而现场只看得到「锐化偏弱」这种说不清的偏差。
9. **对比度 / 饱和度的 `val` 是 1 整数位 + 7 小数位 ⇒ `128` 就是 `1.0×`。**
   blob 给的 `brightness`/`contrast`/`saturation`/`hue` 就是这个 `val` 的原值，
   **直接写、不做任何换算**（乘 1000 写进去会拿到 `INVALID_ARG`）。
10. **四个 Color 字段共用一组寄存器** ⇒ 分四次写会有三次是拿旧值覆盖新值。
    必须「任一位置起就重发整组」。
11. **`metadata.flags` 必须每拍清零再交给 blob** —— 它是**输出**参数，blob 只置位、不清位。
    不清的话上一拍的位会一直留着，分发层会拿陈旧的字段反复写硬件。
    官方 `esp_video` 在 `isp_task` 里也是每拍 `isp->metadata.flags = 0`。
12. **`s_info.cur_exposure` / `cur_gain` 只在下发成功之后才更新。** blob 的控制律是
    **增量式**的（拿 `cur` 与算出来的目标比），写早了它会以为已经到位而停止调整，
    喂陈旧值则会让它每拍都以为「还没到位」而持续加码 —— 表现为曝光震荡。
13. **直方图的 25 个权重之和必须精确等于 256。** 驱动 `s_esp_isp_hist_config_hardware()`
    硬性检查。⚠️ 「10 为主 / 内十字 11 / 中心 12」加起来是 260，照抄会直接 `ESP_ERR_INVALID_ARG`。
    本工程取 IDF 测试那组 `24×10 + 中心 16 = 256`。RGB 三个系数的 `integer` 域必须为 0；
    小数部取 **86/85/85** 让和恰好 256。15 个阈值必须严格落在 `(0, 256)` ⇒ 取 16 的整数倍。
14. **`sc202cs_abs_gain_val_map[]` 有两份同名表**（`sc202cs.c:73` 与 `:475`），
    由 `CONFIG_CAMERA_SC202CS_DIG_GAIN_PRIORITY` 二选一，长度分别是 **197 / 192**。
    跨文档引用增益表长度时必须说明是哪一份 —— 所以 `cam_ipa.c` 一个数都不写死，全靠
    `esp_cam_sensor_query_para_desc()` 运行时查。另有 `sc202cs.c:1167` 的上游 off-by-one（见上文）。
15. **`esp_cam_sensor_set_format()` 必须调**，`sc202cs_detect()` 一个寄存器都没写。
    而 `set_format` 会**重写整张模式寄存器表** ⇒ 读 `0x3902` 与调 `cam_ipa_init()`
    都必须排在它**之后**（曝光上下限、增益表、默认值都是驱动在 `set_format` 里才填好的）。
16. **CCM 行和是一条可用的现场判据。** 官方每档矩阵的行和都是 1.000，而右乘
    `diag(rg,1,bg)` 只缩放列、**不改行和** ⇒ 中性面仍映射到中性面、整体增益仍为 1。
    所以「拍白纸时三通道均值差 <5%」是个有依据的判据，不是感觉。

### 参数在哪调：**只有一个 Kconfig 开关**

返工之后本工程**没有画质参数**了 —— 那些数全在官方标定文件里，由 blob 消费。
`main/cam_tune.h` 连同它那 60 多个宏已经删除。剩下的只有：

| 开关 | 位置 | 默认 | 关掉 = 什么 |
|---|---|---|---|
| `CONFIG_AIO_CAM_IPA` | `main/Kconfig.projbuild` | **y** | 不建 IPA pipeline、不下发任何 metadata、不建节拍任务。取流/去马赛克/PPA/JPEG/UVC 全部照常，三块硬件统计也照常建照常跑（自检行仍有数）。**画面发绿 + 偏暗 + 四角暗角 + 曝光固定** —— 这是**预期，不是故障** |

调这一个开关的唯一用途：**把「画质不对」与「取流 / USB 不对」两类问题分开。**
怀疑 blob 把画面调坏了（或在某个场景下卡住了），关掉重烧一次；
若画面仍然不出、或 fps 仍然掉，问题就不在画质层。查完记得打回来。

代码里另有三个**不是给人调的**编译期常量（改它们要先读懂对应注释）：

| 常量 | 值 | 性质 |
|---|---|---|
| `CAM_IPA_HAS_BLC` / `_HAS_WBG` / `_HAS_LSC`（`cam_ipa.c`） | `0` / `0` / `1` | rev v1.0 的**硬件能力门**，与 `esp_video` 的 `ESP_VIDEO_ISP_DEVICE_*` 逐条对应。写成常量而不是运行期查 efuse，是因为整个固件已被 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` 钉死在 rev <3.0 上 |
| `CAM_IPA_TASK_PRIO` / `_STACK` / `CAM_IPA_FALLBACK_MS`（`camera_csi.c`） | `3` / `4096` / `100` | 节拍任务的三个数，取值理由见 `camera_csi.c` 里各自上方的注释。⚠️ **栈是估的**，第一次烧板要照自检行的「栈余」复核 |
| `CAM_IPA_SENSOR_NAME`（`cam_ipa.c`） | `"SC202CS"` | 必须与标定 JSON 的顶层键**逐字符相同** |

JPEG 与尺寸相关的常量另在三处：`main/cam_jpeg.c` 的 `CAM_JPEG_QUALITY`（70）、
`CAM_JPEG_SUBSAMPLE`（4:2:2）、`CAM_JPEG_BUFS`（2）；
`main/usb_descriptors.h` 的 `UVC_W/H/FPS/EP_SIZE/MAX_FRAME_BYTES`；
`main/tab5_pins.h` 的 `CAM_SENSOR_W/H`、`CAM_MIPI_LANES/MBPS`、`SC202CS_*`。

**`CAM_JPEG_QUALITY` 的调法有判据，不是拍脑袋**（照 `uvc:` 自检行第二条读）：

| 峰值帧字节 | 动作 |
|---|---|
| > 44 KB（占满 100/100 ms） | 帧发不完，拒收会跟着涨 ⇒ **质量 −10** |
| 30–44 KB | 保持，但已经贴着预算，**别再往上调** |
| < 20 KB 且拒收 = 0 | 才允许 **+10** 换画质 |

### 自检日志怎么读

**从上往下读，第一条不对的就是根因。** 五组，**顺序就是排查顺序**：

| 组 | 行 | 回答什么 |
|---|---|---|
| ① `camera:` 取流 | `SCCB` / `CSI` | **有没有帧** |
| ② `camera:` 统计 | `统计` / `AE 25 块` / `AWB 白点数` / `HIST` | **三块统计是不是真的在看画面** |
| ③ `camera:` 节拍与内容 | `IPA 节拍` / `帧内容` / `传感器 BLC` | **算法有没有按 30 Hz 跑、帧里有没有东西** |
| ④ `cam_ipa:` 算法 | `IPA：` 五行 | **官方算法在做什么、下发了什么** |
| ⑤ `uvc:` | `streaming` / `编码` / `缩放` / `画面` | **帧有没有发出去** |

每一格都必须能分出**四种情况**（别用同一个哨兵表达其中两种）：

| 打出来的 | 含义 |
|---|---|
| `未编译` | `CONFIG_AIO_CAM_IPA = n`，整段代码不在镜像里（由 `#else` 分支那行说出来） |
| `未运行` | 编译进来了但一次都没配过 / 没跑过 |
| `<错误码>` | 配了、硬件或驱动拒了 ⇒ 打的是 `esp_err_to_name()`，直接可查 |
| `ESP_OK` | 配上了 ⇒ **同时打出此刻硬件里的关键参数值** |

> ⚠️ 「没跑过」一律打成 `未运行`，**绝不打成 `-1`**（沿用音频那一章的教训）。
>
> 默认档日志走 UART0（G37/G38，需外接 USB-TTL）；调试档走 USB CDC 并每 10 秒复读一次。

#### `camera:` + `cam_ipa:` —— 取流、统计、算法

```
camera:  [自检] SCCB(0x36)=ESP_OK pid_rd=ESP_OK pid=0xeb52(期望 0xeb52) detect=1
camera:  [自检] CSI fb=ESP_OK ctlr=ESP_OK cbs=ESP_OK isp=ESP_OK fmt=ESP_OK start=ESP_OK
              | 取流中=1 帧=300 抢缓冲=0 丢弃=0 取帧超时=0 帧长不符=0(实收 1843200，应为 1843200)
camera:  [自检] 统计 AE=ESP_OK(帧 300) AWB=ESP_OK(帧 300) HIST=ESP_OK(帧 300)
              | 运行 AE=ESP_OK AWB=ESP_OK HIST=ESP_OK
camera:  [自检] AE 25 块 [ 52  58  61  57  50 | ...25 个彼此不同的数... ]
camera:  [自检] AWB 白点数=41232 Σr=… Σg=… Σb=…（平均G=143，官方框 [98,210]；
              r/g=0.588 b/g=0.645）
camera:  [自检] HIST Σbin=921600（应 ≈ 921600）暗(bin0)=… 亮(bin15)=…
camera:  [自检] IPA 节拍 唤醒=300 通知=300 处理=298 跳过=2 超时兜底=0 单次最多=1 条
              | AE 统计交付=300 ⇒ 处理/统计=99%（应 ≈100）| 优先级 3 栈余 NNNN B
camera:  [自检] 帧内容 采样=28800 亮度 均值=118 最小=3 最大=255 校验和=0x7a3f10c2
              | 通道均值 R=… G=… B=…
camera:  [自检] 传感器 BLC(0x3902) 读=ESP_OK 值=128（0xc0=开着⇒基座≈0；0x80=关着⇒基座≈16…）
cam_ipa: IPA：配置=ESP_OK 建立=ESP_OK 初始化=ESP_OK 范围=ESP_OK 处理=ESP_OK
              拍数=298（≈29.8 Hz 距上一行自检，取流中应 ≈30）统计seq=300
cam_ipa: IPA：本拍 flags=[ET,GN]  至今见过=[RG,BG,ET,GN,BF,SH,GAMMA,CCM,CN,ST,DM,LSC,BLC]
cam_ipa: IPA：下发 曝光=12 次（当前 624 行 = 20800 µs）增益=4 次（当前 1.000×）下发码=ESP_OK
cam_ipa: IPA：ISP 重配 CCM=3 gamma=2 LSC=1；块状态 BF=ESP_OK DM=ESP_OK SHARP=ESP_OK
              COLOR=ESP_OK CCM=ESP_OK GAMMA=ESP_OK LSC=ESP_OK
cam_ipa: IPA：色彩 对比度=128 饱和度=130 色调=0 亮度=0（128 = 1.0×）；BLC 位本板忽略
```

> ⚠️ **上面是格式示例，数字是编的** —— 返工后没有上过板，一个真实读数都还没有。

| 现象 | 结论 |
|---|---|
| `detect=0` | 传感器没探到。`SCCB(0x36)=ESP_ERR_NOT_FOUND` ⇒ 不应答，查供电与走线；`pid` 不符 ⇒ 装的不是 SC202CS |
| **`ctlr=ESP_ERR_NOT_SUPPORTED`** | **特指一件事**：`csi_cfg` 的 input/output 颜色格式不相等，触发了桥的颜色转换，而本板 rev <3.0 没这个硬件块 |
| `fmt!=ESP_OK` | SCCB 写寄存器表失败：总线在探测之后掉了 |
| 六步全 `ESP_OK` 但 `帧=0` | 管线建起来了、传感器也 stream on 了，但一帧都没到 ⇒ 查 MIPI 走线 / lane 速率 |
| **`帧长不符` 非零** | `received_size` 与 `CAM_FB_BYTES` 对不上 ⇒ `output_data_color_type` 理解错了。**此时这些帧一律不交出去，所以「帧」不会涨** —— 两个数要一起看 |
| `帧` 在涨 | 取到了。**此时才轮到看统计与算法那几行** |
| AE `帧=0` 而 CSI 帧在涨 | 连续统计没启动 ⇒ 看「运行 AE=」那格 |
| **AE 25 块全 0** | 窗口 `bsize = 0`（坑 2） |
| **AE 25 块全都相同的非零值** | 分块没生效（窗口与分辨率对不上） |
| 遮住镜头 ⇒ 25 块全掉；只遮半边 ⇒ **只有一侧掉** | 抽头正常 |
| AWB `白点数` 一直是 0 | 白点框画错了，或画面里确实没有接近中性的像素（怼着单色物体）。换白纸/灰卡再看 |
| AWB `平均G` 落在 `[98, 210]` 之外 | 白点框与实际画面不匹配 |
| `HIST Σbin` 明显 ≠ 921600 | 直方图窗口配错了 |
| `处理/统计 ≈ 100%` 且 `单次最多=1` | **每份 AE 统计恰好消费一次 ⇒ 节拍对齐了**。绝对频率看 `cam_ipa` 那行的「拍数」 |
| `单次最多 ≥ 2` | 任务没跟上，两份统计被合并成一拍，blob 少看了帧 ⇒ 看 CPU 负载与「下发码」（I2C 是否在阻塞） |
| `超时兜底` 持续涨 | AE 统计断供，整条 IPA 掉回 10 Hz 兜底节拍 ⇒ 根因看「运行 AE=」 |
| `跳过` 持续涨而取流中 | 三块统计一份都没到（都没建起来） |
| **`栈余 < 512 B`** | `CAM_IPA_TASK_STACK` 该加大了。**这一格第一次烧板必看** |
| `唤醒 = 0` 而取流中 | 节拍任务根本没建起来，看开机那条 warning |
| `配置=ESP_ERR_NOT_FOUND` | 标定 JSON 没编进来 ⇒ 查 `CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_CONFIGURATION_FILE` 与 `build/.../esp_video_ipa_config.c` |
| `建立` / `初始化` 非 OK | blob 拒了。多半是某个算法模块没被链进来（`CONFIG_ESP_IPA_*_ALGORITHM` 被关掉了） |
| `拍数=0` 而在取流 | 统计一份都没送进来 ⇒ 回去看「IPA 节拍」那行 |
| **`Hz ≈ 10` 而不是 ≈ 30** | 掉进了兜底节拍（AE 统计断供），同样看「超时兜底」与「运行 AE=」 |
| `Hz ≈ 30` 但 `拍数` 与 `统计seq` 差得多 | 有统计被重复消费或被跳过，两者应当同步增长 |
| `至今见过` 里有 **`BLC`** | ✅ **预期如此**，本板忽略它 |
| `至今见过` 里有 `AF` / `FP` / `AETL` / `SR` | ⛔ **不该出现**（标定文件没有 `af`/`atc` 两节）⇒ 换过标定文件，回去重看 `dispatch()` 的假设 |
| `至今见过` 里**始终没有 `ET`/`GN`** | `范围=` 那格非 OK（查不到曝光/增益可调范围），或 blob 认为已收敛 —— **遮挡镜头应当立刻出现** |
| `下发 曝光=`/`增益=` 一直不涨 | blob 在死区里。用手电或遮挡制造 3 档以上的亮度变化再看 |
| `块状态` 某格是 `ESP_ERR_INVALID_STATE` | 撞了 FSM 门（`enable` 调了两次）—— 见坑 4、5 |
| `块状态` 某格是认不出的码 | `intr_priority` 不一致，驱动返回的是布尔 `1`（坑 6） |
| `帧内容` 的 `最暗 == 最亮` | **纯色，不是真实画面**，上面全部作废 |
| `帧内容` 校验和帧帧不变 | 取到的是同一块没被重写的缓冲 |
| `帧内容` 通道均值 `R<G>B` 比例固定 | 白平衡没生效（IPA 没跑，或 CCM 没配上） |

#### `uvc:` —— 编码与发送

```
uvc: [自检] streaming=1 提交=1000 完成=1000 拒收=0 | commit×1 payload=448(应为 448)
           frame_max=65536 interval=1000000
uvc: [自检] 编码=1000 失败=0 | 帧字节 最近=24310 平均=23980 峰值=31204
           → 峰值占 70/100 ms | 编码耗时=9137 us
uvc: [自检] 缩放=1000 失败=0 耗时=4210 us | 实测 10.0 fps(距上一行自检) | 摄像头启停=ESP_OK
uvc: [自检] 画面 采样=28800 均值118 最暗3 最亮255 (下1/8 均值102 最亮241,
           历史最亮 全帧255/下1/8 241) 校验和 7a3f10c2
           | PSRAM 读 空载... → 取流中... → 停流后... MB/s
```

| 现象 | 结论 |
|---|---|
| `streaming=0` 一直不变 | host 没选中 alt 1 ⇒ 问题在协商/描述符，不在取流 |
| `streaming=1` 但 `提交=0` | 帧泵没跑起来（任务没建 / 优先级饿死） |
| **`提交` 一直涨、`完成` 不涨** | 包发不出去 ⇒ **多半是 EP4 IN 的 FIFO 没分到**（见上文，`FIFO: EP4 IN=112 words` 那一行是否出现） |
| `payload ≠ 448` | `dwMaxVideoFrameBufferSize` 那个静默带宽陷阱 |
| `拒收` 在涨 | 上一帧还在飞就提交了下一帧 ⇒ 帧太大发不完，看下一行的峰值 |
| `峰值 > 44 KB` | 帧发不完 ⇒ `CAM_JPEG_QUALITY` −10 |
| **`缩放 失败` 非零** | PPA 提交被拒。**几乎只有一个原因**：输出缓冲没按 cache line 对齐。它是启动时一次性分配的，所以**要么全失败要么全成功**，中间态不存在 |
| `缩放 耗时` | 就是每 100 ms 里 `display_blit()` 可能被顶住的时长**上界**（PPA 引擎是共享硬件，两个 client 在引擎信号量上排队）。**显示掉帧时先看这个数，别一上来就怪带宽** |
| `实测 fps` | 判据 **≥ 9.0**。**用「完成」而不是「提交」算** —— 提交了没发完的帧 host 一帧都看不见 |
| `采样=0` | 一次都没统计过 = 从来没取到过帧 ⇒ 回去看 `camera` 那一行 |
| **`最暗 == 最亮`** | **纯色，不是真实画面** |
| **校验和帧帧不变** | 取到的是同一块没被重写的缓冲 |
| **`下1/8 历史最亮` 恒为 0 而全帧见过光** | **DMA 只填了上半张**（固件会自动打一条 ERROR 点名 `input_data_color_type`） |
| PSRAM 三个数 | 取流中比空载掉一两成算正常；**掉一半以上**说明 DPI 面板也在挨饿，重点看 GUD 有没有撕裂；停流后没回到空载 ⇒ 停流没停干净 |

> 「有帧」与「帧里有东西」是**两件事** —— 一块没被写过的零缓冲在帧计数上与真实画面
> 一模一样。上面那四条（`最暗==最亮` / 校验和不变 / 下 1/8 / 采样=0）就是为此存在的。

### 上板验证清单（**返工后的固件一次都没烧过，这份清单也是全新的**）

> **为什么要重写这份清单**：返工前那份「六阶段」验的是**自研控制律的收敛行为**
> （ρ ≈ 0.79、`env.luma` 重建、黑电平基座决定 CCM 强度……），
> 而那套代码已经整体删除，那些判定点连同被判定的对象一起消失了。
>
> **现在要验的是另一件事**：官方算法是既定的、标定数据是官方的、控制律不是我们写的
> ⇒ 不需要判断「参数调得对不对」，只需要判断「**这条管道有没有把统计正确地喂进去、
> 把结果正确地发出来**」。判据因此简单得多，而且几乎全是可证伪的计数关系。
>
> **原则仍然是从底层往上**：先验统计抽头在不在画面上（阶段 2），
> 再验节拍对不对（阶段 3），再验算法有没有在动（阶段 4），最后才看观感（阶段 5）。
> 顺序颠倒的话，一个「抽头压根没配上」会被误读成「官方算法不行」。

#### 阶段 0：烧板前的闸门（不用板子，全部在宿主机跑）

```bash
. $HOME/esp/esp-idf/export.sh
cd components/packages/tab5-all-in-one/firmware
rm -rf build sdkconfig && idf.py build            # 判据：零 warning
python3 test/check_usb_desc.py build/tab5_aio.elf # 判据：384 字节 / 7 接口
ls build/esp-idf/espressif__esp_ipa/esp_video_ipa_config.c   # 判据：存在（标定编进来了）
cd test && for t in touch_map kbd_translate standby_screen audio_frame uac_volume \
                    uvc_pattern cam_frame_stats; do
  cc -std=c11 -Wall -Wextra -Werror -I../main test_$t.c ../main/$t.c -o /tmp/$t && /tmp/$t
done                                              # 判据：7 组全 OK
```

**判据**：全过。任一项不过 ⇒ **不要烧**，先修。
`git diff --stat` 里出现 `usb_descriptors.*` / `tusb_config.h` ⇒ 同样不要烧
（端点/FIFO 账是四条 IN 端点满配的，动一下 UVC 就没位置了）。

> ⓘ 返工删掉了 `test_cam_tune.c` / `test_cam_isp_map.c`（它们测的是已删除的控制律）
> 与 `isp_cal_extract.py --check`（标定不再由我们提取）。宿主机测试从 9 组变成 **7 组**。

#### 阶段 1：既有能力没被打断（摄像头**先不开**，5 分钟）

返工只动了画质层，但它改了 `camera_csi.c` 的启停路径、加了一条会做 I2C 写的任务。
先确认四项已验证能力都还在。

| # | 检查 | 判据 | 不过 ⇒ |
|---|---|---|---|
| 1.1 | 开机日志 | `[自检] CSI` 六步全 `ESP_OK`；`FIFO: EP4 IN=112 words` 出现 | 与画质无关，回去看 USB / CSI 那两章 |
| 1.2 | host `lsusb` | `16d0:10a9`，IN 端点恰为 `0x81/0x82/0x83/0x84` | 同上 |
| 1.3 | GUD 显示 | `/dev/dri/cardN` 存在，`modetest` 出图 | 同上 |
| 1.4 | HID 键盘 | `evtest` 收到按键，含六键同时按 | 同上 |
| 1.5 | ⭐ **HID 多点触摸** | `evtest` 收到 5 点绝对坐标；**连续快划 30 秒以上，坐标不卡住、不跳变、不掉点** | 见下方 ⚠️ |
| 1.6 | UAC1 | `aplay` 出声、`arecord` 有波形 | 同上 |

> ⚠️⚠️ **触摸要多划几下，这是本轮回归风险最高的一项。**
> IPA 节拍任务会下发曝光/增益，走的是 `esp_cam_sensor_set_para_value()` → SCCB，
> 而 SCCB 复用的正是**触摸/codec/IO 扩展共用的那条内部 I2C 总线（G31/G32）**。
> 返工前 `process()` 是 10 Hz、且挂在帧泵里；现在是 **30 Hz、一条独立任务**
> ⇒ 同一条总线上的写事务频率涨了三倍。
> 任务优先级取 3（**低于**触摸的 5）正是为此，但「优先级排对了」不等于「实测没影响」。
> 判据：**摄像头开着连续快划时的手感与摄像头关着时没有差别**；
> 若出现卡顿/掉点，先用 `CONFIG_AIO_CAM_IPA = n` 重烧一次做 A/B —— 那一档不下发任何
> 曝光/增益，总线上就没有这些写事务了。

#### 阶段 2：三块统计抽头是不是真的在看画面（**纯观测**）

> 这一阶段的全部意义：**一块没被写过的零缓冲，在计数器上与真实画面一模一样。**
> 打开 `ffplay` 让摄像头取流，然后照做。

| # | 抽头 | 动作 | 判据 | 不过 ⇒ |
|---|---|---|---|---|
| 2.1 | **AE 5×5** | 看 `[自检] AE 25 块` | 25 个数**彼此不同**（全 0 = 窗口 `bsize = 0`；全都相同的非零值 = 分块没生效） | 抽头没配上 ⇒ blob 的 `agc` 拿不到输入 ⇒ 曝光不会动。查 `ae_cfg` 的窗口 |
| 2.2 | AE 5×5 | 只遮**半边**镜头 | **只有一侧的块掉下去**（顺带把硬件块排布方向测出来） | 同上 |
| 2.3 | AE 5×5 | 手电照中心 | 中心块 > 250 | 同上 |
| 2.4 | **HIST** | 遮住镜头 | 16 个 bin 整体左移、`暗(bin0)` 显著变大；**`Σbin ≈ 921600`（= 1280×720）** | `Σbin` 差很多 ⇒ 直方图窗口配错了 |
| 2.5 | **AWB 白点** | 拍**白纸**（充满画面） | `白点数` 显著大于 0（占 921600 的一成以上） | 见 2.7 |
| 2.6 | AWB 白点 | 拍**红墙**（或任何单色物体） | `白点数` 掉到接近 0 | 见 2.7 |
| 2.7 | AWB 白点 | 读同一行 | ⭐ **`平均G` 落在官方框 `[98, 210]` 内** | 白点恒 0 或 `平均G` 长期落在框外 ⇒ **手抄的那 6 个数与实际画面不匹配**（唯一需要人工同步的标定量，见上文），回去核对 `sc202cs_default.json` 的 `awb.range` |
| 2.8 | 帧统计本身 | 读 `[自检] 帧内容` | `最暗 ≠ 最亮`、**校验和帧帧在变** | 这两条不过说明取到的不是真实画面，上面全部作废 |

#### 阶段 3：⭐ 节拍对不对（**这是返工的核心改动，单独一阶段**）

前提：阶段 2 全过。取流中读 `[自检] IPA 节拍` 与 `cam_ipa: IPA：配置=…` 两行。

| # | 量 | 判据 | 不过 ⇒ |
|---|---|---|---|
| 3.1 | `拍数` 的频率 | **≈30 Hz**（自检行括号里直接打出来，取流中应 ≈30） | ≈10 ⇒ 掉进兜底节拍（AE 统计断供），看 3.3 |
| 3.2 | `处理/统计` | **≈100%** | 明显 <100% ⇒ 有统计被跳过，看「跳过=」与「超时兜底=」 |
| 3.3 | `单次最多` | **= 1 条** | ≥2 ⇒ 任务没跟上，两份统计被合并成一拍。查 CPU 负载与「下发码」（I2C 阻塞） |
| 3.4 | `超时兜底` | **不涨** | 持续涨 ⇒ AE 统计断供，根因看「运行 AE=」 |
| 3.5 | `拍数` vs `统计seq` | **同步增长**（差值不随时间拉大） | 拉大 ⇒ 统计被重复消费或被跳过 |
| 3.6 | ⭐ **`栈余`** | **> 512 B**，并记下这个数 | ≤512 ⇒ 把 `CAM_IPA_TASK_STACK` 从 4096 加大重烧。**这个值从来没有量过，第一次烧板必看** |
| 3.7 | `唤醒` | 取流中持续涨 | =0 ⇒ 节拍任务没建起来，看开机 warning |

#### 阶段 4：官方算法在不在动

| # | 检查 | 动作 | 判据 | 不过 ⇒ |
|---|---|---|---|---|
| 4.1 | pipeline 起没起来 | 读 `cam_ipa: IPA：配置= 建立= 初始化= 范围=` | 四格全 `ESP_OK` | `配置=ESP_ERR_NOT_FOUND` ⇒ 标定 JSON 没编进来；`范围` 非 OK ⇒ 曝光/增益查不到可调范围，AE 不会动 |
| 4.2 | ⭐ **flag 集合** | 读 `至今见过=[…]` | **有** `RG,BG,ET,GN,BF,SH,GAMMA,CCM,DM,LSC` 与 `BR/CN/ST/HUE` 中的若干；**有 `BLC`（预期，本板忽略）**；**没有 `AF`/`FP`/`AETL`/`SR`** | 出现 `AF`/`FP`/`AETL`/`SR` ⇒ 换过标定文件，`dispatch()` 里那段假设不再成立；缺 `ET`/`GN` ⇒ 看 4.1 的「范围=」 |
| 4.3 | 块状态 | 读 `块状态 BF= DM= SHARP= COLOR= CCM= GAMMA= LSC=` | 全 `ESP_OK` | `INVALID_STATE` ⇒ FSM 门（坑 4/5）；认不出的码 ⇒ `intr_priority`（坑 6） |
| 4.4 | ⭐ **曝光跟随** | 手电照 / 遮挡，各三次 | `下发 曝光=`、`增益=` 两个计数跟着涨，「当前 N 行」明显变化；**约 1 秒内稳定下来**（`agc.exposure.frame_delay = 3` @30 Hz ⇒ 每步约 100 ms） | 完全不动 ⇒ 看 4.1「范围=」与 4.2 有没有 `ET`/`GN`；来回摆不停 ⇒ 记录现象，**不要改参数**（参数是官方的），先确认 3.1–3.5 全过 |
| 4.5 | 白平衡跟随 | 换光源（白炽 ↔ 日光） | `ISP 重配 CCM=` 跟着涨并停住；画面色温跟着变 | `CCM=0` 一直不涨 ⇒ 看 2.5–2.7（白点统计没进来，blob 的 `awb` 没有输入） |
| 4.6 | LSC / gamma | 取流几十秒后读 | `LSC=` 至少 1、`gamma=` 至少 1 | `LSC=0` 且 `块状态 LSC=ESP_ERR_INVALID_SIZE` ⇒ 格数与驱动分配的不一致（换过分辨率） |
| 4.7 | 色彩 | 读 `IPA：色彩 对比度= 饱和度= 色调= 亮度=` | 四个数都在 `[0,255]`，对比度/饱和度在 128 附近 | 明显越界 ⇒ 换算被人改动过（`128 = 1.0×`，直接写不换算） |

#### 阶段 5：观感（前四阶段全过才轮到）

| # | 检查 | 判据 |
|---|---|---|
| 5.1 | 整体亮度 | `ffplay` 里曝光正常，不是「几乎全黑」也不是削顶发白 |
| 5.2 | 颜色 | 人脸不是蓝的（没有 R/B 互换）；白纸是白的；红色物体是红的 |
| 5.3 | 白平衡到位 | 拍白纸时 `[自检] 帧内容` 的三个通道均值差 **< 5%**（依据：官方 CCM 行和恒为 1，右乘 `diag` 不改行和） |
| 5.4 | 暗角 | 拍白墙，四角/中心亮度差 **< 15%** |
| 5.5 | 噪声 / 锐化 | 暗处噪点可接受；边缘**没有**白边/黑边（过锐 ⇒ 定点换算的整数位/小数位颠倒了） |
| 5.6 | 方向 | 画面不上下颠倒、不左右镜像 |
| 5.7 | UVC 出图 | ⭐ `[自检] 缩放` 那行的 **`实测 fps ≥ 9.0`**；`[自检] streaming` 的 **`拒收 = 0`**；`编码 失败` / `缩放 失败` 都是 0 |

#### 阶段 6：alt 0 的「零占用」仍然成立

停掉 `ffplay`，等 10 秒，再读两次自检行：

| 量 | 判据 |
|---|---|
| ⭐ `[自检] IPA 节拍 唤醒=` | **停止增长**（节拍任务在 `portMAX_DELAY` 上睡着了） |
| `[自检] 统计 AE=/AWB=/HIST=` 的三个「帧 N」 | 停止增长（stop 路径把三块统计都停了） |
| `cam_ipa: IPA：… 拍数=` 的 Hz | **回到 0** |
| `[自检] 画面 … PSRAM 读 停流后` | 回到空载同量级 |
| 固件日志 | 出现「摄像头取流 停止」 |

任一项不过 ⇒ 停流路径漏了东西，回去看 `camera_csi_stop()` 与 `cam_ipa_task` 里那两处
`s_streaming` 判断。

#### 阶段 7：复合回归

见文末「**五项能力复合回归规程**」。**这是 P0 / P3 欠账的采集时机**，不要单独再跑一次。

#### 失败时的唯一一条退路

返工之后**没有分级开关了** —— 画质要么全是官方的，要么一个都不下发。
出问题时的二分只有一刀：

```
CONFIG_AIO_CAM_IPA = n  →  重烧
```

- **画面仍然不出 / fps 仍然掉** ⇒ 问题不在画质层，回阶段 1–2 查取流与 USB；
- **画面出来了（发绿、偏暗、带暗角、曝光固定）** ⇒ 问题确实在 IPA 这条路上，
  带着阶段 3/4 的自检行去定位是「统计没喂进去」还是「metadata 没发出来」。

⚠️ 这一档**不是产品形态，也不是「已知好状态」** —— 它同样没有上过板。
历史上唯一实机验证过的画质配置是 `43288ae9`，那套代码已被删除
（要 A/B 只能 `git checkout 43288ae9 -- …` 单独烧一版）。

### 「不用时零占用」的两个落点

**摄像头对显示的影响严格为零，直到有人真的打开它。** 这不是优化，是整章取舍成立的基础：

1. **USB 侧** —— VideoStreaming 停在 **alt 0（零端点、零带宽）**，host 不预留任何 ISO 带宽；
2. **PSRAM 侧** —— **CSI 只在 host 选中 alt 1 时才 `start`**。不流时不取流、不缩放、不编码，
   CSI 那 ≈55 MB/s 的 PSRAM 写入（DPI 面板刷新 ≈89–107 MB/s 读的直接竞争者）归零。

反过来，**打开摄像头会让显示明显变慢**：周期性传输从 172 B/ms 涨到 584 B/ms，
留给 GUD bulk 的理论上限从约 1364 掉到约 916 B/ms（**−33%**）。
**这是全速口的物理上限，不是 bug。** ⏳ **实测数字尚未取得**，上面是推算。

> ⓘ 缓冲与编码器**在启动时一次建好**，不做按需分配 —— 分配失败要在开机日志里立刻可见，
> 而不是等 host 打开摄像头时才在帧泵里静默失败（那时 host 侧表现为「有 `/dev/videoN`
> 但取不到流」，从现象反推不到内存不够）。代价是没人开摄像头也占着 PSRAM，**带宽代价为零**。

> ⚠️ **不要用模块内的 `in_flight` 标志去影子跟踪「有没有帧在飞」** ——
> host 快速 `alt1 → alt0 → alt1` 时，切到 alt 0 那一刻驱动在 `_open_vs_itf()` 里把
> `bufsize` 清了、**完成回调不会再来**，而标志留在 true，从此每一拍都以为上一帧还在飞，
> **流再也起不来（只能重新插拔）**。判据一律现问 `tud_video_n_streaming()`。

### 依赖：引 `esp_cam_sensor` + `esp_ipa`，**不引** `esp_video`

`esp_video` 2.3.0 的 manifest **强制拖进**：

```
espressif/usb_host_uvc  2.5.*   ← ⚠️ USB **Host** 栈
espressif/esp_h264      1.3.0   ← 纯软件 H.264 编码器
espressif/esp_ipa       2.2.*
```

在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB **Host** 栈，
是 spec §8.1「不引入 usb-host 依赖」的正面违反。而它那层 V4L2 语义我们也用不上 ——
本工程只需要「一个固定模式、拿到一帧 RGB565」。

**但 `esp_ipa` 可以、而且必须单独引。** 依赖方向是

```
esp_video ──▶ esp_ipa                     （单向）
esp_ipa   ──▶ cmake_utilities 0.* + idf>=5.4   （**再无其他**）
```

`cmake_utilities` 早就在树里（`esp_cam_sensor` 也用它）⇒ 引 `esp_ipa` 只多它自己一个目录。
⛔ **早先「引 `esp_ipa` 会把 `esp_video` 那一半拖进来」的判断是错的**，
它导致自研了一整套本不该写的控制律，代价见上文「依赖方向搞反的代价」。

`esp_cam_sensor` 则一直是干净的 —— 它与已在用的 `esp_lcd_ili9881c` / `esp_lcd_touch_gt911` /
`esp_io_expander_pi4ioe5v6408` / `esp_codec_dev` **同一性质：芯片驱动组件**，
传递依赖只有 `esp_sccb_intf` 与 `cmake_utilities`。
它同时提供 SC202CS 的寄存器序列**与官方标定 JSON**，并由 `project_include.cmake`
把那份 JSON 自动接到 `esp_ipa` 的构建期生成器上 —— **我们一行 CMake 都没写**。

**`managed_components/` 实测 13 个目录**（返工前 12 个 + `espressif__esp_ipa`；
`cmake_utilities` 本来就在，不算新增）。摄像头这条链路一共只让它多了 3 个目录
（`esp_cam_sensor` / `esp_sccb_intf` / `esp_ipa`）。

`libesp_ipa.a` 是**闭源** blob（`lib/esp32p4/v6.0+/`，约 210 KB）。
接受它的理由只有一条：**官方标定数据与官方算法是一对，不可拆**。
19 档 CCM / 9 档 LSC / 4 档 gamma / 25 个 AE 权重都是按这套算法的行为标出来的，
换个控制律那些数就不成立了 —— 而「与官方 1:1」唯一可能的形式就是用官方那个 `.a`。

### Host 侧验证

主机需 mainline `uvcvideo`（`CONFIG_USB_VIDEO_CLASS`，发行版一般自带 `uvcvideo.ko`）。

```bash
lsusb -v -d 16d0:10a9 | grep -E "bInterfaceClass|bEndpointAddress|wMaxPacketSize"

#   → 见 Video(0x0E)；IN 端点恰为 0x81/0x82/0x83/0x84；0x84 的 wMaxPacketSize = 0x01c0 (448)
sudo dmesg | grep -i uvc            # uvcvideo: Found UVC 1.50 device
ls /dev/video*

sudo apt-get install -y v4l-utils ffmpeg
v4l2-ctl -d /dev/videoN --list-formats-ext

#   → MJPG / 640x360 / 10.000 fps（只有这一个，是有意的）

ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
v4l2-ctl -d /dev/videoN --stream-mmap --stream-count=100 --stream-to=/tmp/cam.mjpg
```

判据：

1. `ffplay` 显示**真实画面**，方向正确（不上下颠倒/左右镜像）、
   **颜色正常（人脸不是蓝的 ⇒ 没有 R/B 互换）**；
2. 实测 fps **≥ 9.0**，固件侧 `拒收` / `编码 失败` / `缩放 失败` 都是 0；
3. 平均帧 ≤ 30 KB、峰值 ≤ 44 KB；
4. **停掉 `ffplay` 后固件日志出现「摄像头取流 停止」** —— 这是「不用时零占用」的落点；
5. GUD / 键盘 / 触摸 / 音频不回归。

> ⓘ `ls /dev/video*` 多出**两个**节点属正常现象（后一个是 `uvcvideo` 的 metadata 节点）。
>
> ⓘ 若 `lsusb` 看得到设备、却没有 `/dev/videoN` 且 `dmesg` 无 uvc 相关行，
> 先 `modinfo uvcvideo` —— 那是 host 内核配置问题，不是固件缺陷。

### 宿主机回归测试

摄像头这条链路上仍然可测的纯逻辑只剩帧统计一个（**纯观测量，不参与任何控制**）——
返工把 AE/AWB 控制律与 ISP 映射层整个删除之后，`test_cam_tune.c`（521 用例）、
`test_cam_isp_map.c`（532 用例）与 `isp_cal_extract.py --check` 一并删除：
它们测的是已经不存在的代码，而画质算法现在在闭源 blob 里，**宿主机测不到**。

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_frame_stats.c \
   ../main/cam_frame_stats.c -o /tmp/cam_frame_stats && /tmp/cam_frame_stats

#   cam_frame_stats OK (24 cases)
```

七组全表（**改任一对应源文件后重跑**）：

| 测试 | 盯什么 |
|---|---|
| `test_touch_map.c` | 触摸坐标反变换与报告装填 |
| `test_kbd_translate.c` | 按下集合 → HID 分层翻译 |
| `test_standby_screen.c` | 待机画面版式（含 PPM 预览） |
| `test_audio_frame.c` | USB 单声道 ↔ I2S 立体声 |
| `test_uac_volume.c` | UAC1 音量 ↔ 硬件百分比换算 |
| `test_uvc_pattern.c` | 合成图案（已不在固件 SRCS 里） |
| `test_cam_frame_stats.c` | 帧统计纯函数（亮度均值/最暗/最亮/分通道均值/FNV-1a 校验和） |

```bash
cd firmware/test
for t in touch_map kbd_translate standby_screen audio_frame uac_volume \
         uvc_pattern cam_frame_stats; do
  cc -std=c11 -Wall -Wextra -Werror -I../main test_$t.c ../main/$t.c -o /tmp/$t && /tmp/$t
done
```

> ⚠️ **画质层现在没有宿主机护栏了。** 这是引入闭源算法必然的代价：
> 唯一能证伪的地方在板子上，判据全部落在「上板验证清单」的自检行判读里。
> 相应地，那份清单里凡是可以用**计数关系**证伪的（处理/统计 ≈100%、单次最多 =1、
> `Σbin ≈ 921600`、`平均G ∈ [98,210]`、alt 0 后 `唤醒` 停涨）都优先于「看着对不对」。

USB 描述符另有一道烧板前的闸门（**两档都要过**）：

```bash
. $HOME/esp/esp-idf/export.sh
python3 test/check_usb_desc.py build/tab5_aio.elf
```

它从 ELF 里抠出描述符字节自行解析（**不读 `sdkconfig`，是独立的第二意见**），
UVC 相关断言包括：VC 接口 `bNumEndpoints == 0`、VS alt 0 零端点 / alt 1 恰好 `{0x84}`、
**端点描述符长度 == 7**（9 字节是 UAC1 的形式，说明有人手写错了）、
`wMaxPacketSize == 448`、帧描述符**恰好 30 字节**、
`dwMaxVideoFrameBufferSize / interval_ms + 2 > 448`（静默带宽陷阱）、
以及全局的「IN 端点恰为 `0x81/0x82/0x83/0x84` 四条且 `0x84` 是 ISO IN」。

> ⓘ 画质返工**没有动 USB 侧一个字节** —— 描述符、端点、FIFO 账全部不变。

## 五项能力复合回归规程 ⏳ **未执行**

> **规程，不是结论。** 下面的每一格判据都是**该测出什么**，不是**测出来是多少** ——
> 本节写作时这场回归一次都没跑过，所有「实测」列都留空。
>
> **一次跑完三件事**（不要拆成三次，那样采不到同一时刻的对照）：
>
> 1. **复合回归本身** —— 五项能力同跑 10 分钟，证明**画质返工**没有动到任何一项已验证能力
>    （尤其是触摸：IPA 节拍任务与它共用那条内部 I2C 总线，见「上板验证清单」阶段 1）；
> 2. **P0 欠账** —— 脏矩形 / LZ4 的定量验证、**GUD 帧率实测**（含开/关摄像头的对比）；
> 3. **P3 欠账** —— UAC1 全双工长时稳定性、**无反馈端点的时钟漂移**。

### 前置

- 「上板验证清单」的阶段 0–6 已经过（**至少 0–4**）。摄像头链路与 IPA 节拍不对时这一场没有意义。
- 主机侧准备：

```bash
sudo apt-get install -y v4l-utils ffmpeg alsa-utils evtest \
                        gstreamer1.0-tools gstreamer1.0-plugins-bad
lsusb -d 16d0:10a9                       # 设备在
ls /dev/dri/card*                        # 记下 GUD 那张卡的编号 → $CARD
ls /dev/video*                           # 记下 → $VID
aplay -l | grep -i tab5 ; arecord -l     # 记下声卡号 → $SND
ls /dev/input/event*                     # evtest 交互式选，记下键盘与触摸各一个
```
- 固件侧日志接出来（默认档走 UART0 G37/G38，需外接 USB-TTL）并**全程存盘**：
```bash
# 判据里所有「N 条」都靠 grep 这个文件
python3 -m serial.tools.miniterm /dev/ttyUSB0 115200 | tee /tmp/tab5-fw.log
```
  ⚠️ **不要为了看日志改用 `CONFIG_AIO_DEBUG_CDC` 调试档** —— 那一档**整个音频不编译**，
  第 4、5 两项根本跑不起来，且它拿走了 GUD 的 IN 端点。这场回归**只在默认档跑**。

### 步骤（顺序有讲究：先量没有摄像头的基线，再打开摄像头）

#### 步骤 A：GUD 帧率基线（**摄像头关着**，3 分钟）

```bash
# 终端 1 —— 全屏动态内容，最坏情况（几乎每帧整帧脏区）
gst-launch-1.0 -v videotestsrc pattern=smpte is-live=true \
  ! video/x-raw,width=640,height=360,framerate=30/1 ! videoconvert \
  ! fpsdisplaysink text-overlay=false sync=false \
      video-sink="kmssink driver-name=gud force-modesetting=true"

#   → 每秒打一行 "current: NN.NN, average: NN.NN"
```

记录 3 分钟的 **average fps**，记作 **`fps_A`**。此时：
- `v4l2-ctl -d $VID --list-formats-ext` 仍应报 `MJPG 640x360 10.000 fps`（**只这一个**）；
- 固件日志里 `[自检] 画面 … PSRAM 读 空载 NNN MB/s` 这个数记下来，记作 **`bw_idle`**；
- 固件日志里 `[自检] 统计` 的三个「帧 N」与 `[自检] IPA 节拍 唤醒=` **都不涨**
  （VideoStreaming 停在 alt 0，统计块与节拍任务全都停着）。

#### 步骤 B：五项全开，连续 10 分钟

**保持终端 1 的 GUD 压测不停**，再依次起：

```bash
# 终端 2 —— HID 键盘（人在旁边随机敲，含六键同时按）
sudo evtest /dev/input/eventK

# 终端 3 —— HID 多点触摸（五指同时按/滑）
sudo evtest /dev/input/eventT

# 终端 4 —— UAC1 播放（10 分钟正弦，同时量播放侧漂移）
sox -n -r 16000 -c 1 -b 16 /tmp/tone600.wav synth 600 sine 440 vol 0.3
time aplay -D plughw:$SND,0 /tmp/tone600.wav

# 终端 5 —— UAC1 录音（**按 wall clock 定时，不用 --duration**，这样才量得到漂移）
timeout 600 arecord -D plughw:$SND,0 -f S16_LE -r 16000 -c 1 -t raw -v /tmp/rec.raw

# 终端 6 —— UVC 摄像头（10 分钟连续取流）
timeout 600 ffplay -f v4l2 -input_format mjpeg -video_size 640x360 \
                   -framerate 10 -fflags nobuffer $VID
```

10 分钟里**终端 1 的 fps 读数继续记**，取摄像头开着这一段的 average，记作 **`fps_B`**。

#### 步骤 C：关掉摄像头，再量 1 分钟

`Ctrl-C` 掉终端 6，保持其余四项。判据见下表第 11 行（「alt 0 零占用」）。

### 判据

> 全部判据必须**同时**满足。任一项不过，先照「上板验证清单」定位到具体阶段，
> **不要在这一场里调参数** —— 复合回归改一个变量就得重跑。

| # | 能力 / 项 | 判据 | 实测 |
|---|---|---|---|
| 1 | GUD 显示 | `/dev/dri/card$CARD` 存在、`modetest` 出图；**摄像头取流时屏幕无撕裂/花屏** | ⏳ |
| 2 | HID 键盘 | `evtest` 收到按键；**六键同时按无丢**（6KRO） | ⏳ |
| 3 | HID 多点触摸 | `evtest` 收到 **5 点**绝对坐标；`ABS_MT_SLOT Max 4` | ⏳ |
| 4 | UAC1 播放 | `aplay` 出声、**无爆音/断续**；`alsamixer` 拖 `PCM Playback` 时声压**当场**变（= 改的是 **ES8388 硬件音量**，不是主机软件衰减） | ⏳ |
| 5 | UAC1 录音 | `arecord` 有波形；`arecord -v` **零 `overrun`** | ⏳ |
| 6 | UVC 出图 | `ffplay` 稳定；`v4l2-ctl --list-formats-ext` 仍**只有** `MJPG 640x360 10.000 fps` | ⏳ |
| 7 | AE（官方 `agc`） | 10 分钟里遮挡/复原三次，`下发 曝光=`/`增益=` 三次都跟着动并**约 1 秒内稳住** | ⏳ |
| 8 | AWB（官方 `awb`） | `ISP 重配 CCM=` 不持续线性增长（换光源时涨、光源不动时停）；`AWB 平均G` 落在 `[98, 210]` | ⏳ |
| 8b | ⭐ IPA 节拍 | 全程 `处理/统计 ≈ 100%`、`单次最多 = 1 条`、`超时兜底` 不涨、`拍数` 频率 ≈30 Hz | ⏳ |
| 8c | ⭐ IPA 栈 | `[自检] IPA 节拍 … 栈余` 在 10 分钟里**不再下降**且 > 512 B（记下最小值） | ⏳ |
| 9 | 端点 / FIFO | `python3 test/check_usb_desc.py build/tab5_aio.elf` OK；`git diff` 里**没有** `usb_descriptors.*` / `tusb_config.h` | ✅ 已验（本轮两档均与 `8d9e68c3` 逐字节一致：384 B / 7 接口、259 B / 6 接口） |
| 10 | 依赖树 | `ls managed_components \| wc -l` == **13**（返工引入 `espressif__esp_ipa`，从 12 变 13） | ✅ 已验 |
| 11 | UVC 帧率 | 连续 10 分钟：`实测 fps ≥ 9.0`、`拒收 = 0`、`丢弃 = 0`、`抢缓冲 = 0`、`取帧超时 = 0`、`帧长不符 = 0` | ⏳ |
| 12 | alt 0 零占用 | 步骤 C 之后：`PSRAM 读 停流后` 回到 `bw_idle` **同量级**；`[自检] 统计` 三个「帧 N」与 ⭐ `[自检] IPA 节拍 唤醒=` **全部停止增长**；`cam_ipa` 那行的 Hz 回到 0 | ⏳ |
| 13 | JPEG 预算 | 平均帧 ≤ 30 KB、**峰值 ≤ 44 KB** | ⏳ |
| 14 | 内存 | LSC 的 4×273×4 = **4368 B** 从内部 RAM heap 分配、IPA 任务栈 4096 B，PSRAM 无变化。记下 `esp_get_free_internal_heap_size()` 的实测值 | ⏳ |

**必须为 0 的计数**（`grep -c` 那个 10 分钟的日志文件）：

| 来源 | 判据 |
|---|---|
| `grep -c 'LZ4 解压失败' /tmp/tab5-fw.log` | **0** |
| `grep -c 'SET_BUFFER .* 丢弃' /tmp/tab5-fw.log` | **0**（压缩方式不支持 / 矩形越界 / length 异常，三种都算） |
| `grep -c 'bulk OUT .* 丢弃\|bulk OUT .* 截断' /tmp/tab5-fw.log` | **0** |
| `[自检] 缩放 … 失败=` | **0** —— PPA 提交被拒。**几乎只有一个原因**：输出缓冲没按 cache line 对齐。它是启动时一次性分配的 ⇒ **要么全失败要么全成功**，中间态不存在 |
| `[自检] 编码 … 失败=` | **0** |
| `[自检] streaming … 拒收=` | **0** |
| `[自检] IPA 节拍 … 超时兜底=` | **0** —— 非 0 说明 AE 硬件统计断供，整条 IPA 掉回 100 ms 兜底节拍（根因看同一行左边的「运行 AE=」） |
| `[自检] IPA 节拍 … 单次最多=` | **1 条** —— ≥2 说明节拍任务没跟上，两份统计被合并成一拍，blob 少看了帧 |

### ⭐ 核心采集项：摄像头开 / 关的 GUD 帧率对比

**这是「打开摄像头会让显示明显变慢」那条推算第一次能被证实或证伪。**

推算链条（README 里已经写着，全部是**推算值**）：

```
周期性传输     172 B/ms  ──开摄像头──▶  584 B/ms
留给 GUD bulk  ~1364 B/ms ─────────────▶  ~916 B/ms      (−33%)
```

| 量 | 来源 | 期望 | 实测 |
|---|---|---|---|
| `fps_A`（摄像头**关**） | 步骤 A 的 average fps | — | ⏳ |
| `fps_B`（摄像头**开**） | 步骤 B 的 average fps | — | ⏳ |
| **`fps_B / fps_A`** | 计算 | **≈ 0.67**（−33%）⇒ 推算被证实 | ⏳ |
| `bw_idle` / `bw_stream` / `bw_stopped` | `[自检] 画面 … PSRAM 读` 三个数 | 取流中比空载掉一两成算正常；**掉一半以上**说明 DPI 面板也在挨饿 ⇒ 重点看 GUD 有没有撕裂 | ⏳ |

判读：

- 比值**明显高于 0.67**（例如 0.9）⇒ 推算高估了摄像头的影响。多半是 GUD 本来就没跑满
  带宽上限（脏矩形 + LZ4 把实际字节数压下去了）⇒ **这是好消息，但要把 README 那段
  「−33%」改成实测值并说明前提**。
- 比值**明显低于 0.67** ⇒ 除了 USB 带宽还有别的争用源。第一嫌疑是 **PSRAM**
  （看 `bw_idle` → `bw_stream` 掉了多少），第二嫌疑是 **PPA 引擎信号量**
  （`[自检] 缩放 耗时` 就是 `display_blit()` 可能被顶住的时长上界 ——
  **显示掉帧时先看这个数，别一上来就怪带宽**）。
- 两个 fps 都很低（< 5）⇒ 先排除主机侧：`fpsdisplaysink` 量的是**主机送出去的帧**，
  GUD 是 bulk 传输、天然反压，主机侧 CPU 或 `videoconvert` 也可能是瓶颈。

### ⭐ P3 欠账：无反馈端点的时钟漂移

本工程**坚决不用显式反馈端点**（最后一条 IN `0x84` 留给了 UVC），
代价就是主机与设备的采样时钟只能各走各的。10 分钟是能把漂移量出来的最短窗口。

| 方向 | 测法 | 判据 | 实测 |
|---|---|---|---|
| 录音 | `timeout 600 arecord … -t raw /tmp/rec.raw` 之后 `ls -l /tmp/rec.raw` | 期望 `600 × 16000 × 2 = 19 200 000` 字节，**偏差 < 0.1%（±19 KB）** | ⏳ |
| 播放 | `time aplay /tmp/tone600.wav`（600 秒正弦） | 实际耗时与 600 s 偏差 **< 0.1%（±0.6 s）** | ⏳ |
| 主观 | 全程听 | **无爆音、无周期性断续**（漂移累积到一个缓冲长度时会周期性丢/补） | ⏳ |
| 客观 | `arecord -v` 的输出 | **零 `overrun`**；`dmesg \| grep -i 'snd\|usb' ` 无新增错误 | ⏳ |

> 偏差超 0.1% 时：先确认主机不是在做重采样（`plughw:` 会自动重采样，
> 换成 `hw:` 重测一次 —— `hw:` 下参数不匹配会直接报错，反而是更干净的判据）。
> 确认是设备侧漂移之后，**处置不是加反馈端点**（端点用满了），而是记进 README 当作
> 已知代价，或把数据泵改成按主机节奏丢/补一个采样。

### ⭐ P0 欠账：脏矩形 + LZ4 的定量验证

Linux console 的文本渲染已经在走脏矩形路径且显示正常，但从未定量确认过。
步骤 A / B 的 `videotestsrc` 全屏动态内容是**最坏情况**（几乎每帧整帧脏区），
再补一个**典型情况**：

```bash
# 把文本终端绑到 GUD 卡，跑 vim / htop / 滚屏
sudo chvt 2   # 或直接把某个 tty 的 fbcon 绑到该 card
```

| 项 | 判据 | 实测 |
|---|---|---|
| `LZ4 解压失败` | **0 条**（全程） | ⏳ |
| `ppa srm 失败`（= `[自检] 缩放 失败=`） | **0** | ⏳ |
| 场景 A：全屏动态内容的 fps | 就是 `fps_A` / `fps_B` | ⏳ |
| 场景 B：文本终端的体感 | 「打字无感延迟 / 滚动可见撕裂」这类描述 —— 这才是「USB 瘦终端」的真实使用场景 | ⏳ |

### 失败时的归因顺序

1. **先看固件日志的第一条不对的自检行** —— 六行 `camera` / 四行 `uvc` 是从上往下读的，
   「有没有帧」→「帧对不对」→「帧有没有发出去」；
2. **再看是不是某一项能力单独就不行** —— 停掉其余四项，只跑那一项。
   单跑就不行 ⇒ 不是复合回归的问题，回到「上板验证清单」对应阶段；
3. **只有五项同跑才不行** ⇒ 才是带宽 / 帧泵预算 / PSRAM 争用。
   按「`[自检] 缩放 耗时` → PSRAM 三个数 → USB 周期性带宽账」的顺序查；
4. ⚠️ **不要在这一场里改参数**。改一个变量就得整场重跑 —— 记下现象，回到对应阶段单独调。

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
| `main/Kconfig.projbuild` | 两项：`CONFIG_AIO_DEBUG_CDC`（默认 n，**让出 GUD 的 IN 端点 + 整个音频不编译**，换 USB 日志串口；`0x84` 永久归 UVC）与 `CONFIG_AIO_CAM_IPA`（默认 **y**，官方画质算法总开关；关掉 = ISP 只做去马赛克，**不是**回退到自研算法）；音频在默认档下无条件编译，排障旋钮已删除 |
| `main/uvc_stream.{c,h}` | UVC 类回调（commit / streaming）+ 帧泵任务（100 ms 一拍，**不再驱动 IPA**）+ CSI 按 alt 0/1 启停 + 四行自检统计 |
| `main/camera_csi.{c,h}` | SC202CS 探测（SCCB `0x36`）+ MIPI-CSI + ISP（RAW8→RGB565 去马赛克）+ **三块硬件统计（AE 5×5 / AWB 白点 / 直方图，连续模式 + ISR 回调）** + **IPA 节拍任务**（AE 的 ISR 当拍子，30 Hz，100 ms 兜底）+ PSRAM 读带宽实测，产出 1280×720 RGB565 |
| `main/cam_jpeg.{c,h}` | PPA SRM ×0.5 缩小（**独立 client**，不共用显示那个）+ 硬件 JPEG 编码（RGB565 / 4:2:2 / q=70），双缓冲 |
| `main/cam_ipa.{c,h}` | **官方 `esp_ipa` 的消费侧**：建 pipeline（标定键 `"SC202CS"`）、送统计、把 metadata 按 `IPA_METADATA_FLAGS_*` 逐位分发到 ISP（BF / Demosaic / SHARP / gamma / CCM+RG+BG / Color / LSC）与传感器（曝光 + 增益，走 `GROUP_EXP_GAIN`）。**本工程一行画质控制律都不写**；rev v1.0 的 BLC/WBG 能力门与被忽略的几个 flag 也在这里 |
| `main/cam_frame_stats.{c,h}` | 帧统计纯函数（亮度均值/最暗/最亮/分通道均值/FNV-1a 校验和），零依赖。**纯观测量，不参与任何控制** |
| `main/uvc_pattern.{c,h}` | 合成彩条 + 移动方块，零依赖纯函数。**已不在固件 `SRCS` 里**（Task 9 换成真实摄像头），保留作静态测试图的生成源与宿主机测试对象 |
| `main/uvc_test_jpeg.h` | 静态测试图 JPEG 字节数组（`test/jpeg_to_header.py` 机械生成，注明来源） |
| `test/test_cam_frame_stats.c` | 帧统计纯函数的宿主机回归（24 用例） |
| `test/test_uvc_pattern.c` | 合成图案纯函数回归 + PPM 预览 |
| `test/jpeg_to_header.py` | 把一张 `.jpg` 机械转成 `uvc_test_jpeg.h` |
| `test/check_usb_desc.py` | 从 ELF 抠出 USB 描述符自行解析校验（**两档都要过**，含全部 UVC 断言） |
| `main/codec_audio.{c,h}` | ES8388/ES7210 初始化 + I2S 全双工 + UAC 数据泵 + TinyUSB 音频类回调（含 Feature Unit 的音量/静音落到 ES8388 硬件）+ `codec_audio_report()` 开机自检快照 |
| `main/audio_frame.{c,h}` | USB 单声道 ↔ I2S 立体声转换，零依赖纯函数（宿主机可测） |
| `main/uac_volume.{c,h}` | UAC1 音量(有符号 1/256 dB) ↔ `esp_codec_dev` 百分比 的换算 + 线上小端编解码，零依赖纯函数（宿主机可测）；含 MIN/MAX/RES 取值理由 |
| `test/test_uac_volume.c` | 音量换算的宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tinyusb_config/tusb_config.h` | `include_next` esp_tinyusb 默认配置后追加 `CFG_TUD_AUDIO_*`（它没开放 Audio 类） |
| `test/test_touch_map.c` | 触摸坐标变换与报告装填的宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tab5_pins.h` | 板级 GPIO / 面板与 GUD 尺寸常量（含放大倍数的静态断言） |
| `sdkconfig.defaults` | 目标/PSRAM/分区/控制台/vendor 类、芯片版本互斥的说明，以及末尾默认注释掉的 CDC 调试串口开关 |
| `partitions.csv` | factory 分区 4 MB |
| `main/idf_component.yml` | 依赖精确锁版：esp_tinyusb / tinyusb / io_expander / 两个面板驱动 / esp_codec_dev / esp_cam_sensor / **esp_ipa**（含「为什么不引 `esp_video`、为什么 `esp_ipa` 可以单独引」的逐条依据） |

设计与路线：见仓库
`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` 与
`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`。
