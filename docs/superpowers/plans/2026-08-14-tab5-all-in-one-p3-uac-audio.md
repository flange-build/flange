# Tab5 all-in-one — P3：UAC1 全双工音频（ES8388 + ES7210）实施计划

> **⚠️ 2026-08-14 修订（实施时生效的版本）** —— 与初稿的三处偏离，已同步进本文：
>
> 1. **删掉了原 Task 0「bring-up 屏上状态面板」**（初稿的提交已在分支上 revert）。
>    面板会让数据泵任务变成 PPA 的第三个提交者、占 64 KB PSRAM，而它自己正是
>    Task 9 要测的那个变量。**本阶段不往屏幕上画任何东西**，`standby_screen.*` /
>    `display_dsi.c` 一律不动。于是硬约束 C 的可见通道从三条减为**两条**
>    （宿主机 + host 侧），所有原本落在「屏上第 N 行」的判据一律改到 **host 侧**
>    （`lsusb -v` / `dmesg` / `/proc/asound` / `aplay` / `arecord`）。
> 2. **不做固件自造正弦波的中间步骤。** 原 Task 2/3 用「喇叭响 1 kHz 正弦」和
>    「屏上电平条会动」把 codec 与 USB 分开验，两条判据都依赖屏幕；面板没了之后
>    它们无处落地。直接做到 `aplay` 出声、`arecord` 录到为止 —— 代价是 codec 与
>    USB 两段不再分开归因，缓解办法见 Task 7/8 的排查顺序。
> 3. **HID 保持 IF1 不动**，音频三接口追加在它**之后**（IF2/IF3/IF4）。
>    初稿按 spec §2 把 HID 挪到 IF4，但键盘与多点触摸都已实机验证通过，
>    没有理由为排版去动它们的接口号；IAD 只要求所覆盖的接口连续，不要求排在最前。
>
> 其余部分（关键事实、参数论证、代码片段）原样有效。

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外 `. $HOME/esp/esp-idf/export.sh && idf.py build` 编译验证；烧录、听声、host 侧 ALSA 验证由人工控制者做。

**Goal:** 让 Tab5 作为 Linux 主机的 **USB 声卡**：播放（host → USB → ES8388 → 喇叭）与录音（ES7210 双麦 → USB → host）**同时可用**，host 侧走 mainline `snd-usb-audio`，零自定义驱动。与已实机验证的 GUD 显示、HID 键盘、HID 多点触摸同处一个 USB 复合设备且互不破坏。

**Architecture:** ES8388(0x10) 与 ES7210(0x40) 都挂在**内部 I2C**（G31/G32）上，复用 `board_i2c_bus()` 的总线句柄。I2S 的收发数据线**物理独立**（DOUT=G26 → codec / DSIN=G28 ← ADC），SCLK/LRCK/MCLK 共用，因此在**一个 I2S 端口上组成真全双工**——Cardputer 上那套半双工仲裁逻辑不移植。USB 侧是手工拼装的 **UAC1**（Audio Class 1.0）复合功能：1 个 AudioControl 接口 + 2 个 AudioStreaming 接口（OUT 播放 / IN 录音），**同步类型分别是 adaptive 与 asynchronous，绝不引入显式反馈端点**（理由见下「硬约束 A」）。

**Tech Stack:** ESP-IDF v6.0.2、TinyUSB 0.21.0~1（`espressif/tinyusb`，已原生支持 UAC1）、`espressif/esp_tinyusb` 2.2.1、`espressif/esp_codec_dev`（ES8388 / ES7210 寄存器序列）、IDF 内置 `esp_driver_i2s` 全双工 STD 模式；host 侧 `snd-usb-audio` + `aplay` / `arecord` / `/proc/asound`。

---

## 范围

只做音频。前置：P0（GUD 显示）、P1（HID 键盘）、P2（HID 多点触摸）均已实机验证通过（见 `components/packages/tab5-all-in-one/README.md` 的状态清单）。

设计依据：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` §1（硬件表）、§2（USB 布局与端点预算）、§2.1（带宽零和）、§6（音频）、§8.1（依赖）、§10（阶段 4 的验证标准）。

**不做**：音量/静音的 Feature Unit 控制（host 侧用软件音量即可，见 Task 5 的说明）、回声消除 / 波束成形、多采样率切换、UVC（P4 阶段）。

---

## 四条硬约束（贯穿全计划，每条都有对应的步骤与判据）

### A. 绝不使用显式反馈端点（explicit feedback endpoint）

P4 全速控制器（tinyusb `portable/synopsys/dwc2/dwc2_esp32.h:79`，**已逐字核实**）：

```c
{ .reg_base = DWC2_FS_REG_BASE, .irqnum = ETS_USB_OTG11_CH0_INTR_SOURCE,
  .ep_count = 7, .ep_in_count = 5, .otg_dfifo_depth = 256 },   /* rhport 0 = 全速 */
```

`ep_in_count = 5` **含 EP0**，即非 EP0 的可用 IN 端点只有 **4 条**。

#### IN 端点占用表（四种组合，一次说清互斥关系）

| 组合 | `0x81` | `0x82` | `0x83` | `0x84` | 第 5 条 | 结论 |
|---|---|---|---|---|---|---|
| **当前（P2 结束）** | vendor(GUD) | HID | — | — | — | 2/4，余 2 |
| **+ 音频（本阶段）** | vendor(GUD) | HID | **UAC 录音** | — | — | **3/4，余 1** ✅ |
| **+ 音频 + UVC（P4 阶段）** | vendor(GUD) | HID | UAC 录音 | **UVC 视频流** | — | 4/4，正好用满 ✅ |
| **+ 音频 + CDC 调试串口** | vendor(GUD) | HID | CDC 通知 | CDC 数据 | **UAC 录音** | **5/4 → 不可行** ❌ |
| **+ 音频 + 反馈端点** | vendor(GUD) | HID | UAC 录音 | **反馈 EP** | UVC 无位置 | 音频能跑，但**UVC 被顶掉** ❌ |

两条结论，都要写进代码注释：

1. **反馈端点会顶掉 UVC。** 所以音频的同步类型必须是 adaptive（播放 OUT）与 asynchronous（录音 IN），`bSynchAddress` 全填 0，`CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP` 显式写 0。
2. **CDC 调试串口与音频在全速口上互斥。** CDC 自带 2 条 IN（通知 + 数据，见 `firmware/README.md` 已记录的端点表），加上 vendor 与 HID 正好 4 条用满，音频 IN 就是第 5 条。

超编时 `dcd_dwc2.c:227` 的 `TU_ASSERT(_dcd_data.allocated_epin_count < dwc2_controller->ep_in_count)` 直接失败——而且**默认日志等级下一个字都不打**，症状是 `SET_INTERFACE` 被 STALL、某个接口静默不工作，**看起来与音频毫无关联**。

> ⚠️ 第 2 条对本阶段的实际后果：**「先临时开 CDC 把音频调通」这条退路是堵死的。** 实施者在最需要日志的时候一定会想到它，然后撞上一个像是描述符写错的枚举失败。所以 Task 5 Step 3 会把它变成编译期 `#error`。**初稿给的那条替代观测通道（屏上面板）本版已删**，因此这段 bring-up 期确实是盲的 —— 缓解办法见下方硬约束 C。

**所以：播放 OUT 端点用 `TUSB_ISO_EP_ATT_ADAPTIVE`，录音 IN 端点用 `TUSB_ISO_EP_ATT_ASYNCHRONOUS`，两者的 `bSynchAddress` 都填 0，且 `CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP` 显式写 0。** 异步 IN 端点本来就不需要反馈端点（反馈是给异步 **OUT** sink 用的，设备是 IN 方向的时钟主控）；adaptive OUT sink 靠自己吸收速率差，也不需要反馈。

> ⚠️ **顺带一个静默陷阱**：UAC1 下 `bmAttributes` 的 sync 字段**绝不能填 0**（`TUSB_ISO_EP_ATT_NO_SYNC`）。`audio_device.c:908-922` 的 UAC1 分支正是靠 `sync == TUSB_ISO_EP_ATT_NO_SYNC` 来判定「这是一条反馈端点」的——填 0 会让 TinyUSB 把我们的数据端点当成反馈端点，数据永远发不出去。

判据落点：Task 5（宿主机描述符解析脚本断言 `bSynchAddress == 0` 且 sync 字段非 0）、Task 6（`lsusb -v` 与 `/proc/asound/cardN/stream0` 里不出现 Sync Endpoint）。

### B. FIFO 预算 256 words = 1024 字节，必须给 UVC 留出约 512 字节

`dwc2_esp32.h:79` 给全速控制器的 `otg_dfifo_depth = 256`（words，即 1 KB）。这块 SPRAM 要同时装下**共享 RX FIFO**（所有 OUT 端点共用）与**每条 IN 端点各自的 TX FIFO**。分配公式（`dcd_dwc2.c:201-203` 与 `dfifo_alloc()`）：

```
RX FIFO   = 13 + 1 + 2*(最大 OUT 包字节/4 + 1) + 2*ep_count     ; ep_count = 7
          = 30 + 最大OUT包字节/2
TX FIFO_n = ceil(该 IN 端点最大包字节 / 4)                       ; bulk 且开双缓冲则 ×2
```

分配失败时 `dfifo_alloc()` 只是 `TU_ASSERT` 返回 false，**无日志**。所以本计划必须**实测**（Task 6），不能算完就算数。

判据落点：Task 6 读 DWC2 寄存器打印实际占用与空闲，空闲 ≥ 100 words（400 字节）即算通过，并把数字回填 `firmware/README.md`。

### C. 现场没有任何串口，所以判据不能落在日志上

这块板默认状态下**没有可用串口**：UART0(G37/G38) 只在 M5-Bus 排针上（要外接 USB-TTL），USB-Serial/JTAG 已被 TinyUSB 收走 FSLS PHY，`CONFIG_TINYUSB_CDC_ENABLED` 默认关闭——而按硬约束 A 的端点表，**本阶段连临时打开 CDC 都不行**。

这条约束比它看起来更硬：**它把「用 `ESP_LOGI` 打个数看看」这个默认调试手段整个拿掉了。** 因此本计划的每一条判据都必须落在下面**两条能看见的通道**之一，任何一条判据若只存在于 `ESP_LOG*` 里，就等于没有判据：

| 通道 | 覆盖阶段 | 落点 |
|---|---|---|
| **① 宿主机（不上板）** | 描述符、纯逻辑函数 | Task 4 的 `test_audio_frame.c`、Task 5 的 `check_usb_desc.py` |
| **② host 侧** | USB 枚举之后的一切 | `lsusb -v`、`dmesg`、`/proc/asound/`、`aplay` / `arecord`、`evtest` |

> ⚠️ **这两条通道之间有一段盲区**：从上电到 host 完成枚举之间（codec / I2S bring-up）
> 什么都看不见。初稿用屏上面板补这一格，本版删掉了它（见顶部修订记录），因此
> **接受这段盲区**，代价是 codec 与 USB 两段不再分开归因。缓解办法有三：
> ① 两颗 codec 的初始化失败会各自返回错误码并让 `codec_audio_start()` 整体失败，
> 音频降级但 host 侧仍能枚举出声卡 —— 「有声卡但全静音」本身就是一条 host 侧可见的信号；
> ② I2S 全双工是否成立由**读寄存器**显式判定（见硬约束表下方的第 2 条），不靠日志；
> ③ 真要抓这一段，接 UART0(G37/G38，在 M5-Bus 排针上) 外挂 USB-TTL —— 代码里的
> `ESP_LOG*` 全部保留，它们不是判据，但接上串口时是最快的现场证据。

> ⓘ **订正任务说明中的一条**：本仓库**目前并没有**「从 ELF dump 描述符再用解析器跑一遍」的既有做法——P1/P2 的宿主机验证做的是**纯逻辑函数**回归（`test_kbd_translate.c` / `test_touch_map.c` / `test_standby_screen.c`），HID 报告描述符本身是靠上板后 `evtest` 的行为反推的。本计划把这条做法**新建**出来（Task 5），因为 UAC1 描述符比 HID 报告描述符更长、更多交叉引用（terminal ID 链、`wTotalLength`、`baInterfaceNr`），且失败时没有任何降级形态。

判据落点：Task 5 的 `check_usb_desc.py` 在**不烧板**的前提下把整份配置描述符断言一遍 —— 这是本阶段唯一一道能在烧板前拦住错误的闸门。

### D. 不破坏已验证的 GUD 显示、HID 键盘、HID 多点触摸

接口号会变（见下「接口与端点新旧对照」）。每个上板任务的成功判据都**必须**包含：`modetest -M gud` 仍出图、`evtest` 键盘仍能打字、触摸仍出 `ABS_MT_*`。Task 9 是专门的复合回归。

---

## 关键事实（已核实，不要凭记忆改）

### 硬件（spec §1 + 实机 i2cscan，见 `firmware/README.md` 的「实测 I2C 设备表」）

| 项 | 值 |
|---|---|
| 播放 codec | **ES8388 @ I2C `0x10`**（实机 i2cscan 已应答） |
| 录音前端 | **ES7210 @ I2C `0x40`**（实机 i2cscan 已应答，双麦） |
| I2S MCLK / SCLK / LRCK | **G30 / G27 / G29** |
| I2S DOUT（ESP→ES8388） | **G26** |
| I2S DSIN（ES7210→ESP） | **G28** |
| 内部 I2C | SDA=G31 / SCL=G32，`I2C_NUM_0`，由 `board_power.c` 持有 |
| IO 扩展 | PI4IOE5V6408 ×2：`0x43`（本固件已在用：LCD_EN=PIN4 / TOUCH_EN=PIN5）、`0x44`（尚未使用） |

### I2C 总线怎么共享（**已查证，不是推测**）

`board_power.c:11-14,30-38` 用 `i2c_new_master_bus()` 在 `I2C_NUM_0` 上建了唯一一条内部总线，句柄存 `static i2c_master_bus_handle_t s_i2c`，通过 `i2c_master_bus_handle_t board_i2c_bus(void)` 对外暴露。既有的两个消费者都是**复用**而非新建：

- `display_dsi.c:164-165` 的 `panel_detect()` 直接 `i2c_master_probe(board_i2c_bus(), ...)`；
- `touch_hid.c:4-6` 的注释写明「直接复用 `board_i2c_bus()` 的总线句柄，不像键盘那样自建总线」。

（对照：`kbd_i2c.c` 自建 `I2C_NUM_1`，因为 Tab5 Keyboard 在**物理分离**的 G0/G1 上。）

**音频 codec 的接法**：`esp_codec_dev` 的控制接口正好吃现成的总线句柄——

```c
audio_codec_i2c_cfg_t i2c_cfg = {
    .port       = I2C_NUM_0,
    .addr       = ES8388_I2C_ADDR8,  /* ⚠️ 8 bit 形式 0x20，不是 7 bit 的 0x10，见下一节 */
    .bus_handle = board_i2c_bus(),   /* 复用，绝不新建 master */
};
const audio_codec_ctrl_if_t *ctrl_if = audio_codec_new_i2c_ctrl(&i2c_cfg);
```

