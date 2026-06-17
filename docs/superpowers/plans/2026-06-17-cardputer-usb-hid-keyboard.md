# Cardputer USB 一线通 — HID 键盘 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外 `get_idf_551 && idf.py build` 编译验证；烧录(G0 下载模式)/`evtest` 验证由人工控制者做。

**Goal:** 让 Cardputer 自带矩阵键盘作为 **USB HID 键盘**，与已打通的 GUD 显示同处一个 USB 复合设备，host 上 `/dev/input/eventN` 能收到按键、文本编辑器里打字正常。

**Architecture:** 在现有 `esp_tinyusb`（1.7.6，原生支持 HID，**无需迁 USB 栈**）+ 注入描述符框架上，给复合设备加一个 HID 接口（中断 IN 端点）。固件扫描 74HC138 矩阵键盘 → 映射到 HID usage code → `tud_hid_keyboard_report`。

**Tech Stack:** ESP-IDF 5.5.1、esp_tinyusb HID、TinyUSB `tud_hid_*`；host 侧 mainline `usbhid` + `evtest`。

---

## 范围

本计划只做 **HID 键盘**（设计 spec 的 P2，应用户要求提到音频之前做）。音频(UAC)另案——它需要迁底层 tinyusb + 处理 GPIO43 三重冲突 + 半双工，与本计划无关。

## 关键事实（grounding）

- **esp_tinyusb 支持 HID**：Kconfig 有 `CONFIG_TINYUSB_HID_COUNT`（置 1 即开 `CFG_TUD_HID=1`）。所以沿用 P0 的 esp_tinyusb + `tinyusb_config_t` 注入描述符方式，**只加 HID 接口**，不动 USB 栈。
- **引脚无冲突**：键盘矩阵走 74HC138（列选 + 行读，确切引脚见 M5Cardputer 库），与显示 SPI(33-38)、native USB(19/20)、控制台 UART0(43/44) 均不重叠。
- **键盘扫描权威源**：M5Cardputer Arduino 库 `Keyboard.h/.cpp`（`github.com/m5stack/M5Cardputer`）含确切的列选引脚(典型 `{8,9,11}`→74HC138 A0/A1/A2)、行读引脚(典型 `{13,15,3,4,5,6,7}`)、以及 (x,y)→键值映射表(含 Fn/shift 层)。实现时以该库为准，不要凭记忆杜撰引脚/键值。
- 当前复合描述符：IF0=Vendor(GUD)，端点 bulk OUT 0x01 / IN 0x81。HID 加为 IF1，中断 IN 端点 0x82。

## 文件结构

```
firmware/main/
├── usb_descriptors.{c,h}   # 改：加 HID 接口 + HID report 描述符 + ITF/EP 枚举
├── hid_keyboard.{c,h}      # 新：74HC138 矩阵扫描 + 键值映射 + 上报
├── app_main.c              # 改：启动键盘扫描任务
└── CMakeLists.txt          # 改：加 hid_keyboard.c
firmware/sdkconfig.defaults # 改：CONFIG_TINYUSB_HID_COUNT=1
```

职责：usb_descriptors=描述符；hid_keyboard=扫描+映射+上报；app_main=编排。不要把键盘逻辑写进 gud_device/display。

---

## Task 1：复合设备加 HID 接口 + 最小测试上报

目标：HID 接口枚举成功，host 收到按键事件（先发一个固定键证明通路），GUD 显示不回归。

**Files:** 改 `sdkconfig.defaults`、`main/usb_descriptors.{c,h}`、`main/app_main.c`、`main/CMakeLists.txt`；新建 `main/hid_keyboard.{c,h}`（本任务仅放最小测试上报）。

- [ ] **Step 1：定义成功判据**

烧录后 host：`lsusb -v -d 16d0:10a9` 见新增 HID(keyboard) 接口；`sudo dmesg | grep -i input` 见 `input: ... Keyboard`；`/dev/input/eventN` 出现；最小测试（开机后定时发一次字母 'a'）能在 `sudo evtest <event>` 看到 KEY_A 事件。GUD 显示仍正常（`modetest -M gud` 仍列出 card）。

