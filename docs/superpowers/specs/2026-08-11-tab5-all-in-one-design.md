# Tab5 all-in-one 设计（M5Stack Tab5 / ESP32-P4）

把 `components/packages/cardputer-all-in-one` 的「USB 瘦终端」形态适配到 **M5Stack Tab5**：
一根 USB-C 线接到 flange 嵌入式 Linux 主机，Tab5 同时充当 USB 显示屏 + USB 键盘 + USB 触摸屏
+ USB 麦/扬声器 + USB 摄像头，**host 侧零自定义驱动**（全部走 mainline class driver）。

新建独立包 `components/packages/tab5-all-in-one/`，与 `cardputer-all-in-one` 平行，
**不修改 Cardputer 侧任何代码**。

---

## 1. 目标硬件事实（已核实）

| 项 | 值 | 来源 |
|---|---|---|
| 主控 | ESP32-P4NRW32，RISC-V 双核 360 MHz + LP 核 40 MHz | M5 官方文档 |
| 存储 | 16 MB Flash / 32 MB PSRAM | 同上 |
| 面板 | **原生 720×1280 竖屏**，MIPI-DSI **2 lane @ 1000 Mbps**，RGB565 | esp-bsp `bsp/display.h` |
| 面板控制器 | **ILI9881C 或 ST7123**（随批次） | esp-bsp README / `bsp_display.c` |
| 触摸 | GT911 (0x14) 或 ST7123 (0x55)，内部 I2C，INT = G23 | M5 文档 / esp-bsp |
| 内部 I2C | SDA = G31，SCL = G32 | esp-bsp `m5stack_tab5.h` |
| 音频 | ES8388 (0x10) codec + ES7210 (0x40) 双麦前端 | esp-bsp README |
| I2S | MCLK=G30，SCLK=G27，LRCK=G29，**DOUT=G26 / DSIN=G28** | esp-bsp `m5stack_tab5.h` |
| IO 扩展 | PI4IOE5V6408 ×2 (0x43 / 0x44) | esp-bsp |
| 背光 | G22 | esp-bsp |
| DSI PHY 供电 | 内部 LDO **VO3 @ 2500 mV** | esp-bsp `display.h` |
| 键盘 | Tab5 Keyboard，I2C **0x6D**，SDA=**G0** / SCL=**G1** / INT=**G50**，14×5=70 键 | M5 文档 |
| 摄像头 | SC202CS 2 MP，MIPI-CSI | esp-bsp README |
| UART0 | TXD=G37 / RXD=G38（引到 M5-Bus） | 原理图网络名 |
| BOOT | G35 | 原理图网络名 |

### 1.1 决定性发现：USB-C 只有全速 12 Mbps

逐网络核对官方原理图（`Tab5_Schematics_PDF.pdf` 第 4 页）：

```
USB-C (J8) ── USBIN_DP/DM ── R94/R95(0Ω) ── FT1 ── R111/R112(33Ω)
           └─→ 网络 USB_DEVICE_DP/DM → ESP32-P4 pin 52/53 = GPIO24/25 = USB1P1
                                        （USB 1.1 全速 PHY，与 USB-Serial/JTAG 共用）

USB-A (J10) ── R113/R114(33Ω) ── T2
           └─→ 网络 USB_HOST_DP/DM  → ESP32-P4 pin 49/50 = USB2_OTG_D±
                                        （USB 2.0 高速 PHY）
```

ESP32-P4 数据手册确认：pin 49/50 = `USB_DM`/`USB_DP` 属 USB2 OTG（高速）PHY；
GPIO24/25 = `USB1P1_0-/+`，默认归 USB Serial/JTAG。

**结论：能当 device 用的 USB-C 是 12 Mbps 全速；480 Mbps 高速口被接到了 USB-A 母座。**
本设计的全部带宽取舍都由这一条推导而来。

### 1.2 由此产生的三条硬约束

| 约束 | 后果 |
|---|---|
| USB device 侧只有 12 Mbps | 显示不走 720p 原生，改 **640×360 + 硬件放大**（§3） |
| TinyUSB 接管 FS PHY 后失去 USB-Serial/JTAG | 烧录须按 **BOOT(G35)** 进 ROM 下载；日志走 **UART0 G37/G38**（不与显示/音频争引脚，优于 Cardputer 的无控制台状态） |
| FS OTG 端点数有限 | **键盘与触摸合并为一个 HID 接口**，用 Report ID 区分（§5） |

---

## 2. USB 复合设备布局

VID/PID 沿用 **`16d0:10a9`** —— mainline `drm/gud` 绑定的固定 modalias，必须保留。
设备描述符为 Misc/IAD 复合设备，与 Cardputer 同构。

| 接口 | 类 | 端点 | host 侧 mainline 驱动 |
|---|---|---|---|
| IF0 | Vendor / **GUD** | bulk OUT (+IN) | `drm/gud` → `/dev/dri/cardN` |
| IF1 | **HID** 复合（RID 1 = 键盘，RID 2 = digitizer） | int IN ×1 | `usbhid` + `hid-multitouch` |
| IF2–IF4 | **UAC1** AudioControl + AS-out + AS-in | iso OUT `0x02`, iso IN `0x83` | `snd-usb-audio` → ALSA |
| IF5–IF6 | **UVC** VideoControl + VideoStreaming（MJPEG） | iso IN `0x84` | `uvcvideo` → `/dev/videoN` |

