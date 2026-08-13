# Tab5 AIO 固件（ESP32-P4）

M5Stack Tab5 作为 **USB 设备**，让嵌入式 Linux 主机把它当成一块标准 DRM 显示器
（mainline `gud` 驱动，`/dev/dri/cardN`）。host 送来的 **640×360 RGB565** 帧经 ESP32-P4 的
PPA（Pixel Processing Accelerator，像素处理加速器）**2× 放大 + 90° 旋转**，铺满板载的
720×1280 MIPI-DSI 面板。同一个复合设备上还带 **HID 键盘**（Tab5 Keyboard）与
**HID 多点触摸**（GT911，与键盘共用同一个 HID 接口、靠 Report ID 区分）；
后续阶段追加 UAC 音频 / UVC 摄像头。

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
  - 设备描述符为 Misc/IAD 复合设备，为后续 UAC/UVC 预留。
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

为此 `sdkconfig.defaults` 末尾预留了一个**默认注释掉**的开关：

```
# CONFIG_TINYUSB_CDC_ENABLED=y
# CONFIG_TINYUSB_CDC_COUNT=1
```

取消这两行的注释后，复合设备上会多出一个 CDC ACM 接口，`ESP_LOG*` / `stdout` 改从 USB-C 出来，
`idf.py monitor` 直接可看，**不用接 USB-TTL**。

```bash
# 打开
sed -i '' 's/^# CONFIG_TINYUSB_CDC_/CONFIG_TINYUSB_CDC_/' sdkconfig.defaults
rm -f sdkconfig && idf.py build          # ⚠️ 必须删 sdkconfig，否则 defaults 不重新生效
```

> ⚠️ **`rm -f sdkconfig` 不能省。** `sdkconfig.defaults` 只在 `sdkconfig` **不存在**时被读，
> 改了 defaults 却不删 `sdkconfig`，构建会静默沿用旧配置 —— 表现为「改了开关却没生效」。

代码侧一律走 `#if CONFIG_TINYUSB_CDC_ENABLED` 条件编译（`usb_descriptors.{c,h}` 的接口/端点/
描述符/字符串，`app_main.c` 的 `tinyusb_cdcacm_init()` + `tinyusb_console_init()`）。
`CONFIG_TOTAL_LEN` 与 `_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN)`
两种配置下都成立：**关闭 57 字节 / 开启 123 字节**（`TUD_CDC_DESC_LEN = 66`，自带 IAD、占两个接口）。

#### ⚠️ 代价：开启后 4 条 IN 端点全部用满

| 用途 | 端点 |
|---|---|
| vendor(GUD) | OUT `0x01` / IN `0x81` |
| HID（键盘 + 触摸） | IN `0x82` |
| CDC 通知 | IN `0x83` |
| CDC 数据 | OUT `0x02` / IN `0x84` |

P4 全速控制器只有 4 条可用 IN 端点（见上「端点预算」）。开着 CDC 时 **UAC 音频（麦克风 1 条 IN）
与 UVC 摄像头（视频流 1 条 IN）都放不下** —— 做那两个阶段前必须把开关注释回去。
FIFO 反而不是瓶颈：256 words 里 EP0 16 + vendor 32 + HID 16 + 通知 2 + CDC 数据 32 = 98 words，
余量远大于 RX FIFO 所需的 62 words。

**这是调试设施，不是产品特性。正常构建、提交与出厂固件都应保持关闭**
（关闭态的 Flash/DIRAM 与不带本开关的版本**逐字节相同**：275,062 / 91,228）。

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

当前已用 **2 条 IN 端点**：vendor(`0x81`) + HID(`0x82`)，余 2 条。后续的 UAC + UVC 会把它们用满，
所以**触摸与键盘合并在同一个 HID 接口**上，用 Report ID 区分（RID 1 键盘 / RID 2 digitizer），
**已如此落地**（触摸没有新增任何端点，见下文「HID 多点触摸」）。

> 余下这 2 条也是**可选 CDC 调试串口**（默认关闭）要占的，见下文「日志」章节。
> 三者（CDC / UAC / UVC）不能同时开。

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
| Flash | 275,062 字节（约 269 KB），占 4 MB factory 分区 **7%** |
| 内部 DIRAM | 91,228 字节（**15.8%**），剩余约 474 KB |
| 镜像总大小 | 356,686 字节（`.bin` 另有 padding） |

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