- [ ] **Step 2：sdkconfig.defaults 开 HID**

追加：
```
CONFIG_TINYUSB_HID_COUNT=1
```

- [ ] **Step 3：usb_descriptors.h 加 HID 枚举**

把接口/端点枚举改为：
```c
enum { ITF_NUM_VENDOR = 0, ITF_NUM_HID, ITF_NUM_TOTAL };
enum { EPNUM_VENDOR_OUT = 0x01, EPNUM_VENDOR_IN = 0x81, EPNUM_HID = 0x82 };
```

- [ ] **Step 4：usb_descriptors.c 加 HID report 描述符 + 配置描述符项 + 回调**

```c
/* HID report 描述符：标准键盘 */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD()
};

/* tinyusb 弱回调：返回 HID report 描述符 */
uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance) {
    (void)instance; return aio_hid_report_desc;
}
/* GET_REPORT：无需主动返回，置 0 */
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
        hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen) {
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;
}
/* SET_REPORT：host 设 LED 等，忽略 */
void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
        hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize) {
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}
```
配置描述符 `desc_configuration[]`：在 vendor 项后加 HID 项，并更新总长与接口数：
```c
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN)
...
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(aio_hid_report_desc), EPNUM_HID,
                       CFG_TUD_HID_EP_BUFSIZE, 10),
```
`TUD_CONFIG_DESCRIPTOR` 的接口数参数用 `ITF_NUM_TOTAL`。
> **决策点（用 Opus 处理）**：核实 esp_tinyusb 1.7.6 是否要求/允许自实现 `tud_hid_descriptor_report_cb`（类比 Task2 发现描述符 cb 由组件实现）。若 esp_tinyusb 提供了 HID report 描述符的注入接口而禁止自实现该弱回调（重复符号），改用其接口；否则自实现。以能编译 + host 正确取到 report 描述符为准，在汇报里说明走法。

- [ ] **Step 5：hid_keyboard.{c,h} 最小测试上报**

`hid_keyboard.h`：
```c
#pragma once
void hid_keyboard_start(void);   /* 起扫描/上报任务 */
```
`hid_keyboard.c`（本任务最小版：开机延时后发一次 'a' 再松开，证明通路）：
```c
#include "hid_keyboard.h"
#include "usb_descriptors.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"
#include "class/hid/hid_device.h"

static void kbd_task(void *arg) {
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(3000));            /* 等枚举 */
    if (tud_hid_ready()) {
        uint8_t keys[6] = { HID_KEY_A, 0,0,0,0,0 };
        tud_hid_keyboard_report(0, 0, keys);    /* 按下 a */
        vTaskDelay(pdMS_TO_TICKS(50));
        tud_hid_keyboard_report(0, 0, NULL);    /* 松开 */
    }
    vTaskDelete(NULL);
}
void hid_keyboard_start(void) {
    xTaskCreate(kbd_task, "kbd", 3072, NULL, 4, NULL);
}
```

- [ ] **Step 6：app_main.c 启动 + CMakeLists.txt 加文件**

app_main 在 TinyUSB 安装后调 `hid_keyboard_start();`。CMakeLists SRCS 加 `hid_keyboard.c`。

- [ ] **Step 7：编译**

`get_idf_551 && idf.py build`，必须通过。不烧录（人工做）。

- [ ] **Step 8：提交**

```bash
git add components/packages/cardputer-all-in-one/firmware
git commit -m "feat(cardputer-fw): 复合设备加 HID 接口 + 最小测试上报 (HID Task1)"
```

---

## Task 2：74HC138 矩阵键盘扫描

目标：固件能扫出当前按下的键位 (row,col)，UART0 日志打印按下/松开的键位坐标。

**Files:** 改 `main/hid_keyboard.c`（替换最小测试为真实扫描）、新建 `main/cardputer_kbd_map.h`（引脚 + 键位常量，源自 M5Cardputer 库）。

