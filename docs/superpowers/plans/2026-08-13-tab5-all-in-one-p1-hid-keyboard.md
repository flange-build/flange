# Tab5 all-in-one — P1：HID 键盘（Tab5 Keyboard）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外 `. $HOME/esp/esp-idf/export.sh && idf.py build` 编译验证；烧录与实机观察由人工控制者做。

**Goal:** 让 M5Stack Tab5 Keyboard（I2C 从机 `0x6D`）作为 **USB HID 键盘**，与已跑通的 GUD 显示同处一个 USB 复合设备，host 上 `/dev/input/eventN` 收到标准 6KRO 按键事件，在 GUD 显示的 Linux console 里能正常打字。

**Architecture:** 键盘挂在**独立于内部 I2C 的另一条总线**（SDA=G0 / SCL=G1），中断线 G50 低有效。用键盘固件的 **Normal 模式**（寄存器 `0x10` 写 0）读行列事件，固件侧自建「当前按下键集合」状态机生成 6KRO 报告 —— 不用键盘自带的 HID 模式（理由见 §关键事实）。行列→HID usage 映射表从 M5 官方固件 vendor（MIT）。

**Tech Stack:** ESP-IDF v6.0.2、`driver/i2c_master`、`driver/gpio` 中断、esp_tinyusb HID class、TinyUSB `tud_hid_*`；host 侧 mainline `usbhid` + `evtest`。

---

## 范围

本计划只做 **HID 键盘**。触摸屏（GT911）另案 —— 但**描述符从一开始就带 Report ID**，让触摸以 RID 2 追加时是纯增量改动（原因见 §端点预算）。

