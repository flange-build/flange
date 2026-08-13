# Tab5 all-in-one — P2：HID 触摸屏（GT911）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外 `. $HOME/esp/esp-idf/export.sh && idf.py build` 编译验证；烧录与实机标定由人工控制者做。

**Goal:** 让 Tab5 的电容触摸屏作为 **USB HID digitizer（绝对坐标）**上报，与已跑通的 GUD 显示、HID 键盘同处一个 USB 复合设备。host 侧走 mainline `hid-multitouch` / `usbhid`，在 GUD 显示的画面上点哪儿、指针就落哪儿。

**Architecture:** GT911 挂在**内部 I2C**（G31/G32，与 `board_power` 共用总线）、INT = G23。用 `espressif/esp_lcd_touch_gt911` 读原始坐标，做与显示**相同的 90° 变换**还原成 host 看到的横向坐标系，再以 **Report ID 2** 从已有的 HID 接口上报 —— 复用键盘那条中断 IN 端点，不新增端点。

**Tech Stack:** ESP-IDF v6.0.2、`espressif/esp_lcd_touch_gt911`、`esp_lcd_new_panel_io_i2c`、TinyUSB HID；host 侧 `hid-multitouch` + `evtest`。

---

## 范围

只做触摸。前置：P0（显示）与 P1（键盘）均已实机验证通过。
设计依据：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` §5。

---

## 关键事实（已核实，不要凭记忆改）

### 硬件与组件

- 触摸控制器随面板批次为 **GT911(0x14)** 或 **ST7123(0x55)**；**开发用机是 ILI9881C 批次，触摸是 GT911**（实机 i2cscan 见 `0x14`、无 `0x55`）。
- GT911 在**内部 I2C**（SDA=G31 / SCL=G32）上，与 IO 扩展/codec/IMU 共用 —— 直接用 `board_i2c_bus()`，**不要新建总线**（键盘那条 G0/G1 是另一回事）。
- 中断 **INT = G23**。触摸使能在 IO 扩展 `PI4IOE5V6408-1(0x43)` 的 `IO_EXPANDER_PIN_NUM_5`，
  `board_power_init()` 已经拉高，**不用再动**。

> ⚠️ **GT911 的默认 I2C 地址是 `0x5D`，`0x14` 是备用地址** —— 而 Tab5 用的正是 `0x14`。
> 组件的 `ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG()` 宏默认填 `0x5D`，且
> `esp_lcd_touch_gt911.c:128-134` 只校验传入值合法、**不会自动探测**。
> 必须显式传 `ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP`（= `0x14`），否则探不到。

组件：`espressif/esp_lcd_touch_gt911` 1.2.1（依赖 idf ≥5.2）+ 它带的 `esp_lcd_touch`。

### 坐标变换（本计划的核心）

显示链路是 **640×360 横向 → PPA 2× 放大 + 90° CCW 旋转 → 720×1280 竖向面板**。
触摸控制器按**面板原生朝向**出坐标，而 host 画的是横向内容 —— 两者必须落到同一可视坐标系，否则点哪儿指针跑到别处。

`DISPLAY_ROT_CCW90 = 1`（已实机标定）下，显示的逐像素映射是：

```
GUD gy ↦ panel x ∈ [2·gy, 2·gy+2)
GUD gx ↦ panel y ∈ [1280−2·gx−2, 1280−2·gx)
```

**反解**（触摸给 panel 坐标 → 还原 GUD 坐标）：

```
gud_x = (PANEL_H − 1 − panel_y) / 2        /* 0..639 */
gud_y = panel_x / 2                        /* 0..359 */
```

边界自检：`gud(0,0)` ↔ `panel(0,1279)`；`gud(639,359)` ↔ `panel(718,0)`。两端都对得上。

> ⚠️ **前提是 GT911 确实按 720×1280 面板原生朝向出数**。这一点**必须实机标定**（Task 2）——
> `esp_lcd_touch_config_t` 有 `x_max` / `y_max` 与 `swap_xy` / `mirror_x` / `mirror_y` 三个 flag，
> 触摸模组的贴装方向不一定与面板扫描方向一致。**先打印原始坐标看四角，再决定这三个 flag**，
> 不要一上来就套上面的公式。

### USB 侧

- **不新增端点**：以 **Report ID 2** 复用键盘的 HID 接口（IF1，端点 `0x82`）。
  P4 全速控制器最多 4 条可用 IN 端点，UAC/UVC 还要用，这是 spec §2 定死的布局。
- 键盘的报告描述符已经带 `HID_RID_KEYBOARD = 1`，本计划追加 `HID_RID_TOUCH = 2` 是**纯增量**。
- ⚠️ 现有 `TUD_HID_DESCRIPTOR` 传的是 `HID_ITF_PROTOCOL_KEYBOARD`（把 `bInterfaceSubClass` 设为 BOOT）。
  加了 digitizer 之后这个接口不再只是键盘 —— **评估是否改为 `HID_ITF_PROTOCOL_NONE`**。
  boot 协议本来就不允许 Report ID，改成 NONE 反而更自洽；代价是 BIOS/UEFI 阶段不再能当 boot 键盘用
  （本用途不涉及）。**这是 Task 3 要拍板的一个决定，见该任务。**

---

## 文件结构

```
firmware/main/
├── touch_hid.{c,h}      # 新：GT911 初始化 + 坐标变换 + digitizer 上报
├── usb_descriptors.{c,h}# 改：报告描述符追加 RID 2 digitizer
├── tab5_pins.h          # 改：加 PIN_TOUCH_INT / GT911 地址
├── app_main.c           # 改：启动触摸
└── CMakeLists.txt       # 改：加 touch_hid.c
firmware/test/
└── test_touch_map.c     # 新：坐标变换的宿主机回归测试
```

**坐标变换要抽成零依赖纯函数**（照 `kbd_translate.c` 的做法），让 `test/` 能直接编译真实源码做回归 ——
这是本计划里最容易写错、又完全可以在宿主机验证的部分。

---

## Task 1：GT911 bring-up + 原始坐标（不碰 USB）

目标：确认触摸能读出坐标，**先不做任何变换**，打印原始值。

**Files:** Modify `tab5_pins.h`、`main/idf_component.yml`、`CMakeLists.txt`、`app_main.c`；Create `touch_hid.{c,h}`

- [x] **Step 1：成功判据**

UART 日志见 `touch: gt911 ready (addr=0x14)`；手指点屏幕**四个角与正中**，各打印一组
`touch: raw x=.. y=.. n=..`，坐标随手指移动连续变化。GUD 显示与键盘均不回归。

- [x] **Step 2：`idf_component.yml` 加组件**

```yaml
  # GT911 触摸（Tab5 是备用地址 0x14，不是默认的 0x5D）
  espressif/esp_lcd_touch_gt911: "1.2.1"
