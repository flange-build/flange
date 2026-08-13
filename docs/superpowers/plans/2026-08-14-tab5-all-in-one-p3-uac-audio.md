# Tab5 all-in-one — P3：UAC1 全双工音频（ES8388 + ES7210）实施计划

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

> ⚠️ 第 2 条对本阶段的实际后果：**「先临时开 CDC 把音频调通」这条退路是堵死的。** 实施者在最需要日志的时候一定会想到它，然后撞上一个像是描述符写错的枚举失败。所以 Task 5 Step 3 会把它变成编译期 `#error`，并且本计划另给了一条**零端点代价**的观测通道（见下方硬约束 C 与 Task 0）。

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

这条约束比它看起来更硬：**它把「用 `ESP_LOGI` 打个数看看」这个默认调试手段整个拿掉了。** 因此本计划的每一条判据都必须落在下面**三条能看见的通道**之一，任何一条判据若只存在于 `ESP_LOG*` 里，就等于没有判据：

| 通道 | 覆盖阶段 | 落点 |
|---|---|---|
| **① 宿主机（不上板）** | 描述符、纯逻辑函数 | Task 4 的 `test_audio_frame.c`、Task 5 的 `check_usb_desc.py` |
| **② 屏上状态面板**（本计划新建，零端点代价） | Task 0–3 的 codec/I2S bring-up，此时 USB 侧还什么都没有 | Task 0 建，Task 2/3 用 |
| **③ host 侧** | USB 枚举之后的一切 | `lsusb -v`、`dmesg`、`/proc/asound/`、`aplay` / `arecord`、`evtest` |

> ⓘ **订正任务说明中的一条**：本仓库**目前并没有**「从 ELF dump 描述符再用解析器跑一遍」的既有做法——P1/P2 的宿主机验证做的是**纯逻辑函数**回归（`test_kbd_translate.c` / `test_touch_map.c` / `test_standby_screen.c`），HID 报告描述符本身是靠上板后 `evtest` 的行为反推的。本计划把这条做法**新建**出来（Task 5），因为 UAC1 描述符比 HID 报告描述符更长、更多交叉引用（terminal ID 链、`wTotalLength`、`baInterfaceNr`），且失败时没有任何降级形态。

判据落点：Task 5 的 `check_usb_desc.py` 在**不烧板**的前提下把整份配置描述符断言一遍；Task 0 把屏幕变成 bring-up 期的仪表。

### C-bis. 为什么屏幕可以当日志通道

P0 已经把「GUD 坐标系的一块紧凑 RGB565 → PPA 缩放旋转 → 面板」这条路实机验证过了（`display_blit()`），而 `616af603` 又落地了零依赖的绘制原语（`standby_screen.c`：填充矩形 / 线框 / 整数倍放大画字符串 + Spleen 8×16 点阵字体）。两者相加，屏上打字**不需要任何新硬件通路，也不占用一条端点**——这正好补上 ② 这一格。

代价与边界条件写在 Task 0，其中最要紧的两条：

- **PPA 的 `max_pending_trans_num` 要跟着提交者数量涨**（现在是 2，面板是第 3 个提交者）；
- **面板是 bring-up 期仪表，做成 Kconfig 开关、默认关闭**，且 Task 9 的复合回归**必须关掉它**——否则它自己就成了扰动被测对象的那个变量。

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
   - **运行时显式判定**：`i2s_std.c:142-146` 的 `i2s_ll_share_bck_ws()` 在 P4 上写的是 `I2S0.tx_conf.sig_loopback`（`components/soc/esp32p4/register/hw_ver1/soc/i2s_struct.h:576-580`，bit 30）。两个通道都 init 完之后**这一位必须是 1**——它就是硬件层面「TX 与 RX 共用 BCLK/WS」的开关。读它，为 0 就走**可见**的失败路径（屏上报错 + 返回错误码，不启动音频），而不是任其 `ESP_OK` 放行后变成噪声。
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

spec §2 的最终布局把 HID 排在 UAC 之后（IF4）。本阶段落实这一点：音频的 3 个接口插在 vendor 与 HID 之间，**HID 从 IF1 移到 IF4**。

| | 现在（P2 结束） | 本阶段之后 | UVC（P4，预留） |
|---|---|---|---|
| IF0 | Vendor(GUD) | Vendor(GUD) | 同 |
| IF1 | **HID（键盘+触摸）** | **AudioControl** | 同 |
| IF2 | — | AudioStreaming OUT（播放） | 同 |
| IF3 | — | AudioStreaming IN（录音） | 同 |
| IF4 | — | **HID（键盘+触摸）** | 同 |
| IF5/IF6 | — | — | VideoControl / VideoStreaming |