前置：P0（`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`）已完成，GUD 显示实机验证通过。
设计依据：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` §4。

---

## 关键事实（已核实，不要凭记忆改）

### 硬件

- 键盘是**独立的 STM32F030 I2C 从机**，地址 `0x6D`，挂在 **SDA=G0 / SCL=G1**，
  与内部 I2C（G31/G32，接触摸/codec/IMU/IO 扩展）**物理分离**，必须新建一条 `i2c_master_bus`。
- 中断线 **G50**，**低有效** —— 键盘固件 `user_int.c` 用 `INT_GPIO_Port->BRR = INT_Pin` 拉低表示有事件、
  `BSRR` 拉高表示清除。故 ESP 侧配**上拉 + 下降沿触发**。
- 键盘矩阵 **5 行 × 14 列 = 70 键**。

### 寄存器（取自官方固件 `user_i2c_reg.h`，**不是**照协议图猜的）

| 地址 | 名称 | 说明 |
|---|---|---|
| `0x00` | INTR_CONFIG | bit0 普通模式中断使能 / bit1 HID / bit2 字符，默认 `0x07` |
| `0x01` | INTR_STATUS | 同位布局；**写 0 释放中断信号并清状态** |
| `0x02` | EVENT_NUM | 当前模式队列长度 0~32；**读一次事件自动减 1**；写 0 清空队列并释放中断 |
| `0x03` | RGB_BRIGHTNESS | 0~100，默认 20 |
| `0x10` | KEYBOARD_MODE | **0 = Normal / 1 = HID / 2 = Character**，默认 0 |
| `0x11` | RGB_MODE | 0 绑定 / 1 自定义 |
| `0x20` | KEY_EVENT | Normal 模式事件，**1 字节**：bit7 = 按下(1)/释放(0)，bit[6:4] = 行(0~4)，bit[3:0] = 列(0~13)；**队列空读回 `0xFF`** |
| `0x30` | HID_EVENT | 2 字节（本计划不用） |
| `0x40` / `0x50` | CHAR_EVENT_LENGTH / CHAR_EVENT | 字符模式（本计划不用） |
| `0x60`–`0x67` | RGB_VALUE | RGB1_B/G/R、RGB2_B/G/R |
| `0xFD` | IAP_UPDATE | 固件升级（**别误写**） |
| `0xFE` | FIRMWARE_VERSION | 只读 |
| `0xFF` | I2C_ADDRESS | 读写，改后立即生效并存 Flash（**别误写**） |

> ⚠️ **协议图容易读错**：图里最后一行标 `0xF0`，那是**块基址**，Version/Address 分别在该行的
> E/F 列，即绝对地址 `0xFE` / `0xFF`。直接按 `0xF0` 读会读到别的东西。
> `0xFD` 是固件升级入口，图上没画，**误写会变砖**。

### 为什么不用键盘自带的 HID 模式

读 M5 官方固件 `user_keyboard_handle.c`（MIT）确认，HID 模式（寄存器 `0x30`）有两个硬伤：

1. **修饰键不进队列**：Ctrl / Alt / Sym / Aa 被标记为 `special_key`，只更新内部 `modifier_mask`，
   不产生 HID 事件 ⇒ host 永远看不到「单独按住 Ctrl」；
2. **一次只能表达一个键**：按下推 `{modifier, keycode}`，松开推 `{modifier, 0}`，没有多键并发的表达能力。

对「Linux 终端」这个用途，组合键与按住状态都是刚需。故用 Normal 模式自建状态机。

### 键位表

官方固件的 `key_value_map[5][14]`，元素为
`{name, firstModifierMask, firstKeyCode, name2, secondModifierMask, secondKeyCode}`，
另有 `key_modifier_flag[5][14]` 标记「Sym 层与基础层不同」的键。**MIT 许可**。

四个功能键的位置（官方 `updatemodifier_mask()` 里写死的）：

| 键 | 位置 (row, col) |
|---|---|
| Sym | (3, 0) |
| Aa | (3, 1) |
| Ctrl | (4, 0) |
| Alt | (4, 1) |

> ⚠️ 官方表里 **Sym 与 Aa 的 `firstKeyCode` 都是 `KEY_LEFTSHIFT`**，但它们在本设计里是
> **本地层键、不上报**。原因：物理键盘上标「!」的那个键，其基础层本身就是 `Shift+1`
> （`{"!", KEY_MOD_LSHIFT, KEY_1, ...}`）—— Sym 不是 Shift，而是切到第二层（「!」→「?」）。
> 若把 Sym 当 Shift 上报，符号全错。

### 端点预算（决定描述符形态）

P4 全速控制器：`ep_count = 7`、`ep_in_count = 5`（含 EP0），即**最多 4 条可用 IN 端点**。
后续 UAC(1) + HID + UVC(1) 会用满，所以 **键盘与触摸必须共用同一个 HID 接口**，
用 Report ID 区分（RID 1 键盘 / RID 2 digitizer）。

⇒ **本计划的 HID 报告描述符从一开始就带 Report ID**。多花 1 字节/报告，换来触摸阶段是纯增量改动，
不必回头改键盘的报告格式。

### 已有代码的约定（照做，别另起一套）

- 板级常量在 `main/tab5_pins.h`；I2C 地址与 `IOEXP_ADDR` / `GT911_I2C_ADDR` 并列。
- 内部 I2C 总线由 `board_power.c` 持有，`board_i2c_bus()` 取句柄。**键盘是另一条总线**，
  由 `kbd_i2c.c` 自己持有，不要塞进 `board_power`。
- 模块内错误一律 `ESP_RETURN_ON_ERROR` 返回错误码，`app_main` 顶层 `ESP_ERROR_CHECK`。
- 注释用中文解释「为什么」，标识符英文。

---

## 文件结构

```
firmware/main/
├── kbd_i2c.{c,h}        # 新：键盘 I2C 总线 + INT + 事件队列 + 按下集合状态机 + HID 上报
├── tab5_kbd_map.h       # 新：行列→HID usage 表（vendor 自 M5 官方固件，MIT）
├── usb_descriptors.{c,h}# 改：加 IF1 = HID 接口（RID 1 键盘）
├── tab5_pins.h          # 改：加键盘 I2C/INT 引脚与地址
├── app_main.c           # 改：启动键盘任务
└── CMakeLists.txt       # 改：加 kbd_i2c.c
firmware/sdkconfig.defaults  # 改：CONFIG_TINYUSB_HID_COUNT=1
```

职责边界：`kbd_i2c` 管「从 I2C 拿到当前按下了哪些键、并上报」；`usb_descriptors` 只管描述符数据；
`app_main` 只管编排。**不要**把键位映射逻辑写进 `usb_descriptors.c`。

---

## Task 1：键盘 I2C 总线 + 通信验证（不碰 USB）

目标：确认键盘在 G0/G1 上应答、能读出固件版本、能设成 Normal 模式、**轮询**读到原始行列事件。
先不用中断、不接 USB —— 把「这条独立总线通不通」单独验掉。

**Files:**
- Modify: `firmware/main/tab5_pins.h`
- Create: `firmware/main/kbd_i2c.c` / `kbd_i2c.h`
- Modify: `firmware/main/CMakeLists.txt`、`firmware/main/app_main.c`

- [ ] **Step 1：成功判据**

UART 日志见 `kbd: fw=0x.. addr=0x6d mode=normal`，按下任意键后见
`kbd: raw press row=.. col=..` / `raw release row=.. col=..`，行列值与实际按键位置对得上
（例如左上角 `esc` 应为 row=0 col=0）。GUD 显示不受影响（屏幕仍显示 Linux console）。

- [ ] **Step 2：`tab5_pins.h` 加键盘常量**

在 `GT911_I2C_ADDR` 那组之后追加：

```c
/* Tab5 Keyboard：独立的 STM32F030 I2C 从机，挂在与内部 I2C 分离的另一条总线上。
 * INT 低有效（键盘固件拉低表示有事件），故 ESP 侧上拉 + 下降沿触发。 */