```

- [x] **Step 3：`tab5_pins.h` 加常量**

```c
#define PIN_TOUCH_INT      23
/* GT911 在 Tab5 上用的是**备用**地址；组件默认填 0x5D 且不会自动探测。 */
#define GT911_I2C_ADDR_USED  0x14
```
（`GT911_I2C_ADDR 0x14` 已存在、用于面板批次探测，不要重复定义 —— 复用它即可，
本条视实际代码决定是否需要。）

- [x] **Step 4：`touch_hid.c` 初始化**

要点：
- 用 `board_i2c_bus()` 拿内部总线，`esp_lcd_new_panel_io_i2c()` 建 IO（config 从
  `ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG()` 起手，**把 `dev_addr` 改成 `ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP`**）
- `esp_lcd_touch_config_t`：`x_max = PANEL_W`、`y_max = PANEL_H`、`int_gpio_num = PIN_TOUCH_INT`、
  `rst_gpio_num = -1`（Tab5 触摸无独立 reset）、三个 flag **本任务全填 0**（标定在 Task 2）

> ⚠️ **本步这一条最终被推翻**：`int_gpio_num` 必须填 `GPIO_NUM_NC`，且要先把 G23 配成输出
> 并驱动为低 —— 板上到 3V3 的上拉会压住 GT911 不出坐标，**现象是完全静默**。
> 照本步原样写会一个坐标都读不到，坑了整整一轮排查（fix 见 commit `2b0d1ac0`，
> 根因详见 `firmware/README.md` 的「HID 多点触摸」）。
- `esp_lcd_touch_new_i2c_gt911()`
- 起一个任务：`esp_lcd_touch_read_data()` → `esp_lcd_touch_get_coordinates()` → 打印原始 x/y/点数

轮询即可（20ms），中断驱动留到后面按需 —— 触摸不像键盘那样怕丢事件。

- [x] **Step 5：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): GT911 触摸 bring-up，打印原始坐标 (P2 Task1)"
```

---

## Task 2：坐标标定与变换（仍不碰 USB）

目标：把原始坐标变换成 host 看到的 640×360 横向坐标，并用屏幕上的实际位置验证。

**Files:** Create `main/touch_map.{c,h}`、`test/test_touch_map.c`；Modify `touch_hid.c`

- [ ] **Step 1：成功判据**