- [ ] **Step 1：定义成功判据**

接 UART0(G43/G44 @115200) 看日志：按不同键打印不同 (row,col)，松开打印释放；无串口适配器则此任务并入 Task3 一起用 host `evtest` 验。

- [ ] **Step 2：从 M5Cardputer 库取引脚与扫描法**

WebFetch 或参考 `github.com/m5stack/M5Cardputer` 的 `src/utility/Keyboard.h/.cpp`：取列选引脚(到 74HC138 的 3 条 select)、行读引脚、扫描时序（设 select → 读行）。写入 `cardputer_kbd_map.h`。**以库为准**。

- [ ] **Step 3：实现扫描**

按 74HC138：遍历 8 个列选值(3 bit) → 读 7 行 → 得到按下矩阵。去抖（连续 2 次一致才算）。维护"当前按下键位集合"。变化时 `ESP_LOGI` 打印 (col,row)。

- [ ] **Step 4：编译 + 提交**

`get_idf_551 && idf.py build`；commit `feat(cardputer-fw): 74HC138 矩阵键盘扫描 (HID Task2)`。

---

## Task 3：键位 → HID usage 映射 + 真实上报

目标：在 Cardputer 上打字，host 文本框/`evtest` 出正确字符，含 Shift/Fn/Ctrl/Alt/Opt 修饰。

**Files:** 改 `main/hid_keyboard.c`、`main/cardputer_kbd_map.h`（加键值表）。

- [ ] **Step 1：定义成功判据**

host `evtest` 或文本编辑器：按 Cardputer 字母/数字/符号→对应字符；Shift+字母→大写；回车/空格/退格/方向键(若有)→对应键；Fn 层（若库有定义）→对应符号。无幽灵键、无粘键。

- [ ] **Step 2：从 M5Cardputer 库取键值表**

参考库的 (x,y)→keyValue 表（含 main/shift/fn 层）。把每个物理键位映射到 **HID usage code**（`HID_KEY_*`）+ 修饰位。注意：HID 上报的是 usage code 不是 ASCII，需把库的字符映射转成 usage（建立 char/功能→HID_KEY_* 的对照）。修饰键（shift/ctrl/alt/opt/fn）单独处理：shift/ctrl/alt → HID modifier 位；Fn/Opt → 选择键值层。

- [ ] **Step 3：实现上报**

扫描得到按下键位集合 → 分离修饰键与普通键 → 普通键映射成 usage（最多 6 个，6KRO）+ 修饰字节 → 仅在与上次上报不同时 `tud_hid_keyboard_report(0, modifier, keycodes)`。松开全部时发空报告。

- [ ] **Step 4：编译 + 提交**

`get_idf_551 && idf.py build`；commit `feat(cardputer-fw): 键位→HID usage 映射 + 真实键盘上报 (HID Task3)`。

---

## Task 4：收尾 — README + tag

- [ ] 更新 `firmware/README.md`：能力加"USB HID 键盘"，描述符布局更新(IF0 GUD / IF1 HID)，验证命令(`evtest`)。
- [ ] 更新组件 `README.md` 状态：HID 键盘 ✅。
- [ ] commit `docs(cardputer): HID 键盘 README`；`git tag cardputer-hid-keyboard`。

---

## 完成判据（DoD）

- [ ] 一根 USB 线，Cardputer 既是 GUD 显示器又是 USB 键盘，host `/dev/input/eventN` 收按键、打字正确。
- [ ] GUD 显示不回归（显示 + 键盘同一复合设备共存）。
- [ ] 全程命令可复现，README 记录。

## 自检（against 设计 spec §3.1 / §4）

- §3.1 HID 接口 int IN：Task1 `TUD_HID_DESCRIPTOR` + EP 0x82 ✓
- §4 hid_keyboard 模块(扫描+Fn 层映射)：Task2/3 ✓
- 与 GUD 复合共存：Task1 成功判据含 GUD 不回归 + Task 各步保留 vendor 接口 ✓
- 无 over-build：不碰音频/不迁 USB 栈 ✓