> **订正（阶段 4 落地时）**：本表原先把 UAC 排在 IF1–IF3、HID 排在 IF4。实际落地是
> **IF0 vendor / IF1 HID / IF2–IF4 UAC** —— 键盘与多点触摸都已实机验证通过，
> 没有理由为排版去动它们的接口号；IAD 只要求它覆盖的接口连续，不要求排在最前。
> 端点号同样刻意不动（vendor `0x01/0x81`、HID `0x82`）。
>
> 另一条阶段 4 才查清的硬约束：**绝不引入显式反馈端点** —— 它会占掉第 4 条 IN
> 端点 `0x84`，而那一条要留给 UVC。16 kHz 整数 samples/ms 让 adaptive OUT +
> asynchronous IN 就够用。详见 `firmware/README.md`。

端点预算：IN = vendor / audio / HID / UVC 共 4 条 + EP0；OUT = vendor / audio 共 2 条 + EP0。
落在 FS 控制器预算内。**若阶段 0 实测端点不足**，按此顺序降级：
1. 去掉 vendor 的 IN 端点（GUD 只用 EP0 控制 + bulk OUT，IN 端点是 `TUD_VENDOR_DESCRIPTOR` 顺带声明的）；
2. 砍 UVC（见 §7）。

> **订正（阶段 5 落地时）**：三条。
>
> 1. **UVC 落在 IF5–IF6，`0x84` 已用满**（默认档 7 接口 / 384 字节配置描述符）。
>    4 条非 EP0 的 IN 端点 **4/4 用尽**，不得再加任何 USB 功能。
> 2. **FIFO 可分配的是 242 words，不是 256。** `dcd_dwc2.c` 的 `dfifo_device_init()`
>    在 buffer DMA 模式下先扣 `2 × ep_count = 14`，而本工程 `CONFIG_TINYUSB_MODE_DMA=y`
>    且 P4 OTG1.1 的 `ghwcfg2.arch == 2`（internal DMA），两个条件都成立。
>    UVC ISO IN 取 448 字节（112 words），余 11 words —— 没取满 492 是因为
>    `dfifo_alloc()` 失败**无任何日志**，且 448 在 DMA/slave 两种模式下都装得下。
> 3. **`CONFIG_AIO_DEBUG_CDC` 的语义变了**：它原先借走 `0x84`，与 UVC 直接撞号。
>    现在这一档改为**整体不编译音频**换出一条 IN 端点，`0x84` 永久归 UVC
>    （调试档 6 接口 / 259 字节）。有 USB-TTL 时优先接 **UART0(G37/G38)** ——
>    零端点代价、能抓上电最早的日志、默认档也能用。

### 2.1 带宽是零和的

同步（isochronous）带宽只在 host 选中**非 0 的 alternate setting** 时才预留。因此：

- 不开摄像头、不放音时，12 Mbps 全归 GUD 的 bulk 传输；
- UVC + UAC + GUD 三者同时使用会明显互相拖慢，这是全速口的物理上限，不是实现缺陷。

该取舍必须写进包的 README，避免使用者误判为 bug。

> **阶段 5 补充**：这条在实现上有**两个**落点，缺一不可。
>
> - **USB 侧**：VideoStreaming 接口停在 alt 0（零端点、零带宽），host 不预留 ISO 带宽；
> - **PSRAM 侧**：CSI **只在 host 选中 alt 1 时才 start** —— 否则 CSI 那 ≈55 MB/s 的
>   PSRAM 写入会直接和 DPI 面板刷新的 ≈110 MB/s 读抢带宽。
>
> 带宽账（1500 字节/毫秒）：摄像头开着时周期性传输从 172 B/ms 涨到 584 B/ms，
> 留给 GUD bulk 的理论上限从约 1364 掉到约 916 B/ms（**−33%**）。
> ⏳ **实测值尚未取得**（阶段 5 的 Task 10 未执行），此处只有推算，不得当作实测引用。

---

## 3. 显示：640×360 → PPA（2× 缩放 + 旋转 90°）→ 720×1280

### 3.1 为什么是 640×360

720p RGB565 整帧 = 1.84 MB；全速实测吞吐约 1 MB/s ⇒ 整屏刷新约 1.8 秒，交互不可用。
640×360 整帧 = 460 KB，且相对面板是**整数 2 倍**，硬件放大无插值伪影。

GUD descriptor 只声明**单一模式 640×360 / RGB565**，标记 `PREFERRED`，
声明 `GUD_COMPRESSION_LZ4`（host 逐帧择优，压缩与未压缩两条收帧路径都要处理）。

### 3.2 流水线

```
host ──(bulk OUT, 可选 LZ4)──▶ s_fb: 640×360 RGB565 (PSRAM)
                                 │
                                 ├─ LZ4_decompress_safe（压缩帧）
                                 │
                                 ▼  PPA SRM 单次操作
                          scale 2.0 + rotate 90°
                                 │
                                 ▼
                    DPI 帧缓冲: 720×1280 RGB565 (PSRAM)
                                 │
                                 ▼  MIPI-DSI 2 lane @ 1 Gbps
                              面板
```

- **一次 PPA 操作同时完成缩放与旋转**：ESP32-P4 的 PPA 是 SRM（Scale-Rotate-Mirror）引擎，
  `ppa_do_scale_rotate_mirror()` 的 `scale_x/scale_y` 与 `rotation_angle` 可同时生效，
  无需两遍搬运。这是选 PPA 而非软件缩放的核心理由。
- **脏矩形**：GUD 的 damage 矩形在 640×360 横向坐标系；PPA 的输出块偏移
  （`out.block_offset_x/y`）按「×2 后再旋转 90°」映射到 720×1280 竖向坐标系，
  只放大变化区域，不做全屏重算。坐标变换是本阶段最容易写错的地方，需单独验证。
- **不做 byteswap**：`BSP_LCD_BIGENDIAN=0`、`COLOR_SPACE=RGB`，
  Cardputer 上为抵消 ST7789 4-line SPI 字节序而加的 per-pixel `bswap16` 在这里必须**删除**。