`.bus_handle` 这个字段的用法有 IDF 官方例子为证：`$IDF_PATH/examples/peripherals/i2s/i2s_codec/i2s_es7210_tdm/main/i2s_es7210_record_example.c:189-195`。

### 音频器件的供电与上电时序（**已查证 esp-bsp，不是推测**）

来源：`espressif/esp-bsp` 的 `bsp/m5stack_tab5/`（Apache-2.0）。

| 事实 | 出处 |
|---|---|
| **喇叭功放使能 = `SPEAKER_EN`，在 `0x43` 那颗 PI4IOE5V6408 的 PIN1** | `include/bsp/m5stack_tab5.h:88` `#define BSP_SPEAKER_EN (IO_EXPANDER_PIN_NUM_1)`；`src/bsp_feature_en.c:33-39` 走的是 `bsp_io_expander_init()`（`BSP_IO_EXPANDER_ADDRESS` = `..._ADDRESS_LOW` = **0x43**，见本工程 `managed_components/espressif__esp_io_expander_pi4ioe5v6408/include/esp_io_expander_pi4ioe5v6408.h:30`）——**与本固件已在用的 `LCD_EN`(PIN4) / `TOUCH_EN`(PIN5) 是同一颗**，`board_power.c` 的 `ioexp_out()` 直接复用，不必新建 expander 句柄 |
| **`BSP_POWER_AMP_IO = GPIO_NUM_NC`**，即功放没有独立 GPIO | `include/bsp/m5stack_tab5.h:87`。⇒ `es8388_codec_cfg_t.pa_pin` 填 −1 后 ES8388 驱动内建的 PA 控制是**空操作**（`es8388.c:201-208` 遇 `pa_pin == -1` 直接 return），功放**必须我们自己经 IO 扩展驱动** |
| **两颗 codec 没有任何独立 reset / power-enable 引脚**，常供电，复位只靠 I2C 软复位寄存器 | esp-bsp 的 Tab5 板级头里除 `BSP_SPEAKER_EN` 外没有任何 codec 相关引脚；ES7210 软复位 `REG00: 0xff → 0x41`，ES8388 `CHIPPOWER(0x02): 0xF0 → 0x00` |
| 0x43 上其余分配：`WIFI_EN`=PIN0、`USB_EN`=PIN3、`LCD_EN`=PIN4、`TOUCH_EN`=PIN5、`CAMERA_EN`=PIN6 | 同头文件。**PIN0/PIN3 别碰**（那两个在 esp-bsp 里走的是 0x44 那颗，语义待考） |

> ⚠️ **esp-bsp 自己的上电顺序不理想，本计划刻意不照抄。** `src/bsp_audio.c:97-145` 的顺序是
> I2C → I2S 通道创建并 enable → **`bsp_feature_enable(BSP_FEATURE_SPEAKER, true)`** → 建 codec 对象
> →（由应用后续调 `esp_codec_dev_open()` 才真正写 ES8388 的 ~33 条寄存器）。
> **功放在 codec 尚未配置、DAC 尚未上电时就已经导通**，代码里没有任何延时或静音处理。
>
> 本计划改为：**I2S → `esp_codec_dev_open()`（ES8388 的 `open()` 第一条就是 `DACCONTROL3=0x04` 静音，
> 随后由 `esp_codec_dev_open()` 内部 unmute）→ 稳定延时 → 才拉高 `SPEAKER_EN`**；关流/关机时**反序**
> （先拉低 `SPEAKER_EN` 再 close）。这与本固件已有的背光处置**同构**：`board_power_init()` 只把
> 引脚配好并保持关闭，真正打开归各自的功能域（见 `board_power.c:51-56` 与 `display_init()`）。
>
> ⓘ 这是从代码顺序**推出**的风险，esp-bsp 的注释与 issue 里**没有**关于 Tab5 爆音的已知报告。
> 判据只能是实机耳朵：Task 2 要求「上电与开始播放的瞬间没有可闻的『啪』声」。

### `esp_codec_dev` 的依赖与两个陷阱（**已查证 v1.6.2 源码**）

- **依赖只有 `idf >= 4.0`**，CMake 的 `PRIV_REQUIRES` 全是 IDF 内置（`freertos esp_ringbuf esp_hw_support esp_driver_gpio esp_driver_i2c esp_driver_i2s esp_driver_spi esp_adc`），**不含 esp-bsp / esp_lcd / LVGL / adf**。依赖树干净这条成立。
- 各 codec 由 Kconfig 单独门控（`CONFIG_CODEC_ES8388_SUPPORT` / `CONFIG_CODEC_ES7210_SUPPORT` 默认 y，其余十来颗可全关），能裁到只编两个 `.c`。
- ⚠️ **陷阱一：`audio_codec_i2c_cfg_t.addr` 收的是 8 bit 形式的地址**，驱动内部 `>> 1`（`platform/audio_codec_ctrl_i2c.c:52`）。组件自带的常量就是 8 bit 的：`ES8388_CODEC_DEFAULT_ADDR = 0x20`（= 7 bit 的 0x10）、`ES7210_CODEC_DEFAULT_ADDR = 0x80`（= 7 bit 的 0x40）。而 `i2c_master_probe()` 收的是 **7 bit**。**两种地址必须分别定名**，混用的症状是 codec 初始化返回失败或写到别的器件上。
- ⚠️ **陷阱二：`esp_codec_dev_close()` 不会去关功放**（`esp_codec_dev.c:563-569` 只调 codec 与 data_if 的 `enable(false)`）。关流时不自己拉低 `SPEAKER_EN` 就会残留导通，容易有关机 pop。

### TinyUSB 的 UAC1 支持（**订正任务说明中的一条**）

> ⚠️ 任务说明里的「TinyUSB 没有 UAC1 描述符模板宏，`TUD_AUDIO10_*` 不存在，必须逐字节手写」**与本仓库锁定的版本不符**。
>
> 本工程锁的是 `espressif/tinyusb: "0.21.0~1"`，`managed_components/espressif__tinyusb/src/device/usbd.h:472-546` 有**完整的 `TUD_AUDIO10_*` 模板宏**（`DESC_STD_AC` / `DESC_CS_AC` / `DESC_INPUT_TERM` / `DESC_OUTPUT_TERM` / `DESC_FEATURE_UNIT` / `DESC_STD_AS_INT` / `DESC_CS_AS_INT` / `DESC_TYPE_I_FORMAT` / `DESC_STD_AS_ISO_EP` / `DESC_CS_AS_ISO_EP` …），UAC1 的结构体也齐（`audio.h:317-527`，含带 `bRefresh`/`bSynchAddress` 的 9 字节 `audio10_desc_as_iso_data_ep_t`）。
>
> **不存在的是「整功能」模板**：只有 `TUD_AUDIO10_MIC_ONE_CH_DESCRIPTOR`（单麦，且不带 IAD），**没有 speaker 方向、也没有播放+录音复合的现成模板**。所以「一个 AC + 两个 AS」的复合布局仍然要**自己用底层宏拼**——这与「逐字节手写」的工作量差别很大，但审查强度不能降低（宏只保证每条 item 的 `bLength`/tag 自洽，**不校验** terminal ID 链、`wTotalLength`、`baInterfaceNr` 这些跨描述符引用，那正是 Task 5 那个宿主机脚本要管的）。
>
> **而且本仓库已有可直接照搬的先例**：`components/packages/cardputer-all-in-one/firmware/main/usb_descriptors.c:26-74` 的 `UAC1_AUDIO_DESCRIPTOR` 宏就是用这批 `TUD_AUDIO10_*` 拼出来的「1×AC + 播放 AS + 录音 AS」，Cardputer 上已实机跑通。本计划直接以它为底稿改。

### esp_tinyusb 没有 audio 的 Kconfig，要自己接 `tusb_config.h` 覆盖

`espressif__esp_tinyusb/Kconfig` 里 `AUDIO` 零命中，`include/tusb_config.h` 里也没有 `CFG_TUD_AUDIO`。启用办法是让 **tinyusb 与 esp_tinyusb 两个库**都优先看到我们自己的 `tusb_config.h`（只改一个会让两边的 `CFG_TUD_*` 不一致，接口数/描述符长度对不上）。

Cardputer 已经把这套 CMake 接线跑通了，**逐行照搬**：`components/packages/cardputer-all-in-one/firmware/main/CMakeLists.txt:6-27`。

### TinyUSB 0.21 的 `CFG_TUD_AUDIO_*` 项（与老教程不同，逐条已核实）

- **已删除**：`CFG_TUD_AUDIO_FUNC_1_DESC_LEN`、`CFG_TUD_AUDIO_FUNC_1_N_AS_INT`、`CFG_TUD_AUDIO_FUNC_1_CTRL_BUF_SZ`、以及全部 encoding/decoding 相关宏。描述符长度现在由 `audiod_open()` 运行时扫描得出（`audio_device.c:860-886`）。
- **必须定义**（否则 `audio_device.h:56-143` 直接 `#error`）：启用 IN 时的 `CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX` + `..._EP_IN_SW_BUF_SZ`（后者必须 ≥ 前者）；启用 OUT 时的 `..._EP_OUT_SZ_MAX` + `..._EP_OUT_SW_BUF_SZ`。
- `CFG_TUD_AUDIO_CTRL_BUF_SZ` 现在是**全局**项（`audio_device.h:42-44`），默认 64，够用。
- UAC1 的采样率控制走**端点**请求（`AUDIO10_EP_CTRL_SAMPLING_FREQ`，`audio_device.c:1334-1343`），不是 UAC2 的 clock source 实体——回调是 `tud_audio_get_req_ep_cb` / `tud_audio_set_req_ep_cb`。

### I2S 全双工的两条硬性要求（IDF v6.0，**已读源码核实**）

1. **TX 与 RX 必须在同一个 I2S 端口，且两次 `i2s_channel_init_std_mode()` 传的 `i2s_std_config_t` 要能 `memcmp` 相等**（`components/esp_driver_i2s/i2s_std.c:257-262`）。所以要**给两个句柄传同一份 config**——其中 `dout` 与 `din` **两个都填**（IDF 官方文档的 full-duplex 例子就是这么写的，`docs/en/api-reference/peripherals/i2s.rst:922-945`）。
2. **配置不一致时不会报错**：P4 是 `SOC_I2S_HW_VERSION_2`，走的是 `i2s_std.c:286` 那条分支，只打一条 **DEBUG 级**的 `"TX & RX on I2S%d are simplex"`，然后**两个方向各自去驱动 BCLK/WS**——症状是时钟打架、声音全是噪声或全静音，而所有函数都返回 `ESP_OK`。**这是本阶段最容易静默踩掉的坑。**

   ⚠️ **不要把判据寄托在那条 DEBUG 日志上**：本工程现场没有串口（硬约束 C），那行字谁也看不见。本计划改用两道**自己的**防线（Task 2 Step 3）：

   - **结构上保证一致**：TX/RX 的 `i2s_std_config_t` 由**同一个 `const` 局部变量**派生，两次 `i2s_channel_init_std_mode()` 传的是同一个对象的地址，「填得不一样」在结构上就不可能发生；
   - **运行时显式判定**：`i2s_std.c:142-146` 的 `i2s_ll_share_bck_ws()` 在 P4 上写的是 `I2S0.tx_conf.sig_loopback`（`components/soc/esp32p4/register/hw_ver1/soc/i2s_struct.h:576-580`，bit 30）。两个通道都 init 完之后**这一位必须是 1**——它就是硬件层面「TX 与 RX 共用 BCLK/WS」的开关。读它，为 0 就走**可见**的失败路径（返回错误码、不启动音频，host 侧表现为「声卡在但全静音」），而不是任其 `ESP_OK` 放行后变成一屋子噪声。