#define PIN_KBD_SDA        0
#define PIN_KBD_SCL        1
#define PIN_KBD_INT        50
#define KBD_I2C_ADDR       0x6D
```

- [ ] **Step 3：写 `firmware/main/kbd_i2c.h`**

```c
#pragma once
#include "esp_err.h"

/* 初始化键盘 I2C 总线(G0/G1)、探测 0x6D、设为 Normal 模式，并启动读取任务。
 * 须在 TinyUSB 安装之后调用（上报依赖 tud_hid_ready()）。 */
esp_err_t kbd_start(void);
```

- [ ] **Step 4：写 `firmware/main/kbd_i2c.c`（本任务只到「打印原始事件」）**

```c
/*
 * M5Stack Tab5 Keyboard（I2C 从机 0x6D）→ USB HID 键盘。
 *
 * 键盘挂在与内部 I2C（G31/G32）物理分离的另一条总线（G0/G1）上，故本文件
 * 自己持有一条 i2c_master_bus，不复用 board_power 的那条。
 *
 * 用固件的 Normal 模式（寄存器 0x10 写 0）读行列事件，自建按下集合状态机；
 * 不用键盘自带的 HID 模式 —— 它的修饰键不进队列、且一次只能表达一个键。
 */
#include "kbd_i2c.h"
#include "tab5_pins.h"
#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "kbd";

/* 寄存器地址取自官方固件 user_i2c_reg.h。注意 0xFE/0xFF 是绝对地址——
 * 协议图最后一行标的 0xF0 是块基址，Version/Address 在该行 E/F 列。
 * 0xFD 是固件升级入口，误写会变砖，本文件永不触碰。 */
#define REG_INTR_CONFIG    0x00
#define REG_INTR_STATUS    0x01
#define REG_EVENT_NUM      0x02
#define REG_KEYBOARD_MODE  0x10
#define REG_KEY_EVENT      0x20
#define REG_FW_VERSION     0xFE

#define KBD_MODE_NORMAL    0

/* Normal 模式事件：bit7 按下(1)/释放(0)，bit[6:4] 行，bit[3:0] 列；队列空读回 0xFF */
#define KEY_EVENT_EMPTY    0xFF

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;

static esp_err_t kbd_read_reg(uint8_t reg, uint8_t *out, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, out, len, 100);
}