### 3.3 面板 bring-up（自建薄板级驱动）

不依赖 `espressif/m5stack_tab5` BSP 组件（它会拖入 LVGL / esp_video / usb-host 依赖树）。
自己写 `display_dsi.c`，参数照 esp-bsp `bsp_display.c` 复刻（Apache-2.0，代码头注明来源）：

```
LDO VO3 @ 2500 mV  →  esp_lcd_new_dsi_bus(2 lane, 1000 Mbps)
                   →  esp_lcd_new_panel_io_dbi
                   →  esp_lcd_new_panel_<ili9881c|st7123>(dpi_config, init_cmds)
```

DPI 时序（两种面板二选一）：

| 面板 | dpi_clk | hbp / hpw / hfp | vbp / vpw / vfp |
|---|---|---|---|
| ILI9881C | 60 MHz | 140 / 40 / 40 | 20 / 4 / 20 |
| ST7123 | 70 MHz | 40 / 2 / 40 | 8 / 2 / 220 |

**两种面板都要支持**，型号在**运行时**由 I2C 探测决定（探到 0x55 ⇒ ST7123；
探到 0x14 ⇒ GT911 + ILI9881C），两条初始化路径都编进固件，两个驱动组件
（`esp_lcd_ili9881c` + `esp_lcd_st7123`）都进依赖。

> 权衡已知并接受：两份 vendor init 命令数组合计近 12 KB 源码，且**只有实机那一份
> 能被验证**，另一份属于「照 esp-bsp 复刻但未上板」的状态。代价是固件体积与
> 一份不可验证的数据；收益是同一份固件对两个批次的 Tab5 都能开箱即用，
> 不需要按批次分别构建。这是产品侧的取舍，由使用者拍板。
>
> 实现上要求：未验证的那条路径必须在日志里明确标注（如
> `panel ST7123 (未经实机验证的路径)`），避免日后有人误以为两条都验过。

对外接口与 Cardputer 保持同名同形，便于对照：`display_init()` / `display_blit(x,y,w,h,pixels)`。

---

## 4. 键盘：Normal 模式 + vendor 官方键位表

Tab5 Keyboard 是独立的 STM32F030 I2C 从机（0x6D），挂在 **G0(SDA)/G1(SCL)**，
与内部 I2C（G31/G32）**物理分离**，需单独初始化一条 I2C 总线。中断线 **G50**。

### 4.1 不用键盘固件自带的 HID 模式

读 M5 官方固件 `M5Tab5-Keyboard-Internal-FW`（MIT）的 `user_keyboard_handle.c` 后确认，
HID 模式（寄存器 0x30）有两个硬伤：

1. **修饰键不进队列**：Ctrl / Alt / Sym / Aa 被标记为 `special_key`，只更新内部
   `modifier_mask`，不产生 HID 事件 ⇒ host 永远看不到「单独按住 Ctrl」；
2. **一次只能表达一个键**：按下推 `{modifier, keycode}`，松开推 `{modifier, 0}`，
   没有多键同时按下的表达能力。

对「Linux 终端」这个用途，组合键与按住状态都是刚需，故不采用。

### 4.2 采用 Normal 模式自建状态机

- 写寄存器 `0x10` 的 Keyboard 字段 = 0（Normal 模式）；
- 读寄存器 `0x20`：1 字节事件 —— bit7 = 按下(1)/释放(0)，bit[6:4] = 行(0~4)，bit[3:0] = 列(0~13)；
  队列空读回 `0xFF`；
- 寄存器 `0x00` 的 `EVENT_NUM` 给出队列长度，用于**一次中断内排空队列**；
- **G50 下降沿中断驱动**读取，不做定时轮询，避免占用 I2C 与 CPU；
- 固件自己维护「当前按下键集合」→ 生成标准 **6KRO** HID 报告。

行列 → HID usage 的 5×14 映射表从官方 `key_value_map`（MIT）vendor 进
`tab5_kbd_map.h`，注明来源与许可。语义分层与 Cardputer 的 `hid_keyboard.c` 一致：

- Ctrl(4,0) / Alt(4,1) → HID modifier 位（`LEFTCTRL` / `LEFTALT`），不占 keycode 槽；
- Sym(3,0) / Aa(3,1) → **本地层**，切换到映射表的 second 层（`secondModifierMask` / `secondKeyCode`），
  不向 host 上报；
- 其余键 → 查表得 `{modifier, keycode}`，合并进报告。

### 4.3 已知取舍

官方表里 Sym 与 Aa 的 `firstKeyCode` 都是 `KEY_LEFTSHIFT`，但在本设计中它们是本地层键、
不作为 Shift 上报；大小写与符号由本地层查表产生对应的 `modifier | keycode` 组合发给 host。
这样 host 收到的是标准键盘语义，不需要任何特殊配置。

### 4.4 实机验证结论（P1 Task 5）

**Normal 模式 + 自建状态机方案实机验证通过**：键盘输入在 GUD 显示的 Linux console 上正常。

实施阶段（P1 Task3）发现并绕开了两个上游语义陷阱，回归用例见
`firmware/test/test_kbd_translate.c`：

1. **底行字母 `firstModifierMask` 陷阱**：官方 `key_value_map` 里 `z x c v b n m` 的
   `firstModifierMask` 是 `KEY_MOD_LSHIFT`（第 0–3 行字母都是 `KEY_MOD_RESERVED`），但官方
   `convert_to_hid()` 的小写分支根本不读这个字段。若实现无条件取用该字段，整个底行会打出
   大写。`kbd_translate.c` 对字母基础层硬写 `mod = 0`，与官方语义一致。