**接口号变动对 host 侧没有功能影响**：`drm/gud` 按 VID/PID + 接口类绑定，`usbhid` / `hid-multitouch` 按接口类绑定，`snd-usb-audio` 按 IAD + 接口类绑定，**没有任何一方按接口号绑定**。真正需要跟着改的只有三处，都在固件内：`ITF_NUM_*` 枚举、`TUD_*_DESCRIPTOR` 的第一个参数、以及 `tud_audio_set_itf_cb()` 里用 `ITF_NUM_AUDIO_STREAMING_OUT/IN` 做的方向判断。

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
├── Kconfig.projbuild          # 新：TAB5_AUDIO_PANEL 开关（默认 n）
├── audio_panel.{c,h}          # 新：bring-up 屏上状态面板（PSRAM 缓冲 + 节流 + display_blit）
├── audio_panel_render.{c,h}   # 新：面板版式与电平条渲染，零依赖纯函数（宿主机可测）
├── standby_screen.{c,h}       # 改：最小导出 3 个绘制原语 + RGB565 宏（其余仍 static）
├── display_dsi.c              # 改：PPA max_pending_trans_num 随提交者数量调整
├── codec_audio.{c,h}          # 新：ES8388/ES7210 初始化 + I2S 全双工 + UAC 数据泵
├── audio_frame.{c,h}          # 新：单↔双声道转换与峰值计算，零依赖纯函数（宿主机可测）
├── tinyusb_config/tusb_config.h  # 新：include_next 默认配置后追加 CFG_TUD_AUDIO_*
├── usb_descriptors.{c,h}      # 改：加 UAC1 三接口 + 两 ISO 端点；HID 接口号 1→4
├── tab5_pins.h                # 改：加 I2S 引脚、功放使能脚、两个 codec 的 7/8 bit 地址
├── board_power.{c,h}          # 改：功放开关（配好但保持关闭）+ codec 探测
├── app_main.c                 # 改：启动面板与音频 + FIFO 占用实测
├── idf_component.yml          # 改：加 espressif/esp_codec_dev
└── CMakeLists.txt             # 改：加源文件、tinyusb_config 接线、esp_driver_i2s
firmware/test/
├── test_audio_panel_render.c  # 新：面板渲染的宿主机回归 + PPM 版式预览
├── test_audio_frame.c         # 新：audio_frame 纯函数回归（直接编译真实源码）
└── check_usb_desc.py          # 新：从 ELF 解析并校验整份配置描述符（烧板前的闸门）
firmware/sdkconfig.defaults    # 改：裁 esp_codec_dev 的 codec 列表 + 默认注释掉的面板开关
```

**转换逻辑与面板版式都抽成零依赖纯函数**（照 `kbd_translate.c` / `touch_map.c` / `standby_screen.c` 的先例），让 `test/` 能直接编译真实源码做回归。

---

## Task 0：bring-up 屏上状态面板（先于一切音频代码）

目标：把已经实机验证过的显示通路变成 bring-up 期的**仪表**。没有它，Task 2/3 的判据无处可落（硬约束 C）。

**Files:** Create `main/Kconfig.projbuild`、`main/audio_panel.{c,h}`、`main/audio_panel_render.{c,h}`、`test/test_audio_panel_render.c`；Modify `main/standby_screen.{c,h}`、`main/display_dsi.c`、`main/app_main.c`、`main/CMakeLists.txt`、`sdkconfig.defaults`

> ⚠️ **`main/app_main.c` 是实施时补上的，原清单漏了它 —— 而漏掉它这个任务就验不了。**
> 面板本身没有任何调用者：Step 1 的实机判据（三行文字、电平条随数据变化）需要有人喂数据，
> 而 Task 1 Step 4 才是第一个真实调用点。更麻烦的是它**没有任何编译期症状**：
> `--gc-sections` 会把整个未被引用的模块丢掉，于是「打开开关重编」测出来的 Flash/DIRAM
> 与基线**逐字节相同**，看上去正好像是"零成本"判据通过了，实际上镜像里根本没有面板。
> 所以 Step 5 之后要在 `app_main()` 末尾加一段 `#if CONFIG_TAB5_AUDIO_PANEL` 的自检
> （已知假数据扫一遍电平条），Task 1 起改由真实数据驱动、该段随之删除。

- [ ] **Step 1：成功判据**（宿主机与编译判据已过；实机部分待烧板验证）

> ⓘ 实施补充：面板脚印取 x 64..576 / y 276..360，把待机画面的分隔线(y=292)、
> 脚注1(y 310..326)、脚注2(y 330..346) **完整**盖住 —— 半截露出来的线会被当成显示故障，
> 反过来污染这把尺子自己的可信度。由此还推出「状态区与电平条必须紧邻无缝」：两块分别
> blit，中间留 4 px 缝隙，缝里的待机像素就原样露出来。这几条都有 `_Static_assert` 与
> 宿主机用例把关。

宿主机：

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -Werror -I../main test_audio_panel_render.c \
   ../main/audio_panel_render.c ../main/standby_screen.c -o /tmp/tap && /tmp/tap /tmp/panel.ppm
# → OK (N cases)，并导出一张可肉眼验收版式的 PPM
```

实机（临时打开开关烧一次）：屏幕下方出现状态面板，三行文字可读、两条电平条随手动喂进去的假数据变化；**待机画面的「NO SIGNAL」与等待点动画仍在正常工作、没有被面板压住或互相覆盖**；GUD/键盘/触摸不回归。

关掉开关重编：Flash 与 DIRAM 应与本任务开始前**逐字节相同**（照 `firmware/README.md` 记录 CDC 开关时的同一条判据），证明它真的是零成本的可选设施。

- [x] **Step 2：`main/Kconfig.projbuild` —— 做成开关，默认关闭**

```kconfig
menu "Tab5 AIO"

config TAB5_AUDIO_PANEL
    bool "音频 bring-up 屏上状态面板（调试设施，默认关闭）"
    default n
    help
      在待机画面下方画一块状态面板：三行文字 + 左右声道电平条。

      这块板默认没有任何可用串口（UART0 只在 M5-Bus 排针上，USB-Serial/JTAG 被
      TinyUSB 收走，CDC 与 UAC 音频在全速口上互斥），codec/I2S bring-up 阶段
      USB 侧又还什么都没有 —— 屏幕是那一段唯一看得见的输出。

      **这是调试设施，不是产品特性。** 打开后 PPA 多一个周期性提交者，
      占用 64 KB PSRAM（状态区 48 KB + 电平条 16 KB），电平条以 5 Hz 刷新
      约合 80 KB/s 的 PPA 搬运；出厂固件应保持关闭。

endmenu
```

`sdkconfig.defaults` 末尾追加（与既有的 CDC 开关同一写法与同一警告）：

```
# ── bring-up 屏上状态面板（默认关闭）─────────────────────────────
# 取消注释后，codec/I2S 的状态与麦克风电平会画在屏幕下方 —— 这块板没有串口，
# bring-up 阶段这是唯一看得见的输出。取消注释后必须 `rm -f sdkconfig` 再 build。
# ⚠️ Task 9 的复合回归必须关掉它：它自己会占 PPA 与 PSRAM 带宽，开着测显示帧率
#    等于把仪表算进被测对象。
# CONFIG_TAB5_AUDIO_PANEL=y
```

- [x] **Step 3：`standby_screen.{c,h}` 最小导出**

只导出**面板真正用得到的**三样，其余（`draw_char` / `draw_frame` 与全部版式常量）保持 `static`：

```c
/* ── 供 audio_panel_render.c 复用的最小子集 ──────────────────────
 * 只导出真正被复用的两个原语与画布类型。draw_char / draw_frame 以及全部版式
 * 常量仍是 static —— 导出得越多，日后改待机画面版式时要顾虑的调用方就越多。
 * 这里导出的三样都是纯像素运算，宿主机可直接编译。 */
