# tab5-all-in-one

用一根 USB-C 线，把 **M5Stack Tab5（ESP32-P4）** 接到 flange 嵌入式 Linux 主机，让它当一个
「USB 瘦终端」：USB 显示屏 + USB 键盘 + USB 触摸屏 + USB 麦/扬声器 + USB 摄像头，
全走 mainline 驱动（host 侧零自定义驱动）。

姊妹包是 `components/packages/cardputer-all-in-one`（M5Cardputer / ESP32-S3），同一形态、
互不共享代码。

## 两侧分工

| 侧 | 内容 | 构建 |
|----|------|------|
| **Tab5 固件** | `firmware/`（ESP-IDF + TinyUSB）—— GUD 显示 / HID 键盘 + 多点触摸 / UAC1 音频 / 后续 UVC | **容器外** `idf.py`（见 `firmware/README.md`）|
| **Linux 组件** | 内核 config fragment（`CONFIG_DRM_GUD` / `HID_MULTITOUCH` / `SND_USB_AUDIO` / `USB_VIDEO_CLASS`）+ 验收工具/文档 | `flange build` |

Linux 侧零自定义驱动：显示用 **GUD**（Generic USB Display，`drivers/gpu/drm/gud`）、
音频用 **UAC + snd-usb-audio**、键盘与触摸用 **usbhid + hid-multitouch**、摄像头用 **uvcvideo**。

## 状态

- ✅ **USB-C 枚举为 `16d0:10a9`，host `gud` 绑定成功** —— 实机验证通过。
  两个必要条件缺一不可：`TINYUSB_CONFIG_FULL_SPEED`（选对端口），
  以及 `usb_wrap_ll_phy_select(&USB_WRAP, 0)`（把内部 FSLS PHY 0 从
  USB-Serial/JTAG 划给 OTG1.1）。**只做前者的话主机只看得到 `303a:1001` 的 CDC ACM**，
  详见 `firmware/README.md`。
- ✅ **GUD 出图** —— Linux console 已实机显示在 Tab5 屏上，
  即 USB 枚举 → `drm/gud` 绑定 → `/dev/dri/cardN` → 收帧 → PPA 缩放旋转 → 面板
  整条链路打通。
- ✅ **MIPI-DSI 面板点亮** —— 720×1280 竖屏，2 lane @ 1000 Mbps，两种面板批次运行时 I2C 探测。
  实机验证通过（开发用机为 ILI9881C 批次；ST7123 路径只编译未上板）。
- ✅ **PPA 缩放 + 旋转** —— 一次 SRM 操作完成 2× 放大 + 90° 旋转，640×360 铺满面板。
  实机验证通过，旋转方向已标定（`DISPLAY_ROT_CCW90 = 1`）。
- ⏳ **脏矩形 + LZ4 的定量验证**：Linux console 的文本渲染已经在走脏矩形路径且显示正常，
  但尚未对着 UART 日志确认 `LZ4 解压失败` / `ppa srm 失败` 均为 0 条，也未跑
  GStreamer 全屏动态内容压测。
- ⏳ **帧率实测**（两个场景：`videotestsrc` 全屏动态内容测下限、文本终端测实际体感）。
- ✅ **HID 键盘**（Tab5 Keyboard，I2C `0x6D`，独立总线 G0/G1，INT G50）—— 实机验证通过，
  键盘输入正常。用键盘固件的 Normal 模式自建 6KRO 状态机，不用其自带的 HID 模式
  （修饰键不进队列、一次只能表达一个键），详见 `firmware/README.md`。
- ✅ **HID 多点触摸**（GT911，`0x14`，与键盘共用一个 HID 接口、用 Report ID 区分：
  RID 1 键盘 / RID 2 digitizer，不新增端点）—— 实机验证通过：host 侧 `hid-multitouch`
  正常绑定，键盘仍是独立的 input 设备；`ABS_MT_SLOT Max 4`（= `TOUCH_CONTACTS_MAX` − 1）
  证明 Contact Count Maximum 的 Feature 报告被内核读到；**多点触摸已验证（实测 3 指同时）**，
  4/5 指未验证。最大的坑是 **TP_INT(G23) 上到 3V3 的上拉电阻会压住 GT911 不出坐标**
  （现象是完全静默），必须把该脚驱动为低**且**给驱动传 `int_gpio_num = GPIO_NUM_NC`，
  详见 `firmware/README.md`。
- ⏳ **触摸的四角坐标标定待验**：需依次点四角、确认 X 与 Y 都能各自跑到接近 0 与
  接近 32767。已知某次抓取里所有触点的 Y 都落在满量程的 78%–99%，既可能是手指位置所致、
  也可能是 Y 轴映射问题，日志无法区分。
- ⏳ **UAC1 全双工音频**（ES8388 播放 `0x10` / ES7210 双麦录音 `0x40`，一个 I2S 端口真全双工，
  **16 kHz / 单声道 / S16_LE**）—— 代码已落地，描述符已在宿主机上逐项校验（`test/check_usb_desc.py`），
  **尚未实机验证**。占 IF2/IF3/IF4 与端点 `0x02`(播放 ISO OUT) / `0x83`(录音 ISO IN)；
  **坚决不用显式反馈端点**，因为最后一条 IN(`0x84`) 要留给 UVC。参数不是听感定的而是 FIFO 账定的：
  16 kHz 单声道的 OUT 包 36 B 小于 vendor 已有的 64 B，共享 RX FIFO 一个 word 都不涨，
  整个音频功能的 FIFO 代价只有录音那 9 words（256 words 里余 137）；48 kHz 立体声会把余量压到
  31 words，UVC 直接没位置。详见 `firmware/README.md` 的「UAC1 全双工音频」。
- ⏳ 规划中：UVC 摄像头（SC202CS，风险最高、允许砍）；
  主机侧全局内核 config（`flange_common.config` + builder 注入，对所有 board 生效）。

> USB-C 只有 **12 Mbps 全速**（480 Mbps 的高速口被接到了 USB-A 母座）。带宽是零和的：
> 摄像头/音频/显示同时使用会明显互相拖慢，这是全速口的物理上限，**不是实现缺陷**。

详见 `firmware/README.md`。

## 文档

- 设计/可行性：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md`
- 实施计划：`docs/superpowers/plans/2026-08-11-tab5-all-in-one-p0-gud-display.md`（GUD 显示）、
  `docs/superpowers/plans/2026-08-13-tab5-all-in-one-p1-hid-keyboard.md`（HID 键盘）、
  `docs/superpowers/plans/2026-08-13-tab5-all-in-one-p2-hid-touch.md`（HID 触摸）
- 固件细节与构建/烧录/验证：`firmware/README.md`