2. **Aa 未被 Ctrl/Alt 门控**：若不排除，按住 Aa 时 `Ctrl+C` 会变成 `Ctrl+Shift+C`
   （终端里前者是 SIGINT、后者通常是「复制」）。`kbd_translate.c` 取
   `aa = pressed[ROW_AA][COL_AA] && !ctrl && !alt`，且 ctrl/alt 状态取自当前按下集合，
   不取正在累加中的 `modifier`。

---

## 5. 触摸：与键盘共用一个 HID 接口

- 控制器随面板批次为 GT911(0x14) 或 ST7123(0x55)，在内部 I2C（G31/G32）上，INT = G23；
  与 §3.3 的面板探测**同一次探测**决定，直接依赖 `espressif/esp_lcd_touch_gt911`
  或 `espressif/esp_lcd_touch_st7123`。
- 以 **HID digitizer（绝对坐标，最多 5 点）** 上报，host 侧由 mainline `hid-multitouch` 处理。
- **坐标要做与显示相同的 90° 变换**：触摸控制器按面板原生 720×1280 竖向坐标出数，
  而 host 的显示内容是横向的 —— 二者必须落到同一可视坐标系，否则触摸与画面错位。
- 与键盘共用同一个中断 IN 端点，靠 Report ID 区分（RID 1 键盘 / RID 2 digitizer），
  省下一条 IN 端点（见 §2 端点预算）。接口号在 §2 的**最终**布局里是 IF4；
  UAC/UVC 尚未落地，当前实现里 HID 就是 **IF1**（`ITF_NUM_HID`，端点 `0x82`）。

### 5.1 实施订正（P2）

原文写「变换方向与是否需要镜像，在阶段 3 用实机标定」—— **实际不需要标定**：
官方 esp-bsp `bsp/m5stack_tab5/src/bsp_display.c` 的 `tp_cfg` 已给出取值
（`x_max/y_max = 720/1280`、`swap_xy / mirror_x / mirror_y` 三个 flag 全 false），
即 GT911 就按面板原生 720×1280 竖向出数，直接套 §3.2 显示正变换的反解即可。
这条订正在实施中已确认（commit `9a4b54d6`）。

原文没有提到、但**实际是本阶段最大障碍**的一点：**INT(G23) 不是用来接中断的，
而是必须被 ESP 侧主动驱动为低**。Tab5 v1 硬件在该脚上有一颗到 3V3 的上拉电阻，
会压住 GT911 不置位 buffer-ready，表现为**完全静默**（I2C 通、初始化成功、
一个坐标都读不到）。修法是「G23 配成输出并拉低」+「`tp_cfg.int_gpio_num` 填
`GPIO_NUM_NC`」两句缺一不可 —— 只做前者会被 GT911 驱动重新 `gpio_config()` 成 INPUT
而失效。代价是放弃中断驱动，改为 20ms 轮询（触摸是状态量、不怕丢边沿，无影响）。
根因与 Plan B 详见 `firmware/README.md` 的「HID 多点触摸」章节。

### 5.2 实机验证结论（P2 Task 5）

在 `khadas-vim3l`（arm64）上用 `evtest` 验证：

- 设备枚举为 `bus 0x3 vendor 0x16d0 product 0x10a9`，名为 `flange Tab5 USB Terminal`；
- **`hid-multitouch` 正常绑定**，且**键盘仍是独立的 input 设备**
  （`flange Tab5 USB Terminal Keyboard`）—— 二者共用一个 HID 接口不冲突，
  §2 靠 Report ID 省一条 IN 端点的设计成立；
- 能力表含 `ABS_MT_SLOT`（Max 4）、`ABS_MT_POSITION_X/Y`（均 Max 32767）、
  属性 `INPUT_PROP_DIRECT`；
- `ABS_MT_SLOT` 的 Max 4（= `TOUCH_CONTACTS_MAX` − 1）证明 **Contact Count Maximum
  那份 Feature 报告被内核读到了**，而不是退回 `hid-multitouch` 的默认值 10；
- **多点触摸已验证：实测三指同时接触**，分别落在 slot 0/1/2，各有独立且稳定的
  `ABS_MT_TRACKING_ID`，坐标各自独立更新。⚠️ **4/5 指未验证**。

**四角坐标标定：已实机验证通过。** 依次点四角，X 与 Y 各自都能跑到接近 0 与接近 32767，
反变换与轴向都对。（曾有一次抓取里所有触点的 Y 都落在满量程的 78%–99%，一度疑似 Y 轴
映射问题；四角标定通过 ⇒ 那是当时手指位置所致。再遇到类似偏态分布，先按四角标定复核。）

坐标算式本身有宿主机纯函数回归测试（`firmware/test/test_touch_map.c`，32 用例，
含与显示正变换的往返一致性）。

---

## 6. 音频：UAC1 全双工

- ES8388(0x10) 播放 + ES7210(0x40) 采集，经 `esp_codec_dev` 初始化；
- I2S 收发数据线**物理独立**（DOUT=G26 / DSIN=G28）⇒ **真全双工**，
  Cardputer 上因 GPIO43 被扬声器 WS 与麦克风 PDM CLK 共享而写的**半双工仲裁逻辑整体删除**；
- UAC1 参数沿用 Cardputer 的 mono 16 kHz / 16 bit / `S16_LE`，
  描述符宏（`UAC1_AUDIO_DESCRIPTOR`）可整体照搬；
- **补：采样率是 FIFO 账定的，不是听感定的。** 全速控制器整块 dfifo 只有 256 words，
  16 kHz 单声道的 OUT 包 36 B **小于 vendor 已有的 64 B ⇒ 共享 RX FIFO 一个 word 都不涨**，
  整个音频功能只花录音那 9 words；48 kHz 立体声会把余量压到 15 words，UVC 直接没位置；