3. 由 2 推论：**TX 与 RX 不能一个用 STD、一个用 TDM**（两者的 `mode_info` 结构体都对不上）。ES8388 与 ES7210 都按 **STD Philips 立体声 2 slot** 配，不用 TDM——ES7210 的驱动本身也是「≥3 只麦才开 TDM」（`es7210.c:16,177-185` 的 `ENABLE_TDM_MAX_NUM = 3`），Tab5 只有 2 只麦，`REG12` 写 `0x00`，MIC1→左 slot、MIC2→右 slot。
4. **两个通道必须在一次 `i2s_new_channel()` 调用里同时要到**（`&tx, &rx` 一起传），不能先起 TX 再追加 RX——ESP32-P4 的 I2S v2 上分两次建会失败（[esphome#16043](https://github.com/esphome/esphome/issues/16043)）；esp-bsp 的 `bsp_audio.c:50` 也是一次调用建两个。
5. **不要用 `I2S_SLOT_MODE_MONO`**：`I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(..., MONO)` 会把 `slot_mask` 设成 `I2S_STD_SLOT_LEFT`，录音就**只拿得到 ES7210 的 MIC1，MIC2 白装**（esp-bsp 的 `bsp_audio.c:34` 正是这么配的）。线上统一走 STEREO，单↔双的转换放到 `audio_frame.c` 的纯函数里。
6. **运行时改采样率会短暂中断 TX**：`esp_codec_dev` 的 `audio_codec_data_i2s.c:421-427` 有原注「Set RX clock will not take effect if in full duplex mode, need update TX clock also」，它会自动 disable/reconfig/enable TX 来补。所以**固定单一采样率、不做运行时重配**——这也是本计划只在描述符里声明一个采样率的另一个理由。同文件 `:432-455` 的 `check_fs_compatible()` 在 TX/RX 采样率不同时直接返回 `ESP_CODEC_DEV_NOT_SUPPORT`。

---

## 参数选定：16 kHz / 16 bit / 单声道，双向

**结论：`UAC_SAMPLE_RATE = 16000`、`UAC_CHANNEL_COUNT = 1`、16 bit（`S16_LE`），播放与录音同参数。**

### 为什么两个方向必须同采样率

不是选择题：全双工的 TX/RX 共用 BCLK 与 WS（上一节第 1 条），采样率、位宽、slot 数三项都必须一致。想要两个方向不同采样率就得占两个 I2S 端口，而 Tab5 的 SCLK/LRCK/MCLK 在物理上只有一组。

### 为什么是 16 kHz 而不是 48 kHz —— FIFO 账（这是决定性的那一笔）

端点最大包按 `每毫秒样本数 × 声道数 × 2 字节` 再留一个样本的余量算。代入硬约束 B 的公式（当前最大 OUT 包是 vendor 的 64 字节，RX FIFO = 30 + 64/2 = **62 words**，与 `firmware/README.md` 记的实测值一致）：

| 方案 | OUT 包 | IN 包 | RX FIFO | 音频 IN 的 TX FIFO | 合计已用 | 空闲（留给 UVC） |
|---|---|---|---|---|---|---|
| **16 kHz 单声道（本方案）** | 36 B | 36 B | **62**（不涨） | 9 | **135** | **121 words = 484 B** ✅ |
| 32 kHz 单声道 | 68 B | 68 B | 64 | 17 | 145 | 111 words = 444 B |
| 16 kHz 立体声 | 68 B | 68 B | 64 | 17 | 145 | 111 words = 444 B |
| 48 kHz 单声道 | 100 B | 100 B | 80 | 25 | 169 | 87 words = 348 B |
| 48 kHz 立体声 | 196 B | 196 B | 128 | 49 | 241 | **15 words = 60 B** ❌ UVC 没位置 |

（合计已用 = RX + EP0 IN 16 + vendor IN 32 + HID IN 16 + 音频 IN。）

**16 kHz 单声道有一个别的档位没有的性质：OUT 包 36 B < vendor 已有的 64 B，共享 RX FIFO 一个 word 都不涨**，整个音频功能的 FIFO 代价只有录音那 9 words。48 kHz 立体声则会把空闲压到 60 字节，**UVC 阶段直接没位置**——而这条在实机上不会有任何报错，只会表现为「加了摄像头之后音频或摄像头随机不工作」。

### 为什么 16 kHz 也让「不用反馈端点」这件事成立

`16000 % 1000 == 0` ⇒ 每个 USB 帧**恰好 16 个样本**，没有小数包。若选 44 100 Hz，就是每帧 44.1 个样本、必须按 9/10 的比例交替发 44 和 45 个样本并跟踪相位漂移——那正是逼人上显式反馈端点的场景。选整千倍数的采样率，adaptive/asynchronous 就足够了。这条与硬约束 A 是同一个决定的两面。

### 带宽账（全速 12 Mbps = 1500 字节/毫秒；ISO+INT 规范上限约 90% = 1350 字节/毫秒）

| 项 | 每毫秒字节 | 占 1500 B/ms |
|---|---|---|
| UAC 播放 ISO OUT（16 样本 × 2 B） | 32（端点声明 36） | 2.4% |
| UAC 录音 ISO IN | 32（端点声明 36） | 2.4% |
| HID 中断 IN（64 B / 10 ms，按峰值帧计） | ≤64 | ≤4.3% |
| **周期性合计（须 ≤ 1350）** | **≤136** | **9%** |
| GUD bulk（尽力而为，实测约 1 MB/s ≈ 1000 B/ms） | 余下 ~1364 | — |

也就是说：音频满负荷跑时，留给 GUD bulk 的理论上限仍有约 1364 B/ms，**高于 GUD 目前实测能跑到的吞吐**。所以本阶段的预期是「音频不会让显示明显变慢」，Task 9 要验证这一点；若实测显示明显掉帧，说明瓶颈不在带宽账上（多半是 CPU 或 PSRAM 争用），要单独归因。

### 声道数与位深

- **单声道**：省一半 ISO 带宽与 TX FIFO；I2S 线上仍走**立体声 2 slot**（codec 与 ADC 都是双声道器件，且全双工要求 TX/RX slot 配置一致），单↔双的转换在 `audio_frame.c` 的纯函数里做（Task 4，宿主机可测）。
- **16 bit / `S16_LE`**：ES8388 与 ES7210 原生支持；24 bit 会让每包涨 50% 而听感在一只板载喇叭上无差别。

### 升级阶梯（本阶段**不做**，留给 UVC 结论出来之后）

采样率/声道数是 `usb_descriptors.h` 里的两个常量。从上表可见，**32 kHz 单声道**与 **16 kHz 立体声**只多吃 10 words FIFO、64 B/ms 带宽，属于「几乎免费」的升级档；48 kHz 立体声则不可行。等 P4（UVC）的可行性结论出来、且 Task 6 的 FIFO 实测数字在手上之后再抬，比现在赌一个数省事。Task 10 要把这张表写进 `firmware/README.md`。

---

## 接口与端点新旧对照

spec §2 的最终布局把 HID 排在 UAC 之后（IF4）。**本阶段刻意不落实这一点**：音频三接口追加在 HID **之后**，`IF0` vendor 与 `IF1` HID 的编号一个都不动。

| | 现在（P2 结束） | 本阶段之后 | UVC（P4，预留） |
|---|---|---|---|
| IF0 | Vendor(GUD) | Vendor(GUD) | 同 |
| IF1 | **HID（键盘+触摸）** | **HID（键盘+触摸）不变** | 同 |
| IF2 | — | AudioControl | 同 |
| IF3 | — | AudioStreaming OUT（播放） | 同 |
| IF4 | — | AudioStreaming IN（录音） | 同 |
| IF5/IF6 | — | — | VideoControl / VideoStreaming |

**为什么不按 spec §2 排**：接口号对 host 侧本来就没有功能影响 —— `drm/gud` 按 VID/PID + 接口类绑定，`usbhid` / `hid-multitouch` 按接口类绑定，`snd-usb-audio` 按 **IAD** + 接口类绑定，**没有任何一方按接口号绑定**。既然重排一分好处也没有，就没有理由去动两个已经实机验证过的接口 —— 硬约束 D 要防的正是这类「顺手改一下」。IAD 只要求它覆盖的接口**连续**，不要求它们排在配置描述符的最前面（TinyUSB 的 `audiod_open()` 也是从 AC 接口往后扫到下一个非 AS 接口或下一条 IAD 为止，音频排在末尾完全合法）。

于是固件内需要改的只有两处：`ITF_NUM_*` 枚举末尾追加三项，以及 `tud_audio_set_itf_cb()` 里用 `ITF_NUM_AUDIO_STREAMING_OUT/IN` 做方向判断。`TUD_VENDOR_DESCRIPTOR` / `TUD_HID_DESCRIPTOR` 的参数一个字都不用改。

端点：

| 端点 | 归属 | 变动 |
|---|---|---|
| `0x01` / `0x81` | vendor(GUD) bulk OUT / IN | 不变 |
| `0x82` | HID 中断 IN | **不变**（接口号变了，端点号刻意不动，减少变量） |
| `0x02` | **UAC 播放 ISO OUT** | 新增 |
| `0x83` | **UAC 录音 ISO IN** | 新增 |
| `0x84` | UVC 视频流 IN | 预留 |

> ⚠️ **CDC 调试串口与 UAC 互斥**：CDC 要占 `0x83`（通知）+ `0x84`（数据）两条 IN，与音频、UVC 直接撞号。本计划在 `usb_descriptors.h` 里加一条 `#error` 把这件事变成编译期错误，而不是留给后人调试（见 Task 5 Step 3）。

---

## 文件结构

```
firmware/main/
├── codec_audio.{c,h}          # 新：ES8388/ES7210 初始化 + I2S 全双工 + UAC 数据泵 + 音频类回调
├── audio_frame.{c,h}          # 新：单↔双声道转换，零依赖纯函数（宿主机可测）
├── tinyusb_config/tusb_config.h  # 新：include_next 默认配置后追加 CFG_TUD_AUDIO_*
├── usb_descriptors.{c,h}      # 改：加 UAC1 三接口(IF2/3/4) + 两 ISO 端点；IF0/IF1 不动
├── tab5_pins.h                # 改：加 I2S 引脚、功放使能脚、两个 codec 的 7/8 bit 地址
├── board_power.{c,h}          # 改：功放开关（配好但保持关闭）
├── app_main.c                 # 改：在 touch_start() 之后启动音频
├── idf_component.yml          # 改：加 espressif/esp_codec_dev
└── CMakeLists.txt             # 改：加源文件、tinyusb_config 接线、esp_driver_i2s
firmware/test/
├── test_audio_frame.c         # 新：audio_frame 纯函数回归（直接编译真实源码）
└── check_usb_desc.py          # 新：从 ELF 解析并校验整份配置描述符（烧板前的闸门）
firmware/sdkconfig.defaults    # 改：裁 esp_codec_dev 的 codec 列表
```

**声道转换抽成零依赖纯函数**（照 `kbd_translate.c` / `touch_map.c` 的先例），让 `test/` 能直接编译真实源码做回归。

> ⓘ `standby_screen.{c,h}` 与 `display_dsi.c` **不在本清单里** —— 本阶段不碰显示链路的任何一行，
> 这是「不破坏已验证功能」最省事的落实方式。

---

## Task 1：音频供电、codec 探测与依赖引入（不碰 I2S、不碰 USB）

目标：把 ES8388 / ES7210 的电与 I2C 通路坐实，并确认 `esp_codec_dev` 没有污染依赖树。

**Files:** Modify `main/idf_component.yml`、`main/tab5_pins.h`、`main/board_power.{c,h}`、`main/CMakeLists.txt`、`main/app_main.c`

- [ ] **Step 1：成功判据**

本任务**没有上板判据**（面板已删，此时 USB 侧还什么都没有）。判据全在宿主机：

1. `idf.py reconfigure` 后 `managed_components/` **只多出 `espressif__esp_codec_dev` 一个目录**（Step 5）；
2. `idf.py build` 通过；
3. `idf.py size` 的增量如实记下来，Task 10 要写进 README。

两颗芯片的存在性早已由 `firmware/README.md` 的实测 I2C 设备表证实（`0x10` / `0x40` 都应答过），
本步不重复探测 —— 探测结果只能进 `ESP_LOG*`，而日志不是判据。真出问题时，
`esp_codec_dev_open()` 会在 Task 2/3 直接返回失败，host 侧表现为「声卡在但全静音」。

- [ ] **Step 2：`idf_component.yml` 加 `esp_codec_dev`**

```yaml
  # ES8388 播放 + ES7210 录音的寄存器序列（各约 40 / 50 条，含 ES8388 那三条无文档的
  # 0x35/0x37/0x39 DLL 寄存器，手抄一遍既无收益也无从验证）。这是**芯片驱动**组件，
  # 与已在用的 esp_lcd_ili9881c / esp_lcd_touch_gt911 / esp_io_expander_pi4ioe5v6408
  # 同一性质，不是 esp-bsp 板级组件：它的依赖只有 idf>=4.0，PRIV_REQUIRES 全是 IDF 内置，
  # 不会拖进 LVGL / esp_video / usb-host（Step 5 会验证）。
  # 它的 audio_codec_i2c_cfg_t.bus_handle 正好吃我们已有的 board_i2c_bus()，
  # 因此不会在 G31/G32 上再建一个 master。
  espressif/esp_codec_dev: "1.6.2"
```

`main/CMakeLists.txt` 的 `PRIV_REQUIRES` 追加 `esp_driver_i2s`（`soc` / `hal` 由 IDF 公共依赖提供——`app_main.c` 现在就直接 include 了 `hal/usb_wrap_ll.h`）。

`sdkconfig.defaults` 末尾追加（把组件裁到只剩要用的两颗，其余十来颗 codec 不编）：

```
# esp_codec_dev 默认把十几颗 codec 全编进来。Tab5 只用 ES8388(播放) 与 ES7210(录音)，
# 其余全关 —— 省 flash，也让「哪颗芯片在起作用」这件事在配置里一目了然。
CONFIG_CODEC_ES8311_SUPPORT=n
CONFIG_CODEC_ES8156_SUPPORT=n
CONFIG_CODEC_ES8374_SUPPORT=n
CONFIG_CODEC_ES8389_SUPPORT=n
CONFIG_CODEC_ES7243_SUPPORT=n
CONFIG_CODEC_ES7243E_SUPPORT=n
CONFIG_CODEC_AW88298_SUPPORT=n
CONFIG_CODEC_TAS5805M_SUPPORT=n
CONFIG_CODEC_ZL38063_SUPPORT=n
CONFIG_CODEC_CJC8910_SUPPORT=n
```

> ⚠️ 改了 `sdkconfig.defaults` **必须 `rm -f sdkconfig` 再 build**，否则 defaults 不重新生效（`firmware/README.md` 里已经为 CDC 开关记过这一条）。
> ⚠️ 上面这批 Kconfig 名以 `managed_components/espressif__esp_codec_dev/Kconfig` 实际有的为准：`idf.py build` 会对不存在的项报 warning，按 warning 增删即可（**不要**留下拼错的行——那只是静默无效）。

- [ ] **Step 3：`tab5_pins.h` 加常量**

引脚与功放使能均**已查证**（esp-bsp `bsp/m5stack_tab5/include/bsp/m5stack_tab5.h:82-88`，Apache-2.0），不是推测：

```c
/* ── 音频 ────────────────────────────────────────────────────────
 * I2S 收发数据线物理独立（DOUT/DSIN 是两根脚），因此是真全双工，
 * 不需要 Cardputer 上那套半双工仲裁。取自 esp-bsp bsp/m5stack_tab5。 */
#define PIN_I2S_MCLK       30
#define PIN_I2S_SCLK       27   /* BCLK */
#define PIN_I2S_LRCK       29   /* WS */
#define PIN_I2S_DOUT       26   /* ESP → ES8388，播放 */
#define PIN_I2S_DSIN       28   /* ES7210 → ESP，录音 */

/* 喇叭功放使能：与 LCD_EN(PIN4) / TOUCH_EN(PIN5) 同在 0x43 那颗 PI4IOE5V6408 上
 * （esp-bsp 的 BSP_SPEAKER_EN = IO_EXPANDER_PIN_NUM_1，其 BSP_IO_EXPANDER_ADDRESS
 * 就是 ..._ADDRESS_LOW = 0x43）。功放**没有**独立 GPIO：esp-bsp 的
 * BSP_POWER_AMP_IO = GPIO_NUM_NC，所以 es8388_codec_cfg_t.pa_pin 那条路是空操作，
 * 必须由我们经 IO 扩展自己驱动。 */
#define IOEXP_PIN_SPEAKER_EN  IO_EXPANDER_PIN_NUM_1

/* ⚠️ 两种地址形式必须分开定名：i2c_master_probe() 收 7 bit，而 esp_codec_dev 的
 * audio_codec_i2c_cfg_t.addr 收 **8 bit**（内部再 >>1，见
 * platform/audio_codec_ctrl_i2c.c:52）。混用的症状是 codec 初始化失败或写到别的
 * 器件上 —— 而 I2C 写不会有任何反馈。 */
#define ES8388_I2C_ADDR7   0x10 /* 播放 codec，内部 I2C（实测 i2cscan 已应答） */
#define ES8388_I2C_ADDR8   0x20 /* = ES8388_CODEC_DEFAULT_ADDR */
#define ES7210_I2C_ADDR7   0x40 /* 双麦前端 */
#define ES7210_I2C_ADDR8   0x80 /* = ES7210_CODEC_DEFAULT_ADDR */
```

- [ ] **Step 3b：`usb_descriptors.h` 先落音频参数常量**

这几个常量 Task 2/3 的 I2S 配置就要用（采样率、每帧样本数），而描述符要到 Task 5 才写——**先落常量、后落描述符**，免得 Task 2 里出现一个后面还要改的魔法数。放 `usb_descriptors.h` 而不是 `tab5_pins.h`：它们描述的是**对 host 声明的格式**，不是板级布线。

```c
/* ── UAC1 音频参数 ───────────────────────────────────────────────
 * 16 kHz / 单声道 / 16 bit。选定理由（FIFO 账与带宽账）见
 * docs/superpowers/plans/2026-08-14-tab5-all-in-one-p3-uac-audio.md。
 * 两句话：① 16000 % 1000 == 0 ⇒ 每帧恰好 16 个样本、没有小数包，adaptive/async
 * 就够用，不必上显式反馈端点（那会顶掉 UVC 的 IN 端点）；② OUT 包 36 B 小于
 * vendor 已有的 64 B，共享 RX FIFO 一个 word 都不涨。
 * ⚠️ 播放与录音**必须**同采样率：全双工的 TX/RX 共用 BCLK 与 WS。 */
#define UAC_SAMPLE_RATE      16000
#define UAC_CHANNEL_COUNT    1
#define UAC_BYTES_PER_SAMPLE 2
#define UAC_FRAME_SAMPLES    (UAC_SAMPLE_RATE / 1000)
#define UAC_FRAME_BYTES      (UAC_FRAME_SAMPLES * UAC_CHANNEL_COUNT * UAC_BYTES_PER_SAMPLE)

/*
 * 端点最大包 = 标称帧 + 一个样本的余量（4 字节，按 word 对齐）。
 * 异步 IN 在设备时钟略快于 host 帧钟时需要偶尔多发一个样本；adaptive OUT 同理，
 * host 也可能多送一个。端点大小恰等于标称值会把这条路堵死，只能丢样本 ——
 * 听感是周期性的轻微咔哒，而且极难归因。多出来的 FIFO 代价是 1 个 word。
 */
#define UAC_EP_OUT_SIZE      (UAC_FRAME_BYTES + 4)
#define UAC_EP_IN_SIZE       (UAC_FRAME_BYTES + 4)

_Static_assert(UAC_SAMPLE_RATE % 1000 == 0, "采样率必须产生整数 samples/ms，否则要上反馈端点");
```

- [ ] **Step 4：`board_power.{c,h}` 加功放开关（配好但**保持关闭**）与 codec 探测**

功放**不在 `board_power_init()` 里打开**——这与本固件已有的背光处置同构（`board_power.c:51-56`：引脚配好、保持熄灭，真正点亮归 `display_init()`）。理由：ES8388 在 `esp_codec_dev_open()` 之前 DAC 未上电、输出端电平未定，此时导通功放正是产生开机「啪」声的经典配方。**esp-bsp 自己就是先开功放后配 codec 的**（`src/bsp_audio.c:110` vs 寄存器写入时机），本计划刻意不照抄。

`board_power.h` 追加（与既有的 `board_backlight(bool)` 同形）：

```c
/* 喇叭功放使能。board_power_init() 只把引脚配成推挽输出并**保持关闭**，
 * 真正打开归音频域 —— 不变式是「功放导通 ⟺ ES8388 已配置完成且已解除静音」，
 * 提前导通会在开机时发出一声「啪」。关流/关机时必须先关它再关 codec：
 * esp_codec_dev_close() 不会碰这个引脚（esp_codec_dev.c:563-569）。 */
void board_speaker_enable(bool on);
```

`board_power.c`：在 `board_power_init()` 的 `TOUCH_EN` 之后追加 `ESP_RETURN_ON_ERROR(ioexp_out(IOEXP_PIN_SPEAKER_EN, 0), TAG, "SPEAKER_EN");`（注意电平是 **0**），并实现

```c
void board_speaker_enable(bool on)
{
    esp_io_expander_set_level(s_ioexp, IOEXP_PIN_SPEAKER_EN, on);
}
```

在 `board_power_init()` 末尾（现有的 50ms 稳定延时之后）加探测日志：

```c
    const bool es8388 = (i2c_master_probe(s_i2c, ES8388_I2C_ADDR7, 100) == ESP_OK);
    const bool es7210 = (i2c_master_probe(s_i2c, ES7210_I2C_ADDR7, 100) == ESP_OK);
    /* 用 INFO 而不是 ERROR：音频与键盘/触摸一样是可选能力，探不到只降级不拦启动
     * （见 app_main.c 对 kbd_start/touch_start 的处置原则）。但必须打出来 ——
     * 后面 codec 初始化失败时，这一行是区分「电没上/地址错」与「寄存器序列错」的唯一证据。 */
    ESP_LOGI(TAG, "audio 使能就绪 (ES8388=%d ES7210=%d，功放待 codec 就绪后打开)",
             es8388, es7210);
```

> ⚠️ **本版连这段探测日志也一并删掉了。** 它唯一的出口是 `ESP_LOG*`（原本还要送一份
> 上屏，面板已删），而日志不是判据；探不到 codec 的后果 —— `esp_codec_dev_open()` 失败 —— 
> 已经有明确的返回值路径，再多一次 I2C 事务只是在给挂着触摸 20 ms 轮询的总线添堵。
> 于是 `board_power.{c,h}` 本任务只多一件事：把 `SPEAKER_EN` 配成推挽输出并**保持 0**。
> 初稿的 `board_audio_present()` / `board_codec_t` 一并作废。

- [ ] **Step 5：验证依赖树没被污染**

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh && rm -f sdkconfig && idf.py reconfigure
ls managed_components/
```

**判据**：新增的目录只有 `espressif__esp_codec_dev`（它的 manifest 里只有 `idf: ">=4.0"`，不该带来别的），**不得出现** `lvgl`、`esp_video`、`usb_host_*`、`m5stack_tab5` 之类。出现了就退回本步，改为按「关键事实」里列出的寄存器表自己写薄驱动。

- [ ] **Step 6：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): 音频供电与 ES8388/ES7210 探测，引入 esp_codec_dev (P3 Task1)"
```

---

## Task 2：I2S 全双工 + ES8388 播放 bring-up（不碰 USB）

目标：把 I2S 全双工与 ES8388 配起来，并让功放在正确的时刻导通。

> ⚠️ **本版删掉了初稿的「固件自造 1 kHz 正弦自检」**（见顶部修订记录）。它的判据是
> 「喇叭响 + 屏上 duplex=1」，面板没了之后只剩耳朵，而「有没有声音」在 Task 7
> 用 `aplay` 一样能听 —— 多写一段开机后要删的临时代码换不来新信息，还会在开机头
> 3 秒占住 TX、盖掉 host 的第一段音频。**代价要说清楚**：codec 与 USB 两段不再分开
> 归因，`aplay` 没声音时得同时怀疑两边，排查顺序见 Task 7 Step 1。

**Files:** Create `main/codec_audio.{c,h}`；Modify `main/CMakeLists.txt`、`main/app_main.c`

- [ ] **Step 1：成功判据**

`idf.py build` 通过，且 **GUD 显示与键盘触摸不回归**（本任务不改任何已有链路）。
听感判据推迟到 Task 7（`aplay` 出声时一并听「有没有开机『啪』声、音高对不对」）。

> ⚠️ **全双工判定不靠听，也不靠日志。** `i2s_duplex_active()` 直接读
> `I2S0.tx_conf.sig_loopback`，为 0 就返回错误码、不启动音频。检查点只有一个：
> 两次 `i2s_channel_init_std_mode()` 传的是不是**同一个** `i2s_std_config_t` 对象
> （Step 3 的写法在结构上排除了这种可能，所以真出现 0 更可能是有人后来把它拆成了两份）。

- [ ] **Step 2：`codec_audio.h`**

```c
#pragma once
/*
 * M5Stack Tab5 音频：ES8388(0x10) 播放 + ES7210(0x40) 双麦录音，
 * 经一个 I2S 端口全双工，向 host 呈现为 UAC1 声卡。
 *
 * 两颗芯片与 IO 扩展/触摸/IMU 同挂内部 I2C(G31/G32)，故复用 board_i2c_bus()，
 * 不新建 master —— 与 touch_hid.c 同一处置。
 */
#include "esp_err.h"

/* 初始化 I2S 全双工 + 两颗芯片，并起数据泵任务。
 * 须在 board_power_init() 与 tinyusb_driver_install() 之后调用。
 * 失败时调用方只降级、不拦启动（同 kbd_start / touch_start）。 */
esp_err_t codec_audio_start(void);
```

- [ ] **Step 3：`codec_audio.c` 的 I2S 全双工初始化**

```c
#define AUDIO_I2S_PORT       I2S_NUM_0
/* DMA 每描述符正好一个 USB 帧（1ms）的样本数，让 I2S 读写与 USB 帧天然同拍。 */
#define AUDIO_DMA_FRAME_NUM  UAC_FRAME_SAMPLES
#define AUDIO_DMA_DESC_NUM   4

static i2s_chan_handle_t s_tx, s_rx;

static esp_err_t i2s_full_duplex_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(AUDIO_I2S_PORT, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num  = AUDIO_DMA_DESC_NUM;
    chan_cfg.dma_frame_num = AUDIO_DMA_FRAME_NUM;
    chan_cfg.auto_clear    = true;   /* 欠载时自动填 0，而不是重放上一帧（那是"嗡"声的来源） */
    /*
     * ⚠️ TX 与 RX 必须在**这一次调用**里同时要到，不能先起 TX 再追加 RX ——
     * ESP32-P4 的 I2S v2 上分两次建通道会失败（esphome#16043）。esp-bsp 的
     * bsp_audio.c:50 也是一次调用建两个。
     */
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, &s_tx, &s_rx), TAG, "i2s chan");

    /*
     * ⚠️ TX 与 RX 必须传**同一份** config：i2s_std.c 的
     * s_i2s_channel_try_to_constitude_std_duplex() 对两边的 i2s_std_config_t 做
     * memcmp，相等才组成全双工（共享 BCLK/WS）。不相等时 P4(HW_VERSION_2) 只打一条
     * **DEBUG 级**的 "TX & RX on I2S0 are simplex" 就放行 —— 然后两个方向各自去驱动
     * BCLK/WS，症状是噪声或全静音，而日志一切正常。
     * 所以 dout 与 din **两个都填**（IDF 官方全双工例子即如此）。
     */
    i2s_std_config_t std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(UAC_SAMPLE_RATE),
        /* 线上固定走立体声 2 slot：ES8388 是立体声 DAC、ES7210 是双麦，
         * 且全双工要求两个方向 slot 配置一致。USB 侧的单声道由
         * audio_frame.c 的纯函数转换，不靠 I2S 的 MONO 模式。 */
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = PIN_I2S_MCLK,
            .bclk = PIN_I2S_SCLK,
            .ws   = PIN_I2S_LRCK,
            .dout = PIN_I2S_DOUT,
            .din  = PIN_I2S_DSIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    /* MCLK 倍率显式写 256×fs：ES7210 与 ES8388 的分频器都按这个假设配。 */
    std_cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;

    /* ⚠️ 两次传的是**同一个对象的地址**，不是两份长得一样的结构体。
     * 驱动靠 memcmp 判定能否组成全双工，"结构上不可能填错"比"记得填一样"可靠。 */
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx, &std_cfg), TAG, "i2s tx");
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std_cfg), TAG, "i2s rx");

    /*
     * 显式判定全双工是否真的成立，**不依赖 IDF 那条看不见的 DEBUG 日志**。
     *
     * i2s_std.c:142-146 的 i2s_ll_share_bck_ws() 在 P4 上写的就是
     * I2S0.tx_conf.sig_loopback（soc/i2s_struct.h 的 bit 30），它是硬件层面
     * 「TX 与 RX 共用 BCLK/WS」的开关。两个通道都 init 完之后这一位必须是 1。
     *
     * 为 0 意味着驱动判定两边配置不同、退回了 simplex —— 而它在 P4 上**只打一条
     * DEBUG 级日志就放行**，所有函数照样返回 ESP_OK。本工程现场没有串口，那行字
     * 谁也看不见，所以必须在这里变成一条可见的失败：返回错误码，让
     * codec_audio_start() 整个失败（host 侧表现为「声卡在但全静音」），
     * 而不是带病运行成一屋子噪声。
     */
    const bool duplex = i2s_duplex_active();
    ESP_LOGI(TAG, "I2S %dHz/16bit/2slot duplex=%d", UAC_SAMPLE_RATE, duplex);
    ESP_RETURN_ON_FALSE(duplex, ESP_ERR_INVALID_STATE, TAG,
                        "I2S 未组成全双工：两次 init 传的不是同一份 std_cfg");
    return ESP_OK;
}
```

`i2s_duplex_active()` 就是一次寄存器读，单独成函数是为了把那句"为什么读这一位"的注释挂在一个地方：

```c
#include "soc/i2s_struct.h"

/* 见上：sig_loopback 就是 i2s_ll_share_bck_ws() 写的那一位。
 * AUDIO_I2S_PORT 固定是 I2S_NUM_0，故直接取 I2S0；换端口时这里要一起改，
 * 下面的断言会拦住忘改的情况。 */
_Static_assert(AUDIO_I2S_PORT == I2S_NUM_0, "i2s_duplex_active() 读的是 I2S0 的寄存器");

static bool i2s_duplex_active(void)
{
    return I2S0.tx_conf.sig_loopback != 0;
}
```

- [ ] **Step 4：ES8388 初始化（`esp_codec_dev`）**

先核对组件的真实签名（组件此时才刚被拉下来）：

```bash
grep -n "es8388_codec_cfg_t\|es8388_codec_new\|audio_codec_i2c_cfg_t\|audio_codec_i2s_cfg_t\|esp_codec_dev_sample_info_t" \
    firmware/managed_components/espressif__esp_codec_dev/include/*.h
```

**判据**：`es8388_codec_new()`、`audio_codec_new_i2c_ctrl()`、`audio_codec_new_i2s_data()`、`esp_codec_dev_new()`、`esp_codec_dev_open()` 五个符号都在，且 `ES8388_CODEC_DEFAULT_ADDR` 的值是 **0x20**（8 bit 形式，印证「关键事实」里的陷阱一）。字段名以头文件为准（下面按 1.6.x 的形态写）：

```c
static esp_codec_dev_handle_t s_spk_dev;

static esp_err_t es8388_init(void)
{
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = I2C_NUM_0,
        .addr = ES8388_I2C_ADDR8,          /* ⚠️ 8 bit 形式(0x20)，驱动内部会 >>1 */
        .bus_handle = board_i2c_bus(),     /* 复用内部总线，绝不新建 master */
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_RETURN_ON_FALSE(ctrl, ESP_FAIL, TAG, "es8388 i2c ctrl");

    audio_codec_i2s_cfg_t i2s_cfg = { .port = AUDIO_I2S_PORT, .tx_handle = s_tx, .rx_handle = NULL };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_RETURN_ON_FALSE(data, ESP_FAIL, TAG, "es8388 i2s data");

    es8388_codec_cfg_t cfg = {
        .ctrl_if     = ctrl,
        .codec_mode  = ESP_CODEC_DEV_WORK_MODE_DAC,  /* 只做播放，ADC 归 ES7210 */
        .master_mode = false,                        /* ESP 是 I2S master，codec 是 slave */
        /* ⚠️ 填 −1 让驱动的 PA 控制变成空操作（es8388.c:201-208 见 -1 直接 return）。
         * Tab5 的功放没有独立 GPIO（esp-bsp 的 BSP_POWER_AMP_IO = GPIO_NUM_NC），
         * 使能在 IO 扩展上，由 board_speaker_enable() 管，见下方 Step 4b。 */
        .pa_pin      = -1,
    };
    const audio_codec_if_t *codec = es8388_codec_new(&cfg);
    ESP_RETURN_ON_FALSE(codec, ESP_FAIL, TAG, "es8388 new");

    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT, .codec_if = codec, .data_if = data,
    };
    s_spk_dev = esp_codec_dev_new(&dev_cfg);
    ESP_RETURN_ON_FALSE(s_spk_dev, ESP_FAIL, TAG, "es8388 dev");

    /* channel 填 2：线上是立体声 2 slot（USB 侧的单声道在 audio_frame.c 转换）。 */
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16, .channel = 2, .sample_rate = UAC_SAMPLE_RATE,
    };
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_spk_dev, &fs) == ESP_CODEC_DEV_OK,
                        ESP_FAIL, TAG, "es8388 open");
    /* 开机音量取 70%：满量程直推板载小喇叭在中低频容易破音，且 host 侧还会再叠一层
     * 软件音量（本阶段不声明 Feature Unit，见 Task 5）。 */
    esp_codec_dev_set_out_vol(s_spk_dev, 70);
    ESP_LOGI(TAG, "ES8388 播放就绪");
    return ESP_OK;
}
```

> ⚠️ `esp_codec_dev_open()` 内部会通过 `data_if` 去 `i2s_channel_enable()`（`audio_codec_data_i2s.c` 的 open 路径会 reconfig + enable）。所以**不要**再自己调 `i2s_channel_enable(s_tx)`——重复 enable 会返回 `ESP_ERR_INVALID_STATE`。若实测发现它并不 enable（表现为完全没有声音、且 BCLK 没在动），再在这里补上并把结论写进注释。

- [ ] **Step 4b：功放使能的时序（这一步决定有没有开机「啪」声）**

`codec_audio_start()` 的顺序**必须**是：

```
i2s_full_duplex_init()          /* 时钟先跑起来 */
  → es8388_init()               /* 含 esp_codec_dev_open()：ES8388 的 open() 第一条就是
                                 * DACCONTROL3(0x19)=0x04 静音，随后由 esp_codec_dev_open()
                                 * 内部 set_out_mute(false) 带 ramp 解除 */
  → vTaskDelay(pdMS_TO_TICKS(50))   /* 让 DAC 输出电平稳定下来 */
  → board_speaker_enable(true)      /* 最后才导通功放 */
```

```c
    /* 功放最后开。ES8388 的 DAC 上电与解除静音都已完成、输出端电平稳定之后再导通，
     * 否则开机会有一声「啪」。50ms 是保守值，只在启动走一次。
     * ⚠️ esp-bsp 的 bsp_audio.c:110 是**先**开功放**后**配 codec 的，本处刻意不照抄。 */
    vTaskDelay(pdMS_TO_TICKS(50));
    board_speaker_enable(true);
    ESP_LOGI(TAG, "功放已使能");
```

对称地，若日后加关流路径，必须**先** `board_speaker_enable(false)` **再** `esp_codec_dev_close()`——`esp_codec_dev_close()` 不会碰这个引脚（`esp_codec_dev.c:563-569`），顺序反了就是关机 pop。本阶段不做关流（音频一路常开），但把这条写进 `codec_audio.c` 的注释。

- [ ] **Step 5：数据泵任务**

任务在本步就建起来，Task 7/8 往里加 USB 收发，**不要每个任务另起一个新任务**。
本步只需要一个空转的骨架（`while (1) vTaskDelay(...)`）——初稿在这里灌 3 秒正弦，
本版删掉了，理由见 Task 2 开头。

```c
#define AUDIO_TASK_STACK_SIZE 4096
/*
 * 与 TinyUSB 的任务同优先级（esp_tinyusb 的 TINYUSB_DEFAULT_TASK_PRIO = 5，
 * 见 managed_components/espressif__esp_tinyusb/include/tinyusb_default_config.h:85）。
 * 本任务每毫秒只搬 128 字节，绝大部分时间阻塞在 i2s_channel_read() 上，没有理由
 * 压过 USB 栈；同优先级下 FreeRTOS 时间片轮转，两者都不会饿死。
 * 若 Task 9 的复合回归发现显示掉帧，降到 4 再测（见 Task 9 Step 2）。
 */
#define AUDIO_TASK_PRIORITY   5
```

`codec_audio_start()` 末尾 `xTaskCreate(audio_pump_task, "audio", AUDIO_TASK_STACK_SIZE, NULL, AUDIO_TASK_PRIORITY, NULL)`，失败返回 `ESP_ERR_NO_MEM`（并先把功放关回去，别留着一个空转的功放）。

- [ ] **Step 6：`app_main.c` 调用**

在 `touch_start()` 之后追加，处置原则与键盘/触摸一致（失败只 WARNING、不拦启动）：

```c
    err = codec_audio_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "音频不可用(%s)，继续启动", esp_err_to_name(err));
```

- [ ] **Step 7：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): I2S 全双工与 ES8388 播放 bring-up (P3 Task2)"
```

---

## Task 3：ES7210 录音初始化（仍不碰 USB）

目标：把 ES7210 配起来，并让它与已经打开的 ES8388 共处同一个 I2S 端口而不互相破坏。

> ⚠️ **本版删掉了初稿的「屏上电平条自检」**（见顶部修订记录）。它的全部判据都在屏上，
> 面板没了就无处落地。双麦是否真在出数据推迟到 Task 8 用 `arecord` + `sox stat` 判 ——
> 那是更客观的判据（RMS 数字，不是条的长度）。

**Files:** Modify `main/codec_audio.c`

- [ ] **Step 1：成功判据**

`idf.py build` 通过，**GUD 显示与键盘触摸不回归**。

> ⓘ **本步有一个只能上板才知道的风险，先记下来**：`esp_codec_dev_open(s_mic_dev, ...)`
> 会经它的 I2S data_if 去 `i2s_channel_reconfig_std_slot/clock(s_rx)` ——
> 而 RX 此刻已经是 `full_duplex_slave`，TX 正在跑。逐行读过 `audio_codec_data_i2s.c`
> 的 `check_fs_compatible()`：因为两边的 `sample_rate` / `channel` / `bits_per_sample`
> 完全相同，它会走「同参数直接 set」那条分支，且**不会**去 disable/reconfig TX
> （那条补救分支的条件是 `paired->out_enable == false`，而 TX 已经 enable）。
> 所以预期是「重配成同样的值 = 无变化」。若实测录音全零或播放被打断，
> 从这里查起，并把结论写进 `codec_audio.c` 的注释。

- [ ] **Step 2：ES7210 初始化**

```c
static esp_codec_dev_handle_t s_mic_dev;