typedef struct {
    uint16_t *px;
    int w, h;
} standby_canvas_t;

/* 填充矩形。整条绘制链只有这一个函数写像素，边界钳位因此只需在这里做对一次；
 * 越界的 x/y/w/h 会被钳到画布内，不会越界写。 */
void standby_fill_rect(const standby_canvas_t *c, int x, int y, int w, int h, uint16_t color);

/* 画一行字符串，整数倍放大（scale=1 时是 8×16）。表外字符画成 '?'，不静默吞掉。 */
void standby_draw_text(const standby_canvas_t *c, int x, int y, const char *s,
                       uint16_t color, int scale);

/* RGB565 打包。⚠️ R/B 只有 5 bit、G 只有 6 bit，低位会被丢掉 ——
 * 调色请对着实际显示值看，不要对着设计值。 */
#define STANDBY_RGB565(r, g, b) \
    ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))
```

`standby_screen.c` 侧是**纯机械改名**：`canvas_t` → `standby_canvas_t`、`fill_rect` → `standby_fill_rect`、`draw_text` → `standby_draw_text`（去掉 `static`），原来的 `RGB565` 宏改为直接用 `STANDBY_RGB565`。`draw_char` / `draw_frame` 不动。

**判据**：`test_standby_screen.c` 的 35 个用例**原样全过**（它只调 `standby_render` / `standby_render_dots`，不该受改名影响）——若有用例挂了，说明改名改错了地方，不要改测试。

- [x] **Step 4：`audio_panel_render.h` —— 版式常量与两个纯函数**

面板分两块，**分别 blit**：状态区（内容变了才画，一次开机就几次）与电平条（5 Hz）。分开是为了别让 5 Hz 的刷新去搬状态区那 48 KB。

```c
#pragma once
/*
 * bring-up 屏上状态面板的版式与渲染，纯函数、零依赖（只用 standby_screen.h
 * 导出的绘制原语与 tab5_pins.h 的 GUD_W/GUD_H）。上屏由 audio_panel.c 负责。
 *
 * 拆成独立文件的理由与 standby_screen.c 相同：电平条的长度换算、数字格式化、
 * 越界钳位都能在宿主机上钉死，而这些错在实机上只表现为"条画得不对"，
 * 从现象几乎反推不出来。见 test/test_audio_panel_render.c。
 */
#include <stdint.h>

/* ── 版式（GUD 640×360 横向坐标系；上屏时 PPA 会 2× 放大并旋转 90°）──
 *
 * 面板放在屏幕**最下方**，理由是必须避开待机画面的等待点动画（y 236..268）——
 * 两者都在周期性重画，重叠就会互相覆盖，表现为文字闪烁或缺一块。
 * 下面那条 _Static_assert 把这个约束钉死。
 */
#define AUDIO_PANEL_X            64
#define AUDIO_PANEL_Y            276
#define AUDIO_PANEL_STATUS_W     512
#define AUDIO_PANEL_STATUS_LINES 3
#define AUDIO_PANEL_STATUS_H     (AUDIO_PANEL_STATUS_LINES * 16)   /* 48 */
#define AUDIO_PANEL_COLS         (AUDIO_PANEL_STATUS_W / 8)        /* 64 列，1× 字号 */

#define AUDIO_PANEL_METER_X      AUDIO_PANEL_X
#define AUDIO_PANEL_METER_Y      (AUDIO_PANEL_Y + AUDIO_PANEL_STATUS_H + 4)  /* 328 */
#define AUDIO_PANEL_METER_W      256
#define AUDIO_PANEL_METER_H      32     /* 两行 × 16 px：L 一行、R 一行 */
#define AUDIO_PANEL_BAR_W        140    /* 条的最大长度，像素 */

/* 电平条满刻度。与 audio_frame_peak() 的返回域一致（0..32768），
 * 取 32768 而不是 32767 是因为 INT16_MIN 的绝对值就是 32768。 */
#define AUDIO_PANEL_PEAK_FULL    32768

/*
 * 状态区渲染：n 行文本 → 紧凑的 AUDIO_PANEL_STATUS_W × AUDIO_PANEL_STATUS_H 缓冲。
 * lines[i] 为 NULL 或空串时该行画成背景色。超过 AUDIO_PANEL_COLS 的部分被截断
 * （截断而不是换行：面板是定高的，换行会把后面的行挤出画）。
 * n 超过 AUDIO_PANEL_STATUS_LINES 时按上限截断。
 */
void audio_panel_render_status(uint16_t *buf, const char *const *lines, int n);

/*
 * 电平条渲染：两路峰值 → 紧凑的 AUDIO_PANEL_METER_W × AUDIO_PANEL_METER_H 缓冲。
 * 每行 = 标签("L"/"R") + 条 + 5 位十进制峰值。
 * peak 超过 AUDIO_PANEL_PEAK_FULL 时条按满格画（钳位，不是绕回）。
 */
void audio_panel_render_meter(uint16_t *buf, uint16_t peak_l, uint16_t peak_r);

/*
 * 峰值 → 条长度（像素）。单独导出是为了能在宿主机上单独钉死这条换算 ——
 * 它是整块面板里唯一一处算术，也是唯一一处会被"顺手优化"改错的地方。
 * 用 uint32_t 中间量：32768 × 140 = 4,587,520，早已超出 uint16_t。
 */
uint16_t audio_panel_bar_len(uint16_t peak);
```

配套断言（放 `audio_panel_render.c`，需要 `#include "standby_screen.h"` 拿 `STANDBY_DOTS_*`）：

```c
_Static_assert(AUDIO_PANEL_Y >= STANDBY_DOTS_Y + STANDBY_DOTS_H,
               "面板必须在待机动画的等待点下方：两者都在周期性重画，重叠会互相覆盖");
_Static_assert(AUDIO_PANEL_X + AUDIO_PANEL_STATUS_W <= GUD_W, "状态区右边缘出画");
_Static_assert(AUDIO_PANEL_METER_Y + AUDIO_PANEL_METER_H <= GUD_H, "电平条下边缘出画");
_Static_assert(AUDIO_PANEL_STATUS_H == AUDIO_PANEL_STATUS_LINES * FONT8X16_H,
               "状态区高度必须正好装下整数行");
```