- **补：两个方向必须同采样率/位宽/slot 数** —— 全双工的 I2S TX/RX 共用 BCLK 与 WS，
  要跑不同速率就得占两个 I2S 端口，而 Tab5 的 SCLK/LRCK/MCLK 物理上只有一组；
- 喇叭功放使能在 IO 扩展芯片的 `SPEAKER_EN`（PI4IOE5V6408 P1，`0x43`）——
  功放**没有**独立 GPIO（esp-bsp 的 `BSP_POWER_AMP_IO = GPIO_NUM_NC`），
  上电顺序定死为「codec 配完 + 解除静音 → 延时 50 ms → 才开功放」（避免开机 pop），
  与 esp-bsp 自身的顺序相反，刻意不照抄；
- **实机状态（阶段 4）**：播放与录音**均已验证**（喇叭出声、录音正常）；
  **未验证**：全双工同时收发的长时间稳定性、对 GUD 帧率的影响、无反馈端点的时钟漂移。
  过程中最贵的一个坑是「配 G26/G27 会让 IDF 的 `gpio_ll_func_sel()` 误关 USB-C 焊盘」，
  机理与修法见 `firmware/main/tab5_pins.h` 与 `firmware/README.md`。

---

## 7. 摄像头：UVC MJPEG（最后阶段，允许砍掉）

- SC202CS 经 MIPI-CSI 取流；P4 有**硬件 JPEG 编码器**，编码不占 CPU；
- 经 TinyUSB video class 以 **MJPEG 640×360 @ 10 fps** 输出，ISO IN `0x84`、448 字节/帧；
- **这是全场风险最高的一项**：TinyUSB 的 UVC device 支持相对小众，
  `esp_tinyusb` 也没有对应 Kconfig，需通过现有的 `main/tinyusb_config/tusb_config.h`
  覆盖机制手工开启 `CFG_TUD_VIDEO`（**且必须同时定义 `CFG_TUD_VIDEO_STREAMING`**，
  只定义前者会让 `video_device.c` 编成空文件、链接期缺 6 个符号）；
- 排在最后一个阶段；**若阶段 5 判定不可行，直接砍掉，不阻塞前四项已交付的能力**。

### 7.1 ⛳ 订正一：分辨率是 **640×360**，不是本节原写的 640×480（阶段 5 落地）

**不是带宽不够** —— 640×480 在 10 fps 上每帧预算 44.6 KB，而典型 MJPEG 4:2:2
中等质量是 23–38 KB，带宽上本来是够的。做不到的原因是**像素管线**，三条叠在一起：

1. **SC202CS 唯一可用的模式是 1280×720（16:9）** —— 它四个模式全是 RAW，
   1600×1200 的 1200 行超过 P4 ISP 的 1920×1080 输入上限，1600×900 裁不出 4:3；
2. **P4 的 ISP 没有缩放器**（`esp_driver_isp` 只有 `isp_crop.h`），只能裁不能缩；
3. **唯一的缩放器 PPA，缩放比粒度是 1/16** —— `1280×720 → 640×360` 是精确的
   8/16；而 640×480 要「裁 960×720 再乘 2/3」，**2/3 表达不出来**（最近的 11/16
   给出 660×495）。

⇒ 640×360 是这条管线上唯一既精确、又不改变视野与宽高比的输出尺寸。
附带好处：与 §3 的 GUD 显示模式同为 640×360，整个包里只有一个分辨率要记；
且 640 与 360 都整除 4:2:2 的 MCU（16×8），编码器不需要补边
（4:2:0 的 MCU 是 16×16，360 不整除 —— 这是选 4:2:2 子采样的直接原因）。

### 7.2 ⛳ 订正二：**不用 `esp_video`**，改用 `esp_cam_sensor` + IDF 内置 CSI/ISP/JPEG/PPA

本节原文与 §8.1 的依赖表都写的是 `esp_video`。**实测其组件 manifest 后这条被推翻**：

```
espressif/esp_video 2.3.0 依赖：
  espressif/esp_cam_sensor、espressif/esp_ipa、
  espressif/esp_h264      1.3.0    ← 纯软件 H.264 编码器
  espressif/usb_host_uvc  2.5.*    ← ⚠️ USB **Host** 栈
```

在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB **Host** 栈，
是 §8.1「不引入 usb-host 依赖」的正面违反；`esp_h264` 同理。

**实际路线 = 「薄板级驱动 + vendor 传感器寄存器序列」**，与 §3.3 面板、§6 codec 完全同构：

| 层 | 用什么 |
|---|---|
| SC202CS 寄存器序列 | `espressif/esp_cam_sensor`（传递依赖只有 `esp_sccb_intf` + `cmake_utilities`） |
| MIPI-CSI / ISP / JPEG 编码 / 缩放 | IDF 内置 `esp_driver_cam` / `esp_driver_isp` / `esp_driver_jpeg` / `esp_driver_ppa` |
| 取流编排、AE/AWB 控制律 | 自己写的 `camera_csi.c` / `cam_tune.c` |

**实测依赖树 `managed_components/` 仍是 12 个目录**（相对阶段 4 只多出
`espressif__esp_cam_sensor` 与 `espressif__esp_sccb_intf`，`cmake_utilities` 早已在树里）。

### 7.3 ⛳ 订正三：AE 做了闭环，AWB 也做了 —— 但**不引 `esp_ipa`**

阶段 5 的计划原本写「不做 AE/AWB 闭环，用传感器默认曝光增益，代价是换光照会
过曝/欠曝」。实际落地时这条被现场推翻（实机首图「整体发绿 + 亮度均值 45 已削顶」），
于是自己写了两个控制器，**仍然没有引 `esp_ipa`**：