static esp_err_t es7210_init(void)
{
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = I2C_NUM_0,
        .addr = ES7210_I2C_ADDR8,          /* ⚠️ 8 bit 形式(0x80)，驱动内部会 >>1 */
        .bus_handle = board_i2c_bus(),
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_RETURN_ON_FALSE(ctrl, ESP_FAIL, TAG, "es7210 i2c ctrl");

    audio_codec_i2s_cfg_t i2s_cfg = { .port = AUDIO_I2S_PORT, .tx_handle = NULL, .rx_handle = s_rx };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_RETURN_ON_FALSE(data, ESP_FAIL, TAG, "es7210 i2s data");

    es7210_codec_cfg_t cfg = {
        .ctrl_if      = ctrl,
        .master_mode  = false,                 /* ESP 是 I2S master */
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2,   /* Tab5 是双麦 */
        .mclk_src     = ES7210_MCLK_FROM_PAD,  /* MCLK 由 ESP 的 G30 提供 */
        .mclk_div     = I2S_MCLK_MULTIPLE_256, /* 与 std_cfg.clk_cfg.mclk_multiple 一致 */
    };
    const audio_codec_if_t *codec = es7210_codec_new(&cfg);
    ESP_RETURN_ON_FALSE(codec, ESP_FAIL, TAG, "es7210 new");

    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN, .codec_if = codec, .data_if = data,
    };
    s_mic_dev = esp_codec_dev_new(&dev_cfg);
    ESP_RETURN_ON_FALSE(s_mic_dev, ESP_FAIL, TAG, "es7210 dev");

    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16, .channel = 2,
        .channel_mask    = ES7210_SEL_MIC1 | ES7210_SEL_MIC2,
        .sample_rate     = UAC_SAMPLE_RATE,
    };
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_mic_dev, &fs) == ESP_CODEC_DEV_OK,
                        ESP_FAIL, TAG, "es7210 open");
    /* 30 dB 是 IDF 官方 es7210 例子的取值，对驻极体麦是个能听清说话又不啸叫的起点。 */
    esp_codec_dev_set_in_gain(s_mic_dev, 30.0f);
    ESP_LOGI(TAG, "ES7210 录音就绪");
    return ESP_OK;
}
```

> ⚠️ **必须走 STD 立体声 2 slot，不能改用 TDM。** IDF 官方的 ES7210 例子用 TDM 是因为它接 4 只麦；Tab5 只有 2 只，驱动本身也是 `≥3` 只麦才开 TDM（`es7210.c:16,177-185`），2 只麦时 `REG12` 写 `0x00`、MIC1 走左 slot、MIC2 走右 slot。而且**混不得**：全双工要求 TX 与 RX 的 `mode_info` 结构体相等，一个 STD、一个 TDM 直接组不成全双工（见「关键事实」第 3 条）。
>
> ⓘ **采样率对 ES7210 是无所谓的**：slave 模式下 `es7210_config_sample()` 开头就 `if (!master_mode) return OK;`（`es7210.c:143-146`），速率完全由 ESP 的 LRCK 决定。所以 16 kHz 不会撞上它内部那张系数表。
>
> ⓘ **`mclk_div` 必须与 `std_cfg.clk_cfg.mclk_multiple` 一致（都是 256）**：ES7210 靠 `REG02=0xc1` 启用 DLL/倍频器，倍率对不上就采不准。MCLK 物理上接在 G30，`ES7210_MCLK_FROM_PAD` 正是「用外部引脚来的 MCLK」。

- [ ] **Step 3：数据泵仍保持空转**

初稿在这里把空转循环换成「读 RX + 写正弦 + 屏上电平条」。本版跳过：真正的收发循环
在 Task 7/8 一次写成（RX 读作节拍源 → `tud_audio_write()` → `tud_audio_read()` → TX 写），
中间不做一个开机后要删的形态。

⚠️ 顺带说明：**本阶段数据泵不会成为 PPA 的提交者**（它不画任何东西），
所以 `display_dsi.c` 的 `max_pending_trans_num` 保持 2 不动 —— 初稿里那条
「要涨到 3」的要求随面板一起作废。

- [ ] **Step 4：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): ES7210 双麦录音初始化 (P3 Task3)"
```

