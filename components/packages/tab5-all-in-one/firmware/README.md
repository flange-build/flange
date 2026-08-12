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

佐证：此时在主机上跑 esptool，报的是 `USB mode: USB-Serial/JTAG`（全速 PHY 仍归 ROM 的
USB-Serial/JTAG，说明 TinyUSB 没接管它）。

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

## 文件

| 文件 | 职责 |
|------|------|
| `main/app_main.c` | 编排：board_power → display → gud → TinyUSB 安装 |
| `main/usb_descriptors.{c,h}` | USB 复合描述符数据（当前仅 IF0 GUD vendor） |
| `main/gud_protocol.h` | GUD 协议定义（vendor 自内核 6.8） |
| `main/gud_device.{c,h}` | GUD 控制协议状态机 + 收帧（脏矩形累积 / LZ4 解压）→ `display_blit()` |
| `main/lz4.{c,h}` | 官方 LZ4 v1.9.4 参考实现（BSD-2-Clause），仅用 `LZ4_decompress_safe` |
| `main/display_dsi.{c,h}` | 显示 HAL：LDO + DSI + 面板探测/初始化 + PPA 缩放旋转 + 自检图 + 背光点亮 |
| `main/panel_init_data.h` | 两种批次的面板 init 命令序列（vendor 自 esp-bsp，Apache-2.0） |
| `main/board_power.{c,h}` | 内部 I2C 总线 + PI4IOE5V6408 上电时序 + 背光开关 |
| `main/tab5_pins.h` | 板级 GPIO / 面板与 GUD 尺寸常量（含放大倍数的静态断言） |
| `sdkconfig.defaults` | 目标/PSRAM/分区/控制台/vendor 类，以及芯片版本互斥的说明 |
| `partitions.csv` | factory 分区 4 MB |
| `main/idf_component.yml` | 依赖精确锁版：esp_tinyusb / tinyusb / io_expander / 两个面板驱动 |

设计与路线：见仓库
`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` 与
`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`。