`audio_panel_bar_len()` 的实现：

```c
uint16_t audio_panel_bar_len(uint16_t peak)
{
    if (peak >= AUDIO_PANEL_PEAK_FULL)
        return AUDIO_PANEL_BAR_W;
    return (uint16_t)(((uint32_t)peak * AUDIO_PANEL_BAR_W) / AUDIO_PANEL_PEAK_FULL);
}
```

- [x] **Step 5：`audio_panel.{c,h}` —— 上屏、脏检查与节流**

```c
#pragma once
/*
 * bring-up 期的屏上状态面板。整个模块由 CONFIG_TAB5_AUDIO_PANEL 门控，
 * 关闭时下面三个函数全部编译成空（见 audio_panel.c 的 #if），调用点不必加条件。
 *
 * 为什么需要它：这块板默认没有可用串口，而 codec/I2S bring-up 阶段 USB 侧还
 * 什么都没有 —— 屏幕是那一段唯一看得见的输出。详见计划的硬约束 C。
 */
#include <stdint.h>
#include "esp_err.h"

/* 分配 PSRAM 缓冲。须在 display_init() 之后调用（要用 display_blit）。 */
esp_err_t audio_panel_init(void);

/* 设置第 line 行（0..AUDIO_PANEL_STATUS_LINES-1）的文本。
 * **内容没变就不重画**，因此可以在任何地方无脑调用。 */
void audio_panel_status(int line, const char *text);

/* 更新电平条。**内部按 5 Hz 节流**，因此可以在每毫秒的数据泵里无脑调用。 */
void audio_panel_levels(uint16_t peak_l, uint16_t peak_r);
```

实现要点：

- 两个 PSRAM 缓冲（状态区 512×48×2 = 49,152 B、电平条 256×32×2 = 16,384 B），`audio_panel_init()` 一次分配、不释放（bring-up 工具，生命周期就是整个开机）。
- `audio_panel_status()` 把文本存进一份 `char[LINES][COLS+1]`，`strcmp` 不同才重渲染 + `display_blit(AUDIO_PANEL_X, AUDIO_PANEL_Y, ...)`。
- `audio_panel_levels()` 用 `esp_timer_get_time()` 做 5 Hz 节流；节流期内把峰值取 `max` 累积，**不要直接丢弃**——丢弃会让一次拍手正好落在节流窗口里而看不见。
- **两者都从调用方的任务上下文里直接 blit**，不另起任务：数据泵任务本来就是 1 ms 一转，5 Hz 的额外工作落在它身上完全吃得下，而多一个任务就要多一个 PPA 提交者名额。

  ⓘ 于是**PPA 的第三个提交者就是数据泵任务**（Task 2 起存在），不是一个独立的面板任务。

- [x] **Step 6：`display_dsi.c` 的 PPA 提交者数量**

现在的 `.max_pending_trans_num = 2` 对应两个提交者（TinyUSB 收帧任务 + 等待点动画任务）。面板让数据泵任务成为**第三个**，必须跟着涨——池子空时 `ppa_do_scale_rotate_mirror()` **不等待、直接返回 `ESP_FAIL`**（`ppa_srm.c` 尾部 "exceed maximum pending transactions"），落在 GUD 侧就是 host 的一块脏矩形永远不上屏，而脏矩形不会自动重发。

```c
/*
 * 元素数 = **并发提交者数**（只用阻塞模式，每个提交者最多占 1 个）：
 *   ① TinyUSB 任务（GUD 收帧）
 *   ② 待机画面的等待点动画任务（收到第一帧后退出）
 *   ③ 音频数据泵任务（仅 CONFIG_TAB5_AUDIO_PANEL，画状态面板与电平条）
 * 池子空时 ppa_do_scale_rotate_mirror() 不等待、直接返回 ESP_FAIL
 * （ppa_srm.c "exceed maximum pending transactions"），那一次 blit 就丢了。
 * 窗口很窄，但代价不对称（GUD 那边是永久性的一块不刷新），故按提交者数量给足。
 * 退出/关闭后多出来的元素闲置，几百字节内部 RAM，不值得回收。
 */
#if CONFIG_TAB5_AUDIO_PANEL
        .max_pending_trans_num = 3,
#else
        .max_pending_trans_num = 2,
#endif
```

> ⓘ `CONFIG_TAB5_AUDIO_PANEL` 未定义时 `#if` 求值为 0，两种配置下都成立，不必写 `#ifdef`。

- [x] **Step 7：`test/test_audio_panel_render.c`**

照 `test_standby_screen.c` 的形式（`main()` + `assert`，无框架，可选导出 PPM 预览）。用例至少覆盖：

1. `audio_panel_bar_len`：0 → 0；`AUDIO_PANEL_PEAK_FULL` → `AUDIO_PANEL_BAR_W`；`AUDIO_PANEL_PEAK_FULL/2` → `AUDIO_PANEL_BAR_W/2`（±1）；**超过满刻度 → 钳到 `AUDIO_PANEL_BAR_W`，不绕回**（这是 `uint32_t` 中间量那条注释要防的错）；
2. `render_status`：越界哨兵（缓冲前后各放一个魔数，渲染后必须没被动过）；`lines[i] = NULL` 那行是纯背景色；超长字符串被截断而不越界；`n > LINES` 被截断；
3. `render_meter`：两路不同峰值画出**不同长度**的条；`peak = 0` 时条区域全是背景色；两行互不侵占（用行带占用检查，照 `test_standby_screen.c` 的做法）；
4. 版式：状态区与电平条的矩形**不重叠**，且都不与 `STANDBY_DOTS_*` 重叠（这条与 `_Static_assert` 重复是故意的——断言防编译期，测试防有人把断言删了）。