点屏幕**横持视角**的四角，日志里的 `gud x/y` 应分别接近 `(0,0)` / `(639,0)` / `(0,359)` / `(639,359)`；
点正中接近 `(320,180)`。宿主机回归测试全过。

> ⚠️ **只完成了一半，故不勾。** 宿主机回归测试全过（`test_touch_map.c`，32 用例）；
> 但**四角标定至今未验证** —— 某次抓取里所有触点的 Y 都落在满量程的 78%–99%，
> 既可能是手指位置所致、也可能是 Y 轴映射问题，日志无法区分。
> 补验方法（改在 host 侧做更直接）：`evtest` 里依次点四角，确认
> `ABS_MT_POSITION_X` 与 `ABS_MT_POSITION_Y` 都能各自跑到接近 0 与接近 32767。
> 记录在 spec §5.2 的「待验项」。

- [x] **Step 2：先标定 GT911 的朝向（人工，出数据）**

> 实际**未做人工标定**：官方 esp-bsp 的 `tp_cfg` 已给出取值（三个 flag 全 false、
> GT911 按面板原生 720×1280 竖向出数），据此直接定案，见 commit `9a4b54d6`。

用 Task 1 的原始坐标日志，记录**横持视角**下四个角各自的原始 (x, y)。据此判断：

| 观察 | 结论 |
|---|---|
| 原始 x 范围 ≈ 0..719、y ≈ 0..1279 | GT911 按面板原生竖向出数 → 直接用下面的公式 |
| 原始 x 范围 ≈ 0..1279 | 触摸模组 xy 与面板相反 → `swap_xy = 1` |
| 某轴方向与手指移动相反 | 对应的 `mirror_x` / `mirror_y` 置 1 |

**把标定结果写进代码注释**，像 `DISPLAY_ROT_CCW90` 那样写明「已实机标定」。

- [x] **Step 3：抽出纯函数 `touch_map.c`**

零 ESP-IDF 依赖，便于宿主机测试：

```c
/* 把面板原生坐标(720×1280 竖向)还原成 host 看到的 GUD 坐标(640×360 横向)。
 * 与 display_blit 的 90° CCW 变换互逆，见 firmware/README.md 的推导。 */
void touch_map_panel_to_gud(uint16_t panel_x, uint16_t panel_y,
                            uint16_t *gud_x, uint16_t *gud_y);
```

实现：
```c
    *gud_x = (PANEL_H - 1 - panel_y) / GUD_SCALE;
    *gud_y = panel_x / GUD_SCALE;
```
并对结果做**上限钳位**（`gud_x ≤ GUD_W-1`、`gud_y ≤ GUD_H-1`）—— 触摸可能报出略超面板范围的值。

- [x] **Step 4：写 `test/test_touch_map.c`**

照 `test_kbd_translate.c` 的形式：`main()` + assert，无框架，不挂 IDF 构建。
用例至少覆盖：四角、正中、越界钳位、以及**与显示正变换的往返一致性**
（对若干 GUD 点算出 panel 坐标再反解，应回到原点附近）。

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -I../main test_touch_map.c ../main/touch_map.c -o /tmp/t && /tmp/t
```

- [x] **Step 5：编译 + 上板验证 + 提交**

---

## Task 3：HID digitizer 单点上报

目标：host 出触摸设备，点屏幕能移动指针。**先只做单点**，把「描述符对不对、host 认不认、坐标准不准」三件事与多点分开。

**Files:** Modify `usb_descriptors.{c,h}`、`touch_hid.c`

- [x] **Step 1：成功判据**

```bash
cat /proc/bus/input/devices          # 见新增的 touch 设备
sudo evtest /dev/input/eventN        # 点屏幕见 ABS_X / ABS_Y / BTN_TOUCH
```
且**键盘与 GUD 显示均不回归**。

- [x] **Step 2：拍板接口协议字段**

现有 `TUD_HID_DESCRIPTOR(..., HID_ITF_PROTOCOL_KEYBOARD, ...)` 会把 `bInterfaceSubClass` 设成 BOOT，
宣称支持 boot keyboard —— 而 boot 协议**不允许 Report ID**，加了 digitizer 后这个声明更不自洽。

**决定：改为 `HID_ITF_PROTOCOL_NONE`。** 理由：本接口现在承载键盘 + digitizer 两种报告、
必须用 Report ID，与 boot 协议在规范上互斥；Linux `usbhid` 默认走 report 协议，
日常使用零影响。代价是 BIOS/UEFI/GRUB 早期阶段不再能当 boot 键盘 —— 本产品形态（USB 瘦终端接 Linux 主机）
不涉及那个场景。

**改完必须重新验证键盘仍工作**（这是本任务唯一可能碰坏已验证功能的地方）。

- [x] **Step 3：报告描述符追加 RID 2**

TinyUSB 没有现成的 digitizer 宏，手写。单点最小可用形态：

```
Usage Page (Digitizer), Usage (Touch Screen), Collection (Application),
  Report ID (HID_RID_TOUCH),
  Usage (Finger), Collection (Logical),
    Usage (Tip Switch),   Logical Min 0, Max 1,     Report Size 1,  Report Count 1, Input(Data,Var,Abs),
    Report Size 7, Report Count 1, Input(Cnst),                       // 补齐到 1 字节
    Usage Page (Generic Desktop),
    Usage (X), Logical Min 0, Max 32767, Report Size 16, Report Count 1, Input(Data,Var,Abs),
    Usage (Y), Logical Min 0, Max 32767, Report Size 16, Report Count 1, Input(Data,Var,Abs),
  End Collection,