---

## Task 4：`audio_frame.c` 纯函数 + 宿主机回归测试

目标：把「单↔双声道转换」钉死在宿主机上。这类错误在实机上只表现为「声音小一半 / 只有一边有声 / 音高快一倍」，从现象反推极难，而在宿主机上验几乎零成本。

> ⚠️ **`audio_frame_peak()` 随屏上电平条一起删掉了**（见顶部修订记录）：它唯一的消费者就是那块面板。判录音有没有信号改用 host 侧的 `sox /tmp/tab5.wav -n stat`，那是更客观的判据。下面凡提到 `peak` 的用例一并作废。

**Files:** Create `main/audio_frame.{c,h}`、`test/test_audio_frame.c`；Modify `main/CMakeLists.txt`

- [ ] **Step 1：成功判据**

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -Werror -I../main test_audio_frame.c ../main/audio_frame.c -o /tmp/ta && /tmp/ta
# → OK (N cases)
```

全部用例通过，且 Task 2/3 的实机行为不变（本任务只是把已经写出的函数补上测试与边界处理）。

- [ ] **Step 2：`audio_frame.h`**

```c
#pragma once
/*
 * USB 单声道帧 ↔ I2S 线上立体声帧 的转换，以及录音电平峰值。
 *
 * 纯函数，不依赖 ESP-IDF —— 与 kbd_translate.c / touch_map.c 同样的理由：
 * 这几行完全可以在宿主机验证，而写错了在实机上只表现为「声音小一半 / 只有
 * 一边有声 / 电平数字不对」，从现象几乎反推不出来。
 * 见 firmware/test/test_audio_frame.c。
 */
#include <stdint.h>
#include <stddef.h>

/*
 * 单声道 → 交错立体声：左右两路填同一个样本。
 * frames = 样本帧数；mono 有 frames 个元素，stereo 有 2*frames 个元素。
 * 两个缓冲不得重叠。
 *
 * 为什么不用 I2S 的 I2S_SLOT_MODE_MONO 代替：全双工要求 TX 与 RX 的 slot 配置
 * 完全一致，而录音侧必须是双声道（两只麦）—— 线上只能统一成立体声 2 slot。
 */
void audio_frame_mono_to_stereo(const int16_t *mono, int16_t *stereo, size_t frames);

/*
 * 交错立体声 → 单声道：两路取算术平均。
 * 用 (l + r) >> 1（int32 上的算术右移，向下取整）而不是 /2：
 *   - int32 中间量不会溢出（两个 int16 之和最多 ±65536）；
 *   - 右移对负数向下取整、除法向零取整，两者对半波会产生不同的直流偏置；
 *     选定右移并在测试里钉死，免得日后有人"顺手改成 /2"而听不出差别却改了行为。
 */
void audio_frame_stereo_to_mono(const int16_t *stereo, int16_t *mono, size_t frames);

/* ⚠️ 初稿这里还有一个 audio_frame_peak()，随屏上电平条一起删掉了 —— 它唯一的
 * 消费者就是那块面板。判录音有没有信号改用 host 侧 `sox ... -n stat` 的 RMS。 */
```

- [ ] **Step 3：`audio_frame.c`**

```c
#include "audio_frame.h"

void audio_frame_mono_to_stereo(const int16_t *mono, int16_t *stereo, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        stereo[2 * i]     = mono[i];
        stereo[2 * i + 1] = mono[i];
    }
}

void audio_frame_stereo_to_mono(const int16_t *stereo, int16_t *mono, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        const int32_t sum = (int32_t)stereo[2 * i] + (int32_t)stereo[2 * i + 1];
        mono[i] = (int16_t)(sum >> 1);
    }
}
```

- [ ] **Step 4：`test/test_audio_frame.c`**

照 `test_touch_map.c` 的形式：`main()` + `assert`，无框架，不挂 IDF 构建。用例至少覆盖：

1. `mono_to_stereo`：3 帧，左右两路都等于源；`frames == 0` 不写任何字节（用哨兵值检查）；
2. `stereo_to_mono`：`(100, 200) → 150`；`(-100, -200) → -150`（`(-300)>>1 == -150`）；`(1, 0) → 0`（右移向下取整，**不是** 0.5 四舍五入）；`(-1, 0) → -1`（这是右移与 `/2` 唯一会分叉的那一类，必须钉死）；
3. `stereo_to_mono`：`(INT16_MAX, INT16_MAX) → 32767`、`(INT16_MIN, INT16_MIN) → -32768`（证明不溢出）；
5. **往返一致性**：`mono → stereo → mono` 应逐样本相等（因为左右同值，平均即原值）。

- [ ] **Step 5：编译 + 跑测试 + 提交**

```
git commit -m "feat(tab5-fw): audio_frame 声道转换纯函数与宿主机回归测试 (P3 Task4)"
```

---

## Task 5：UAC1 描述符 + tusb_config 覆盖 + **宿主机描述符校验**（不上板）

目标：把 USB 侧描述符写完，并在**烧板之前**就把它验一遍。这是硬约束 C 的落点。

**Files:** Create `main/tinyusb_config/tusb_config.h`、`test/check_usb_desc.py`；Modify `main/usb_descriptors.{c,h}`、`main/CMakeLists.txt`

- [ ] **Step 1：成功判据**

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh && idf.py build     # 含全部 _Static_assert
python3 test/check_usb_desc.py build/tab5_aio.elf                # → 打印描述符树 + OK
```

