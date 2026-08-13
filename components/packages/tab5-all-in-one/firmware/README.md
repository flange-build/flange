# Tab5 AIO 固件（ESP32-P4）

M5Stack Tab5 作为 **USB 设备**，让嵌入式 Linux 主机把它当成一块标准 DRM 显示器
（mainline `gud` 驱动，`/dev/dri/cardN`）。host 送来的 **640×360 RGB565** 帧经 ESP32-P4 的
PPA（Pixel Processing Accelerator，像素处理加速器）**2× 放大 + 90° 旋转**，铺满板载的
720×1280 MIPI-DSI 面板。后续阶段在同一个复合设备上追加 UAC 音频 / HID 键盘触摸 / UVC 摄像头。

> ESP-IDF 项目，**容器外**构建（flange 的 Docker 无 ESP 工具链）。

## 能力

- USB 复合设备，**VID/PID = `16d0:10a9`**（mainline `gud` 绑定的固定 modalias，**不可更改**）。
  - **IF0 Vendor(GUD) 显示**：GUD 设备协议最小子集，单 connector / 单模式 **640×360** /
    **RGB565**，支持 LZ4 压缩与 dirty rectangle（脏矩形）；收 host 帧（SET_BUFFER + bulk OUT）
    →（可选 LZ4 解压）→ PPA 缩放旋转 → DPI 帧缓冲 → 面板。
  - 设备描述符已按 Misc/IAD 复合设备声明，为后续 UAC/HID/UVC 预留；本阶段只有 IF0。
- 协议头 `main/gud_protocol.h` 从内核 6.8 `include/drm/gud.h` vendor（Dual MIT/GPL）；
  面板 init 序列与 DSI/DPI 参数复刻自 esp-bsp `bsp/m5stack_tab5`（Apache-2.0）。

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

`lsusb` 里根本没有 `16d0:10a9`，屏幕自检图正常、UART 日志也正常打出
`TinyUSB Driver installed on port 0` —— 固件一切「看起来正常」，只是 PHY 不归它。

> 这两项只影响**应用**阶段。bootloader 阶段 USJ 仍然启用，按住 BOOT 进下载模式照常能烧录
> （IDF Kconfig 原文即如此说明）。

### 端点预算（后续阶段会用满）

P4 全速控制器（tinyusb `dwc2_esp32.h`）：`ep_count = 7`、`ep_in_count = 5`（含 EP0）、
FIFO 256 words（1 KB），即**最多 4 条可用 IN 端点**。

本阶段只用 vendor 的 IN/OUT 各一条，余量充足。后续的 UAC + HID + UVC 会把 IN 端点用满，
届时**键盘与触摸必须合并成一个 HID 接口**，用 Report ID 区分（RID 1 键盘 / RID 2 digitizer）。

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
**实机验证取值为 `1`**：横持时红色象限落在左上角，与 GUD 坐标系一致。

> ⚠️ 「画面铺满全屏」**验不出方向** —— 两个分支都产生 (0,0) 起的 720×1280 输出，
> 差别只在内容转了 180°。判据必须是内容的落角（自检图的红色象限），不是有没有黑边。

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

> Tab5 Keyboard 在**另一条** I2C 上：SDA = G0 / SCL = G1 / INT = G50，地址 `0x6D`。
> 本阶段未使用，键盘阶段再单独初始化那条总线。

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
开机自检图（四象限 + 中央黑方块）被 host 画面覆盖这一变化本身，即是 GUD 打通的证据；
若开机就黑屏，则可据此区分「显示坏了」与「GUD 没送帧」。

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
| Flash | 255,126 字节（约 249 KB），占 4 MB factory 分区 **6%** |
| 内部 DIRAM | 90,738 字节（**15.7%**），剩余约 474 KB |
| 镜像总大小 | 336,328 字节（`.bin` 另有 padding） |

大块缓冲全在 PSRAM，不占内部 RAM：GUD 收帧缓冲共约 900 KB（未压缩帧与压缩帧各一份，
每份 `640×360×2` = 460,800 字节），DPI 帧缓冲 1.84 MB。
开机自检图另临时占一份 460,800 字节，用完即释放。

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
IN 端点（见上），UAC/UVC 会用满，触摸必须与键盘共用本接口，届时以 **RID 2 = digitizer**
追加是纯增量改动。

> ⚠️ **已知的规范不自洽**：`TUD_HID_DESCRIPTOR` 传 `HID_ITF_PROTOCOL_KEYBOARD` 会把
> `bInterfaceSubClass` 设为 BOOT，宣称支持 boot keyboard，而 **boot 协议报告格式不允许
> Report ID**。Linux `usbhid` 默认走 report 协议，**本用途不受影响**；受影响的只有
> BIOS/UEFI/GRUB 早期阶段（记录在此免得日后有人报「BIOS 里打不了字」）。

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

## 文件

| 文件 | 职责 |
|------|------|
| `main/app_main.c` | 编排：board_power → display → gud → TinyUSB 安装 |
| `main/usb_descriptors.{c,h}` | USB 复合描述符数据（IF0 GUD vendor + IF1 HID 键盘） |
| `main/gud_protocol.h` | GUD 协议定义（vendor 自内核 6.8） |
| `main/gud_device.{c,h}` | GUD 控制协议状态机 + 收帧（脏矩形累积 / LZ4 解压）→ `display_blit()` |
| `main/lz4.{c,h}` | 官方 LZ4 v1.9.4 参考实现（BSD-2-Clause），仅用 `LZ4_decompress_safe` |
| `main/display_dsi.{c,h}` | 显示 HAL：LDO + DSI + 面板探测/初始化 + PPA 缩放旋转 + 自检图 + 背光点亮 |
| `main/panel_init_data.h` | 两种批次的面板 init 命令序列（vendor 自 esp-bsp，Apache-2.0） |
| `main/board_power.{c,h}` | 内部 I2C 总线 + PI4IOE5V6408 上电时序 + 背光开关 |
| `main/kbd_i2c.{c,h}` | 键盘 I2C 总线 + G50 中断 + 事件排空 + HID 上报（Normal 模式） |
| `main/kbd_translate.{c,h}` | 按下集合 → HID modifier/keycode 分层翻译，零依赖纯函数（宿主机可测） |
| `main/tab5_kbd_map.h` | 行列 → HID usage 映射表（vendor 自 M5 官方固件，MIT） |
| `test/test_kbd_translate.c` | `kbd_translate()` 宿主机回归测试（直接编译真实源码，非复制体） |
| `main/tab5_pins.h` | 板级 GPIO / 面板与 GUD 尺寸常量（含放大倍数的静态断言） |
| `sdkconfig.defaults` | 目标/PSRAM/分区/控制台/vendor 类，以及芯片版本互斥的说明 |
| `partitions.csv` | factory 分区 4 MB |
| `main/idf_component.yml` | 依赖精确锁版：esp_tinyusb / tinyusb / io_expander / 两个面板驱动 |

设计与路线：见仓库
`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` 与
`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`。