- [ ] **Step 8：编译（开/关两种配置）+ 上板验证 + 提交**（开/关两种配置均已编过、关闭时与基线逐节相同、自检调用点已就位；只剩上板那一次目视验证）

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh
rm -f sdkconfig && idf.py build && idf.py size      # 关：记下 Flash/DIRAM
sed -i '' 's/^# CONFIG_TAB5_AUDIO_PANEL=y/CONFIG_TAB5_AUDIO_PANEL=y/' sdkconfig.defaults
rm -f sdkconfig && idf.py build                     # 开：烧板验证
```

验证完把开关注释回去，重编并核对 Flash/DIRAM 与「关」那次**逐字节相同**。

```
git commit -m "feat(tab5-fw): bring-up 屏上状态面板（默认关闭），补上无串口下的观测通道 (P3 Task0)"
```

> **何时移除**：本面板的使命在 Task 8 结束（音频全通、host 侧 `/proc/asound` 与 `arecord` 成为更好的观测手段）。届时**不删代码、保持默认关闭**——理由与 CDC 调试串口同：下一个阶段（UVC）还会有一段"USB 侧什么都没有"的 bring-up 期，那时它仍是唯一看得见的输出。Task 10 要在 README 里写明这个定位与重新打开的方法。

---

## Task 1：音频供电、codec 探测与依赖引入（不碰 I2S、不碰 USB）

目标：把 ES8388 / ES7210 的电与 I2C 通路坐实，并确认 `esp_codec_dev` 没有污染依赖树。

**Files:** Modify `main/idf_component.yml`、`main/tab5_pins.h`、`main/board_power.{c,h}`、`main/CMakeLists.txt`、`main/app_main.c`

- [ ] **Step 1：成功判据**

**屏上**（Task 0 的面板，第 0 行）出现：

```
I2C  ES8388 OK   ES7210 OK
```

即两颗芯片的 `i2c_master_probe()` 都返回 `ESP_OK`（**探测用 7 bit 地址** `0x10` / `0x40`，与 `firmware/README.md` 的实测 I2C 设备表一致）。任一为 `--` 就停下来查电与地址，别往下走。

同一句话也照常 `ESP_LOGI` 一份（接了 USB-TTL 时更方便），但**判据是屏上那一行**——现场没有串口。

且 `idf.py build` 通过、**GUD 显示与键盘触摸均不回归**（本任务不改任何已有链路，出现回归说明依赖引入撞车了，立刻停下来查）。

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

并把同一结论送上屏（`board_power.c` 不该依赖音频模块，所以这一句写在 `app_main.c` 里，紧跟 `board_power_init()` 之后）：

```c
    char l0[AUDIO_PANEL_COLS + 1];
    snprintf(l0, sizeof(l0), "I2C  ES8388 %s   ES7210 %s",
             board_audio_present(BOARD_CODEC_ES8388) ? "OK" : "--",
             board_audio_present(BOARD_CODEC_ES7210) ? "OK" : "--");
    audio_panel_status(0, l0);
```

`board_power.h` 相应导出探测结果（探测在 `board_power_init()` 里做过一次，不重复打 I2C）：

```c
typedef enum { BOARD_CODEC_ES8388, BOARD_CODEC_ES7210 } board_codec_t;
/* board_power_init() 期间那一次探测的结果。重复探测没有坏处，但会在总线上
 * 多打两个事务，而这条总线同时挂着触摸的 20ms 轮询，能省则省。 */
bool board_audio_present(board_codec_t which);
```

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

## Task 2：I2S 全双工 + ES8388 播放 bring-up（固件自造正弦，不碰 USB）

目标：喇叭能出一个干净的 1 kHz 正弦音。**这一步把「codec 通了没有」与「USB 通了没有」彻底分开**——之后若 `aplay` 没声音，就不用再怀疑 codec。

**Files:** Create `main/codec_audio.{c,h}`；Modify `main/CMakeLists.txt`、`main/app_main.c`

- [ ] **Step 1：成功判据**

**屏上**第 1 行出现（`duplex=1` 是我们自己读寄存器判定的，不是"函数返回了 OK"）：

```
I2S  16000Hz 16bit 2slot  duplex=1
```

第 2 行出现 `ES8388 OK  vol=70  PA=on`。

加三条听感判据（缺一不可，都只能靠耳朵）：

1. **喇叭连续发出稳定的 1 kHz 正弦**约 3 秒，不断续、不沙哑；
2. 从上电到正弦开始之间**没有可闻的「啪」声**（这是 Step 4b 那套上电顺序要买的东西）；
3. 音高听着就是 1 kHz 而不是 500 Hz 或 2 kHz（半速/倍速说明声道数或 slot 配置错了）。

GUD 显示与键盘触摸不回归。

> ⚠️ **`duplex=0` 时必须停在这里，不要往下走。** 那说明 TX 与 RX 没有共用 BCLK/WS，两个方向在抢时钟——继续下去听到的一切噪声都无从归因。检查点只有一个：两次 `i2s_channel_init_std_mode()` 传的是不是**同一个** `i2s_std_config_t` 对象（Step 3 的写法在结构上排除了这种可能，所以真出现 0 更可能是有人后来把它拆成了两份）。

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
     * 谁也看不见，所以必须在这里变成一条可见的失败：屏上报错 + 返回错误码，
     * 让 codec_audio_start() 整个失败，而不是带病运行成一屋子噪声。
     */
    const bool duplex = i2s_duplex_active();
    ESP_LOGI(TAG, "I2S %dHz/16bit/2slot duplex=%d", UAC_SAMPLE_RATE, duplex);
    audio_panel_status(1, duplex ? "I2S  16000Hz 16bit 2slot  duplex=1"
                                 : "I2S  duplex=0  !! TX/RX 未共用 BCLK/WS !!");
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

- [ ] **Step 5：数据泵任务的骨架 + 自检正弦（正弦是临时代码，Task 7 删掉）**

任务在本步就建起来，Task 3 与 Task 7/8 逐步往里加内容，**不要每个任务另起一个新任务**。

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

/* 1kHz @ 16kHz 采样 = 每周期恰好 16 点，Q15 × 0.25。
 * 幅度取满量程的 1/4：直推板载小喇叭时满幅容易破音，而破音会让人误判成时钟错。 */
static const int16_t k_sine_1khz[UAC_FRAME_SAMPLES] = {
    0, 3135, 5793, 7568, 8192, 7568, 5793, 3135,
    0, -3135, -5793, -7568, -8192, -7568, -5793, -3135,
};

static void audio_pump_task(void *arg)
{
    int16_t tx_stereo[UAC_FRAME_SAMPLES * 2];
    (void)arg;

    /* 开机自检：连续 3 秒把正弦灌进 TX。目的是把「codec/I2S 通了没有」与
     * 「USB 通了没有」分开验 —— 之后 aplay 没声音就不必再怀疑这一段。 */
    audio_frame_mono_to_stereo(k_sine_1khz, tx_stereo, UAC_FRAME_SAMPLES);
    for (int ms = 0; ms < 3000; ms++) {
        size_t written = 0;
        i2s_channel_write(s_tx, tx_stereo, sizeof(tx_stereo), &written, pdMS_TO_TICKS(20));
    }
    ESP_LOGI(TAG, "正弦自检结束");

    while (1) vTaskDelay(pdMS_TO_TICKS(100));   /* Task 3 起被真正的收发循环取代 */
}
```

