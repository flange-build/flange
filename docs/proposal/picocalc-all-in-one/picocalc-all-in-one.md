# PicoCalc all-in-one 固件迁移评估

把现有 `components/packages/cardputer-all-in-one`（M5Stack Cardputer / ESP32-S3 上的「USB 瘦终端」固件）迁移到 **Clockwork PicoCalc + Raspberry Pi Pico 2 W（RP2350）**。

## 概述

- **本质**：这是一次 **MCU → MCU 的固件移植**（ESP32-S3 → RP2350），**不是** Linux 系统迁移。Pico 不跑 Linux 与本任务无关 —— 固件本身就是裸机/RTOS 级 USB 设备端代码。
- **结论**：**可行（feasible-with-caveats）**。约 **90% 的协议/算法代码可字节级或近原样搬运**（两边同基于上游 TinyUSB）；工作量集中在四处「上板 bring-up」，每处都有成熟解法，**无阻断性问题**。
- **选型前提（已验证正确）**：必须用 **RP2350（Pico 2 / Pico 2 W）**，不能用初代 RP2040（Pico / Pico W）—— 320×320 RGB565 整帧 = 200 KB，RP2350 的 520 KB SRAM 装得下，RP2040 的 264 KB 装不下。用户选的 Pico 2 W 正确。
- **工作量**：约 **2–3 人周**（核心编码 1–1.5 周，其余为上板验证与标定）。
- **参考实现兜底**：[`notro/gud-pico`](https://github.com/notro/gud-pico) —— 同 RP 家族的 GUD（Generic USB Display）设备端固件，复用同一 Linux 主机驱动与 VID:PID。

> 本评估由多 agent 调研 + 对 4 条 make-or-break 风险逐条 web 证伪得出，证据来源见文末「参考资料」。

## 背景：现固件做什么

`cardputer-all-in-one`（ESP-IDF + TinyUSB）用**一根 USB-C** 把 M5Cardputer 接到 flange 嵌入式 Linux 主机，让它当一个「USB 瘦终端」，**host 侧零自定义驱动**：

| 接口 | 角色 | host 侧 mainline 驱动 |
|---|---|---|
| IF0 Vendor / **GUD** | USB 外接显示器（收 host 帧 → blit 到屏） | `drivers/gpu/drm/gud` → `/dev/dri/cardN` |
| IF1 **HID** 键盘 | 矩阵键盘 → HID usage 上报 | `usbhid` → `/dev/input/eventN` |

- USB 复合设备，**VID:PID = `16d0:10a9`**（mainline `gud` 驱动绑定的固定 modalias，**必须保留**）。
- GUD 显示链路、HID 键盘已在 Cardputer 上跑通；规划中：LZ4+脏矩形、UAC 音频。
- 真正的自定义代码很小：`gud_device.c`(357) + `hid_keyboard.c`(176) + `display_st7789.c`(86) + `usb_descriptors.c`(81) + `app_main.c`(48)；`lz4.c`(2722) 是第三方库、`gud_protocol.h`(231) 是从内核 vendor 的协议头，均与平台无关。**核心移植面 ≈ 七八百行平台相关 C。**

## 目标硬件：PicoCalc + Pico 2 W

| 项 | 值 |
|---|---|
| 主控 | Raspberry Pi Pico 2 W（RP2350，双核 Cortex-M33 或 RISC-V Hazard3，520 KB SRAM） |
| 显示 | 4″ 方形 IPS，**320×320**，控制器 **ILI9488**（新批次标 ST7365P，约 99% 指令兼容），走 **SPI1** |
| 键盘 | 板载独立 **STM32F103**，作 **I2C 从机（地址 `0x1F`）**，挂在主控 **i2c1** |
| SD 卡 | 走独立 **SPI0**（与 LCD 的 SPI1 物理分离） |
| 音频 | 双路 **PWM**（无 I2S / 无 DAC） |
| 电源 | 18650 锂电 + **AXP2101 PMU**，经键盘 STM32 暴露给主控 |
| 其他 | carrier board 集成 8 MB PSRAM（接线随批次存疑） |

### 引脚映射（移植时按此重定）

| 外设 | 总线 | 引脚（RP2350 GP） | 备注 |
|---|---|---|---|
| LCD | SPI1 | SCK=GP10, MOSI=GP11, MISO=GP12, CS=GP13, DC=GP14, RST=GP15 | ILI9488/ST7365P，lcdspi 默认 ~25 MHz |
| 键盘 | I2C1 | SDA=GP6, SCL=GP7 | 从机 `0x1F`，**强制 10 kHz** |
| SD 卡 | SPI0 | MISO=GP16, CS=GP17, SCK=GP18, MOSI=GP19 | 与 LCD 独立 |
| 音频 | PWM | 左=GP26, 右=GP27 | 占用后 ADC0/ADC1 不可用 |
| WiFi（Pico 2 W） | — | 核心板内部 GP23/24/25/29 | **不与 PicoCalc 外设冲突** |

键盘 STM32 还经同一 I2C 暴露：背光 `0x05`(LCD)/`0x0A`(键盘)、电量 `0x0B`、关机 `0x0E` —— 整条 i2c1 都受 10 kHz 约束。

## 可移植性总览（最大利好）

固件核心价值建立在**协议与纯 C 逻辑**上，而这部分恰好最可移植。两边都基于**上游 TinyUSB**（Pico SDK 的 `tinyusb_device` 即 hathach/tinyusb，rp2040 端口覆盖 RP2350），设备侧 `tud_*` 弱回调签名字节级一致：

| 资产 | 可移植性 | 说明 |
|---|---|---|
| `gud_protocol.h` | **100% 照搬** | 中立 stdint + 小端定义，RP2350 同为小端 |
| GUD 控制状态机（`gud_handle_control`） | **原样重用** | 仅依赖 `tud_control_xfer/tud_control_status` |
| 收帧路径（`tud_vendor_rx_cb` + LZ4 + byteswap + blit 逻辑） | **原样重用** | 仅 `display_blit` 与日志需替换 |
| 描述符 `TUD_*` 字节 / `16d0:10a9` / 接口端点编号 | **必须且本就照搬** | Linux `gud` 驱动绑定依赖 |
| `lz4.c/.h` | **drop-in** | 零平台依赖纯 C |
| HID 上报 + 键值映射表（`hid_base/hid_fn`） | **近零改动** | `tud_hid_keyboard_report` 在 Pico 上仍是 TinyUSB |

## 子系统迁移映射

| 子系统 | 结论 | 工作量 | 头号风险 |
|---|---|---|---|
| **USB / GUD + HID 复合** | ~90% 字节级重用；唯一改写 = 描述符交付从 `esp_tinyusb` 托管反写为自实现 `tud_descriptor_*_cb`（含 UTF-16 `string_cb`）+ `tusb_init()` + 主循环 `tud_task()` + 手写 `tusb_config.h` | 低（数天） | UTF-16 string_cb 自做；GUD+HID 复合在 Pico 上无公开实测 |
| **显示 / 帧处理** | `display_st7789.c`（仅 ~90 行）整体重写：`esp_lcd` 无 Pico 等价物，须用 `hardware_spi`/PIO/**HSTX** + DMA 自建，**或复用 PicoCalc 官方 `lcdspi`**；lz4 与帧逻辑保留 | 中（数天） | RGB666 展开 + blit 异步（两项 make-or-break，见下） |
| **键盘 / HID 输入** | 扫描层 ~70% 重写：丢弃 74HC138 矩阵扫描，改为 I2C 读 `0x1F` 事件流；映射/上报层近零改动；Fn 层可整删（STM32 直接给特殊键） | 中（~1.5 人日） | `sleep_ms(16)` 饿死 tud_task；cooked-ASCII↔HID 阻抗失配 |
| **构建 / RTOS / 骨架** | 机械翻译：ESP-IDF CMake/sdkconfig/分区表 → Pico SDK CMake + `tusb_config.h` + 裸机超级循环；**已核实工程零 RTOS 同步原语**（仅一个键盘扫描任务） | 低（1–2 天） | 去 RTOS 后并发模型须保证 `tud_task` 不被饿死 |

> 唯一硬绑 `esp_tinyusb` 的点是 `app_main.c` 的 `tinyusb_driver_install()`（它替你实现了 `tud_descriptor_*_cb`、做 UTF-16/langid 转换、托管后台 USB 任务）。`usb_descriptors.h` 中「勿实现否则重复符号」的约束，在 Pico 上**反转为「必须实现」**。

## 关键风险与证伪（4 条 make-or-break 全部 confirmed）

四条决定移植成败的风险均经 web 证伪为 `confirmed`，且都有成熟规避：

1. **ILI9488 在 4-wire SPI 下不原生支持 RGB565**（仅 18-bit RGB666，3 字节/像素）。直推 RGB565 字节流必然黑/花屏 —— 显示能否出图的根本门槛。
   - **缓解**：blit 末端做 `RGB565→RGB666` 流式展开（每通道补齐到 6 位）+ `COLMOD=18bit`，**或直接复用 PicoCalc 官方 `lcdspi`（已内建转换）**。原厂手册 / TFT_eSPI / esp_lcd_ili9488 / fbtft / 官方 lcdspi 五源交叉证实。

2. **blit 不能在 `tud_vendor_rx_cb` 上下文同步推屏**：320×320 RGB666 全屏 @25 MHz≈98 ms / @62.5 MHz≈39 ms，会让协作式 `tud_task` 停摆几十个调度周期 → 端点 NAK 风暴 / 吞吐塌缩 / 控制传输超时。
   - **缓解**：`hardware_dma` 异步 blit（`rx_cb` 仅在上次 DMA 完成后再发起），或把 blit/键盘放 **core1、core0 专跑 `tud_task`**。RP2350 另有 **HSTX**（每脚 300 Mbps、不占 PIO）是驱屏最优路径。注意 62.5 MHz 对 ILI9488 不可达，帧率预算按 25–50 MHz 重算。

3. **去 RTOS 后键盘 I2C 阻塞饿死 tud_task**：官方 `read_i2c_kbd()` 选寄存器 `0x09` 后 `sleep_ms(16)` 再读；i2c1 又被强制 10 kHz。照搬进 core0 主循环这 16 ms 阻塞会卡死 GUD 收帧/枚举。
   - **缓解**：键盘轮询放 **core1（`multicore_launch_core1`）** 或非阻塞状态机/定时器中断；core0 主循环禁用任何 `sleep_ms` 级同步阻塞。社区 `BlairLeduc/picocalc-text-starter` 已用定时器+信号量证明可规避。

4. **「键盘协议拿不到」—— 不成立**（已 confirmed）。PicoCalc 键盘协议**完全公开**：从机 `0x1F`，写 `0x09` 读 2 字节 FIFO（低字节 state = `1`按下/`2`保持/`3`释放，高字节 keycode），BBQ10（BlackBerry Q10）血统，官方 **GPLv3** `keyboard.ino` + 多个独立 GPLv3 驱动 + 上游 i2c_puppet 三重佐证。
   - **唯一的坑（cooked-ASCII）**：官方固件已把 shift **烘进可打印字符**（'3'→'#'、大写转小写），高字节对可打印键是 ASCII 而非纯物理 scancode；修饰键又作为**独立按键事件**单独进 FIFO。桥接到 HID（键身份 + modifier 位模型）需做 **ASCII → HID usage 反解**（可用 TinyUSB `HID_ASCII_TO_KEYCODE` 128 项表 + 自写特殊键小表），**或干脆改 GPLv3 固件让其输出原始 keycode**。

## 性能与带宽天花板（诚实）

- **USB 是硬瓶颈**：RP2350 仅 **USB 1.1 全速 12 Mbps**（实测 bulk ≈1.0–1.1 MB/s），**与 ESP32-S3 同档 → 移植不引入回归**。320×320 RGB565 未压缩整帧 = 200 KB → 仅约 **5–6 fps**。
- **靠 GUD 脏矩形 + LZ4 提升有效帧率**（协议已声明 `GUD_COMPRESSION_LZ4`）：`notro/gud-pico` 实测 320×240+LZ4 ≈ **13 fps**、320×135 ≈ 23 fps。对**终端/文本/UI 可用**；320×320 动态内容真实帧率**需上板实测**。
- **面板链路不缺带宽**：SPI（只写）/PIO+DMA/HSTX 都能给 320×320 RGB565 提供 30 fps+；瓶颈在 USB 入口而非屏。
- **RAM**：单 framebuffer 200 KB 在 520 KB SRAM 下宽裕；双缓冲 400 KB 偏紧（余 ~120 KB），MVP 建议单缓冲 + DMA 完成等待，留在 SRAM（不依赖 PSRAM）。

## 工作量估算

约 **2–3 人周**：

- 核心代码移植 ≈ 1–1.5 周（USB/GUD 数天 + 构建骨架 1–2 天 + 显示重写数天 + 键盘 ~1.5 天，四者部分可并行）。
- 其余 ≈ 1–1.5 周为上板 bring-up 与标定（ILI9488 出图/RGB666/字节序、DMA 异步不饿死 tud_task、键盘 I2C 非阻塞、GUD+HID 复合在真实 Linux 主机的枚举/绑定/帧率验证、方向/反色/背光标定）。
- **无算法重写、无并发同步原语风险** —— 时间主要吃在硬件验证而非编码。

## 推荐实施路线（对齐 OpenSpec）

- **阶段 0 — 提案 + 最小可枚举骨架**（`/opsx:explore` → `/opsx:propose`）：在 `components/packages/` 下新建 `picocalc-all-in-one/firmware`（Pico SDK CMake 工程，`PICO_BOARD=pico2_w`，ARM 内核）；参照仓库正在加的 amp scaffold 评估是否引入新 firmware scaffold type。落地：手写 `tusb_config.h`（`CFG_TUD_VENDOR=1`/`CFG_TUD_HID=1`）+ 自实现三个描述符回调（套 `pico-examples/dev_hid_composite` + `notro/gud-pico` 模板，照搬 `16d0:10a9` 与 IF/EP 字节）+ `tusb_init()` + `while(1){tud_task();}`。**验证**：`lsusb` 见 `16d0:10a9`、`dmesg` 见 `drm/gud` 绑定 vendor 接口（屏未出图前即可验枚举）。
- **阶段 1 — 最小 GUD 显示**（`/opsx:apply` 第一批）：搬 `gud_protocol.h`(零改) + `gud_device.c` 状态机（240×135→320×320、模式时序/`GUD_FB_CAP`/缓冲重算、`ESP_LOG`→`printf`）+ `lz4.c`。重写 `display_st7789.c`：优先复用官方 `lcdspi` 的 ILI9488 init + 窗口设置 + RGB565→RGB666 推送；`display_blit` 走 `hardware_dma` 异步并放 core1。先跑未压缩整屏帧。**验证**：host 写 `/dev/dri/cardN` 出正确图像、无撕裂卡死、core0 单次循环耗时有上界。byteswap/INVON/MADCTL 做成编译开关按真机标定。
- **阶段 2 — 键盘 HID**（`/opsx:apply` 第二批）：`i2c_init(i2c1, 10000)`，写 `0x09` 读 2 字节事件流，轮询放 core1 非阻塞；ASCII→HID usage 反解 + 自写特殊键小表 + 修饰键跟踪；上报层原样保留。落地前先 `printf` dump 原始 2 字节 + 读 GPLv3 固件锁定特殊键 keycode/state。**验证**：host `evtest` 见按键，与 GUD 显示同时工作不互相饿死。
- **阶段 3 — 压缩/带宽/外设**（`/opsx:apply` 第三批）：开 `GUD_COMPRESSION_LZ4` + 脏矩形打满帧率，必要时加低位深；背光/电量/关机经键盘 STM32 同一 I2C 串行化；音频（PWM）按需排在最后或砍掉。**验证**：实测 320×320 文本/终端有效帧率、I2C 总线无争用丢键。
- **阶段 4 — 接入 flange + 归档**（`/opsx:archive`）：明确刷写形态 —— **Pico 是 `.uf2`/`picotool`，不走 `flange flash`**（后者面向 Linux 镜像分区刷写）；补 board/platform 定义与 docs；按 OpenSpec 归档。

## 需要拍板的开放问题

1. **核心板**：Pico 2 W vs Pico 2？WiFi 对本固件功能无影响（CYW43 只占核心板内部 GPIO），仅影响 LED/BOM。内核建议选 **ARM（Cortex-M33）** 而非 RISC-V（TinyUSB/库/示例更成熟）。
2. **纳入 flange 的形态**：包装成新 firmware scaffold type（类比 amp），还是独立 Pico SDK 子工程？
3. **分辨率/帧率取舍**：坚持 320×320 全屏，还是允许低位深 / 缩小可视区换帧率？产品对终端/UI 帧率的最低可接受值？320×320 动态帧率缺基准，需上板回填。
4. **许可**：是否接受把 PicoCalc 官方 `lcdspi` / 键盘固件（**GPLv3**）引入本包？上游 `gud-pico` 已于 2025-01 归档（read-only），需自行 fork。
5. **音频是否要做**：PicoCalc 仅 PWM 软合成（GP26/27），占用后 ADC0/1 不可用 —— 可否砍。
6. **面板控制器标定**：量产机是 ILI9488 还是 ST7365P 随批次变（约 99% 兼容）；需读 `RDID(0x04)` / 目检确认 init/gamma；ILI9488 接线下是否仍需 byteswap16 / BGR / INVON 须上板标定。
7. **日志通路**：vendor+HID 已占满复合配置、无 USB-CDC 控制台 → 须走 UART0；PicoCalc 默认 GP0/GP1 是否引出需对官方原理图确认（或退用 SWD/RTT）。
8. **PSRAM/双缓冲**：若要双缓冲（2×200 KB，520 KB 下偏紧）是否依赖板载 8 MB PSRAM？PSRAM 接线各源不一致，需按官方原理图逐脚核对；MVP 建议单缓冲留 SRAM。

## 参考资料

**目标硬件（PicoCalc）**
- LCD（ILI9488/ST7365P 320×320，SPI1 GP10-15）：<https://raw.githubusercontent.com/clockworkpi/PicoCalc/master/Code/picocalc_helloworld/lcdspi/lcdspi.h>
- 键盘 I2C（i2c1，SDA=GP6/SCL=GP7，从机 0x1F）：<https://raw.githubusercontent.com/clockworkpi/PicoCalc/master/Code/picocalc_helloworld/i2ckbd/i2ckbd.h>
- 读键寄存器 0x09 / state 枚举 / 寄存器表：<https://github.com/clockworkpi/PicoCalc/blob/master/Code/picocalc_keyboard/keyboard.h> ，<https://raw.githubusercontent.com/clockworkpi/PicoCalc/master/Code/picocalc_keyboard/reg.h>
- 键盘编程指南 / I2C 必须 10 kHz：<https://deepwiki.com/clockworkpi/PicoCalc/5.3-keyboard-programming> ，<https://deepwiki.com/clockworkpi/PicoCalc/7-troubleshooting>
- cooked-ASCII 烘 shift（keyboard.ino）：<https://raw.githubusercontent.com/clockworkpi/PicoCalc/master/Code/picocalc_keyboard/keyboard.ino>
- BBQ10 血统：<https://github.com/solderparty/i2c_puppet> ，<https://github.com/cuu/arduino_picocalc_kbd>
- 引脚/SD/音频/PSRAM：<https://github.com/LennartHennigs/PicoCalc-Notes> ，<https://deepwiki.com/clockworkpi/PicoCalc/2.3-display-and-audio> ，<https://www.clockworkpi.com/picocalc>
- 面板批次 ST7365P + 本地刷屏速度：<https://forum.clockworkpi.com/t/new-lcd-screen-st7365p-in-recent-picocalc-commit/17649>
- 可复用驱动生态：<https://github.com/jblanked/awesome-pico-calc>

**目标主控（RP2350 / Pico 2 W）**
- RP2350 数据手册（USB 1.1 FS、外设）：<https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf>
- HSTX 高速串行发送：<https://www.cnx-software.com/2024/08/15/raspberry-pi-rp2350-hstx-high-speed-serial-transmit-interface/>
- Pico SDK USB = 上游 TinyUSB / 复合设备示例：<https://github.com/raspberrypi/pico-examples/tree/master/usb/device/dev_hid_composite>
- Pico 2 W 引脚（CYW43 不冲突）：<https://datasheets.raspberrypi.com/picow/pico-2-w-pinout.pdf>

**GUD / 参考实现**
- `notro/gud-pico`（RP 家族 GUD 设备端，已归档）：<https://github.com/notro/gud-pico>
- gud-pico 实测帧率（1 MB/s、320×240+LZ4 ≈13 fps）：<https://forums.raspberrypi.com/viewtopic.php?t=310757>
- Linux mainline `drm/gud`（5.13 起、绑 16d0:10a9）：<https://www.phoronix.com/news/Generic-USB-Display-GUD-5.13> ，<https://cateee.net/lkddb/web-lkddb/DRM_GUD.html>
- TinyUSB vendor class 示例：<https://github.com/hathach/tinyusb/blob/master/examples/device/webusb_serial/src/main.c>