- **AE**：曝光量 `ev = 曝光 × 增益` 合成一个标量做 P 控制，分配上曝光优先、增益垫底；
  四道防振荡闸（死区 / 阻尼 / 单步限幅 / 更新周期），状态里存**量化后的实际 ev**；
- **AWB**：灰世界反推 `diag(kr, 1, kb)` 的对角增益，经 **CCM** 施加 ——
  本板 P4 rev v1.0 的硬件白平衡增益（WBG）有 rev≥3.0 的版本门，用不了，
  **CCM 是唯一能给三通道分别加增益的地方**（上限 4.0）。四道灰世界防护挡单色场景。

控制律全在不依赖 ESP-IDF 的 `cam_tune.c` 里，宿主机 281 个用例覆盖。
机理、参数与标定流程见 `firmware/README.md` 的「UVC 摄像头」章节。

### 7.4 实机验证结论（阶段 5）

| 项 | 状态 |
|---|---|
| UVC 链路（MJPEG 640×360 @ 10 fps，ISO IN `0x84` × 448 B） | ✅ 已实机验证：`ffplay` 出图、零拒收、每 10 秒精确 +100 帧、提交 == 完成 |
| 硬件 JPEG 实时编码（RGB565 输入 / 4:2:2 / q=70） | ✅ 已实机验证 |
| SC202CS 探测（SCCB `0x36`，PID `0xeb52`） | ✅ 已实机验证 `detect=1` |
| MIPI-CSI + ISP 取流 1280×720 RAW8 → RGB565 | ✅ 已实机验证：30 fps 稳定、抢缓冲/丢弃/取帧超时全 0、帧长 1843200 正确、亮度跟手 |
| PPA 2× 缩小接入 UVC | ✅ 已实机验证：`ffplay` 出真实摄像头画面 |
| **AE 闭环** | ✅ 已实机验证 |
| **AWB 闭环** | ⏳ **未上板** —— 只过了 281 个宿主机用例。`CAM_AWB_ENABLE=0` 可退回已验证的静态白平衡 |
| 单色场景防护的实际效果 | ⏳ 未上板 |
| 五项能力的复合回归（同跑 10 分钟） | ⏳ **未做** —— 阶段 5 计划的 Task 10 |
| 摄像头开着时对 GUD 帧率的影响、PSRAM 带宽争用实测值 | ⏳ **未测** |

---

## 8. 工程结构

```
components/packages/tab5-all-in-one/
├── README.md
└── firmware/                      # ESP-IDF 工程（容器外构建，project(tab5_aio)）
    ├── CMakeLists.txt
    ├── sdkconfig.defaults
    ├── partitions.csv
    └── main/
        ├── app_main.c             # 初始化 + TinyUSB 安装 + 编排
        ├── usb_descriptors.{c,h}  # 复合描述符 + HID 复合 report 描述符
        ├── tinyusb_config/tusb_config.h
        ├── gud_protocol.h         # 自 Cardputer 拷贝（内核 vendor，Dual MIT/GPL）
        ├── gud_device.{c,h}       # 自 Cardputer 拷贝 + 改四处（见下）
        ├── lz4.{c,h}              # 自 Cardputer 拷贝（BSD-2-Clause，零改动）
        ├── tab5_pins.h            # 板级 GPIO / 尺寸常量
        ├── board_power.{c,h}      # 内部 I2C + PI4IOE5V6408 上电时序
        ├── display_dsi.{c,h}      # MIPI-DSI 面板 + PPA 缩放旋转 + display_blit
        ├── kbd_i2c.{c,h}          # 键盘 I2C + G50 中断 + 按下集合状态机
        ├── tab5_kbd_map.h         # 行列→HID usage 表（vendor 自 M5 官方固件，MIT）
        ├── touch_hid.{c,h}        # 触摸 → digitizer 报告
        └── codec_audio.{c,h}      # ES8388/ES7210 + I2S 全双工 + UAC1 回调
```

`gud_device.c` 相对 Cardputer 的四处改动：
1. 尺寸常量 640×360 与对应的模式时序 / `GUD_FB_CAP`；
2. **删除** per-pixel `bswap16`（§3.2）；
3. `display_blit` 语义从「直接推 SPI 屏」变为「PPA 缩放旋转进 DPI 帧缓冲」；
4. `s_fb` / `s_cbuf` 从内部 SRAM 静态数组改为 `heap_caps_malloc(MALLOC_CAP_SPIRAM)`
   运行时分配 —— 640×360 下两者各 460 KB、合计 900 KB，放内部 SRAM 链接不过
   （计划里称为「Task 1 的改动 4」）。

### 8.1 依赖（保持依赖树干净，不引入 LVGL / esp_video / usb-host）

| 组件 | 用途 | 阶段 |
|---|---|---|
| `espressif/esp_tinyusb` + `espressif/tinyusb` | USB device 栈（沿用 Cardputer 的精确锁版做法） | 0 |
| `espressif/esp_lcd_ili9881c` **或** `esp_lcd_st7123` | 面板（二选一，按实机） | 1 |
| `espressif/esp_io_expander_pi4ioe5v6408` | LCD_EN / TOUCH_EN / SPEAKER_EN 等上电时序 | 1 |
| `espressif/esp_lcd_touch_gt911` **或** `esp_lcd_touch_st7123` | 触摸（二选一，按实机） | 3 |
| `esp_codec_dev` | ES8388 / ES7210 寄存器序列 | 4 |
| ~~`esp_video`~~ → **`espressif/esp_cam_sensor`** | SC202CS 寄存器序列（**只要传感器驱动，不要取流框架**） | 5 |