### 待验项：四角坐标标定

**尚未验证**。已知情况：某次抓取里所有触点的 Y 都落在满量程的 **78%–99%**（对应横屏画面
最下方约 20% 的一条带），这**既可能**是当时手指本来就点在那一带、**也可能**是 Y 轴映射有问题
—— **日志无法区分这两种解释**，所以不能据此下任何结论。

验证方法：依次点屏幕**横持视角**的四个角，确认 X 与 Y **各自都能跑到接近 0 与接近 32767**
（`evtest` 里看 `ABS_MT_POSITION_X` / `ABS_MT_POSITION_Y` 的取值范围）。四角都能到量程两端，
才算标定通过；某一轴始终挤在一小段区间里，才是真的映射错了。

## 文件

| 文件 | 职责 |
|------|------|
| `main/app_main.c` | 编排：board_power → display → gud → TinyUSB 安装 |
| `main/usb_descriptors.{c,h}` | USB 复合描述符数据（IF0 GUD vendor + IF1 HID 键盘 RID1 / 多点触摸 RID2） |
| `main/gud_protocol.h` | GUD 协议定义（vendor 自内核 6.8） |
| `main/gud_device.{c,h}` | GUD 控制协议状态机 + 收帧（脏矩形累积 / LZ4 解压）→ `display_blit()` |
| `main/lz4.{c,h}` | 官方 LZ4 v1.9.4 参考实现（BSD-2-Clause），仅用 `LZ4_decompress_safe` |
| `main/display_dsi.{c,h}` | 显示 HAL：LDO + DSI + 面板探测/初始化 + PPA 缩放旋转 + 待机画面上屏/动画任务 + 背光点亮 |
| `main/standby_screen.{c,h}` | 待机画面（`NO SIGNAL`）的绘制原语与版式，零依赖纯函数（宿主机可渲染预览） |
| `main/font8x16.h` | Spleen 8×16 点阵字体，ASCII 0x20-0x7E（vendor 自 fcambus/spleen，BSD-2-Clause） |
| `test/test_standby_screen.c` | 待机画面宿主机回归测试 + PPM 版式预览（直接编译真实源码，非复制体） |
| `main/panel_init_data.h` | 两种批次的面板 init 命令序列（vendor 自 esp-bsp，Apache-2.0） |
| `main/board_power.{c,h}` | 内部 I2C 总线 + PI4IOE5V6408 上电时序 + 背光开关 |
| `main/kbd_i2c.{c,h}` | 键盘 I2C 总线 + G50 中断 + 事件排空 + HID 上报（Normal 模式） |
| `main/kbd_translate.{c,h}` | 按下集合 → HID modifier/keycode 分层翻译，零依赖纯函数（宿主机可测） |
| `main/tab5_kbd_map.h` | 行列 → HID usage 映射表（vendor 自 M5 官方固件，MIT） |
| `test/test_kbd_translate.c` | `kbd_translate()` 宿主机回归测试（直接编译真实源码，非复制体） |
| `main/touch_hid.{c,h}` | GT911 初始化（INT 拉低 + 备用地址 `0x14`）+ 20ms 轮询 + digitizer 上报（RID 2） |
| `main/touch_map.{c,h}` | 面板坐标 → GUD 坐标反变换 + HID 归一化 + 报告装填，零依赖纯函数（宿主机可测） |
| `test/test_touch_map.c` | 触摸坐标变换与报告装填的宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tab5_pins.h` | 板级 GPIO / 面板与 GUD 尺寸常量（含放大倍数的静态断言） |
| `sdkconfig.defaults` | 目标/PSRAM/分区/控制台/vendor 类、芯片版本互斥的说明，以及末尾默认注释掉的 CDC 调试串口开关 |
| `partitions.csv` | factory 分区 4 MB |
| `main/idf_component.yml` | 依赖精确锁版：esp_tinyusb / tinyusb / io_expander / 两个面板驱动 |

设计与路线：见仓库
`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` 与
`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`。