`codec_audio_start()` 末尾 `xTaskCreate(audio_pump_task, "audio", AUDIO_TASK_STACK_SIZE, NULL, AUDIO_TASK_PRIORITY, NULL)`，失败返回 `ESP_ERR_NO_MEM`。

（`audio_frame_mono_to_stereo()` 在 Task 4 才有宿主机测试，但函数本身要在本步就写出来——Task 4 是补测试与边界用例，不是补实现。`k_sine_1khz` 的元素个数正好等于 `UAC_FRAME_SAMPLES`，加一条 `_Static_assert(sizeof(k_sine_1khz)/sizeof(k_sine_1khz[0]) == UAC_FRAME_SAMPLES, "正弦表长度必须等于一帧样本数")` 钉住——改采样率时这张表会失效，而症状只是音高不对，很难联想到。）

- [ ] **Step 6：`app_main.c` 调用**

在 `touch_start()` 之后追加，处置原则与键盘/触摸一致（失败只 WARNING、不拦启动）：

```c
    err = codec_audio_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "音频不可用(%s)，继续启动", esp_err_to_name(err));
```

- [ ] **Step 7：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): I2S 全双工与 ES8388 播放 bring-up，正弦自检出声 (P3 Task2)"
```

---

## Task 3：ES7210 录音 bring-up（屏上电平条，仍不碰 USB）

目标：确认双麦真的在出数据，且没有把已经能出声的播放弄坏。

**Files:** Modify `main/codec_audio.c`

- [ ] **Step 1：成功判据**

**屏上**第 2 行变成 `ES8388 OK  ES7210 OK  PA=on`，且**电平条开始动**（这正是 Task 0 那块面板存在的理由——没有它，本任务在没有串口的板子上根本没有判据）：

- **安静环境**下两条都很短、数字很小（经验上 < 500，具体阈值以实测为准，如实记进 README）；
- **对着麦克风说话/拍手**时两条都明显冲长、数字跳到数千以上，且**停止后回落**；
- **L 与 R 是两只不同的麦**（L = MIC1、R = MIC2）：贴近其中一只说话，两条应该**长度不同**。两条永远等长说明只接到了一只麦（多半是误用了 `I2S_SLOT_MODE_MONO`）；
- 播放的正弦自检**同时仍在响**——**这就是全双工成立的第一手证据**：屏上 `duplex=1` 证明硬件共用了 BCLK/WS，边放边录证明两个方向真的都在搬数据。

GUD 显示与键盘触摸不回归。

> ⚠️ 若两条恒为 0 长：先看 MCLK 有没有真出（`ES7210_MCLK_FROM_PAD` 要求 ESP 从 G30 提供 MCLK），再看是不是 Step 2 的 `mic_selected` 掩码选错了通道。若两条恒为同一个非零长度且**不随声音变化**，多半是 I2S 收到的是空闲电平而非采样，回去看屏上的 `duplex=` 那一位。

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

- [ ] **Step 3：把 `audio_pump_task` 的空转循环换成收发循环（电平自检是临时代码，Task 8 删掉）**

把 Task 2 Step 5 里那句 `while (1) vTaskDelay(...)` 换成真正的循环：每次 `i2s_channel_read()` 一帧（= 1 ms），同时继续 `i2s_channel_write()` 正弦；每累计 1000 帧用 `audio_frame_peak()` 打印左右两路峰值。**读写在同一个任务里交替，这就是最终数据泵的雏形**，Task 7/8 只是把正弦换成 USB 数据。

```c
    int16_t rx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t ch[UAC_FRAME_SAMPLES];
    uint16_t peak_l = 0, peak_r = 0;
    int n_frames = 0;

    while (1) {
        size_t got = 0;
        /* 用 RX 读作为节拍源：DMA 描述符正好是 1ms 的样本数，读满即阻塞到下一个 1ms，
         * 比 vTaskDelay(1) 更贴合 USB 帧，也省掉一个定时器。 */
        if (i2s_channel_read(s_rx, rx_stereo, sizeof(rx_stereo), &got,
                             pdMS_TO_TICKS(50)) != ESP_OK)
            continue;

        for (int i = 0; i < UAC_FRAME_SAMPLES; i++) ch[i] = rx_stereo[2 * i];
        uint16_t p = audio_frame_peak(ch, UAC_FRAME_SAMPLES);
        if (p > peak_l) peak_l = p;
        for (int i = 0; i < UAC_FRAME_SAMPLES; i++) ch[i] = rx_stereo[2 * i + 1];
        p = audio_frame_peak(ch, UAC_FRAME_SAMPLES);
        if (p > peak_r) peak_r = p;

        size_t written = 0;
        i2s_channel_write(s_tx, tx_stereo, sizeof(tx_stereo), &written, pdMS_TO_TICKS(20));

        /* 每帧无脑调用即可：audio_panel_levels() 内部按 5 Hz 节流，
         * 且节流窗口内取 max 累积 —— 直接丢弃的话，一次拍手正好落在窗口里就看不见了。
         * 关掉面板时它编译成空，这一行零成本。 */
        audio_panel_levels(peak_l, peak_r);

        if (++n_frames >= 1000) {          /* 每秒一次，别在每帧路径里打日志 */
            ESP_LOGI(TAG, "mic peak L=%u R=%u", peak_l, peak_r);
            peak_l = peak_r = 0;           /* 面板有自己的累积窗口，这里只管日志的 */
            n_frames = 0;
        }
    }