End Collection
```

坐标用 **0..32767 归一化**（`gud_x * 32767 / (GUD_W-1)`），不把描述符与 GUD 分辨率耦死。

报告结构：`{ uint8_t tip; uint16_t x; uint16_t y; }`（`__attribute__((packed))`），
经 `tud_hid_report(HID_RID_TOUCH, &rpt, sizeof(rpt))` 发出。

⚠️ 加了这段之后 `aio_hid_report_desc` 变长，**`_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN)` 仍必须成立** ——
`TUD_HID_DESCRIPTOR` 里的报告描述符长度是 `sizeof(aio_hid_report_desc)`，会自动跟着变，但务必确认没炸。

- [x] **Step 4：上报时同样要处理端点忙**

键盘那边踩过的坑：`tud_hid_ready()` 为假时直接丢弃，会丢掉「抬起」报告 → host 认为手指还按着。
触摸的上报路径**照搬键盘的等待 + 失败告警写法**，不要重新发明。

- [x] **Step 5：编译 + 上板验证 + 提交**

---

## Task 4：扩到多点（最多 5 点）

目标：`hid-multitouch` 识别为真多点触摸屏。

**Files:** Modify `usb_descriptors.c`、`touch_hid.c`

- [x] **Step 1：成功判据**

`evtest` 见 `ABS_MT_SLOT` / `ABS_MT_TRACKING_ID` / `ABS_MT_POSITION_X/Y`；两指同时点有两个 slot。

- [x] **Step 2：描述符加多点必需字段**

在单点基础上，每个 contact 的 Logical Collection 里加 **Contact Identifier**，
collection 外加 **Contact Count**，并提供 **Contact Count Maximum 的 Feature 报告**
（`hid-multitouch` 靠它判定最大触点数）。Feature 报告要在 `tud_hid_get_report_cb()` 里应答 ——
该回调目前是返回 0 的空实现，**这里要真正实现它**。

- [x] **Step 3：`touch_hid.c` 上报多点**

`esp_lcd_touch_get_coordinates()` 本来就返回多点，逐点变换后填进报告。

- [x] **Step 4：编译 + 上板验证 + 提交**

> 若 Task 4 在实机上迟迟不通，**单点（Task 3）已经可用**，可以先停在那里 —— 对「USB 瘦终端」
> 这个用途，单点绝对定位已经覆盖绝大部分场景。不要为了多点把已经能用的单点搞坏。

---

## Task 5：文档与收尾

- [x] `firmware/README.md` 加触摸章节：GT911 备用地址 `0x14` 的坑、坐标反变换推导与标定结果、
      Report ID 布局、接口协议改 NONE 的理由与代价、宿主机回归测试跑法。
- [x] 包级 `README.md` 状态清单：HID 触摸屏移到 ✅（如实机通过）。
- [x] spec §5 回填实测结论（GT911 实际朝向、三个 flag 的标定值）。
- [x] 提交。

---

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| GT911 朝向与假设不符 | 点哪儿都不对 | Task 2 先打原始坐标标定，再套公式；三个 flag 可调 |
| 改 `HID_ITF_PROTOCOL_NONE` 弄坏键盘 | 已验证功能回归 | Task 3 Step 2 单独拍板并立即回归验证键盘 |
| 多点描述符写错导致整个 HID 接口不枚举 | 键盘一起挂 | Task 4 与 Task 3 分开；不通就停在单点 |
| 触摸与显示坐标系错位 | 视觉上「点偏了」 | 纯函数 + 宿主机往返一致性测试，上板前先排掉算式错误 |