static esp_err_t kbd_write_reg(uint8_t reg, uint8_t val)
{
    const uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

static void kbd_task(void *arg)
{
    (void)arg;
    while (1) {
        uint8_t n = 0;
        if (kbd_read_reg(REG_EVENT_NUM, &n, 1) == ESP_OK && n > 0) {
            for (uint8_t i = 0; i < n; i++) {
                uint8_t ev = KEY_EVENT_EMPTY;
                if (kbd_read_reg(REG_KEY_EVENT, &ev, 1) != ESP_OK || ev == KEY_EVENT_EMPTY)
                    break;
                ESP_LOGI(TAG, "raw %s row=%u col=%u",
                         (ev & 0x80) ? "press" : "release",
                         (unsigned)((ev >> 4) & 0x07), (unsigned)(ev & 0x0F));
            }
        }
        vTaskDelay(pdMS_TO_TICKS(15));
    }
}

esp_err_t kbd_start(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_1,          /* I2C_NUM_0 已被 board_power 的内部总线占用 */
        .sda_io_num = PIN_KBD_SDA,
        .scl_io_num = PIN_KBD_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &s_bus), TAG, "kbd i2c bus");

    ESP_RETURN_ON_ERROR(i2c_master_probe(s_bus, KBD_I2C_ADDR, 100), TAG,
                        "键盘未应答(0x%02x)，检查排线与 G0/G1", KBD_I2C_ADDR);

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = KBD_I2C_ADDR,
        .scl_speed_hz = 100000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev), TAG, "kbd i2c dev");

    uint8_t fw = 0;
    ESP_RETURN_ON_ERROR(kbd_read_reg(REG_FW_VERSION, &fw, 1), TAG, "读固件版本失败");
    ESP_RETURN_ON_ERROR(kbd_write_reg(REG_KEYBOARD_MODE, KBD_MODE_NORMAL), TAG, "设 Normal 模式失败");

    ESP_LOGI(TAG, "fw=0x%02x addr=0x%02x mode=normal", fw, KBD_I2C_ADDR);
    xTaskCreate(kbd_task, "kbd", 4096, NULL, 5, NULL);
    return ESP_OK;
}
```

- [ ] **Step 5：`CMakeLists.txt` 加 `kbd_i2c.c`**

SRCS 追加 `"kbd_i2c.c"`。`PRIV_REQUIRES` 已有 `esp_driver_i2c`，无需改。

- [ ] **Step 6：`app_main.c` 在 TinyUSB 安装之后启动键盘**

```c
    ESP_ERROR_CHECK(kbd_start());
```
加 `#include "kbd_i2c.h"`。放在 `tinyusb_driver_install()` **之后**（后续任务的上报依赖 `tud_hid_ready()`）。

- [ ] **Step 7：编译**

```bash
. $HOME/esp/esp-idf/export.sh
cd /Volumes/bsp/flange/components/packages/tab5-all-in-one/firmware
idf.py build
```
Expected: `Project build complete.`

- [ ] **Step 8：上板验证（人工控制者执行）**

烧录后按几个已知位置的键，核对行列值。典型失败：

| 现象 | 处置 |
|---|---|
| `键盘未应答(0x6d)` | 确认键盘底座插好；用 `i2c_master_probe` 扫 G0/G1 整条总线看有无任何设备 |
| 有应答但 `fw=0x00`/`0xFF` | 读时序问题，确认是 `transmit_receive` 而非分开的 write+read |
| 行列值与按键位置对不上 | 不是 bug —— 官方表的行列原点见 `tab5_kbd_map.h`，Task 3 映射时对齐即可 |

- [ ] **Step 9：提交**

```bash
git add components/packages/tab5-all-in-one
git commit -m "feat(tab5-fw): 键盘 I2C 总线与 Normal 模式通信验证 (P1 Task1)"
```

---

## Task 2：改中断驱动 + 一次排空队列

目标：去掉 15ms 轮询，改由 G50 下降沿唤醒读取，一次中断内按 `EVENT_NUM` 排空队列。

**Files:** Modify `firmware/main/kbd_i2c.c`

- [ ] **Step 1：成功判据**

按键响应与 Task 1 一致（行列日志正确），但 UART 上不再有空转；快速连打多个键不丢事件。

- [ ] **Step 2：加 GPIO 中断与任务通知**

`kbd_i2c.c` 里加：

```c
#include "driver/gpio.h"

static TaskHandle_t s_kbd_task;

/* INT 低有效：键盘固件拉低表示队列非空。用下降沿唤醒读取任务，
 * ISR 里只做任务通知，I2C 读取放任务上下文（I2C 不能在 ISR 里做）。 */
static void IRAM_ATTR kbd_int_isr(void *arg)
{
    (void)arg;
    BaseType_t hp = pdFALSE;
    vTaskNotifyGiveFromISR(s_kbd_task, &hp);
    portYIELD_FROM_ISR(hp);
}
```

`kbd_start()` 里在建任务**之后**配置中断（ISR 要用到 `s_kbd_task`）：