```

⚠️ **这一步同时让数据泵任务成为 PPA 的第三个提交者**——Task 0 Step 6 已经把 `max_pending_trans_num` 调好了。若跳过 Task 0 直接做本任务，池子会不够，症状是 GUD 偶发地有一小块永远不刷新（脏矩形不会重发），**而且与音频看起来毫无关系**。

- [ ] **Step 4：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): ES7210 双麦录音 bring-up，全双工电平自检通过 (P3 Task3)"
```

---

## Task 4：`audio_frame.c` 纯函数 + 宿主机回归测试

目标：把「单↔双声道转换」与「峰值计算」钉死在宿主机上。这类错误在实机上只表现为「声音小一半 / 只有一边有声 / 电平数字不对」，从现象反推极难，而在宿主机上验几乎零成本。

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

/*
 * 一段样本里的峰值绝对值，供录音电平自检打印。
 * n == 0 返回 0。
 *
 * ⚠️ INT16_MIN(-32768) 的绝对值是 32768，放不进 int16_t —— 本函数返回
 * uint16_t 并如实返回 32768，不做钳位。调用方只用它打日志/比阈值，不回填样本。
 */
uint16_t audio_frame_peak(const int16_t *samples, size_t n);
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

uint16_t audio_frame_peak(const int16_t *samples, size_t n)
{
    uint16_t peak = 0;
    for (size_t i = 0; i < n; i++) {
        const int32_t v = samples[i];
        const uint16_t a = (uint16_t)(v < 0 ? -v : v);
        if (a > peak) peak = a;
    }
    return peak;
}
```

- [ ] **Step 4：`test/test_audio_frame.c`**

照 `test_touch_map.c` 的形式：`main()` + `assert`，无框架，不挂 IDF 构建。用例至少覆盖：

1. `mono_to_stereo`：3 帧，左右两路都等于源；`frames == 0` 不写任何字节（用哨兵值检查）；
2. `stereo_to_mono`：`(100, 200) → 150`；`(-100, -200) → -150`（`(-300)>>1 == -150`）；`(1, 0) → 0`（右移向下取整，**不是** 0.5 四舍五入）；`(-1, 0) → -1`（这是右移与 `/2` 唯一会分叉的那一类，必须钉死）；
3. `stereo_to_mono`：`(INT16_MAX, INT16_MAX) → 32767`、`(INT16_MIN, INT16_MIN) → -32768`（证明不溢出）；
4. `peak`：正负混合取最大绝对值；含 `INT16_MIN` 时返回 32768；`n == 0` 返回 0；
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

脚本必须打印出 5 个接口（IF0 vendor / IF1 AC / IF2 AS-out / IF3 AS-in / IF4 HID）、2 条 ISO 端点，且**全部断言通过**，其中包括「没有任何端点的 `bSynchAddress` 非 0」与「没有任何 ISO 端点的 sync 字段为 0」。本任务**不上板**。

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
    /* UAC1 三接口。顺序不能动：AudioControl 必须是 IAD 覆盖的第一个接口，
     * 两个 AudioStreaming 必须紧随其后且连号（IAD 只能描述连续区间）。 */
    ITF_NUM_AUDIO_CONTROL,
    ITF_NUM_AUDIO_STREAMING_OUT,   /* 播放 */
    ITF_NUM_AUDIO_STREAMING_IN,    /* 录音 */
    ITF_NUM_HID,                   /* ⚠️ 由 1 变为 4：音频插在了前面 */
    ITF_NUM_TOTAL
};

#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82      /* 刻意不动：接口号变了，端点号不变，少一个变量 */
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

- [ ] **Step 4：删掉 Task 2 的正弦自检**

`audio_pump_task` 开头那段 3 秒正弦、`k_sine_1khz` 表与配套的 `_Static_assert` 整体删除。它的使命（把 codec 与 USB 分开验）已经完成，留着会在开机后头 3 秒占住 TX、盖掉 host 的第一段音频。

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

峰值打印从数据泵里移除（`audio_frame_peak()` 与它的测试**保留**——排查时随时可以临时接回去，且它是被测过的）。

- [ ] **Step 4：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): UAC1 录音通路打通，全双工同时收发验证 (P3 Task8)"
```

---

## Task 9：与 GUD / HID 的复合回归

目标：证明音频跑起来没有把已交付的三项能力弄坏。这是硬约束 D 的落点，也是 spec §10 对阶段 4 的验证要求。

**Files:** 无（纯验证；发现问题则回到对应任务）

- [ ] **Step 1：前置检查（做之前先确认，别做到一半才发现缺工具）**

**a) 固件侧：屏上面板必须关闭。**

```bash
grep -n "^CONFIG_TAB5_AUDIO_PANEL" firmware/sdkconfig.defaults   # 应无输出（保持注释态）
```

理由：面板每 200 ms 往 PPA 提交一次 16 KB 的搬运（约 80 KB/s），本任务恰恰要测「音频跑起来会不会让显示变慢」——开着它等于把仪表算进被测对象。**必须用关闭态的固件跑本任务**，测完再说。

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

0. **屏上面板忘了关**（Step 1a）——它每 200 ms 提交一次 16 KB 的 PPA 搬运（约 80 KB/s），是这张单子上最容易犯也最容易排除的一条，先确认；
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
  - **bring-up 屏上状态面板**：为什么需要（无串口 + CDC 退路被堵死）、怎么开（`CONFIG_TAB5_AUDIO_PANEL` + `rm -f sdkconfig`）、代价（PPA 第三个提交者、64 KB PSRAM）、**Task 9 必须关掉它**、以及「不删代码、留给 UVC 阶段复用」的定位；`standby_screen.h` 最小导出了哪三样、为什么其余保持 `static`；
  - host 侧验证命令（`/proc/asound/cards`、`aplay -l`、`arecord -l`、`stream0`、`--dump-hw-params`、全双工同时跑法）；
  - 两个宿主机验证跑法：`test_audio_frame.c` 与 `check_usb_desc.py`（后者要写明依赖 IDF python 环境的 pyelftools）；
  - Task 9 的复合回归结论与欠载计数实测值。