脚本必须打印出 5 个接口（IF0 vendor / IF1 HID / IF2 AC / IF3 AS-out / IF4 AS-in）、2 条 ISO 端点，且**全部断言通过**，其中包括「没有任何端点的 `bSynchAddress` 非 0」与「没有任何 ISO 端点的 sync 字段为 0」。本任务**不上板**。

- [ ] **Step 2：`main/tinyusb_config/tusb_config.h`**

```c
#pragma once

/*
 * esp_tinyusb 2.2.1 的默认 tusb_config.h 把 Vendor/HID/CDC 等映射到了 Kconfig，
 * 但**没有开放 Audio 类**（其 Kconfig 与 include/tusb_config.h 里 AUDIO 零命中）。
 * include_next 保留它的平台、FreeRTOS 与既有 class 配置，再追加本工程的 UAC1 参数。
 * CMake 侧的接线见 main/CMakeLists.txt —— 必须同时改 tinyusb 与 esp_tinyusb 两个库
 * 的 include 顺序，只改一个会让两边的 CFG_TUD_* 不一致。
 */
#include_next "tusb_config.h"

#undef CFG_TUD_AUDIO
#define CFG_TUD_AUDIO 1

/* 播放（host → 设备）。SZ_MAX 必须 ≥ 描述符里声明的 wMaxPacketSize，
 * SW_BUF_SZ 必须 ≥ SZ_MAX（audio_device.h:109-143 会 #error）。
 * 256 字节软件缓冲 ≈ 7 个 USB 帧，足够吸收任务调度抖动。 */
#define CFG_TUD_AUDIO_ENABLE_EP_OUT             1
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX      36
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ   256

/* 录音（设备 → host） */
#define CFG_TUD_AUDIO_ENABLE_EP_IN              1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX       36
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ    256

/* 让 TinyUSB 按软件 FIFO 水位决定每帧发几个样本（标称 ±1），
 * 这正是「异步 IN 不需要反馈端点」的实现基础。 */
#define CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL        1

/*
 * ⚠️ 显式写 0，不靠默认值。P4 全速控制器只有 4 条可用 IN 端点，
 * 已经分给 vendor(0x81)/HID(0x82)/UAC 录音(0x83)/UVC 预留(0x84)。
 * 一条反馈端点就会顶到第 5 条，dcd_dwc2.c:227 的 TU_ASSERT 失败且**无日志**。
 */
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP        0
/* AudioControl 的中断端点同理：不用，省一条 IN。 */
#define CFG_TUD_AUDIO_ENABLE_INTERRUPT_EP       0
```

- [ ] **Step 3：`usb_descriptors.h` 的接口/端点/参数**

```c
enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_HID,                   /* ⚠️ 保持 1 不动：音频追加在它之后 */
    /* UAC1 三接口。相对顺序不能动：AudioControl 必须是 IAD 覆盖区间的第一个接口，
     * 两个 AudioStreaming 必须紧随其后且连号（IAD 只能描述连续区间）。
     * 但整段排在 HID 之后完全合法 —— IAD 不要求它覆盖的接口位于配置描述符最前。 */
    ITF_NUM_AUDIO_CONTROL,
    ITF_NUM_AUDIO_STREAMING_OUT,   /* 播放 */
    ITF_NUM_AUDIO_STREAMING_IN,    /* 录音 */
    ITF_NUM_TOTAL
};

#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82      /* 与接口号一样刻意不动，少一个变量 */
#define EPNUM_AUDIO_OUT  0x02      /* ISO OUT，播放 */
#define EPNUM_AUDIO_IN   0x83      /* ISO IN，录音；0x84 留给 UVC */

/*
 * ⚠️ CDC 调试串口与 UAC 互斥：CDC 要占 0x83(通知) + 0x84(数据) 两条 IN，
 * 与音频、UVC 直接撞号，且 4 条可用 IN 端点也不够。做音频阶段时必须关掉它。
 * 变成编译期错误，而不是留给后人在没有串口的板子上调试。
 */
#if CONFIG_TINYUSB_CDC_ENABLED
#error "CDC 调试串口与 UAC 音频互斥（IN 端点不够，且 0x83/0x84 撞号）：请注释回 sdkconfig.defaults 末尾那两行"
#endif
```

（`UAC_SAMPLE_RATE` / `UAC_FRAME_*` / `UAC_EP_*_SIZE` 这批参数常量已在 **Task 1 Step 3b** 落地，本步不重复。）

`usb_descriptors.c` 里补上与 `tusb_config.h` 的对账（两边分处两个文件、无法互相 include，只能靠断言钉住）：

```c
_Static_assert(UAC_EP_OUT_SIZE <= CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX,
               "描述符声明的播放端点大小超过 tusb_config.h 里给驱动的上限");
_Static_assert(UAC_EP_IN_SIZE <= CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX,
               "描述符声明的录音端点大小超过 tusb_config.h 里给驱动的上限");
_Static_assert(CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP == 0,
               "全速控制器只有 4 条可用 IN 端点，反馈端点会顶掉 UVC 的位置");
```

- [ ] **Step 4：`usb_descriptors.c` 的 UAC1 描述符**

以 `components/packages/cardputer-all-in-one/firmware/main/usb_descriptors.c:26-74` 为底稿，**改两处**：录音端点的 sync 类型与 lock delay，其余照搬。

```c
/*
 * UAC1（Audio Class 1.0）复合功能：一个 AudioControl 接口管两条 AudioStreaming。
 *
 * TinyUSB 0.21 有完整的 TUD_AUDIO10_* 底层模板（usbd.h:472-546），但**没有**
 * 播放+录音复合的整功能模板（只有 TUD_AUDIO10_MIC_ONE_CH_DESCRIPTOR，单麦且不带
 * IAD），所以这套布局要自己拼。底稿取自 cardputer-all-in-one，那边已实机跑通。
 *
 * 拓扑（terminal ID 是本文件内自洽的编号，被 baSourceID 交叉引用）：
 *   播放：ID1 输入端子(USB Streaming) → ID2 输出端子(Speaker)
 *   录音：ID3 输入端子(Microphone)    → ID4 输出端子(USB Streaming)
 * 不放 Feature Unit（音量/静音）：host 侧软件音量已经够用，而 Feature Unit 会
 * 引入一组必须正确应答的 GET/SET_CUR 控制请求 —— 应答错了 snd-usb-audio 会在
 * probe 阶段就报错，属于典型的"加了功能反而不能用"。要做也该等基础通路稳了再说。
 *
 * ⚠️ 两条 ISO 端点的 bSynchAddress 都填 0（宏的最后一个参数），且 sync 字段
 * 都非 0 —— 见本文件顶部与计划的硬约束 A。
 */
#define UAC1_STREAM_DESC_LEN (TUD_AUDIO10_DESC_STD_AS_LEN * 2 + \
                              TUD_AUDIO10_DESC_CS_AS_INT_LEN + \
                              TUD_AUDIO10_DESC_TYPE_I_FORMAT_LEN(1) + \
                              TUD_AUDIO10_DESC_STD_AS_ISO_EP_LEN + \
                              TUD_AUDIO10_DESC_CS_AS_ISO_EP_LEN)

#define UAC1_AUDIO_DESC_LEN (8 /* IAD */ + \
                             TUD_AUDIO10_DESC_STD_AC_LEN + \
                             TUD_AUDIO10_DESC_CS_AC_LEN(2) + \
                             2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                  TUD_AUDIO10_DESC_OUTPUT_TERM_LEN) + \
                             2 * UAC1_STREAM_DESC_LEN)

#define UAC1_AUDIO_DESCRIPTOR(_ac_itf, _spk_as, _mic_as, _stridx, _epout, _epin) \
    /* IAD：告诉 host「这 3 个接口是一个音频功能」，snd-usb-audio 靠它成组绑定 */ \
    8, TUSB_DESC_INTERFACE_ASSOCIATION, _ac_itf, 3, TUSB_CLASS_AUDIO, 0, 0, _stridx, \
    TUD_AUDIO10_DESC_STD_AC(_ac_itf, 0 /* 无中断端点 */, _stridx), \
    TUD_AUDIO10_DESC_CS_AC(0x0100 /* bcdADC = UAC 1.0 */, \
                           2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                TUD_AUDIO10_DESC_OUTPUT_TERM_LEN), \
                           _spk_as, _mic_as), \
    /* 播放链：USB 流 → 喇叭 */ \
    TUD_AUDIO10_DESC_INPUT_TERM(1, AUDIO_TERM_TYPE_USB_STREAMING, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, 0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(2, AUDIO_TERM_TYPE_OUT_GENERIC_SPEAKER, 0, 1, 0), \
    /* 录音链：麦克风 → USB 流 */ \
    TUD_AUDIO10_DESC_INPUT_TERM(3, AUDIO_TERM_TYPE_IN_GENERIC_MIC, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, 0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(4, AUDIO_TERM_TYPE_USB_STREAMING, 0, 3, 0), \
    /* ── 播放 AS：alt 0 = 零带宽（host 不放音时不占 ISO 预留），alt 1 = 有端点 ── */ \
    TUD_AUDIO10_DESC_STD_AS_INT(_spk_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_spk_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(1 /* 连到 ID1 */, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, UAC_SAMPLE_RATE), \
    /* adaptive sink：设备自己吸收速率差，不需要反馈端点。最后一个参数 0 = bSynchAddress */ \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epout, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ADAPTIVE, \
                                   UAC_EP_OUT_SIZE, 1 /* bInterval = 每帧 */, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_UNDEFINED, 0), \
    /* ── 录音 AS ── */ \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(4 /* 连到 ID4 */, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, UAC_SAMPLE_RATE), \
    /* asynchronous source：设备是时钟主控，按自己的 I2S 时钟出数据。IN 方向的
     * 异步**不需要**反馈端点（反馈是给异步 OUT sink 用的）。同样 bSynchAddress = 0。 */ \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epin, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ASYNCHRONOUS, \
                                   UAC_EP_IN_SIZE, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_MILLISEC, 1)
```

配置描述符（`CONFIG_TOTAL_LEN` 从 57 变成 **230** = 9 + 23 + 173 + 25；`AIO_CDC_DESC_LEN` 那一支被 Step 3 的 `#error` 拦掉，可一并删除）：

```c
#define CONFIG_TOTAL_LEN \
    (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + UAC1_AUDIO_DESC_LEN + TUD_HID_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    UAC1_AUDIO_DESCRIPTOR(ITF_NUM_AUDIO_CONTROL, ITF_NUM_AUDIO_STREAMING_OUT,
                          ITF_NUM_AUDIO_STREAMING_IN, AIO_STRID_AUDIO,
                          EPNUM_AUDIO_OUT, EPNUM_AUDIO_IN),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_NONE,
                       sizeof(aio_hid_report_desc), EPNUM_HID,
                       CFG_TUD_HID_EP_BUFSIZE, 10),
};
_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN, "USB 配置描述符长度不一致");
```

字符串数组末尾追加 `"Tab5 Audio"`，索引常量 `#define AIO_STRID_AUDIO 4`（原 CDC 用的就是 4，CDC 已被禁用，索引不冲突），并沿用既有的 `_Static_assert` 写法把索引与数组长度钉在一起。

- [ ] **Step 5：`main/CMakeLists.txt` 接 tusb_config 覆盖**

逐行照搬 `cardputer-all-in-one/firmware/main/CMakeLists.txt:6-27`：`INCLUDE_DIRS` 加 `"tinyusb_config"`，然后对 `tinyusb` 与 `esp_tinyusb` 两个 COMPONENT_LIB 都 `target_include_directories(... BEFORE PRIVATE ...)`。

> ⚠️ **`BEFORE` 与「两个库都要加」缺一不可**：esp_tinyusb 自己在 `CMakeLists.txt:76-86` 把它的 `include/` 塞进了 tinyusb 库，不用 `BEFORE` 会排在它后面而不生效；只改 tinyusb 会让 esp_tinyusb 的 `descriptors_control.c` 看到不同的 `CFG_TUD_*`，接口数/描述符长度对不上。

- [ ] **Step 6：`test/check_usb_desc.py`**

从 ELF 里取出 `aio_desc_configuration` 的字节并解析校验。用 `pyelftools`（IDF 的 python 环境自带 0.32，`export.sh` 之后即可用）。