```c
    xTaskCreate(kbd_task, "kbd", 4096, NULL, 5, &s_kbd_task);

    gpio_config_t int_cfg = {
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = 1ULL << PIN_KBD_INT,
        .pull_up_en = GPIO_PULLUP_ENABLE,   /* INT 低有效，常态由上拉保持高 */
        .intr_type = GPIO_INTR_NEGEDGE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&int_cfg), TAG, "kbd int gpio");
    ESP_RETURN_ON_ERROR(gpio_install_isr_service(0), TAG, "isr service");
    ESP_RETURN_ON_ERROR(gpio_isr_handler_add(PIN_KBD_INT, kbd_int_isr, NULL), TAG, "isr add");
```

> `gpio_install_isr_service()` 若已被别处安装会返回 `ESP_ERR_INVALID_STATE`。当前工程无人安装，
> 直接 `ESP_RETURN_ON_ERROR` 即可；若将来触摸阶段也要装，届时改为容忍该错误码。

- [ ] **Step 3：任务改为等通知 + 排空**

把 `kbd_task` 的 `vTaskDelay` 轮询换成：

```c
    while (1) {
        /* 等 INT。超时兜底 100ms：万一中断丢失（例如上电时队列已非空、
         * INT 早于我们配置好中断就拉低了），也能自愈而不是永久卡死。 */
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100));

        uint8_t n = 0;
        if (kbd_read_reg(REG_EVENT_NUM, &n, 1) != ESP_OK)
            continue;
        for (uint8_t i = 0; i < n; i++) {
            uint8_t ev = KEY_EVENT_EMPTY;
            if (kbd_read_reg(REG_KEY_EVENT, &ev, 1) != ESP_OK || ev == KEY_EVENT_EMPTY)
                break;
            ESP_LOGI(TAG, "raw %s row=%u col=%u", ...);   /* 同 Task 1 */
        }
    }
```

> **为什么保留 100ms 超时兜底**：INT 是电平语义（队列非空即低），如果我们在它已经拉低之后
> 才配置下降沿中断，就永远等不到边沿。超时轮询让这种竞态自愈。代价是空闲时每秒 10 次
> 一字节 I2C 读，可忽略。

- [ ] **Step 4：编译**（同 Task 1 Step 7）

- [ ] **Step 5：提交**

```bash
git commit -m "feat(tab5-fw): 键盘改 G50 中断驱动，一次排空事件队列 (P1 Task2)"
```

---

## Task 3：vendor 键位表 + 按下集合状态机（仍不上报）

目标：把行列事件翻译成标准 HID 报告的内容（modifier + 最多 6 个 keycode），先打日志，不发 USB。

**Files:** Create `firmware/main/tab5_kbd_map.h`；Modify `firmware/main/kbd_i2c.c`

- [ ] **Step 1：成功判据**

日志形如 `kbd: report mod=0x01 keys=04 00 00 00 00 00`（按住 Ctrl+A）。
按住 Sym 再按数字键，keycode 切到第二层；Ctrl/Alt 只进 modifier 不占 keycode 槽。

- [ ] **Step 2：vendor 官方键位表**

**不要手工誊写**（几百个条目，照抄必错）。从 M5 官方固件仓库机械提取：

```bash
B=https://raw.githubusercontent.com/m5stack/M5Tab5-Keyboard-Internal-FW/main/code/Keyboard_APP/Core/User
curl -sS "$B/keyboard/user_keyboard_handle.c" -o /tmp/kh.c
curl -sS "$B/keyboard/user_hid_map.h"         -o /tmp/khid.h
```

新建 `main/tab5_kbd_map.h`，内容为：

- 文件头写明来源（`m5stack/M5Tab5-Keyboard-Internal-FW`，`Core/User/keyboard/`）与 **MIT** 许可，保留 SPDX 版权行；
- 从 `user_hid_map.h` 提取 `KeModifierMask_t` 与 `KeScanCode_t` 两个枚举（HID 修饰位掩码与 usage 码）；
- 从 `user_keyboard_handle.c` 提取 `key_value_map[5][14]` 与 `key_modifier_flag[5][14]`，
  以及它们依赖的 `key_value_t` 结构体定义（在 `user_keyboard_handle.h`，一并取）；
- **数组内容一字节不改**，提完自己 diff / MD5 核对；
- 注明四个功能键位置：Sym(3,0)、Aa(3,1)、Ctrl(4,0)、Alt(4,1)。