- [ ] **Step 2**：`firmware/README.md` 的「文件」表补 `codec_audio.{c,h}` / `audio_frame.{c,h}` / `audio_panel.{c,h}` / `audio_panel_render.{c,h}` / `Kconfig.projbuild` / `tinyusb_config/tusb_config.h` / `test/test_audio_frame.c` / `test/test_audio_panel_render.c` / `test/check_usb_desc.py` 九行；更新「能力」一节的接口布局（IF0 GUD / IF1-3 UAC / IF4 HID）；并在「待机画面」章节补一句 `standby_screen.{c,h}` 现在还给面板导出了三个绘制原语。
- [ ] **Step 3**：包级 `components/packages/tab5-all-in-one/README.md` 状态清单：UAC1 全双工音频从「⏳ 规划中」移到 ✅（如实机通过），并写明采样率/声道与「带宽是零和的」这条既有提示的具体数字。
- [ ] **Step 4**：spec 回填：
  - **§6 订正**：原文写「UAC1 参数沿用 Cardputer 的 mono 16 kHz」——采样率结论一致，但**理由要补上 FIFO 账**（原文没有这一层）；同时补上「两个方向必须同采样率（全双工共用 BCLK/WS）」这条原文没有的硬约束；
  - **§6 补充**：喇叭功放使能 = **`0x43` 那颗 PI4IOE5V6408 的 PIN1**（esp-bsp `BSP_SPEAKER_EN`），功放**没有**独立 GPIO；以及「codec 配完再开功放」的上电顺序与理由；
  - **§2 订正**：端点表补上「反馈端点会顶掉 UVC」这条推理，并把实测 FIFO 数字写进 §2 的端点预算；
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
| **现场没有任何串口** | 默认调试手段（`ESP_LOGI` 打个数）整个失效；而「临时开 CDC」这条退路被端点预算堵死 | Task 0 把屏幕做成 bring-up 仪表（零端点代价）；硬约束 C 列了三条可见通道，每条判据都必须落在其中之一；CDC 与 UAC 互斥变成编译期 `#error` |
| **I2S 没组成全双工却不报错** | 声音是噪声或全静音，所有函数返回 `ESP_OK` | 两道自己的防线：① 两次 init 传**同一个** `i2s_std_config_t` 对象（结构上排除"填得不一样"）；② 读 `I2S0.tx_conf.sig_loopback`（就是 `i2s_ll_share_bck_ws()` 写的那一位）显式判定，为 0 则屏上报错并拒绝启动音频。**不依赖 IDF 那条看不见的 DEBUG 日志** |
| **屏上面板自己成了扰动源** | Task 9 测「音频会不会让显示变慢」时把仪表算进被测对象 | 面板是 Kconfig 开关、默认关闭；Task 9 Step 1a 把「确认它关着」作为前置检查，Step 3 的归因清单里它排第 0 位 |
| **PPA 提交者变成 3 个却没调 `max_pending_trans_num`** | 池子空时 `ppa_do_scale_rotate_mirror()` 直接返回 `ESP_FAIL`，GUD 偶发一小块永远不刷新（脏矩形不重发），**且与音频看起来毫无关系** | Task 0 Step 6 随开关条件式调到 3，注释里把「元素数 = 并发提交者数」这条不变式写死；Task 3 Step 3 再提醒一次 |
| **UAC1 描述符的交叉引用写错** | host 完全不认这个设备，而现场没有串口可查 | Task 5 的 `check_usb_desc.py` 在烧板前把 `wTotalLength` / `baInterfaceNr` / terminal ID 链 / ISO 端点属性全部断言一遍；底稿取自已实机跑通的 Cardputer |
| **ISO 端点 sync 字段填成 0** | TinyUSB 的 UAC1 分支把数据端点当成反馈端点，数据永远发不出去 | `check_usb_desc.py` 有专门一条断言；`audio_device.c:908-922` 的判定逻辑写进了注释 |
| 接口号变动（HID 1→4）碰坏已验证功能 | 键盘/触摸回归 | 端点号刻意**不动**（只动接口号），减少变量；Task 6 起每个上板任务的判据都含键盘与触摸 |
| **开机/开流时的爆音（pop）** | 观感上像硬件坏了；而 esp-bsp 自己的顺序就是先开功放后配 codec | Task 2 Step 4b 把顺序定死为「codec 配完 + 解除静音 → 延时 50ms → 才开功放」，`board_power_init()` 只把引脚配好并保持关闭（与背光同构）；判据是 Task 2 Step 1 的三条听感。⚠️ 这是从 esp-bsp 代码顺序**推出**的风险，上游没有已报告的 Tab5 爆音缺陷——若实测没有 pop，也**不要**把顺序改回去，代价是 50ms 开机时间而已 |
| **8 bit / 7 bit I2C 地址混用** | codec 初始化失败，或把寄存器写到别的器件上（I2C 写无反馈） | `tab5_pins.h` 里 `*_ADDR7` 与 `*_ADDR8` 分开定名并注明各自的消费者；Task 2 Step 4 的判据里包含核对 `ES8388_CODEC_DEFAULT_ADDR == 0x20` |
| `esp_codec_dev` 拖进重依赖 | 依赖树被污染，与 spec §8.1「保持依赖树干净」冲突 | 已查证 v1.6.2 的 manifest 只依赖 `idf >= 4.0`；Task 1 Step 5 仍有明确判据（`managed_components/` 里不得出现 LVGL / esp_video / usb_host / m5stack_tab5），不通过就退回按「关键事实」里的寄存器表自己写薄驱动 |
| `esp_codec_dev_open()` 是否会替我们 `i2s_channel_enable` | 重复 enable 报 `ESP_ERR_INVALID_STATE`，或两边都不 enable 导致静默无声 | Task 2 Step 4 已写明预期行为与「若实测相反则补上并记录结论」；判据是听到声音，不是返回值 |
| 音频抢了 GUD 的 CPU / PSRAM 带宽 | 显示掉帧 | Task 9 Step 2 给了按可能性排序的归因清单（优先级 → 欠载超时 → PSRAM），要求写结论而不是碰运气调参 |
| 每帧路径打日志把音频饿死 | 观测干扰被观测，越查越乱 | 欠载/溢出只计数，每 10 秒汇总一条 |