```python
#!/usr/bin/env python3
"""从固件 ELF 里取出 aio_desc_configuration 并逐条校验。

烧板前的闸门：这块板现场没有可用串口（USB-Serial/JTAG 被 TinyUSB 收走、
CDC 在音频阶段被 #error 禁掉、UART0 只在 M5-Bus 排针上），描述符写错的症状是
"host 完全不认这个设备"，没有任何现场证据。所以在宿主机上先把它验一遍。

用法：. $HOME/esp/esp-idf/export.sh && python3 test/check_usb_desc.py build/tab5_aio.elf
"""
import sys
from elftools.elf.elffile import ELFFile

EXPECT = dict(vid=0x16D0, pid=0x10A9, n_itf=5, sample_rate=16000,
              channels=1, subframe=2, bits=16)


def symbol_bytes(path, name):
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        syms = elf.get_section_by_name('.symtab').get_symbol_by_name(name)
        if not syms:
            raise SystemExit(f'ELF 里找不到符号 {name}')
        addr, size = syms[0]['st_value'], syms[0]['st_size']
        for sec in elf.iter_sections():
            if sec['sh_type'] == 'SHT_NOBITS' or not sec['sh_flags'] & 0x2:
                continue
            base = sec['sh_addr']
            if base <= addr < base + sec['sh_size']:
                off = addr - base
                return sec.data()[off:off + size]
    raise SystemExit(f'符号 {name} 不在任何有数据的节里')


def walk(buf):
    """切成 (bLength, bDescriptorType, 整条 bytes) 的列表。"""
    out, i = [], 0
    while i < len(buf):
        ln = buf[i]
        if ln < 2 or i + ln > len(buf):
            raise SystemExit(f'偏移 {i} 处 bLength={ln} 非法')
        out.append((ln, buf[i + 1], buf[i:i + ln]))
        i += ln
    return out


def main():
    elf = sys.argv[1] if len(sys.argv) > 1 else 'build/tab5_aio.elf'
    cfg = symbol_bytes(elf, 'aio_desc_configuration')
    items = walk(cfg)

    # 1) 配置描述符自洽
    assert items[0][1] == 0x02, '第一条必须是 CONFIGURATION'
    total = items[0][2][2] | (items[0][2][3] << 8)
    assert total == len(cfg), f'wTotalLength={total} 与实际 {len(cfg)} 不符'
    n_itf = items[0][2][4]

    itfs, eps, iso_eps, in_eps = [], [], [], []
    ac_hdr = as_general = fmt = None
    for ln, typ, d in items:
        if typ == 0x04:                       # INTERFACE
            itfs.append(d)
        elif typ == 0x05:                     # ENDPOINT
            eps.append(d)
            if d[3] & 0x03 == 0x01:           # bmAttributes.xfer == isochronous
                iso_eps.append(d)
            if d[2] & 0x80:
                in_eps.append(d)
        elif typ == 0x24:                     # CS_INTERFACE
            if d[2] == 0x01 and ac_hdr is None and ln >= 8 and d[3] == 0x00 and d[4] == 0x01:
                ac_hdr = d                    # AC HEADER，bcdADC = 0x0100
            elif d[2] == 0x01 and ac_hdr is not None and ln == 7:
                as_general = d                # AS_GENERAL
            elif d[2] == 0x02 and ln >= 11:
                fmt = d                       # FORMAT_TYPE

    # 2) 接口数
    uniq = sorted({d[2] for d in itfs})
    assert uniq == list(range(EXPECT['n_itf'])), f'接口号应为 0..{EXPECT["n_itf"]-1}，实际 {uniq}'
    assert n_itf == EXPECT['n_itf'], f'bNumInterfaces={n_itf} 与实际接口数不符'

    # 3) UAC1 AC 头：bcdADC 与 baInterfaceNr
    assert ac_hdr is not None, '缺 AudioControl 的 CS 头描述符'
    assert (ac_hdr[3], ac_hdr[4]) == (0x00, 0x01), 'bcdADC 必须是 0x0100(UAC 1.0)'
    n_coll = ac_hdr[7]
    assert n_coll == 2, f'bInCollection 应为 2（播放+录音），实际 {n_coll}'
    assert list(ac_hdr[8:8 + n_coll]) == [2, 3], 'baInterfaceNr 应指向 IF2/IF3'

    # 4) ★硬约束 A：没有反馈端点，且 ISO 端点的 sync 字段不为 0
    assert len(iso_eps) == 2, f'应恰有 2 条 ISO 端点，实际 {len(iso_eps)}'
    for d in iso_eps:
        assert d[0] == 9, 'UAC1 的 ISO 端点描述符必须是 9 字节（含 bRefresh/bSynchAddress）'
        assert d[8] == 0, f'端点 0x{d[2]:02X} 的 bSynchAddress 非 0 —— 引入了反馈端点'
        sync = (d[3] >> 2) & 0x03
        assert sync != 0, (f'端点 0x{d[2]:02X} 的 sync 字段为 0（NO_SYNC）—— '
                           'TinyUSB 的 UAC1 分支会把它当成反馈端点，数据永远发不出去')
    assert len(in_eps) <= 4, f'IN 端点最多 4 条（全速控制器上限），实际 {len(in_eps)}'

    # 5) Type I 格式与预期参数一致
    assert fmt is not None, '缺 Type I Format 描述符'
    assert fmt[3] == 0x01 and fmt[4] == EXPECT['channels'] and fmt[5] == EXPECT['subframe'] \
        and fmt[6] == EXPECT['bits'] and fmt[7] == 1, 'Type I 格式字段与预期不符'
    rate = fmt[8] | (fmt[9] << 8) | (fmt[10] << 16)
    assert rate == EXPECT['sample_rate'], f'采样率 {rate} 与预期 {EXPECT["sample_rate"]} 不符'
    assert as_general is not None and as_general[3] in (1, 4), 'AS bTerminalLink 未指向已有端子'

    for ln, typ, d in items:
        kind = {0x02: 'CONFIG', 0x04: 'INTERFACE', 0x05: 'ENDPOINT',
                0x0B: 'IAD', 0x21: 'HID', 0x24: 'CS_INTERFACE', 0x25: 'CS_ENDPOINT'}
        print(f'  {kind.get(typ, hex(typ)):<12} len={ln:<3} {d.hex()}')
    print(f'OK — {len(cfg)} 字节 / {EXPECT["n_itf"]} 接口 / '
          f'{len(iso_eps)} 条 ISO 端点 / {len(in_eps)} 条 IN 端点 / 无反馈端点')


main()
```

- [ ] **Step 7：跑一遍并提交**（本任务**不上板**）

```
git commit -m "feat(tab5-fw): UAC1 描述符与 tusb_config 覆盖，加宿主机描述符校验 (P3 Task5)"
```

---

## Task 6：上板枚举 + FIFO 与端点占用实测

目标：先只求 host 认出声卡、且 FIFO 装得下。**数据通路还没接，此时播放/录音都应该是静音，这是预期行为。**

**Files:** Modify `main/app_main.c`

- [ ] **Step 1：成功判据**

host 侧：

```bash
lsusb -v -d 16d0:10a9 | grep -A4 -iE "iad|audio|isochronous|synch"
cat /proc/asound/cards                       # 出现 "Tab5 USB Terminal"
aplay -l && arecord -l                       # 各出现一个 USB Audio 设备
cat /proc/asound/card<N>/stream0             # 看 Playback/Capture 两段的 Rates/Format
```

判据：

1. `/proc/asound/cards` 出现本设备，`aplay -l` 与 `arecord -l` **各**列出一个；
2. `stream0` 里两个方向都报 `Format: S16_LE`、`Channels: 1`、`Rates: 16000`；
3. `lsusb -v` 的两条 ISO 端点分别是 `Synch Type   Adaptive` 与 `Synch Type   Asynchronous`，**且都没有 `Usage Type   Feedback` 的端点**；`stream0` 里**不出现 `Sync Endpoint`** 行；
4. **`dmesg` 没有 `snd-usb-audio` 的报错**，也没有重新枚举；
5. **GUD 显示、键盘、触摸全部照旧**（`modetest -M gud` 出图、`evtest` 打字、`ABS_MT_*`）。

固件侧：UART 日志打出 FIFO 占用（下一步），**空闲 ≥ 100 words**。

> ⓘ host 侧需要 `CONFIG_SND_USB_AUDIO`（发行版一般自带 `snd-usb-audio.ko`）。若 `lsusb` 看得到设备、`dmesg` 里却没有音频相关行且 `/proc/asound/cards` 没有本设备，先 `modinfo snd-usb-audio` 确认模块存在——这属于 host 内核配置问题，归 spec §9 那个阶段（`flange_common.config`）处理，**不是本阶段的固件缺陷**。包级 README 的分工表里已经列了这一项。

- [ ] **Step 2：`app_main.c` 加 FIFO 占用实测**

```c
#include "soc/usb_dwc_struct.h"

/*
 * 实测 DWC2 的 FIFO 分配。P4 全速控制器整块 SPRAM 只有 256 words(1 KB)，要装下
 * 共享 RX FIFO + 每条 IN 端点的 TX FIFO。不够时 dcd_dwc2.c 的 dfifo_alloc() 只是
 * TU_ASSERT 返回 false，**默认日志等级下一个字都不打** —— 症状是 SET_INTERFACE 被
 * STALL、某个接口静默不工作。所以主动读寄存器，把这件事变成日志里的一个数字。
 *
 * 布局（dcd_dwc2.c 顶部大注释）：地址 0 起是 RX FIFO，顶部往下依次是 EP0 IN、
 * EP1 IN… 的 TX FIFO，中间那段是空闲。空闲 = 最低的 TX 起始地址 − RX 大小。
 */
static void log_usb_fifo_usage(void)
{
    usb_dwc_dev_t *dev = &USB_DWC_FS;      /* Tab5 的 USB-C 接的是全速控制器 */
    const uint16_t rx = dev->grxfsiz_reg.rxfdep;
    uint16_t lowest = 0xFFFF, used = rx;

    uint16_t sz = dev->gnptxfsiz_reg.nptxfdep, off = dev->gnptxfsiz_reg.nptxfstaddr;
    ESP_LOGI(TAG, "FIFO: RX=%u words, EP0 IN=%u@%u", rx, sz, off);
    used += sz;
    if (sz && off < lowest) lowest = off;

    for (int n = 1; n <= 4; n++) {          /* 全速控制器最多 4 条可用 IN 端点 */
        sz  = dev->dieptxfi_regs[n - 1].inepntxfdep;
        off = dev->dieptxfi_regs[n - 1].inepntxfstaddr;
        if (sz == 0) continue;
        ESP_LOGI(TAG, "FIFO: EP%d IN=%u words @%u", n, sz, off);
        used += sz;
        if (off < lowest) lowest = off;
    }
    ESP_LOGI(TAG, "FIFO: 已用 %u words，空闲 %u words (%u 字节，UVC 阶段要从这里出)",
             used, (unsigned)(lowest - rx), (unsigned)((lowest - rx) * 4));
}
```

调用时机：**必须等 host 完成 SET_CONFIGURATION**（端点是那时才打开、ISO FIFO 是那时才分配的）。在 `app_main()` 末尾的空转循环里加一次性触发：

```c
    bool fifo_logged = false;
    while (1) {
        if (!fifo_logged && tud_mounted()) {
            log_usb_fifo_usage();
            fifo_logged = true;
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
```

- [ ] **Step 3：如果 FIFO 不够怎么办（降级阶梯，按序试，不要跳）**

1. 把 `UAC_EP_*_SIZE` 的 +4 余量去掉（各省 1 word），代价是异步 IN 偶尔丢一个样本；
2. 关掉 vendor 端点的双缓冲（`_tud_cfg.bm_double_buffered`），省 16 words，代价是 GUD bulk 吞吐下降 —— **这一步要重测帧率**；
3. 去掉 vendor 的 IN 端点（spec §2 的第一条降级选项，GUD 只用 EP0 控制 + bulk OUT）；
4. 仍不够则把采样率/声道降到本计划「升级阶梯」表里更省的档位。

每一步都要重跑 Step 1 的全部判据。**不要**为了腾地方去动 HID —— 那是已验证功能。

- [ ] **Step 4：把实测数字回填**

把 Step 2 打出来的 RX/各 TX/空闲写进 `firmware/README.md` 的「端点预算」章节（那里现在只有 CDC 场景的 98/256）。

- [ ] **Step 5：提交**

```
git commit -m "feat(tab5-fw): UAC1 枚举通过，实测 DWC2 FIFO 占用 (P3 Task6)"
```

---

## Task 7：播放通路（host → ES8388 → 喇叭）

目标：`aplay` 能出声。

**Files:** Modify `main/codec_audio.c`

- [ ] **Step 1：成功判据**

```bash
speaker-test -D hw:<card>,0 -F S16_LE -c 1 -r 16000 -t sine -f 1000 -l 3
aplay -D hw:<card>,0 --dump-hw-params -f S16_LE -c 1 -r 16000 /dev/zero   # 参数协商正确
aplay -D hw:<card>,0 /usr/share/sounds/alsa/Front_Center.wav              # 实际内容
```

判据：喇叭出声、音色正常（不是断续/爆音/半速或倍速）；`--dump-hw-params` 报 `FORMAT: S16_LE`、`CHANNELS: 1`、`RATE: 16000`；**GUD 显示与键盘触摸不回归**。

> ⚠️ 若声音是**半速或倍速**，先怀疑 `audio_frame_mono_to_stereo()` 没做（把单声道当立体声直接灌给 I2S，速率就会差一倍）；若只有一边喇叭响，怀疑同一处。

- [ ] **Step 2：UAC 控制回调（照搬 Cardputer，唯一要改的是接口号来源）**

Cardputer 的 `uac_audio.c:286-341` 那四个回调可整体照搬：`tud_audio_set_itf_cb` / `tud_audio_set_itf_close_ep_cb` 维护「host 有没有选中 alt 1」的两个标志位，`tud_audio_get_req_ep_cb` / `tud_audio_set_req_ep_cb` 应答 UAC1 的端点采样率请求（`AUDIO10_EP_CTRL_SAMPLING_FREQ`，UAC1 的采样率控制走端点而非 clock source）。

标志位改为两个独立的 `volatile bool`（**不是** Cardputer 那个三态 `requested_mode`）：

```c
/* 全双工：两个方向各自独立，不存在"谁接管谁"。Cardputer 上那套
 * AUDIO_MODE_SPEAKER/MICROPHONE 仲裁是因为它的扬声器 WS 与麦克风 PDM CLK
 * 共用 GPIO43，Tab5 的 DOUT/DSIN 是两根脚，整段逻辑不移植。 */
static volatile bool s_spk_on;   /* host 选中了播放 AS 的 alt 1 */
static volatile bool s_mic_on;   /* host 选中了录音 AS 的 alt 1 */
```

- [ ] **Step 3：`audio_pump_task` 接上播放**

把 Task 3 的自检循环改成正式的数据泵（仍以 RX 读作节拍源，理由见 Task 3 Step 3）：

```c
static void audio_pump_task(void *arg)
{
    int16_t rx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t tx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t usb_mono[UAC_FRAME_SAMPLES];
    (void)arg;

    while (1) {
        size_t n = 0;
        /* RX 读是本循环的时钟：DMA 描述符恰好一帧(1ms)，读满即返回。 */
        if (i2s_channel_read(s_rx, rx_stereo, sizeof(rx_stereo), &n, pdMS_TO_TICKS(50)) != ESP_OK)
            continue;

        /* ── 播放 ──
         * host 没选 alt 1 时灌静音而不是停写：I2S 时钟保持连续，
         * ES8388 不会因为 BCLK 断续而产生"咔"的一声。代价是一直有 DMA 活动，
         * 每毫秒 64 字节的搬运，可以忽略。 */
        uint16_t got = 0;
        if (s_spk_on && tud_mounted())
            got = tud_audio_read(usb_mono, UAC_FRAME_BYTES);
        if (got < UAC_FRAME_BYTES)
            memset((uint8_t *)usb_mono + got, 0, UAC_FRAME_BYTES - got);
        audio_frame_mono_to_stereo(usb_mono, tx_stereo, UAC_FRAME_SAMPLES);

        size_t written = 0;
        esp_err_t err = i2s_channel_write(s_tx, tx_stereo, sizeof(tx_stereo),
                                          &written, pdMS_TO_TICKS(20));
        if (err != ESP_OK || written != sizeof(tx_stereo))
            s_tx_underrun++;   /* 只计数，不在每毫秒的热路径里打日志 */
    }
}
```

欠载计数用一个 `static uint32_t s_tx_underrun;`，每 10 秒由同一任务打一条汇总日志（**不要**在每帧路径里 `ESP_LOGW`——1 kHz 的日志会自己把音频饿死，这是典型的观测干扰被观测）。

- [ ] **Step 4：（作废）删掉 Task 2 的正弦自检**

本版从来没有写过正弦自检（见顶部修订记录），无可删。

- [ ] **Step 5：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): UAC1 播放通路打通，aplay 出声 (P3 Task7)"
```

---

## Task 8：录音通路 + 全双工同时验证

目标：`arecord` 录得到波形，且**播放与录音同时打开互不干扰**（这是本阶段相对 Cardputer 的核心增量）。

**Files:** Modify `main/codec_audio.c`

- [ ] **Step 1：成功判据**

```bash
arecord -D hw:<card>,0 --dump-hw-params -f S16_LE -c 1 -r 16000 -d 10 /tmp/tab5.wav
aplay /tmp/tab5.wav                     # 回放，应能听清刚才说的话
```

判据：

1. `--dump-hw-params` 报 `S16_LE / 1ch / 16000`；
2. 录下的 wav **不是全零、也不是常数**（用 `sox /tmp/tab5.wav -n stat` 看 RMS/峰值；安静时低、说话时高）；
3. **全双工**：一个终端跑 `speaker-test` 持续放音，同时另一个终端 `arecord` 录 10 秒 —— 两边都正常，录音里能听到说话（听到喇叭的回声属正常，两只麦就在喇叭旁边）；
4. `dmesg` 无 `snd-usb-audio` 报错、无重新枚举；
5. **GUD 显示与键盘触摸不回归**。

- [ ] **Step 2：数据泵接上录音**

在 Task 7 的循环里，`i2s_channel_read()` 之后追加：

```c
        /* ── 录音 ── */
        if (s_mic_on && tud_mounted()) {
            audio_frame_stereo_to_mono(rx_stereo, usb_mono, UAC_FRAME_SAMPLES);
            /* tud_audio_write 写进软件 FIFO，真正的分包由 TinyUSB 按
             * CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL 决定（标称 ±1 个样本）——
             * 这正是异步 IN 不需要反馈端点的实现基础。 */
            if (tud_audio_write(usb_mono, UAC_FRAME_BYTES) != UAC_FRAME_BYTES)
                s_mic_overrun++;
        } else {
            /* host 关掉录音时清空软件 FIFO，否则下次打开会先放出一段陈旧音频。 */
            tud_audio_clear_ep_in_ff();
        }