> **订正（阶段 5 落地时）**：本表原写 `esp_video`，**已推翻** —— 它强制拖进
> `usb_host_uvc`（USB **Host** 栈）+ `esp_h264`（软件编码器）+ `esp_ipa`，
> 正面违反本节标题里「不引入 usb-host 依赖」。改用 `esp_cam_sensor`，
> 其传递依赖只有 `espressif/esp_sccb_intf` 与 `espressif/cmake_utilities`
> （后者早已在树里）。**实测 `managed_components/` 共 12 个目录**。理由详见 §7.2。

MIPI-DSI、PPA、LDO、I2S、I2C 均为 IDF 内置（`esp_lcd` / `esp_driver_ppa` /
`esp_driver_i2s` / `esp_driver_i2c`），不引入额外组件。
**摄像头链路的 MIPI-CSI / ISP / 硬件 JPEG 编码同样是 IDF 内置**
（`esp_driver_cam` / `esp_driver_isp` / `esp_driver_jpeg`）。

### 8.2 sdkconfig 要点

- `CONFIG_IDF_TARGET="esp32p4"`，Flash 16 MB，`partitions.csv` 的 factory 分区放大到 4 MB；
- **PSRAM 打开**（32 MB）—— 帧缓冲、DPI 缓冲、PPA 源目标缓冲全在 PSRAM；
  具体 mode / 频率按 ESP32-P4NRW32 数据手册与实测确定；
- esp_tinyusb 选 **全速端口**（USB-C 接的是 FS PHY，见 §1.1）；
- `CONFIG_ESP_CONSOLE_UART_DEFAULT=y` —— 与 Cardputer 的 `CONSOLE_NONE` 相反，
  UART0(G37/G38) 不与任何外设争用，保留完整串口日志。

### 8.3 烧录

TinyUSB 接管 FS PHY 后 USB-Serial/JTAG 失效，自动复位下载不可用：

1. 按住 **BOOT(G35)** 同时插 USB-C / 复位 → ROM 下载模式；
2. `idf.py -p <port> flash`；
3. 拔插一次 USB-C 正常上电，枚举为 `16d0:10a9`。

---

## 9. Linux 主机侧：两个内核选项对所有板生效

Tab5 比 Cardputer 多两个主机侧需求：HID 触摸屏需 `CONFIG_HID_MULTITOUCH`，
UVC 需 `CONFIG_USB_VIDEO_CLASS`。要求**所有 board 都生效**。

### 9.1 为什么不能靠 platform / SoC 层加行

配置是 platform → SoC → board 三层深度合并，**list 是覆盖而非追加**。
板级 `kernel.defconfig` 一旦写成完整 list 就会整体替换上层 —— `atk-rk3506b/config.py`
里那句「板级 defconfig 为覆盖式列表，显式保留 GUD 主机侧 DRM 驱动」正是这个坑的现场证据。
所以 `CONFIG_DRM_GUD=y` 才会在 8 个 SoC config 里被重复书写。

### 9.2 方案：仓库级 fragment + builder 注入

分层遵守 ProjectSpec §9 的契约（数据在内容层，机制在代码层）：

- **内容层**：新增 `components/platform/flange_common.config`，内容为
  `CONFIG_HID_MULTITOUCH=m` + `CONFIG_USB_VIDEO_CLASS=m`；
- **代码层**：`builder/kernel_base.py` 的 `_resolve_defconfig_targets()` 把该 fragment
  拷进 `arch/<ARCH>/configs/` 并插入 target 链的**首个 defconfig 之后、
  `flange_inline.config` 之前**。位置是硬要求：
  - 必须在 base defconfig **之后** —— `make xxx_defconfig` 会重置整个 `.config`；
  - 必须在 `flange_inline.config` **之前** —— 保证 SoC / board 的 raw option 仍能覆盖它。
- **Qualcomm 单独接**：`builder/platforms/qualcommqcs6490/kernel.py` 不走
  `_resolve_defconfig_targets()`，需在其自有的 config 处理路径上等价接入一处。
- **rootfs 基线**补 `v4l-utils`（`components/rootfs/`，平台无关基线）。

### 9.3 已知代价

该改动会让**所有 board 的内核 config 哈希变化 → 全部触发内核重建**。
这是一次性的、明确的代价，实施时安排在最后一个阶段，避免反复触发。

---

## 10. 阶段划分与验证

每阶段拆成 ≤ 2 小时的任务。

| 阶段 | 内容 | 验证标准 |
|---|---|---|
| **0** | 工程骨架；esp_tinyusb 全速端口；只有 GUD vendor 接口 | `lsusb` 见 `16d0:10a9`；`dmesg` 见 `drm/gud` 绑定；**实测端点预算是否够 §2 的布局** |
| **1** | 实机 I2C 扫描定面板型号；DSI 起屏；640×360 GUD + PPA 缩放旋转 + LZ4/脏矩形 | `modetest -M gud -s <id>:640x360` 出图且方向/颜色正确；脏矩形局部刷新位置正确；实测终端刷新帧率并记录 |
| **2** | 键盘 I2C Normal 模式 + G50 中断 + HID RID1 | `evtest` 打字正确；`Ctrl+C` / `Alt+Tab` 组合键生效；按住方向键连发正常 |
| **3** | 触摸 → HID RID2 digitizer + 坐标 90° 标定 | `evtest` 见 `ABS_MT_*`；`hid-multitouch` 绑定；触点与画面位置一致 |
| **4** | UAC1 全双工音频 | ✅ 播放（喇叭出声）与录音（`arecord` 正常）已分别实机验证；⏳ **仍待验**：播放与录音**同时**打开互不干扰、与 GUD 并发 10 分钟无爆音/无重新枚举 |
| **5** | UVC MJPEG（可砍） | ✅ **未砍，已打通**：`v4l2-ctl --list-formats-ext` 见 MJPEG 640×360 @10 fps、`ffplay` 出真实摄像头画面、AE 闭环生效（见 §7.4）。⏳ **仍待验**：AWB 闭环（未上板）、五项能力同跑 10 分钟的复合回归、开摄像头时 GUD 帧率的实测变化 |
| **6** | `flange_common.config` + builder 注入 + rootfs `v4l-utils` + README/文档 | 至少 3 块不同平台的 board 重建内核通过；`atk-rk3506b` 上 Cardputer 与 Tab5 复合回归 |