- [ ] **Step 3：状态机 —— 维护按下集合**

`kbd_i2c.c` 里加：

```c
#include "tab5_kbd_map.h"

#define KBD_ROWS 5
#define KBD_COLS 14

/* 当前按下的键（行列位图）。Normal 模式给的是按下/释放边沿事件，
 * 而 HID 报告要的是「此刻按着哪些键」的全量快照，所以必须自己维护集合。 */
static bool s_pressed[KBD_ROWS][KBD_COLS];

/* 四个功能键的位置，取自官方固件 updatemodifier_mask() */
#define IS_SYM(r, c)   ((r) == 3 && (c) == 0)
#define IS_AA(r, c)    ((r) == 3 && (c) == 1)
```

事件处理改为更新 `s_pressed[row][col]`，然后调用下面的报告生成。

- [ ] **Step 4：生成 6KRO 报告**

```c
/*
 * 把当前按下集合翻译成标准 HID 键盘报告。
 *
 * 分层规则（与官方固件语义一致）：
 *   - Sym(3,0) / Aa(3,1)：**本地层键，不上报**。官方表里它们的 firstKeyCode 是
 *     KEY_LEFTSHIFT，但物理键盘上标「!」的键其基础层本身就是 Shift+1 ——
 *     Sym 不是 Shift，而是切到第二层。当 Shift 上报会让符号全错。
 *   - Ctrl(4,0) / Alt(4,1)：查表得到的 usage 落在 0xE0~0xE7（HID 修饰键区间），
 *     由下面的通用规则自动归入 modifier 字节，不占 keycode 槽。
 *   - 其余键：Sym 按住且 key_modifier_flag 置位 → 用 second 层；否则用 first 层。
 *     Aa 生效时字母键用 second 层（即大写 = Shift+字母）。
 */
static void kbd_build_and_report(void)
{
    bool sym = s_pressed[3][0];
    bool aa  = s_pressed[3][1];

    uint8_t modifier = 0;
    uint8_t keys[6] = {0};
    int nk = 0;

    for (int r = 0; r < KBD_ROWS; r++) {
        for (int c = 0; c < KBD_COLS; c++) {
            if (!s_pressed[r][c]) continue;
            if (IS_SYM(r, c) || IS_AA(r, c)) continue;   /* 本地层键，不上报 */

            const key_value_t *k = &key_value_map[r][c];
            bool use_second = (sym && key_modifier_flag[r][c]);
            if (aa && k->firstKeyCode >= KEY_A && k->firstKeyCode <= KEY_Z)
                use_second = true;

            uint8_t mod  = use_second ? k->secondModifierMask : k->firstModifierMask;
            uint8_t code = use_second ? k->secondKeyCode      : k->firstKeyCode;

            modifier |= mod;
            /* 0xE0~0xE7 是 HID 修饰键 usage：转成 modifier 位，不占 keycode 槽 */
            if (code >= 0xE0 && code <= 0xE7) {
                modifier |= (uint8_t)(1u << (code - 0xE0));
            } else if (code != 0 && nk < 6) {
                keys[nk++] = code;
            }
        }
    }

    ESP_LOGI(TAG, "report mod=0x%02x keys=%02x %02x %02x %02x %02x %02x",
             modifier, keys[0], keys[1], keys[2], keys[3], keys[4], keys[5]);
    /* Task 4 在此接 tud_hid_keyboard_report() */
}
```

- [ ] **Step 5：编译 + 提交**

```bash
git commit -m "feat(tab5-fw): vendor 官方键位表 + 按下集合状态机 (P1 Task3)"
```

---

## Task 4：加 HID 接口到 USB 描述符 + 真正上报

目标：host 出 `/dev/input/eventN`，`evtest` 能看到按键。

**Files:** Modify `firmware/sdkconfig.defaults`、`firmware/main/usb_descriptors.{c,h}`、`firmware/main/kbd_i2c.c`

- [ ] **Step 1：成功判据**

```bash
lsusb -v -d 16d0:10a9 | grep -A5 HID      # 见 HID(keyboard) 接口
cat /proc/bus/input/devices | grep -B1 -A5 -i "16d0\|Tab5"
sudo evtest /dev/input/eventN             # 打字见 KEY_* 事件
```
且 **GUD 显示不回归**（Linux console 仍正常显示）。