```

同样只计数、每 10 秒汇总一次。

- [ ] **Step 3：删掉 Task 3 的电平自检**

本版从来没有写过电平自检，`audio_frame_peak()` 也没有实现（见顶部修订记录），无可删。

- [ ] **Step 4：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): UAC1 录音通路打通，全双工同时收发验证 (P3 Task8)"
```

---

## Task 9：与 GUD / HID 的复合回归

目标：证明音频跑起来没有把已交付的三项能力弄坏。这是硬约束 D 的落点，也是 spec §10 对阶段 4 的验证要求。

**Files:** 无（纯验证；发现问题则回到对应任务）

- [ ] **Step 1：前置检查（做之前先确认，别做到一半才发现缺工具）**

**a) 固件侧：无需任何准备。**

初稿在这里要求「确认屏上面板关着」——面板已删，本阶段的固件里没有任何会扰动显示的
调试设施，直接用正式固件跑本任务即可。（这正是删掉面板换来的：被测对象里不再混着仪表。）

**b) host 侧：P2 用的是 `khadas-vim3l`（arm64），先确认工具齐全。**

```bash
which aplay arecord speaker-test evtest modetest gst-launch-1.0
sox --version || true          # 用来对录音做客观判断（RMS/峰值），没有则改用 arecord -V
dpkg -l | grep -E "alsa-utils|gstreamer1.0-tools|libdrm-tests|evtest"
```

缺什么装什么：

```bash
sudo apt-get install -y alsa-utils evtest sox libdrm-tests \
                        gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good
```

**判据**：上面 6 个命令**全部**能找到，且 `gst-inspect-1.0 kmssink` 有输出（`kmssink` 在 `gstreamer1.0-plugins-bad` 里，Debian/Ubuntu 上常常不随 `-tools` 一起装——这是最容易到执行时才发现的一个缺口）。

**c) 内核侧：** `modinfo snd-usb-audio hid-multitouch drm_gud` 三个都在（前两者若缺，属 spec §9 那个阶段的工作，不是本阶段的固件缺陷）。

- [ ] **Step 2：成功判据（四项同时，连续 10 分钟）**

在同一台 host 上同时跑：

```bash
# 终端 1：GUD 显示实时内容
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=640,height=360 ! kmssink driver-name=gud connector-id=<id> force-modesetting=true
# 终端 2：播放
speaker-test -D hw:<card>,0 -F S16_LE -c 1 -r 16000 -t sine -f 440
# 终端 3：录音
arecord -D hw:<card>,0 -f S16_LE -c 1 -r 16000 -d 600 /tmp/soak.wav
# 终端 4：键盘与触摸
sudo evtest       # 交替选键盘那份与触摸那份，各敲/点若干次
```

判据：

1. 10 分钟内 **没有 USB 重新枚举**（`dmesg -w` 全程无新的 `usb ... new full-speed USB device`）；
2. 音频**无周期性爆音、无停声**；`/tmp/soak.wav` 全程有内容；
3. 画面持续更新，**主观上与不放音时无明显差异**；若明显变慢，按下面 Step 2 归因；
4. 键盘能打字、触摸有 `ABS_MT_*`，两者都不卡键（P1/P2 踩过的「丢释放报告」在端点更忙时最容易复现，这里是它的压力测试）；
5. 固件侧 UART 日志：`LZ4 解压失败` / `ppa srm 失败` / 音频欠载与溢出的计数**都是 0**（欠载少量非零可接受，但要如实记录数字，不许四舍五入成 0）。

- [ ] **Step 3：若显示明显变慢，先归因再改**

按带宽账，音频满负荷只吃 ~9% 的周期性带宽，留给 GUD bulk 的理论上限仍高于它实测能跑到的吞吐（见「带宽账」一节）。所以**明显变慢多半不是带宽问题**，候选原因按可能性排序：

1. 数据泵任务优先级压过了 TinyUSB 的任务 —— `AUDIO_TASK_PRIORITY` 与 `TINYUSB_DEFAULT_TASK_PRIO` 现在同为 5，降到 4 再测；
2. `i2s_channel_write()` 的 20ms 超时在欠载时把任务钉住 —— 看欠载计数；
3. PSRAM 带宽争用（DPI 帧缓冲 + PPA + I2S DMA）—— 把 I2S DMA 缓冲确认在**内部 RAM**（`i2s_new_channel` 默认即是；内部 RAM 只剩约 474 KB，见 `firmware/README.md` 的资源占用章节，本阶段的 DMA 缓冲只有几 KB，不构成压力）。

**把归因结论写进 README，不要只写"调了优先级就好了"。**

- [ ] **Step 4：把结论提交（改 README，见 Task 10；本步只产出数据）**

---

## Task 10：文档与收尾

- [ ] **Step 1**：`firmware/README.md` 加「UAC1 全双工音频」章节，至少覆盖：
  - 采样率/声道/位深的选定理由与**那张 FIFO 账表**（含 48 kHz 立体声为什么不可行、以及升级阶梯）；
  - **为什么不用反馈端点**，以及 UAC1 下 sync 字段不能填 0 的陷阱；
  - I2S 全双工的硬性要求（同一份 config、一次调用建两个通道、不能混 STD/TDM、不能用 `SLOT_MODE_MONO` 否则丢掉 MIC2），以及配置不一致时**只有 DEBUG 级日志**这件事；
  - `esp_codec_dev` 复用 `board_i2c_bus()` 的接法，以及**它收 8 bit 地址、`i2c_master_probe()` 收 7 bit** 这个陷阱；
  - **功放使能 = `0x43` 的 PIN1**，与 LCD_EN/TOUCH_EN 同一颗；以及「codec 配完解除静音 → 延时 → 才开功放」的顺序（与背光同构），并注明 esp-bsp 自己的顺序相反、我们刻意不照抄；`esp_codec_dev_close()` 不会关功放；
  - Task 6 实测的 FIFO 数字（更新「端点预算」章节里那组只覆盖 CDC 场景的旧数字）；
  - **那张 IN 端点占用表**（当前 / +音频 / +音频+UVC / +音频+CDC 不可行 / +反馈端点顶掉 UVC），把互斥关系一次说清；`CONFIG_TINYUSB_CDC_ENABLED` 与 UAC 互斥已变成编译期 `#error`，并更新 README 现有那段「开启 CDC 的代价」——它当时写的是「做那两个阶段前必须把开关注释回去」，现在是**编译器会拦住你**；
  - **这段 bring-up 期是盲的**：无串口 + CDC 退路被编译期堵死 + 本阶段不做屏上面板，
    从上电到 host 枚举之间没有任何可见输出；写明缓解办法（codec 失败会整体降级成
    「声卡在但全静音」、全双工靠读寄存器判定、真要抓就接 UART0）；
  - host 侧验证命令（`/proc/asound/cards`、`aplay -l`、`arecord -l`、`stream0`、`--dump-hw-params`、全双工同时跑法）；
  - 两个宿主机验证跑法：`test_audio_frame.c` 与 `check_usb_desc.py`（后者要写明依赖 IDF python 环境的 pyelftools）；
  - Task 9 的复合回归结论与欠载计数实测值。
- [ ] **Step 2**：`firmware/README.md` 的「文件」表补 `codec_audio.{c,h}` / `audio_frame.{c,h}` / `tinyusb_config/tusb_config.h` / `test/test_audio_frame.c` / `test/check_usb_desc.py` 五行；更新「能力」一节的接口布局（**IF0 GUD / IF1 HID / IF2-4 UAC**）。「待机画面」章节不动 —— 本阶段没碰 `standby_screen.{c,h}`。
- [ ] **Step 3**：包级 `components/packages/tab5-all-in-one/README.md` 状态清单：UAC1 全双工音频从「⏳ 规划中」移到 ✅（如实机通过），并写明采样率/声道与「带宽是零和的」这条既有提示的具体数字。
- [ ] **Step 4**：spec 回填：
  - **§6 订正**：原文写「UAC1 参数沿用 Cardputer 的 mono 16 kHz」——采样率结论一致，但**理由要补上 FIFO 账**（原文没有这一层）；同时补上「两个方向必须同采样率（全双工共用 BCLK/WS）」这条原文没有的硬约束；
  - **§6 补充**：喇叭功放使能 = **`0x43` 那颗 PI4IOE5V6408 的 PIN1**（esp-bsp `BSP_SPEAKER_EN`），功放**没有**独立 GPIO；以及「codec 配完再开功放」的上电顺序与理由；
  - **§2 订正**：端点表补上「反馈端点会顶掉 UVC」这条推理，并把实测 FIFO 数字写进 §2 的端点预算；**同时订正接口布局** —— §2 原先设想 HID 排在 UAC 之后（IF4），实际落地是 **IF0 vendor / IF1 HID / IF2-4 UAC**（理由见「接口与端点新旧对照」一节）；
  - **§10 阶段 4** 的验证标准里，`--dump-hw-params` 那条与本计划 Task 7/8 一致，勾掉即可。
- [ ] **Step 5**：`components/packages/tab5-all-in-one/README.md` 的「文档」一节补本计划的链接。
- [ ] **Step 6**：提交。

```
git commit -m "docs(tab5): 补 UAC1 全双工音频的实现说明与实机验证结论 (P3 Task10)"
```

---

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **FIFO 装不下**（256 words 是硬上限） | 音频或 UVC 之一放不进去，且失败**无日志**（`TU_ASSERT` 静默返回） | 参数选定阶段就按公式算过账（16 kHz 单声道的 OUT 包小于 vendor 已有的 64 B，RX FIFO 一个 word 不涨）；Task 6 主动读寄存器实测；Task 6 Step 3 给了按序降级阶梯 |
| **现场没有任何串口** | 默认调试手段（`ESP_LOGI` 打个数）整个失效；而「临时开 CDC」这条退路被端点预算堵死 | 硬约束 C 列了两条可见通道（宿主机 / host 侧），每条判据都必须落在其中之一；CDC 与 UAC 互斥变成编译期 `#error`。**残留风险**：从上电到 host 枚举之间是盲的（初稿的屏上面板已删），缓解见硬约束 C 下方那段 ⚠️ |
| **I2S 没组成全双工却不报错** | 声音是噪声或全静音，所有函数返回 `ESP_OK` | 两道自己的防线：① 两次 init 传**同一个** `i2s_std_config_t` 对象（结构上排除"填得不一样"）；② 读 `I2S0.tx_conf.sig_loopback`（就是 `i2s_ll_share_bck_ws()` 写的那一位）显式判定，为 0 则返回错误码并拒绝启动音频（host 侧表现为「声卡在但全静音」）。**不依赖 IDF 那条看不见的 DEBUG 日志** |
| **codec 与 USB 两段无法分开归因**（删掉正弦/电平自检的代价） | `aplay` 没声音时要同时怀疑 codec 与 USB 两边 | 全双工由读寄存器显式判定，先排除掉最隐蔽的那一类；`check_usb_desc.py` 在烧板前把描述符那一半排除掉；剩下的按 Task 7 Step 1 的顺序查 |
| **esp_codec_dev 打开录音时重配已在跑的全双工 I2S** | 录音全零，或播放被打断 | 已逐行读过 `check_fs_compatible()`：两边参数完全相同 ⇒ 走「同参数直接 set」分支且不动 TX，预期是重配成同样的值。**这条只能上板验**，见 Task 3 Step 1 的 ⓘ |
| **UAC1 描述符的交叉引用写错** | host 完全不认这个设备，而现场没有串口可查 | Task 5 的 `check_usb_desc.py` 在烧板前把 `wTotalLength` / `baInterfaceNr` / terminal ID 链 / ISO 端点属性全部断言一遍；底稿取自已实机跑通的 Cardputer |
| **ISO 端点 sync 字段填成 0** | TinyUSB 的 UAC1 分支把数据端点当成反馈端点，数据永远发不出去 | `check_usb_desc.py` 有专门一条断言；`audio_device.c:908-922` 的判定逻辑写进了注释 |
| 接口号变动（HID 1→4）碰坏已验证功能 | 键盘/触摸回归 | 端点号刻意**不动**（只动接口号），减少变量；Task 6 起每个上板任务的判据都含键盘与触摸 |
| **开机/开流时的爆音（pop）** | 观感上像硬件坏了；而 esp-bsp 自己的顺序就是先开功放后配 codec | Task 2 Step 4b 把顺序定死为「codec 配完 + 解除静音 → 延时 50ms → 才开功放」，`board_power_init()` 只把引脚配好并保持关闭（与背光同构）；判据是 Task 2 Step 1 的三条听感。⚠️ 这是从 esp-bsp 代码顺序**推出**的风险，上游没有已报告的 Tab5 爆音缺陷——若实测没有 pop，也**不要**把顺序改回去，代价是 50ms 开机时间而已 |
| **8 bit / 7 bit I2C 地址混用** | codec 初始化失败，或把寄存器写到别的器件上（I2C 写无反馈） | `tab5_pins.h` 里 `*_ADDR7` 与 `*_ADDR8` 分开定名并注明各自的消费者；Task 2 Step 4 的判据里包含核对 `ES8388_CODEC_DEFAULT_ADDR == 0x20` |
| `esp_codec_dev` 拖进重依赖 | 依赖树被污染，与 spec §8.1「保持依赖树干净」冲突 | 已查证 v1.6.2 的 manifest 只依赖 `idf >= 4.0`；Task 1 Step 5 仍有明确判据（`managed_components/` 里不得出现 LVGL / esp_video / usb_host / m5stack_tab5），不通过就退回按「关键事实」里的寄存器表自己写薄驱动 |
| `esp_codec_dev_open()` 是否会替我们 `i2s_channel_enable` | 重复 enable 报 `ESP_ERR_INVALID_STATE`，或两边都不 enable 导致静默无声 | Task 2 Step 4 已写明预期行为与「若实测相反则补上并记录结论」；判据是听到声音，不是返回值 |
| 音频抢了 GUD 的 CPU / PSRAM 带宽 | 显示掉帧 | Task 9 Step 2 给了按可能性排序的归因清单（优先级 → 欠载超时 → PSRAM），要求写结论而不是碰运气调参 |
| 每帧路径打日志把音频饿死 | 观测干扰被观测，越查越乱 | 欠载/溢出只计数，每 10 秒汇总一条 |