阶段 1–5 每一阶段结束都做一次**复合回归**：已交付的接口同时工作、互不饿死。

---

## 11. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| FS 控制器端点不够 IF0–IF6 | 阻断 §2 布局 | 阶段 0 就验；降级顺序：去 vendor IN 端点 → 砍 UVC |
| PPA 缩放+旋转的脏矩形坐标变换写错 | 画面错位/撕裂 | 阶段 1 单独用固定图案验证四个角与非对称矩形。**实测（Task 3）**：坐标公式经手算 + 实机双重验证（整帧铺满 + 非零偏移的 64×64 局部块落点与颜色均正确），旋转方向标定为 `DISPLAY_ROT_CCW90 = 1`。**但脏矩形路径本身仍待 Task 5 实测** —— 至今只有固件自造的局部块走过它，host 送来的真实 damage 序列还没跑 |
| 未上板的那条面板路径写错 | 换批次的 Tab5 上黑屏/花屏，且无人发现 | 两条路径都实现（运行时探测），但未验证的那条在日志里显式标注；init 数组逐字复刻 esp-bsp 并注明来源。**实测（Task 2）**：开发用机为 **ILI9881C** 批次（内部 I2C 扫到 0x14、无 0x55），面板 ID `0x98/0x81/0x5c`；且**必须传 esp-bsp 的定制 init 序列**，用驱动组件内置的默认序列实机表现为竖纹 + 四角暗角 + 颜色错乱。**ST7123 路径仍未上板**，另注意上游该份 init 数据有两条 `data_size` 多算 1 字节（`0xA3` 声明 40 实际 39、`0xE8` 声明 15 实际 14），会致越界读，是该路径出问题时的首要怀疑对象 |
| **P4 芯片版本互斥** | 本固件编译为支持 rev v0.x/v1.x（实机是 **v1.0**），**跑不了 v3.x 的 P4**。IDF 原文：「rev <3.0 与 >=3.0 互斥，硬件差异巨大」 | **无法运行时兼容**，与双面板不同。若遇到换 v3.x 芯片的 Tab5 批次，只能另出一份固件（改 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=n` + `REV_MIN_301`）。已在 `sdkconfig.defaults` 就地注明 |
| ~~TinyUSB UVC device 不可用~~ | 摄像头功能落空 | **已实测排除**：TinyUSB 的 `class/video/` 在这块板的全速口上能出流，`uvcvideo` 正常绑定、`ffplay` 出图、零拒收。两个必须同时定义的宏是 `CFG_TUD_VIDEO` **与** `CFG_TUD_VIDEO_STREAMING`；另发现上游 `TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC` 等三个宏在全树零调用者且 `bLength` 与 `bFrameIntervalType` 都算错，本工程手写了替代 |
| **ESP32-P4 rev <3.0 缺一批硬件功能** | 照抄 IDF 例程/文档会得到 `ESP_ERR_NOT_SUPPORTED` 或**静默半帧** | 已咬过四次，集中记在 `firmware/README.md` 的「ESP32-P4 rev <3.0 已知不可用的硬件功能」一节：CSI 桥无颜色转换硬件（`mipi_csi_ll.h` 的 `#else` 分支五个函数全空）、JPEG 编码器不吃 YUV420/YUV444、ISP 的 WBG/BLC/crop 不可用（AWB **统计**可用）、CCM 上限 4.0 |
| **PSRAM 带宽争用**（DPI 读 ≈110 MB/s vs CSI 写 ≈55 MB/s） | 屏幕撕裂/花屏，或 GUD 帧率意外掉更多 | CSI **只在 host 选中 alt 1 时才 start**（alt 0 时不取流/不缩放/不编码）；固件侧留了「空载 / 取流中 / 停流后」三点 PSRAM 读带宽实测。⏳ **实测数字尚未取得** —— 阶段 5 的 Task 10 未执行 |
| 全局内核 config 触发全板重建 | 一次性长构建 | 排在最后阶段一次性完成 |
| 640×360 放大后文字发虚 | 观感下降 | 2× 整数放大无插值；若仍不可接受，回退选项是加声明 720p 模式由 host 选（代价是帧率）。**现状：未结论** —— 至今只在实机上验过色块自检图（四象限 + 黑方块），文字观感要等 Task 4/5 把 host 的真实画面（终端 / `videotestsrc`）送上屏后才能判断 |

---

## 12. 明确不做

- 不修改 `cardputer-all-in-one` 的任何代码（零回归风险优先于消除重复）；
- 不按批次分别构建固件（两种面板由同一份固件运行时探测，见 §3.3）；
- 不使用 USB-A 的高速口做 device（需 A-to-A 线且 VBUS 有回灌风险）；
- 不引入 LVGL / ~~esp_video（阶段 5 前）~~ / usb-host 依赖 ——
  **阶段 5 结束时 `esp_video` 一次也没被引入**，摄像头走 `esp_cam_sensor` +
  IDF 内置 CSI/ISP/JPEG/PPA，见 §7.2；
- 不做 SD 卡、IMU、RTC、RS485、电池管理 —— 与「USB 瘦终端」定位无关。