- [ ] **Step 2：`sdkconfig.defaults` 开 HID**

```
# TinyUSB HID 接口：>0 即开启 CFG_TUD_HID
CONFIG_TINYUSB_HID_COUNT=1
```

- [ ] **Step 3：`usb_descriptors.h` 加接口与端点**

```c
enum { ITF_NUM_VENDOR = 0, ITF_NUM_HID, ITF_NUM_TOTAL };

#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82

/* HID Report ID。触摸阶段追加 RID 2 = digitizer，共用本接口与端点
 * （P4 全速控制器最多 4 条 IN 端点，UAC/UVC 会用满，见 firmware/README.md）。 */
#define HID_RID_KEYBOARD 1
```

- [ ] **Step 4：`usb_descriptors.c` 加 HID 描述符**

```c
/* 标准键盘，带 Report ID —— 触摸阶段以 RID 2 追加时是纯增量改动。 */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(HID_RID_KEYBOARD))
};

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(aio_hid_report_desc), EPNUM_HID,
                       CFG_TUD_HID_EP_BUFSIZE, 10),
};
```

并补三个 HID 弱回调（esp_tinyusb 不实现它们）：

```c
uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return aio_hid_report_desc;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}
```

- [ ] **Step 5：`kbd_i2c.c` 接上真实上报**

把 Task 3 的日志行换成（日志降为 `ESP_LOGD`，否则每次按键都刷串口）：

```c
    if (tud_hid_ready())
        tud_hid_keyboard_report(HID_RID_KEYBOARD, modifier, nk ? keys : NULL);
```
加 `#include "tusb.h"` 与 `#include "usb_descriptors.h"`。

- [ ] **Step 6：编译**

⚠️ 注意看 `_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN)` 有没有炸 ——
加接口最容易在这里出错。

- [ ] **Step 7：上板验证（人工控制者执行）**

按 Step 1 逐条核对。典型失败：

| 现象 | 处置 |
|---|---|
| 设备不再枚举（连 GUD 都没了） | 端点冲突或描述符长度错。先看 `_Static_assert`；再确认 `EPNUM_HID = 0x82` 未与 vendor 的 `0x81` 撞 |
| 有 HID 设备但无按键事件 | 看 UART 的 `report mod=.. keys=..` 是否在动；若在动则是描述符/Report ID 问题 |
| 按键字符不对 | 分层规则问题，看 Task 3 的 Sym/Aa 判定 |

- [ ] **Step 8：提交**

```bash
git commit -m "feat(tab5-fw): HID 接口进复合描述符，键盘真实上报 (P1 Task4)"
```

---

## Task 5：文档与收尾

**Files:** Modify `firmware/README.md`、`README.md`、spec

- [ ] **Step 1：`firmware/README.md` 加键盘章节**

覆盖：独立 I2C 总线（G0/G1，与内部 I2C 分离）、INT 低有效、寄存器表（含 **0xFE/0xFF 不是 0xF0** 与 **0xFD 别碰** 两个坑）、
为什么不用键盘自带 HID 模式、Sym/Aa 为什么不当 Shift 上报、Report ID 布局与端点预算、`evtest` 验证方法。

- [ ] **Step 2：包级 `README.md` 状态清单**：HID 键盘从 ⏳ 规划中 移到 ✅（如实机通过）。

- [ ] **Step 3：spec §4 回填实测结论**（键盘固件版本号、实际行列原点、Aa 语义的实机手感）。

- [ ] **Step 4：提交**

```bash
git commit -m "docs(tab5): HID 键盘章节与状态更新 (P1 Task5)"
```

---

## 待拍板的设计选择（实机手感决定，不阻塞实施）

**Aa 键的语义**。官方固件做的是「单击 = 一次性大写、双击 = 大写锁定」的手机键盘语义。
本计划先实现最简单可预测的版本：**按住 Aa 期间字母走第二层（大写）**，即当作瞬时上档键。

理由：小键盘上「按住两键」比「记住当前是否处于锁定态」更不易出错，且无状态、不会出现
「以为没锁其实锁了」的困惑。**上板试过手感后若觉得别扭，改成一次性/锁定语义是局部改动**
（只动 `kbd_build_and_report()` 里 `aa` 的取值来源）。
