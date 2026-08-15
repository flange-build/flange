# Tab5 all-in-one — P4：UVC 摄像头（SC202CS + MIPI-CSI + 硬件 JPEG）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 逐任务实施。
> 步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外
> `. $HOME/esp/esp-idf/export.sh && idf.py build` 编译验证；烧录、看图、host 侧 V4L2
> 验证由人工控制者做。

**Goal:** 让 Tab5 在**同一根 USB-C 线**上再多一个能力：作为标准 **UVC 摄像头**被 Linux 主机的 mainline `uvcvideo` 认出，出 `/dev/videoN`，`v4l2-ctl --list-formats-ext` 看得到 **MJPEG 640×360**，`ffplay` 能出实时画面。**前提是不破坏已实机验证的四项能力**（GUD 显示 / HID 键盘 / HID 多点触摸 / UAC1 全双工音频与播放音量控制）。

**Architecture:** 全速口只剩**一条** IN 端点 `0x84`，UVC 只能用它，且 FIFO 只够 448 字节的 ISO 包 —— 于是整条链路是「**把像素压到 446 B/ms 这根管子里**」这一个约束推导出来的：

```
SC202CS ──MIPI-CSI 1 lane 576 Mbps──▶ ISP(去马赛克+AWB/AE) ──▶ 1280×720 RGB565 (PSRAM)
  (RAW8 1280×720 @30fps)                                            │
                                                                    ▼ PPA SRM  scale 0.5
                                                            640×360 RGB565 (PSRAM)
                                                                    │
                                                                    ▼ 硬件 JPEG 编码器(4:2:2)
                                                              ~20 KB JPEG (PSRAM)
                                                                    │
                                                                    ▼ tud_video_n_frame_xfer()
                                        ISO IN 0x84，448 B/帧(含 2 B UVC 载荷头) @1ms
                                                                    │
                                                                    ▼
                                                   host: uvcvideo → /dev/videoN
```

**关键设计前提（spec §2.1）：ISO 带宽只在 host 选中非 0 alternate setting 时才预留。** 摄像头不打开时，VS 接口停在 alt 0（零端点、零带宽），12 Mbps **全部**留给 GUD bulk —— 即**摄像头对显示的影响严格为零，直到有人真的打开摄像头**。这不是优化，是本阶段全部取舍成立的基础，必须写进 README。

**Tech Stack:** ESP-IDF v6.0.2、TinyUSB 0.21.0~1（`class/video/`，已原生支持 UVC device）、IDF 内置 `esp_driver_cam`(MIPI-CSI) + `esp_driver_isp` + `esp_driver_jpeg` + `esp_driver_ppa`、`espressif/esp_cam_sensor`（SC202CS 寄存器序列）；host 侧 `uvcvideo` + `v4l2-ctl` / `ffplay` / `guvcview`。

---

## 范围

只做摄像头。前置：P0（GUD 显示）、P1（HID 键盘）、P2（HID 多点触摸）、P3（UAC1 全双工音频 + 播放音量控制）**均已实机验证通过**，默认构建开箱即用。

设计依据：`docs/superpowers/specs/2026-08-11-tab5-all-in-one-design.md` §1（硬件表）、§2（USB 布局与端点预算）、§2.1（带宽零和）、§7（摄像头）、§8.1（依赖）、§10（阶段 5）、§11（风险登记）。

**不做**：UVC 的亮度/对比度/曝光等 Processing Unit 控制（host 侧无人要求，每个控制都是一处必须正确应答的请求，错了就是静默 STALL）；still image capture（UVC 的 method 1/2/3 全不做，`bStillCaptureMethod = 0`）；多分辨率 / 多帧率协商（只声明一个格式、一个帧、一个离散帧间隔，理由见「参数选定」）；H.264（`esp_h264` 是纯软件编码，P4 上跑不动实时）；把摄像头画面显示在本机屏上（那是另一个产品形态，且会让 PPA 多一个提交者）。

---

## 📌 落地状态（回填）

**Task 1–9 与 Task 11 已完成；Task 10（五项复合回归）未执行。**

✅ **已实机验证**：UVC 出真实摄像头画面（MJPEG 640×360 @ 10 fps，ISO IN `0x84` × 448 B，
零拒收、每 10 秒精确 +100 帧）、CSI 取流 30 fps 稳定（抢缓冲/丢弃/取帧超时全 0、
帧长 1843200 正确）、SC202CS 探测（`0x36` / `0xeb52`）、硬件 JPEG 实时编码、
PPA ×0.5、**AE 闭环**、五项既有能力各自无回归。

⏳ **未验证**：**AWB 闭环（只过 281 个宿主机用例，没上过板）**、单色场景防护的实际效果、
Task 10 的复合回归、摄像头开着时 GUD 帧率与 PSRAM 带宽争用的实测值、
P3 遗留的全双工长时间稳定性与无反馈端点的时钟漂移。

⛔ **实施推翻了本计划的九处技术判断**，见下面的「实施订正汇总」。

---

## ⛔ 放弃判定点（spec §7 授权，必须在 Task 4 结束时明确判一次）

> ✅ **结果：判定点通过，UVC 没有被砍。** Task 4/5 的三条 host 侧判据全部成立
> （`/dev/videoN` 出现、`v4l2-ctl` 报 `MJPG 640x360 10.000 fps`、`ffplay` 稳定显示），
> 且 GUD / HID / 音频均无回归。下面这一节保留作决策记录。

> spec §7 原文：「**若阶段 5 判定不可行，直接砍掉，不阻塞前四项已交付的能力**」。

**判定点 = Task 4（静态图 MJPEG 流）。** 那一步里**没有摄像头、没有 ISP、没有 JPEG 编码器**，只有「TinyUSB 的 video class 能不能在这块板的全速口上把一段现成的 JPEG 字节流推给 `uvcvideo`」。判据是 host 侧三条：

1. `ls /dev/video*` 多出一个节点，`dmesg` 有 `uvcvideo: Found UVC 1.50 device`；
2. `v4l2-ctl -d /dev/videoN --list-formats-ext` 报 `MJPG` + `640x360` + `10.000 fps`；
3. `ffplay -f v4l2 -input_format mjpeg -video_size 640x360 /dev/videoN` 稳定显示那张静态图。

**放弃条件（满足任意一条即砍掉 UVC，回到 P3 的 HEAD）**：

- Task 4 的三条判据在**穷尽本计划「Task 4 Step 6 排查顺序」全部五步**之后仍不成立；
- 或 UVC 开着时，**GUD / HID / 音频任意一项出现回归**（枚举失败、掉帧到不可用、声卡消失），且不能在不动这三项的前提下修复；
- 或 Task 3 的 FIFO 实测显示 448 B 的 ISO 端点根本分配不出来，且「降级阶梯」四级全部走完仍不行。

**砍掉的动作**：`git revert` 掉 P4 的全部提交（P4 的每一个提交都只碰新文件 + 少数几处带 `#if` 的旧文件，revert 是干净的），在 `firmware/README.md` 写一节「UVC 为什么砍掉」记录实测证据与失败模式，spec §7 与 §10 阶段 5 标注「已尝试，判定不可行」。**不允许留下半截 UVC 代码**——一个描述符里有、固件里不出流的 UVC 接口，会让 host 每次插拔都卡在 `uvcvideo` probe 上，比没有更糟。

---

## 四条硬约束（贯穿全计划，每条都有对应的步骤与判据）

### A. 只剩一条 IN 端点 `0x84`，且**不得新增**

P4 全速控制器（tinyusb `portable/synopsys/dwc2/dwc2_esp32.h:79`，逐字核实）：

```c
{ .reg_base = DWC2_FS_REG_BASE, .irqnum = ETS_USB_OTG11_CH0_INTR_SOURCE,
  .ep_count = 7, .ep_in_count = 5, .otg_dfifo_depth = 256 },   /* rhport 0 = 全速 */
```

`ep_in_count = 5` **含 EP0** ⇒ 非 EP0 的可用 IN 端点只有 **4 条**，`dcd_dwc2.c:226-228` 的
`TU_ASSERT(_dcd_data.allocated_epin_count < dwc2_controller->ep_in_count)` 是硬拦截，
**且默认日志等级下一个字都不打**。

| 端点 | 默认档（本阶段完成后） | UVC 调试档（见硬约束 C） |
|---|---|---|
| `0x81` | vendor(GUD) bulk IN（声明但从不通流量） | **CDC 数据 IN** |
| `0x82` | HID（键盘 + 触摸）中断 IN | 同左 |
| `0x83` | UAC 录音 ISO IN | **CDC 通知**（音频整体不编译） |
| `0x84` | **UVC 视频流 ISO IN（本阶段新增）** | **UVC 视频流 ISO IN（不变）** |
| OUT | `0x01` vendor / `0x02` UAC 播放 | `0x01` vendor / `0x03` CDC 数据 OUT |

两档都是 **4 条 IN 用满**。所以：

- **不得引入任何新 IN 端点**：UVC 的 VideoControl 接口 `bNumEndpoints = 0`（不要状态中断端点）；VideoStreaming 只有 alt 1 带一条 ISO IN。
- **不得动 GUD / HID / 音频的端点与接口号**：本阶段对 `usb_descriptors.c` 里 vendor / HID / UAC1 那三段的改动**只有一处** —— `ITF_NUM_*` 枚举末尾追加两项。宏参数一个字不改。
- **`TUD_VIDEO_DESC_EP_ISO` 写死了 `TUSB_ISO_EP_ATT_ASYNCHRONOUS`**（`video.h:689-691`），这正是我们要的（设备是时钟主控），**且它不带 `bSynchAddress`**（UVC 的 ISO 端点描述符是标准 7 字节，不是 UAC1 那种 9 字节），所以「反馈端点」这件事在 UVC 侧根本无从发生 —— 与 P3 硬约束 A 的落点不同，这里不需要额外断言 `bSynchAddress`，但**需要断言端点描述符是 7 字节**（9 字节意味着有人手写错了）。

判据落点：Task 2（`check_usb_desc.py` 断言 IN 端点恰好 4 条、`0x84` 是 ISO IN、VC 接口 `bNumEndpoints == 0`）、Task 3（两档都过脚本）、Task 4（`lsusb -v` 实机对照）。

### B. FIFO：可用的**不是 256 words，是 242** —— 复算结论与任务说明给的数字不同

> ⚠️ **这是本计划对任务说明的第一处订正，且它直接改变了端点大小的取值。**

`dfifo_device_init()`（`dcd_dwc2.c:257-268`）里有一条任务说明与 `firmware/README.md` 都没算进去的扣除：

```c
_dcd_data.dfifo_top = dwc2_controller->otg_dfifo_depth;   /* 256 */
if (is_dma) {
    _dcd_data.dfifo_top -= 2 * dwc2_controller->ep_count;  /* −2×7 = −14 */
}
```

`is_dma = CFG_TUD_DWC2_DMA_ENABLE && ghwcfg2.arch == GHWCFG2_ARCH_INTERNAL_DMA`
（`dcd_dwc2.c:131-136`）。两个条件**都成立**：

- `CFG_TUD_DWC2_DMA_ENABLE = 1` —— `espressif__esp_tinyusb/include/tusb_config.h:106`，由
  `CONFIG_TINYUSB_MODE_DMA` 门控，而本工程 `sdkconfig` 里 `CONFIG_TINYUSB_MODE_DMA=y`（默认值，从未改过）；
- `ghwcfg2.arch == 2` —— IDF `components/soc/esp32p4/register/hw_ver1/soc/usb_dwc_cfg.h:111`
  的 `#define OTG11_ARCHITECTURE 2`，而 `GHWCFG2_ARCH_INTERNAL_DMA = 2`（`dwc2_type.h:117`）。
  hw_ver1 正是本固件的档位（`CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`）。

⇒ **可分配的 dfifo 顶 = 242 words，不是 256。**

分配公式（`dcd_dwc2.c:201-203` 与 `dfifo_alloc()`，**注意没有任何最小值下限**）：

```
RX FIFO   = 13 + 1 + 2*(最大 OUT 包字节/4 + 1) + 2*ep_count      ; ep_count = 7
TX FIFO_n = ceil(该 IN 端点 wMaxPacketSize / 4)                   ; 未开双缓冲则不 ×2
可用余量  = dfifo_top(242) − RX − Σ TX
```

**默认档的账（本阶段完成后）**：

| 项 | wMaxPacketSize | words | 依据 |
|---|---|---|---|
| RX FIFO（所有 OUT 共享） | 最大 OUT 包 = vendor 的 64 | **62** | `13+1+2*(16+1)+14`；UAC 播放的 36 B 更小，不涨 |
| EP0 IN | 64 | 16 | `CFG_TUD_ENDPOINT0_SIZE` |
| `0x81` vendor bulk IN | 64 | 16 | `bm_double_buffered` 保持默认 0，不 ×2 |
| `0x82` HID 中断 IN | 64 | 16 | `CFG_TUD_HID_EP_BUFSIZE` |
| `0x83` UAC 录音 ISO IN | 36 | 9 | P3 已落地 |
| **小计（UVC 之前）** | | **119** | |
| **余量** | | **242 − 119 = 123 words = 492 字节** | |

**⇒ UVC ISO IN 的 `wMaxPacketSize` 硬上限是 492 字节，不是任务说明说的 548。**

**选定值：`UVC_EP_SIZE = 448`（112 words），留 11 words = 44 字节余量。** 为什么不取满 492：

1. `dfifo_alloc()` 失败时只是 `TU_ASSERT` 返回 false，**无日志**，症状是 `SET_INTERFACE(alt 1)` 被 STALL、`ffplay` 报 `Cannot allocate memory` 之类完全指不到 FIFO 的错；
2. 448 在**两种假设下都成立** —— 即便日后 `is_dma` 变成 false（有人改 `CONFIG_TINYUSB_MODE_SLAVE`），余量从 123 变 137，448 照样装得下；取 492 则会在切成 slave 模式时才「碰巧还能用」，切回来就炸；
3. 代价只有 9% 带宽（446 vs 490 B/ms 有效载荷），而在选定的 640×360 @ 10 fps 上我们有 1.5–2.6 倍余量（见「参数选定」），这 9% 买得起。

**Task 3 会把这笔账变成实测数字**（P3 Task 6 Step 2 那段读 DWC2 寄存器的代码一直留着没实现，本阶段是它真正要用的时候）。若实测空闲 ≥ 32 words，允许在 Task 10 之后单独提一次「448 → 492」，但必须重跑 Task 9 的全部复合回归。

**降级阶梯（按序试，不要跳）**，仅当 Task 3/4 实测装不下时：

1. `UVC_EP_SIZE` 448 → 384（96 words，省 16）→ 320（80 words）；每降一档带宽同比例掉，帧率跟着掉，要重测；
2. 去掉 vendor 的 IN 端点 `0x81`（省 16 words，spec §2 明列的第一条降级选项；调试档已经这么干了，README 有完整依据：mainline `gud_drv.c` 只 `usb_find_bulk_out_endpoint()`，本固件从不 `tud_vendor_write()`）；
3. 把 UAC 采样率/声道降档 —— **不做**，那会破坏已验证的音频（硬约束 D），只在前两级都用尽且产品决定「摄像头比音频重要」时由人拍板；
4. 仍不行 ⇒ 触发放弃判定点。

### C. `CONFIG_AIO_DEBUG_CDC` 与 UVC 撞号 —— 本阶段必须解决的冲突

**现状即冲突**：`CONFIG_AIO_DEBUG_CDC` 这一档**借的正是 `0x84`**（`usb_descriptors.h:81-84`：让出 vendor IN `0x81` 给 CDC 数据、拿 `0x84` 做 CDC 通知）。UVC 落地后两者直接撞号，而这块板**现场没有别的日志通道**（UART0 在 M5-Bus 排针上要外接 USB-TTL，USB-Serial/JTAG 已被 TinyUSB 收走 FSLS PHY）。

**解法：把「UVC 调试档」定义为「关掉音频换回一条 IN 端点」，`0x84` 永远归 UVC。**

| | 默认档 `AIO_DEBUG_CDC=n` | **UVC 调试档** `AIO_DEBUG_CDC=y` |
|---|---|---|
| IF0 | vendor(GUD)，bulk OUT `0x01` + IN `0x81` | vendor(GUD)，**只有 bulk OUT `0x01`** |
| IF1 | HID（键盘+触摸）IN `0x82` | 同左 |
| IF2–IF4 | UAC1（AC + AS-out + AS-in），`0x02` / `0x83` | **整体不编译** |
| IF2/IF3（调试档）/ IF5/IF6（默认档） | **UVC**（VC + VS），ISO IN `0x84` | **UVC**（VC + VS），ISO IN `0x84`（**同一条，不变**） |
| IF4/IF5（调试档） | — | CDC ACM：通知 IN `0x83`、数据 OUT `0x03` + IN `0x81` |
| IN 端点数 | `0x81`+`0x82`+`0x83`+`0x84` = **4/4** ✅ | `0x81`+`0x82`+`0x83`+`0x84` = **4/4** ✅ |
| 接口数 / 配置描述符长度 | 7 / **384 字节** | 6 / **259 字节** |

**FIFO 复算（调试档）**：RX 62（最大 OUT 仍是 64：vendor 与 CDC 数据 OUT 都是 64）
+ EP0 16 + `0x81` CDC 数据 IN(64) 16 + `0x82` HID(64) 16 + `0x83` CDC 通知(**8 B ⇒ 2 words**) 2
= **112 words** ⇒ 余量 `242 − 112 = 130 words = 520 字节` ⇒ 448 B 的 UVC 端点**装得下，且比默认档还宽裕 7 words**。

> ⓘ 顺带订正 `firmware/README.md` 现有的一处小错：那里把「CDC 通知」记成 16 words。
> CDC 通知端点的 `wMaxPacketSize` 是 **8**（`TUD_CDC_DESCRIPTOR(..., EPNUM_CDC_NOTIF, 8, ...)`），
> `ceil(8/4) = 2 words`。不影响任何结论（余量只会更大），但既然要改那一节就一并改对。

**这一档下不可用的能力（必须在 Kconfig help、README、日志三处都写明）**：

| 失去的 | 严重度 | 说明 |
|---|---|---|
| **全部音频**：喇叭播放、双麦录音、`alsamixer` 音量 | 高 | host 侧 `/proc/asound/cards` 里**没有**这块设备，`aplay -l` / `arecord -l` 都不列它。`codec_audio.*` 整体不编译，ES8388/ES7210 不初始化，功放不导通 |
| vendor(GUD) 的 IN 端点 `0x81` | **无** | `drm/gud` 从不使用它（README 有逐条依据），显示照常 |
| 开机最早那几行日志 | 中 | CDC 的 TX 环形缓冲要等 host 打开 `ttyACM*` 才开始流，之前的被覆盖丢弃 —— README 已有此条 |
| 再加任何 USB 功能的余地 | — | 4 条 IN 用满 |

**保留的**：GUD 显示、HID 键盘、HID 多点触摸、**UVC 摄像头**。也就是说：**这一档是专门为「一边跑摄像头一边看日志」设计的**，而摄像头 bring-up（Task 6/7/8）恰恰是本阶段唯一没有 host 侧可见通道的一段。

**第三条路必须一并写进文档**：**接 UART0（G37/G38，在 M5-Bus 排针上）+ USB-TTL**。它**零端点代价、能抓上电最早的日志、且默认档（音频在）也能用**。有 USB-TTL 时优先用它；UVC 调试档是「手边只有一根 USB-C 线」时的替代品。

编译期护栏（Task 3 落地）：

```c
#if CONFIG_AIO_DEBUG_CDC && AIO_HAS_AUDIO
#error "UVC 调试档必须关掉音频才腾得出 IN 端点：AIO_HAS_AUDIO 应由 CONFIG_AIO_DEBUG_CDC 反相定义"
#endif
```

### D. 不破坏已验证的 GUD 显示、HID 键盘、HID 多点触摸、UAC1 音频

**接口号会变**（音频后面追加两个 UVC 接口，IF5/IF6），端点号一个都不动。每个上板任务的成功判据都**必须**包含：`modetest -M gud` 仍出图、`evtest` 键盘仍能打字、触摸仍出 `ABS_MT_*`、`aplay`/`arecord` 仍工作。Task 9 是专门的复合回归。

三条本阶段特有的「不破坏」风险，各有对应步骤：

1. **PPA 多了第二个提交者。** `display_dsi.c` 的 PPA client 现在 `max_pending_trans_num = 2`（GUD 收帧 + 待机画面动画）。摄像头的缩放**必须注册自己的 `ppa_client_handle_t`**（Task 8），不共用 —— 共用会让两条链路的 `PPA_TRANS_MODE_BLOCKING` 互相排队，GUD 的脏矩形延迟直接翻倍。即便如此 PPA 引擎本身仍是共享硬件，Task 9 要实测帧率影响。
2. **PSRAM 带宽争用。** DPI 面板刷新是 720×1280×2 B × 60 Hz ≈ **110 MB/s 的持续 PSRAM 读**，CSI 再写入 1280×720×2 B × 30 fps ≈ **55 MB/s**，PPA 还要读 1.84 MB/写 460 KB。**这是本阶段最可能把已验证功能弄坏的一条**，症状是屏幕撕裂/花屏（DPI 取不到数据）。缓解在 Task 7：CSI **只在 host 选中 alt 1 时才 start**，不流时零占用。
3. **摄像头电源在 `0x43` 那颗 PI4IOE5V6408 的 PIN6**（`CAMERA_EN`），与已在用的 `LCD_EN`(PIN4) / `TOUCH_EN`(PIN5) / `SPEAKER_EN`(PIN1) **同一颗**。必须复用 `board_power.c` 的 `s_ioexp` 句柄，**绝不新建 expander** —— 新建会重置整颗芯片的方向/输出寄存器，把面板和触摸的电一起断掉。

---

## ⛔ 实施订正汇总（**落地后回填 —— 下面这九条推翻了本计划的对应段落**）

> 本计划写在拉下组件之前，有九处与实际不符。**改动本计划的任何相关段落前先读这一节。**
> 权威的现状描述在 `components/packages/tab5-all-in-one/firmware/README.md` 的
> 「UVC 摄像头」与「ESP32-P4 rev <3.0 已知不可用的硬件功能」两章。

| # | 本计划原文 | 实际 | 落点 |
|---|---|---|---|
| ① | CSI 填 `input=RAW8 / output=RGB565`（照 IDF 例程 `mipi_isp_dsi`） | ❌ **实机死在 `esp_cam_new_csi_ctlr() = ESP_ERR_NOT_SUPPORTED`**。该函数内部就调 `s_csi_ctlr_format_conversion()`（`esp_cam_ctlr_csi.c:226`），`input != output` 即在 `:604-608` 查芯片版本，rev <3.0 拒绝。**`mipi_csi_ll.h` 的 `#else` 分支里桥的五个颜色 LL 函数全是空实现 —— 硬件上就没有这个块。**⇒ 两个都填 **RGB565**（桥直通），去马赛克交给 ISP | Task 8 Step 3 |
| ② | （未提）这两个字段只是"颜色标签" | ❌ **双双决定长度**：`input → in_bpp → csi_transfer_size = h*v*in_bpp/64`（DMA 实际搬多少）、`output → out_bpp → fb_size_in_bytes`（帧缓冲大小与 `received_size`）。填 `RAW8/RGB565` ⇒ **只搬 921,600 却声称收到 1,843,200（半帧）**，上层完全看不出来。为此补了「帧长不符计数器」与「下 1/8 亮度」两道自证判据 | Task 8 Step 3 |
| ③ | `esp_cam_ctlr_receive()` 是阻塞取帧 | ❌ 它是**提交缓冲**（`xQueueSend`）。完成通知只走 `on_trans_finished` 回调，且 `esp_cam_ctlr_start()` **硬性要求注册该回调**。⇒ 改成「回调推 `s_done_q`，取帧函数 `xQueueReceive`」 | Task 8 Step 3 |
| ④ | `esp_cam_sensor_set_para_value(ESP_CAM_SENSOR_PARA_STREAM, ...)` | ❌ **`ESP_CAM_SENSOR_PARA_STREAM` 这个符号不存在。** 走 `esp_cam_sensor_ioctl(ESP_CAM_SENSOR_IOC_S_STREAM)` | Task 8 Step 4 |
| ⑤ | `esp_cam_sensor_set_format()` 可能不必调 | ❌ **必须调** —— `sc202cs_detect()` 只把 `cur_format` 指过去，**一个寄存器都没写** | Task 8 Step 4 |
| ⑥ | PPA 的 cache 由驱动自己管，"此处不用管" | ⚠️ **同步**不用管，**对齐**要管：`ppa_srm.c:186-189` 对 `out.buffer` 的**地址与长度都硬性检查** cache line 对齐，不过就 `ESP_ERR_INVALID_ARG` —— 症状是**「一帧都出不来」**，host 侧完全看不出是内存对齐。⇒ 缩放输出缓冲用 `MALLOC_CAP_CACHE_ALIGNED`。（JPEG 编码器那侧反而不要求输入对齐，所以接 PPA 之前一直没事） | Task 9 Step 2 |
| ⑦ | ISO 端点的 FIFO 在 host 选 **alt 1** 时分配，失败症状是 `SET_INTERFACE` 被 STALL | ❌ **`SET_CONFIGURATION` 时就分掉了**：`video_device.c:1404-1422` 的 `videod_open()` 里调 `usbd_edpt_iso_alloc()` → `dcd_dwc2.c:634-637` → `dfifo_alloc()`；alt 1 只调 `usbd_edpt_iso_activate()`，**不碰 FIFO**。而且**返回值根本没人检查、彻底静默**。⇒ 真正的症状是**「提交涨、完成不涨」**，判据是启动日志里 `FIFO: EP4 IN=112 words` 那一行在不在 | Task 5 Step 6 的排查顺序 |
| ⑧ | **不做 AE/AWB 闭环**，用传感器模式表的 `exp_def/gain_def`；代价是「换光照会过曝/欠曝」 | ❌ **被实机推翻**（首图「整体发绿 + 亮度均值 45 已削顶」）。实际自己写了 **AE**（ev 标量 P 控制 + 四道防振荡闸）与 **AWB**（灰世界 + 四道防护 + CCM 施加），**仍然没有引 `esp_ipa`**。⚠️ 白平衡只能走 **CCM** —— 硬件 WBG 有 rev ≥3.0 的版本门，用不了；CCM 无版本门但**系数上限 4.0**。⚠️ 另订正本计划一处错误结论：**`isp_awb` 并无芯片版本门**，那处 `<300` 只否掉 subwindow 子功能且只打 warning | 「自动曝光 / 自动白平衡」一节 + Task 8 Step 3 的注释 |
| ⑨ | 依赖树判据：`managed_components/` 只准多出**三个**目录 | ✅ 结论成立但更好：只多出 **两个**（`espressif__esp_cam_sensor`、`espressif__esp_sccb_intf`），`cmake_utilities` 早已在树里。**实测总计 12 个目录** | Task 7 Step 5 |

另外两条**上游 bug**，本计划未预见、实施时自行挡住：

- **`TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC` 等三个宏是坏的**（`bLength` 算法与
  `bFrameIntervalType` 都错，且**全仓库零调用者**，上游从没跑过）⇒ 手写
  `AIO_UVC_FRM_MJPEG_DISC1(...)` 替代，`check_usb_desc.py` 用 `len(frm) == 30` 钉住；
- **`sc202cs.c:1167` 的增益下标 clamp 是 off-by-one**（默认配置下允许下标 == 表长
  ⇒ 越界读）⇒ `cam_ae_split()` 自己钳死，宿主机测试用 `ev = 1…4×10⁶` 的扫描护着。

**未推翻、已实机证实**的关键前提（列出来免得日后误以为也被订正了）：
`UVC_EP_SIZE = 448`（112 words）装得下、dfifo 顶是 **242 不是 256**、
`dwMaxVideoFrameBufferSize = 65536` 让 `payload` 实测为 448 未被缩水、
CSI 按 alt 0/1 启停、PPA 用独立 client。

---

## 关键事实（已核实，不要凭记忆改）

### TinyUSB 的 UVC device 支持（**逐文件核实**）

| 事实 | 出处 |
|---|---|
| video class 存在且随组件一起分发 | `managed_components/espressif__tinyusb/src/class/video/{video.h, video_device.c, video_device.h}`，1527 行的 `video_device.c` |
| **必须同时定义 `CFG_TUD_VIDEO` 与 `CFG_TUD_VIDEO_STREAMING`** | `usbd.c:229` 只用 `#if CFG_TUD_VIDEO` 就把 videod 驱动挂进驱动表，而 `video_device.c:30` 的编译门是 `#if (CFG_TUD_ENABLED && CFG_TUD_VIDEO && CFG_TUD_VIDEO_STREAMING)` —— **只定义前者会让整个 `video_device.c` 编译成空文件，然后链接期缺 `videod_init` 等 6 个符号**。`tusb_option.h:656` 只给了 `CFG_TUD_VIDEO` 的默认值 0，`CFG_TUD_VIDEO_STREAMING` 连默认值都没有 |
| MJPEG 描述符模板宏齐全 | `video.h:645`(`TUD_VIDEO_DESC_CS_VS_FMT_MJPEG`)、`:650`(`..._FRM_MJPEG_CONT`)、`:657`(`..._FRM_MJPEG_DISC`)、`:570`(`_IAD`)、`:575`(`_STD_VC`)、`:580`(`_CS_VC`)、`:596`(`_CAMERA_TERM`)、`:591`(`_OUTPUT_TERM`)、`:603`(`_STD_VS`)、`:608`(`_CS_VS_INPUT`)、`:683`(`_COLOR_MATCHING`)、`:689`(`_EP_ISO`) |
| **有可直接照搬的整功能模板，但它在 example 里、不在库里** | `examples/device/video_capture/src/usb_descriptors.h` 的 `TUD_VIDEO_CAPTURE_DESCRIPTOR_MJPEG(_stridx,_epin,_width,_height,_fps,_epsize)` —— 与 UAC1 的处境完全一样（库里只有底层宏，整功能要自己拼），但这次上游 example 已经把「1×VC + 1×VS(MJPEG, ISO, alt0/alt1)」拼好了，**逐行照搬 + 改两处**（帧描述符 CONT→DISC、加 `bmaControls` 说明）即可 |
| ISO 端点的 sync 类型写死为 ASYNCHRONOUS，且描述符是 **7 字节** | `video.h:689-691`。与 UAC1 的 9 字节 `audio10_desc_as_iso_data_ep_t` 不同，UVC 用标准 `tusb_desc_endpoint_t` |
| `tud_video_n_frame_xfer(ctl,stm,buf,len)` 一次提交**整帧**，驱动自己切包并置 EOF | `video_device.c:1282-1325`；`_prepare_in_payload()`(`:887-912`) 从 `stm->buffer + offset` **memcpy** 进 EP 缓冲 ⇒ **帧缓冲可以在 PSRAM**（不是 DMA 直读），最后一包自动置 `hdr->EndOfFrame = 1` |
| 一次只能有一帧在飞 | `:1294` `if (... || stm->bufsize) return false;` ⇒ 必须等 `tud_video_frame_xfer_complete_cb()` 才能提交下一帧 |
| 载荷头是 **2 字节**（`bHeaderLength` + `bmHeaderInfo`），带 FrameID 翻转 | `:1174-1176`、`:1317-1319` |
| `dwMaxPayloadTransferSize` 由驱动**算出来**，不是我们填的 | `:562-567`：`payload = ceil(frame_size/interval_ms) + 2`，再 `if (CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE < payload) payload = CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE;` |
| 驱动内部把 rhport 写死成 0 | `:1323`、`:1516` 的 `usbd_edpt_xfer(0, ...)`。本工程的全速口正是 rhport 0（`tinyusb.h:28` `TINYUSB_PORT_FULL_SPEED_0 = 0`，`app_main.c` 用 `TINYUSB_CONFIG_FULL_SPEED`）⇒ **兼容**。若日后有人改成高速口，UVC 会静默不出流 |
| EP 缓冲是静态的 DMA 段数组 | `:129` `TUD_EPBUF_DEF(buf, CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE)` ⇒ 448 字节内部 RAM（内部 RAM 只剩约 474 KB，见 README 资源占用，448 B 可忽略） |

> ⚠️ **`dwMaxPayloadTransferSize` 那条公式是个静默的性能陷阱**：它取 `frame_size/interval_ms + 2` 与
> `EP_BUFSIZE` 的**较小值**。`frame_size` 来自 host 在 COMMIT 里给的 `dwMaxVideoFrameSize`，
> 而 `uvcvideo` 直接抄我们帧描述符里的 `dwMaxVideoFrameBufferSize`。
> 若我们把 `dwMaxVideoFrameBufferSize` 声明成 30000，则
> `30000/100 + 2 = 302 < 448` ⇒ **每个 ISO 包只发 302 字节，带宽白白少三分之一，而且哪里都不报错**。
> ⇒ **必须让 `dwMaxVideoFrameBufferSize / interval_ms ≥ EP_BUFSIZE`**，Task 1 会为此写一条 `_Static_assert`。

### 摄像头链路的三条硬事实（**已查证上游源码与组件仓库**）

| 事实 | 出处 / 后果 |
|---|---|
| **SC202CS 只出 RAW，且最小 MIPI 模式就是 1280×720** | `esp_cam_sensor` 的 `sensors/sc202cs/sc202cs.c:929-947`：四个模式全是 `ESP_CAM_SENSOR_PIXFORMAT_RAW8/RAW10`，最小的是 `MIPI_1lane_24Minput_RAW8_1280x720_30fps`（`mipi_clk = 576000000`、`lane_num = 1`、`fps = 30`、`xclk = 24 MHz`）。**没有 640×480 模式，也没有任何 4:3 模式能用**（见下一条） |
| **1600×1200 / 1600×900 那两个模式对 ISP 不可用** | `esp_cam_sensor` README 原文：「For the ESP32-P4, the maximum input size allowed by the ISP is **1920x1080**」。1600×1200 的 1200 行超了；1600×900 虽然进得去 ISP，但从它裁不出 4:3 的 ≥960 行 ⇒ **1280×720 是唯一可用的传感器模式** |
| **PPA SRM 的缩放粒度是 1/16** | `ppa.h:168-169` 的 `float scale_x/scale_y`，硬件是 1/16 步进。`1280×720 × 0.5 = 640×360` 精确；要得到 640×480 需要先裁 960×720 再乘 2/3，而 2/3 不是 1/16 的整数倍（最近的 11/16 给出 660×495）⇒ **640×480 在这条像素管线上做不出来** |
| `sc202cs_detect()` 是公开 API，SCCB 地址 `0x36`，PID `0xeb52` | `sensors/sc202cs/include/sc202cs.h`。⇒ **不需要 esp_video 的 `ESP_CAM_SENSOR_DETECT_FN` 链接段自动探测机制**，直接调函数即可 |
| CSI 控制器的 `lane_bit_rate_mbps` = `mipi_clk / 1e6` = **576** | esp_video 的 `esp_video_csi_device.c:158` 就是这么换算的（我们不引 esp_video，但照抄它的换算） |
| 摄像头电源 = `0x43` 的 **PIN6**，无 XCLK 引脚、无 RESET 引脚 | esp-bsp `bsp/m5stack_tab5/include/bsp/m5stack_tab5.h:115-117`：`BSP_CAMERA_GPIO_XCLK = GPIO_NUM_NC`、`BSP_CAMERA_RST = GPIO_NUM_NC`、`BSP_CAMERA_EN = IO_EXPANDER_PIN_NUM_6`；`src/bsp_feature_en.c` 的 `BSP_FEATURE_CAMERA` 分支走的是 `bsp_io_expander_init()`（= `0x43`，与 LCD/TOUCH/SPEAKER 同一颗）。⇒ **XCLK 由板上晶振提供，不需要 LEDC 产时钟** |
| P4 硬件 JPEG 编码器：rev <3.0 **不支持 YUV420/YUV444 输入** | IDF `esp_driver_jpeg/jpeg_encode.c:186-198` 的 `#if !(CONFIG_ESP_REV_MIN_FULL < 300 && SOC_IS(ESP32P4))`。本固件是 `REV_MIN_100` ⇒ 可用输入只有 **RGB888 / RGB565 / GRAY / YUV422**。选 **RGB565 输入**（PPA 的输出色彩模式，`ppa_ll.h:251` 有 `PPA_SRM_COLOR_MODE_RGB565`） |
| 输出比特流缓冲**必须 cache line 对齐** | `jpeg_encode.c:144` 的 `ESP_RETURN_ON_FALSE((uintptr_t)bit_stream % cache_line_size == 0, ...)` ⇒ 必须用 `jpeg_alloc_encoder_mem()` 分配，不能 `heap_caps_malloc` |
| `jpeg_encoder_process()` 是**同步阻塞**调用 | `jpeg_encode.c:138`，内部 `xSemaphoreTake(codec_mutex, portMAX_DELAY)` + 等中断 ⇒ 放在自己的任务里跑，不要放在 USB 回调里 |

### 依赖树评估：**用 `esp_cam_sensor`，不要用 `esp_video`**（这是本计划对 spec §8.1 的订正）

spec §8.1 的依赖表把阶段 5 写成 `esp_video`。**实测组件仓库的依赖清单后，这条必须推翻**：

```
$ curl -s https://components.espressif.com/api/components/espressif/esp_video   # 2.3.0
  依赖：espressif/cmake_utilities 0.*
        espressif/esp_cam_sensor  2.3.*
        espressif/esp_h264        1.3.0        ← 软件 H.264 编码器
        espressif/esp_ipa         2.2.*
        espressif/usb_host_uvc    2.5.*        ← ⚠️ USB **Host** 栈
        idf >= 5.4

$ curl -s https://components.espressif.com/api/components/espressif/esp_cam_sensor  # 2.4.0
  依赖：espressif/cmake_utilities 0.*
        espressif/esp_sccb_intf   >=0.0.5      ← 依赖：仅 idf>=5.3
        idf >= 5.3
```

`esp_video` **强制拖进 `usb_host_uvc`** —— 在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB Host 栈，既是 spec §8.1「不引入 usb-host 依赖」的正面违反，也会带来一堆与本产品形态无关的代码。`esp_h264`（软件编码器）同理。

**`esp_cam_sensor` 则是干净的**：它与已在用的 `esp_lcd_ili9881c` / `esp_lcd_touch_gt911` / `esp_io_expander_pi4ioe5v6408` / `esp_codec_dev` **同一性质 —— 芯片驱动组件**，依赖只有 `cmake_utilities`（构建期工具）与 `esp_sccb_intf`（I2C/SPI 寄存器访问薄封装，本身零外部依赖）。

**⇒ 本阶段采用「薄板级驱动 + vendor 传感器寄存器序列」路线**，与 §3.3 面板、§6 codec 完全同构：

| 层 | 用什么 | 为什么不自己写 |
|---|---|---|
| SC202CS 寄存器序列 | **`espressif/esp_cam_sensor` 2.4.x**，只开 `CONFIG_CAMERA_SC202CS` + 1280×720 RAW8 一个模式 | 四张模式表合计数百条寄存器，含无文档项；手抄既无收益也无从验证。与 ES8388/ES7210 走 `esp_codec_dev` 是同一个判断 |
| MIPI-CSI 控制器 | IDF 内置 `esp_driver_cam`（`esp_cam_ctlr_csi.h`） | IDF 内置，不算依赖 |
| ISP（去马赛克 / AWB / AE / BLC） | IDF 内置 `esp_driver_isp` | 同上 |
| 缩放 | IDF 内置 `esp_driver_ppa`（**本工程已在用**） | 同上 |
| JPEG 编码 | IDF 内置 `esp_driver_jpeg` | 同上 |
| **取流编排、V4L2 语义、IPA 自动曝光策略** | **我们自己的 `camera_csi.c`，约 200 行** | 这正是 `esp_video` 那一层，而我们只需要「一个固定模式、一个固定分辨率、拿到一帧 RGB565」，不需要 V4L2 设备节点、不需要多设备管理、不需要 H.264、更不需要 USB Host |

Task 6 Step 5 有明确的依赖树判据（`managed_components/` 只准多出 `espressif__esp_cam_sensor`、`espressif__esp_sccb_intf`、`espressif__cmake_utilities` 三个目录），不通过就退回「按 `sc202cs.c` 的寄存器表自己写薄驱动」。

### 自动曝光 / 自动白平衡：**用 ISP 的硬件统计 + 传感器默认值，不引 `esp_ipa`**

> ⛔ **本节的结论「不做闭环」已被实机推翻，见「实施订正汇总」第 ⑧ 条。**
> 「不引 `esp_ipa`」这一半仍然成立；「用默认曝光增益、不做闭环」这一半不成立 ——
> 实际写了 AE 与 AWB 两个闭环（`cam_tune.c`，零 ESP-IDF 依赖、281 个宿主机用例）。
> ⚠️ **AWB 闭环至今未上板**；AE 已实机验证。

`esp_ipa`（Image Processing Algorithm）是 `esp_video` 用来跑 AE/AWB 闭环的组件。本阶段**不引它**：

- ISP 硬件自带 AWB / AE / 直方图统计单元（`isp_awb.h` / `isp_ae.h` / `isp_hist.h`），能出统计量；
- 但**闭环控制律**（统计 → 调传感器曝光/增益寄存器）要么用 `esp_ipa`，要么自己写；
- 本阶段选**第三条路**：**开 ISP 的 BLC/去马赛克/CCM/Gamma 这些固定环节，AE/AWB 用 `esp_cam_sensor` 模式表里的默认曝光与增益**（`sc202cs_isp_info` 给了 `exp_def = 0x3dc`、`gain_def = 0`），不做闭环。
- **代价必须写清楚**：室内固定光照下画面正常，但**换光照环境会过曝或欠曝，且不会自动恢复**。这对「USB 瘦终端顺带一个摄像头」的产品定位是可接受的；真要自动曝光，是下一个阶段的事，且届时应优先考虑「自己写 30 行 P 控制器」而不是引 `esp_ipa`（后者会把 `esp_video` 的一半拖进来）。
- Task 7 的判据里因此**不含**「不同光照下都正常」，只含「固定室内光照下能看清物体、不是全黑/全白」。

---

## 参数选定：MJPEG **640×360 @ 10 fps**，ISO IN 448 字节/帧

**结论：`UVC_W = 640`、`UVC_H = 360`、`UVC_FPS = 10`（`dwFrameInterval = 1000000` 100 ns 单位）、`UVC_EP_SIZE = 448`、`UVC_MAX_FRAME_BYTES = 65536`。**

### 为什么不是 spec §7 写的 640×480 —— 这是**像素管线**定的，不是带宽定的

先把带宽账摆出来，因为结论可能与直觉相反：

| | 640×480 | **640×360（选定）** |
|---|---|---|
| 像素数 | 307,200 | 230,400 |
| 10 fps 的每帧字节预算（446 B/ms × 100 ms） | 44,600 | 44,600 |
| 典型 MJPEG 4:2:2 中等质量 ≈ 0.6–1.0 bit/pixel | 23–38 KB | **17–29 KB** |
| 余量 | 1.2–1.9× | **1.5–2.6×** |

**⇒ spec §7 的「640×480 约 10 fps」在带宽上是成立的**（需要每帧 ≤ 44.6 KB，而典型值 23–38 KB），任务说明里「据此反推可行的分辨率」的疑虑在这一点上可以放下。

**真正做不到 640×480 的原因是像素管线**（三条已核实的事实叠在一起）：

1. SC202CS 唯一能用的模式是 **1280×720（16:9）**（其余模式要么超 ISP 的 1920×1080 上限，要么裁不出 4:3）；
2. P4 的 ISP **没有缩放器**（IDF `esp_driver_isp/include/driver/` 下只有 `isp_crop.h`，没有任何 scaler 头文件），只能裁不能缩；
3. 唯一的缩放器 PPA 的**缩放比粒度是 1/16**，`1280×720 → 640×360` 是精确的 0.5，而 `→ 640×480` 需要「裁 960×720 再乘 2/3」，2/3 表达不出来。

于是 640×360 是这条管线上**唯一一个既精确、又不改变视野、又不改变宽高比**的输出尺寸。附带三个好处：

- **与 GUD 显示模式同为 640×360** —— 整个包里只有一个分辨率要记；
- 像素数少 25% ⇒ JPEG 小 25% ⇒ 帧率余量大 25%；
- 640 / 16 = 40、360 / 8 = 45，**两个方向都整除 4:2:2 的 MCU（16×8）**，编码器不需要补边（若改用 4:2:0，MCU 是 16×16，360 不整除 —— 这是本计划选 4:2:2 子采样的直接原因，见下）。

**订正 spec §7**：Task 10 要把 §7 的「MJPEG 640×480、目标约 10 fps」改成「MJPEG **640×360**、目标 10 fps」并补上上面这三条管线约束。

### 为什么是 10 fps

- 10 fps ⇒ `interval_ms = 100`，`dwFrameInterval = 1,000,000`（100 ns 单位），`TU_ASSERT(interval_ms != 0)`（`video_device.c:561`）安全；
- 每帧传输耗时 = `帧字节 / 446 B/ms`。17–29 KB ⇒ **38–65 ms**，落在 100 ms 的帧期内，有 35%–62% 的空档给 GUD 的 bulk 抢回一点带宽；
- 若实测 JPEG 稳定在 20 KB 以下，**允许在 Task 8 之后把帧率抬到 15 fps**（每帧预算降到 29.7 KB），但那要重跑 Task 9 的复合回归，且必须记录 GUD 帧率的变化 —— **不在本计划范围内，只留一条升级阶梯**。

### 端点大小与「载荷头吃掉多少」

```
UVC_EP_SIZE            = 448 字节            （112 words FIFO，见硬约束 B）
UVC 载荷头             = 2 字节 / 包         （video_device.c:1174-1176）
有效载荷               = 446 字节 / 毫秒     = 446 KB/s
```

### 带宽账（全速 12 Mbps = 1500 字节/毫秒；周期性传输规范上限 90% = 1350 字节/毫秒）

| 项 | 每毫秒字节 | 占 1500 B/ms |
|---|---|---|
| **UVC 视频 ISO IN（alt 1 时）** | **448** | 29.9% |
| UAC 播放 ISO OUT | 36 | 2.4% |
| UAC 录音 ISO IN | 36 | 2.4% |
| HID 中断 IN（64 B / 10 ms，按峰值帧计） | ≤64 | ≤4.3% |
| **周期性合计（须 ≤ 1350）** | **≤584** | **39%** ✅ |
| GUD bulk（尽力而为） | 余下 ~916 | — |

**⇒ 摄像头开着时，留给 GUD 的理论带宽从约 1364 B/ms 掉到约 916 B/ms（−33%），而 GUD 实测吞吐约 1000 B/ms —— 所以显示会明显变慢，大约掉三分之一。**

**这是全速口的物理上限，不是缺陷**（spec §2.1 已经预告了这一点）。三件事必须做：

1. **写进 README 与包级 README**，用「打开摄像头会让显示明显变慢」这样的大白话，别让用户当 bug 报；
2. **摄像头不开时严格零影响** —— alt 0 不含端点，host 不预留任何 ISO 带宽。Task 9 要实测「未打开摄像头时 GUD 帧率与 P3 相同」；
3. Task 9 要实测并记录「摄像头开着时 GUD 的帧率」这个数字，不许用估算代替。

### `dwMaxVideoFrameBufferSize = 65536`：让 EP_BUFSIZE 成为真正的上限

按「关键事实」里那条陷阱：

```
ceil(dwMaxVideoFrameBufferSize / interval_ms) + 2  >  CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE
ceil(65536 / 100) + 2 = 658  >  448   ✅  ⇒ 每包按 448 发满
```

65536 同时是 JPEG 输出缓冲的大小，两者用**同一个常量**，并在 `cam_jpeg.c` 里对「编码结果超过 65536」走可见的失败路径（丢帧 + 计数），而不是截断成半张图（截断的 JPEG 在 host 侧表现为绿色/灰色的下半屏，极难归因）。

### 子采样：**4:2:2**，不是 4:2:0

- 输入是 RGB565（PPA 的输出），`jpeg_encode.c:146` 只对 **YUV422 输入**强制 `sub_sample == YUV422`，RGB565 输入两种都能选；
- 但 4:2:0 的 MCU 是 16×16，**360 不是 16 的倍数**（360 = 16×22.5）；4:2:2 的 MCU 是 16×8，640 与 360 都整除；
- 代价：4:2:2 比 4:2:0 大约大 20%–25%。按上面的余量（1.5–2.6×）付得起。
- 想省这 20% 有两条路，**都留给以后**：把高度改成 352（16×22，裁掉 8 行）用 4:2:0；或实测确认硬件对非整数 MCU 行会自动补边。**本阶段不赌**。

### 质量参数 `image_quality`

起始值 **70**，Task 8 用实测帧大小调：目标是**平均帧 ≤ 30 KB、峰值帧 ≤ 44 KB**。调法与判据写在 Task 8 Step 5，不许拍脑袋。

---

## 接口与端点新旧对照

| | P3 结束（现状） | 本阶段之后（默认档） | 本阶段之后（UVC 调试档） |
|---|---|---|---|
| IF0 | Vendor(GUD) | Vendor(GUD) **不变** | Vendor(GUD)，无 IN 端点 |
| IF1 | HID（键盘+触摸） | HID **不变** | HID **不变** |
| IF2 | AudioControl | AudioControl **不变** | **VideoControl** |
| IF3 | AudioStreaming OUT | 同 **不变** | **VideoStreaming** |
| IF4 | AudioStreaming IN | 同 **不变** | CDC 控制 |
| IF5 | —（调试档是 CDC 控制） | **VideoControl（新）** | CDC 数据 |
| IF6 | —（调试档是 CDC 数据） | **VideoStreaming（新）** | — |
| 接口数 / 长度 | 5 / 241 B（调试档 7 / 300 B） | **7 / 384 B** | **6 / 259 B** |

**为什么 UVC 追加在最后**：与 P3 同一个理由 —— `uvcvideo` 按 **IAD + 接口类**绑定，不按接口号；`drm/gud` 按 VID/PID + 接口类；`usbhid`/`hid-multitouch` 按接口类；`snd-usb-audio` 按 IAD + 接口类。**没有任何一方按接口号绑定**，所以没有理由去动四个已实机验证的接口。IAD 只要求它覆盖的接口**连续**。

固件内需要改的只有：`ITF_NUM_*` 枚举末尾追加两项（默认档）、`EPNUM_UVC_IN` 一个新常量、以及调试档那一段端点重排。**vendor / HID / UAC 三个描述符宏的参数一个字不改。**

---

## 文件结构

```
firmware/main/
├── uvc_stream.{c,h}            # 新：UVC 类回调 + 帧泵任务 + 帧源切换（静态图/合成图/摄像头）
├── uvc_pattern.{c,h}           # 新：合成彩条 + 移动方块，零依赖纯函数（宿主机可测/可预览）
├── uvc_test_jpeg.h             # 新：静态测试图 JPEG 字节数组（脚本机械生成，注明来源）
├── camera_csi.{c,h}            # 新：SC202CS + MIPI-CSI + ISP，产出 1280×720 RGB565
├── cam_jpeg.{c,h}              # 新：PPA 2× 缩小 + 硬件 JPEG 编码，产出一份 JPEG 字节流
├── tinyusb_config/tusb_config.h  # 改：CFG_TUD_VIDEO / _STREAMING / _EP_BUFSIZE
├── usb_descriptors.{c,h}       # 改：UVC 两接口 + 0x84；调试档端点重排；音频条件编译
├── tab5_pins.h                 # 改：CAMERA_EN、SC202CS 地址、UVC 尺寸/帧率常量
├── board_power.{c,h}           # 改：board_camera_enable()
├── app_main.c                  # 改：uvc_stream_start()；音频调用加 #if AIO_HAS_AUDIO
├── Kconfig.projbuild           # 改：AIO_DEBUG_CDC 的说明改写为「UVC 调试档」
├── idf_component.yml           # 改：加 espressif/esp_cam_sensor
└── CMakeLists.txt              # 改：加源文件、esp_driver_cam/isp/jpeg
firmware/test/
├── test_uvc_pattern.c          # 新：合成图案纯函数回归 + PPM 预览（照 test_standby_screen.c）
├── jpeg_to_header.py           # 新：把一张 .jpg 机械转成 uvc_test_jpeg.h
└── check_usb_desc.py           # 改：UVC 断言 + 两档自动判定
firmware/sdkconfig.defaults     # 改：裁 esp_cam_sensor 只留 SC202CS 的一个模式
```

> ⓘ `display_dsi.c` / `gud_device.c` / `kbd_*.c` / `touch_*.c` / `codec_audio.c` 的**函数体一行都不改**。
> `app_main.c` 与 `usb_descriptors.{c,h}` 里对已有代码的改动全部包在 `#if AIO_HAS_AUDIO` 里，
> 默认档下预处理后的结果与 P3 逐字相同 —— 这是「不破坏已验证功能」最省事的落实方式，
> 也让 Task 3 的判据可以是「默认档的 `aio_desc_configuration` 里 vendor/HID/UAC 三段
> （偏移 9 起的 232 字节）与 P3 的 ELF **逐字节相同**」（只有配置描述符头部的
> `wTotalLength` 与 `bNumInterfaces` 两个字段允许变，因为多了两个接口）。

---

## Task 1：开启 `CFG_TUD_VIDEO` + UVC 描述符（默认档，不上板）

目标：把 UVC 的两个接口与 `0x84` 那条 ISO 端点写进配置描述符，并让工程编译通过。**本任务不上板，也不写任何取流代码。**

**Files:** Modify `main/tinyusb_config/tusb_config.h`、`main/usb_descriptors.{c,h}`、`main/tab5_pins.h`

- [x] **Step 1：成功判据**

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh && rm -f sdkconfig && idf.py build
```

1. 编译通过，**且链接期不缺 `videod_init` / `videod_open` 等符号**（这是 `CFG_TUD_VIDEO_STREAMING` 忘了定义时唯一的症状，见「关键事实」）；
2. 全部 `_Static_assert` 通过，其中包括新加的 `sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN`（默认档应为 **384**）；
3. `idf.py size` 的 Flash 增量如实记下来（Task 10 要写进 README）。

- [x] **Step 2：`tab5_pins.h` 落 UVC 的尺寸/帧率常量**

放 `tab5_pins.h` 而不是 `usb_descriptors.h`？**不**——与 P3 的 `UAC_*` 同处置：这些描述的是**对 host 声明的格式**，不是板级布线，所以放 `usb_descriptors.h`（下一步）。`tab5_pins.h` 本步只加**板级**的两条：

```c
/* ── 摄像头 ──────────────────────────────────────────────────────
 * SC202CS 2 MP，MIPI-CSI **1 lane**。板上自带 24 MHz 晶振，**没有** XCLK 引脚、
 * 也**没有** RESET 引脚（esp-bsp 的 BSP_CAMERA_GPIO_XCLK / BSP_CAMERA_RST 都是
 * GPIO_NUM_NC）⇒ 不需要 LEDC 产时钟，上电只有一件事：拉高 IO 扩展上的使能。
 *
 * ⚠️ CAMERA_EN 与 LCD_EN(PIN4) / TOUCH_EN(PIN5) / SPEAKER_EN(PIN1) **同在
 * 0x43 那一颗 PI4IOE5V6408 上**（esp-bsp 的 BSP_FEATURE_CAMERA 分支走的就是
 * bsp_io_expander_init()，其地址 = ..._ADDRESS_LOW = 0x43）。必须复用
 * board_power.c 已有的 s_ioexp 句柄 —— 新建一个 expander 会重置整颗芯片的
 * 方向/输出寄存器，把面板与触摸的电一起断掉。 */
#define IOEXP_PIN_CAMERA_EN   IO_EXPANDER_PIN_NUM_6

/* SC202CS 的 SCCB(=I2C) 地址，**7 bit**。挂在内部 I2C(G31/G32) 上，
 * 与 GT911(0x14) / ES8388(0x10) / ES7210(0x40) / IO 扩展(0x43,0x44) 共总线。
 * PID 寄存器 0x3107/0x3108 读回应为 0xeb52。取自 esp_cam_sensor 的
 * sensors/sc202cs/include/sc202cs.h（SC202CS_SCCB_ADDR / SC202CS_PID）。
 * ⚠️ 与 esp_codec_dev 那两颗不同，esp_sccb_intf 收的就是 **7 bit** 地址，
 *    不需要再定一份 8 bit 形式。 */
#define SC202CS_I2C_ADDR7     0x36
#define SC202CS_PID_EXPECT    0xeb52

/* 传感器唯一可用的 MIPI 模式（理由见计划的「关键事实」：其余模式要么超出
 * P4 ISP 的 1920×1080 上限，要么裁不出 4:3）。 */
#define CAM_SENSOR_W          1280
#define CAM_SENSOR_H          720
#define CAM_MIPI_LANES        1
#define CAM_MIPI_MBPS         576   /* = sc202cs_format_info[].mipi_info.mipi_clk / 1e6 */
```

- [x] **Step 3：`usb_descriptors.h` 的 UVC 参数常量、接口号与端点号**

```c
/*
 * ── UVC（USB Video Class）：MJPEG 640×360 @ 10 fps ──────────────────
 *
 * 分辨率是**像素管线**定的，不是带宽定的（spec §7 原写 640×480，本阶段订正）：
 *   ① SC202CS 唯一能用的 MIPI 模式是 1280×720（1600×1200 超出 P4 ISP 的
 *      1920×1080 上限，1600×900 裁不出 4:3）；
 *   ② P4 的 ISP **没有缩放器**（esp_driver_isp 只有 isp_crop.h，能裁不能缩）；
 *   ③ 唯一的缩放器 PPA 的缩放比粒度是 1/16 ⇒ 1280×720 ×0.5 = 640×360 精确，
 *      而 640×480 需要 2/3，1/16 表达不出来（最近的 11/16 给出 660×495）。
 * 附带：640/16=40、360/8=45 都整除 4:2:2 的 MCU(16×8)，编码器不必补边；
 * 而且与 GUD 显示模式同为 640×360，整个包只有一个分辨率要记。
 */
#define UVC_W                640
#define UVC_H                360
#define UVC_FPS              10
/* dwFrameInterval 的单位是 100 ns ⇒ 10 fps = 1,000,000。
 * video_device.c:561 有 TU_ASSERT(interval/10000 != 0)，即帧间隔不得小于 1 ms。 */
#define UVC_FRAME_INTERVAL   (10000000 / UVC_FPS)

/*
 * ISO IN 端点大小 = 448 字节（112 words FIFO）。
 *
 * 上限是 **492 字节**，由 DWC2 的 dfifo 账算出来，**不是 1023(全速 ISO 的规范上限)**：
 *   dfifo 顶 = 256 − 2×ep_count(7) = **242 words**（dcd_dwc2.c:257-263，
 *     is_dma 成立：CONFIG_TINYUSB_MODE_DMA=y 且 P4 的 OTG11_ARCHITECTURE=2=INTERNAL_DMA）
 *   已用 = RX 62 + EP0 16 + vendor IN 16 + HID 16 + UAC 录音 IN 9 = 119
 *   余量 = 242 − 119 = 123 words = 492 字节
 * 取 448 而不取满 492：① dfifo_alloc() 装不下时只是 TU_ASSERT 返回 false、
 * **无日志**，症状是 SET_INTERFACE 被 STALL；② 448 在 is_dma 为真(余 123)与为假
 * (余 137) 两种假设下都成立；③ 代价只有 9% 带宽，而 640×360@10fps 有 1.5–2.6 倍余量。
 */
#define UVC_EP_SIZE          448
/* 每包被 UVC 载荷头吃掉 2 字节（video_device.c:1174-1176）。 */
#define UVC_PAYLOAD_HDR      2

/*
 * 一帧 JPEG 的上限。同时是 cam_jpeg.c 输出缓冲的大小。
 *
 * ⚠️ 这个数**不能随便填小**：TinyUSB 用
 *     dwMaxPayloadTransferSize = min(ceil(dwMaxVideoFrameSize/interval_ms) + 2,
 *                                    CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE)
 * （video_device.c:562-567），而 uvcvideo 把我们声明的 dwMaxVideoFrameBufferSize
 * 原样填进 COMMIT。填 30000 的话每包只发 302 字节，带宽白掉三分之一，
 * **而且哪里都不报错**。下面那条 _Static_assert 守着这件事。
 */
#define UVC_MAX_FRAME_BYTES  65536

_Static_assert((UVC_MAX_FRAME_BYTES / (UVC_FRAME_INTERVAL / 10000)) + 2 > UVC_EP_SIZE,
               "dwMaxVideoFrameBufferSize 太小，TinyUSB 会把每包缩到不足 UVC_EP_SIZE，"
               "带宽静默损失（见 video_device.c 的 dwMaxPayloadTransferSize 计算）");
_Static_assert(UVC_W % 16 == 0 && UVC_H % 8 == 0,
               "4:2:2 的 MCU 是 16×8，两个方向都要整除，否则编码器要补边");
```

接口号与端点号（**两档**，与既有写法同构）：

```c
enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_HID,                   /* 键盘 + 多点触摸，靠 Report ID 区分 */
#if AIO_HAS_AUDIO
    ITF_NUM_AUDIO_CONTROL,
    ITF_NUM_AUDIO_STREAMING_OUT,   /* 播放：host → ES8388 → 喇叭 */
    ITF_NUM_AUDIO_STREAMING_IN,    /* 录音：ES7210 双麦 → host */
#endif
    /* UVC 两接口。相对顺序不能动：VideoControl 必须是 IAD 覆盖区间的第一个，
     * VideoStreaming 必须紧随其后。整段排在最后完全合法 —— uvcvideo 按
     * IAD + 接口类绑定，不按接口号。 */
    ITF_NUM_VIDEO_CONTROL,
    ITF_NUM_VIDEO_STREAMING,
#if CONFIG_AIO_DEBUG_CDC
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
#endif
    ITF_NUM_TOTAL
};

#define EPNUM_UVC_IN     0x84      /* ISO IN，视频流。四条可用 IN 端点的最后一条 */
```

（`AIO_HAS_AUDIO` 与调试档的端点重排在 **Task 3** 落地；本任务先按 `#define AIO_HAS_AUDIO 1` 写死在 `usb_descriptors.h` 顶部，Task 3 再把它改成由 `CONFIG_AIO_DEBUG_CDC` 反相定义。这样 Task 1 与 Task 3 的 diff 都小，且 Task 1 结束时默认档已经是完整可编译状态。）

⚠️ **本任务必须临时把 `CONFIG_AIO_DEBUG_CDC` 那一档的 `#error` 打开**——它现在会去抢 `0x84`：

```c
#if CONFIG_AIO_DEBUG_CDC
#error "CONFIG_AIO_DEBUG_CDC 与 UVC 撞号（都要 0x84）：端点重排在 P4 Task 3 落地，在那之前请保持关闭"
#endif
```

Task 3 会把这条 `#error` 换成真正的重排。**不允许跳过这一步直接写重排** —— 那会让 Task 1 的判据同时覆盖两档，一次改两个变量。

- [x] **Step 4：`tinyusb_config/tusb_config.h` 追加 video 配置**

```c
/*
 * ── UVC（Video class）───────────────────────────────────────────────
 * esp_tinyusb 2.2.1 的 Kconfig 与默认 tusb_config.h 里 VIDEO 零命中，
 * 所以与 Audio 一样只能在这里手工开。
 *
 * ⚠️ **两个宏都必须定义。** usbd.c:229 只用 `#if CFG_TUD_VIDEO` 就把 videod
 *    驱动挂进驱动表，而 video_device.c:30 的编译门是
 *    `#if (CFG_TUD_ENABLED && CFG_TUD_VIDEO && CFG_TUD_VIDEO_STREAMING)`。
 *    只定义前者 ⇒ 整个 video_device.c 编译成空文件 ⇒ 链接期缺 videod_init /
 *    videod_deinit / videod_reset / videod_open / videod_control_xfer_cb /
 *    videod_xfer_cb 六个符号。tusb_option.h:656 只给了 CFG_TUD_VIDEO 的默认值 0，
 *    CFG_TUD_VIDEO_STREAMING 连默认值都没有。
 */
#undef CFG_TUD_VIDEO
#define CFG_TUD_VIDEO                     1   /* 一个 VideoControl 功能 */
#define CFG_TUD_VIDEO_STREAMING           1   /* 它下属一个 VideoStreaming 接口 */

/*
 * ISO IN 端点缓冲 = 端点最大包。这个值有**两个**作用，必须与描述符里的
 * wMaxPacketSize 完全相等：
 *  ① TUD_EPBUF_DEF(buf, ...) 的静态 DMA 缓冲大小（video_device.c:129）；
 *  ② dwMaxPayloadTransferSize 的**封顶值**（:564-566）——
 *     它就是 host 每毫秒真正能拿到多少字节。
 * 取值 448 的完整推导见 usb_descriptors.h 的 UVC_EP_SIZE 注释与计划的硬约束 B。
 * ⚠️ 这里写不了 `UVC_EP_SIZE`：tusb_config.h 被 tinyusb 库自身包含，
 *    不能反向 include 应用头。所以是**字面量 + 对账断言**（在 usb_descriptors.c）。
 */
#define CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE  448
```

- [x] **Step 5：`usb_descriptors.c` 的 UVC 描述符**

底稿逐行取自 `managed_components/espressif__tinyusb/examples/device/video_capture/src/usb_descriptors.h` 的 `TUD_VIDEO_CAPTURE_DESCRIPTOR_MJPEG`（MIT），**改两处**：帧描述符从 `_CONT`（连续帧率区间）换成 `_DISC`（单一离散帧率），以及把 `_width/_height/_fps` 换成我们的常量。

```c
/*
 * ── UVC 1.5：一个 VideoControl 接口 + 一个 VideoStreaming 接口（MJPEG）──
 *
 * 底稿取自 tinyusb examples/device/video_capture 的 TUD_VIDEO_CAPTURE_DESCRIPTOR_MJPEG
 * （MIT）。TinyUSB 库里只有底层 TUD_VIDEO_DESC_* 宏，整功能模板在 example 里 ——
 * 与 UAC1 的处境一样，只是这次上游已经拼好了，我们照搬。
 *
 * 拓扑（terminal ID 是本功能内自洽的编号）：
 *   ID1 Camera Terminal（摄像头） → ID2 Output Terminal（USB Streaming）
 *
 * ⚠️ VideoControl 接口 bNumEndpoints = 0：**不要状态中断端点**。
 *    四条可用 IN 端点已经被 vendor/HID/UAC 录音/本视频流用满（见 usb_descriptors.h
 *    的端点表），多一条就撞上 dcd_dwc2.c 的 TU_ASSERT —— 而它**一个字都不打**。
 *
 * ⚠️ 帧描述符用 **_DISC（离散）而不是 _CONT（连续）**，只声明一个帧间隔。
 *    理由：video_device.c:552-559 在 host 把 dwFrameInterval 填 0（问默认值）时，
 *    对「bFrameIntervalType > 1 或 连续区间的 min != max」这两种情况会直接
 *    `return true` 而**不填任何值**，把协商结果推给下一轮。单一离散间隔让这条
 *    路径永远走不到，协商是确定性的。代价是 host 不能选别的帧率 —— 本来也不想给。
 *
 * ⚠️ ISO 端点由 TUD_VIDEO_DESC_EP_ISO 生成，它写死 TUSB_ISO_EP_ATT_ASYNCHRONOUS
 *    且是标准 7 字节端点描述符（不是 UAC1 那种带 bSynchAddress 的 9 字节）——
 *    所以 UVC 侧不存在「反馈端点」这回事，也不存在 P3 那个「sync 字段填 0 会被
 *    当成反馈端点」的陷阱。check_usb_desc.py 仍会断言它是 7 字节（9 字节 = 有人手写错了）。
 */
#define UVC_CAM_TERM_ID   1
#define UVC_OUT_TERM_ID   2
/* UVC 1.5。时基时钟频率是 UVC 1.0 的遗留字段，1.5 下已废弃，照 example 填 27 MHz。 */
#define UVC_BCD_VERSION   0x0150
#define UVC_CLOCK_FREQ    27000000

#define UVC_VS_DESC_LEN (TUD_VIDEO_DESC_CS_VS_FMT_MJPEG_LEN + \
                         (TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC_LEN + 1 * 4) + \
                         TUD_VIDEO_DESC_CS_VS_COLOR_MATCHING_LEN)

#define UVC_DESC_LEN (TUD_VIDEO_DESC_IAD_LEN + \
                      TUD_VIDEO_DESC_STD_VC_LEN + \
                      (TUD_VIDEO_DESC_CS_VC_LEN + 1 /* bInCollection = 1 个 VS */) + \
                      TUD_VIDEO_DESC_CAMERA_TERM_LEN + \
                      TUD_VIDEO_DESC_OUTPUT_TERM_LEN + \
                      TUD_VIDEO_DESC_STD_VS_LEN /* alt 0，零带宽 */ + \
                      (TUD_VIDEO_DESC_CS_VS_IN_LEN + 1 /* bNumFormats × bControlSize */) + \
                      UVC_VS_DESC_LEN + \
                      TUD_VIDEO_DESC_STD_VS_LEN /* alt 1 */ + \
                      7 /* ISO 端点 */)

#define UVC_MJPEG_DESCRIPTOR(_vc_itf, _vs_itf, _stridx, _epin) \
    TUD_VIDEO_DESC_IAD(_vc_itf, 2, _stridx), \
    /* ── VideoControl，无端点 ── */ \
    TUD_VIDEO_DESC_STD_VC(_vc_itf, 0 /* bNumEndpoints，见上方 ⚠️ */, _stridx), \
      TUD_VIDEO_DESC_CS_VC(UVC_BCD_VERSION, \
                           TUD_VIDEO_DESC_CAMERA_TERM_LEN + TUD_VIDEO_DESC_OUTPUT_TERM_LEN, \
                           UVC_CLOCK_FREQ, _vs_itf /* baInterfaceNr[]：唯一的 VS 接口 */), \
        /* Camera Terminal：焦距三项与 bmControls 全 0 = 不支持任何摄像头控制
         * （变焦/对焦/曝光…）。每加一项都是一处必须正确应答的 GET/SET_CUR，
         * 应答错了 uvcvideo 在 probe 阶段就报错 —— 典型的「加了功能反而不能用」。 */ \
        TUD_VIDEO_DESC_CAMERA_TERM(UVC_CAM_TERM_ID, 0, 0, 0, 0, 0, 0), \
        TUD_VIDEO_DESC_OUTPUT_TERM(UVC_OUT_TERM_ID, VIDEO_TT_STREAMING, 0, \
                                   UVC_CAM_TERM_ID, 0), \
    /* ── VideoStreaming alt 0：零端点、零带宽 ──
     * **这是 spec §2.1「带宽零和」的落点**：host 不打开摄像头时停在 alt 0，
     * 不预留任何 ISO 带宽，12 Mbps 全部归 GUD 的 bulk。摄像头对显示的影响
     * 严格为零，直到有人真的打开它。 */ \
    TUD_VIDEO_DESC_STD_VS(_vs_itf, 0, 0, _stridx), \
      TUD_VIDEO_DESC_CS_VS_INPUT(1 /* bNumFormats */, UVC_VS_DESC_LEN, \
                                 _epin, 0 /* bmInfo：不支持动态格式切换 */, \
                                 UVC_OUT_TERM_ID /* bTerminalLink */, \
                                 0 /* bStillCaptureMethod：不做静态抓拍 */, \
                                 0 /* bTriggerSupport */, 0 /* bTriggerUsage */, \
                                 0 /* bmaControls(1)：本格式不支持任何流控制 */), \
        TUD_VIDEO_DESC_CS_VS_FMT_MJPEG(1 /* bFormatIndex */, 1 /* bNumFrameDescriptors */, \
                                       0 /* bmFlags：帧大小**不固定**，这是 MJPEG 的常态 */, \
                                       1 /* bDefaultFrameIndex */, \
                                       0, 0 /* 宽高比不声明 */, 0 /* 逐行 */, 0 /* 无拷贝保护 */), \
          /* 单一离散帧间隔，见上方 ⚠️。dwMaxVideoFrameBufferSize 直接决定
           * 每个 ISO 包发多少字节，别乱填 —— 见 usb_descriptors.h 的
           * UVC_MAX_FRAME_BYTES 与它下面那条 _Static_assert。 */ \
          TUD_VIDEO_DESC_CS_VS_FRM_MJPEG_DISC(1 /* bFrameIndex */, 0 /* bmCapabilities */, \
              UVC_W, UVC_H, \
              (uint32_t)UVC_W * UVC_H * 16 /* dwMinBitRate，信息性 */, \
              (uint32_t)UVC_W * UVC_H * 16 * UVC_FPS /* dwMaxBitRate，信息性 */, \
              UVC_MAX_FRAME_BYTES, UVC_FRAME_INTERVAL /* dwDefaultFrameInterval */, \
              UVC_FRAME_INTERVAL /* 唯一的离散间隔 */), \
        TUD_VIDEO_DESC_CS_VS_COLOR_MATCHING(VIDEO_COLOR_PRIMARIES_BT709, \
                                            VIDEO_COLOR_XFER_CH_BT709, \
                                            VIDEO_COLOR_COEF_SMPTE170M), \
    /* ── VideoStreaming alt 1：带 ISO IN 端点 ── */ \
    TUD_VIDEO_DESC_STD_VS(_vs_itf, 1, 1, _stridx), \
      TUD_VIDEO_DESC_EP_ISO(_epin, UVC_EP_SIZE, 1 /* bInterval = 每帧 */)
```

字符串与配置描述符：

```c
/* 视频功能的字符串索引，同时是 IAD 与两个视频接口的 iInterface。 */
#define AIO_STRID_VIDEO 5
```

在 `aio_string_desc_arr[]` 末尾追加 `"Tab5 Camera"`，并把既有的那条断言从 `== AIO_STRID_AUDIO + 1` 改成 `== AIO_STRID_VIDEO + 1`（**音频的字符串在调试档下虽然没人引用，但数组照旧保留** —— 让两档的字符串索引完全一致，少一个变量）。

`CONFIG_TOTAL_LEN` 与数组：

```c
#define CONFIG_TOTAL_LEN \
    (TUD_CONFIG_DESC_LEN + AIO_VENDOR_DESC_LEN + TUD_HID_DESC_LEN + \
     AIO_AUDIO_DESC_LEN + UVC_DESC_LEN + AIO_CDC_DESC_LEN)

const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    AIO_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_NONE,
                       sizeof(aio_hid_report_desc), EPNUM_HID,
                       CFG_TUD_HID_EP_BUFSIZE, 10),
#if AIO_HAS_AUDIO
    UAC1_AUDIO_DESCRIPTOR(ITF_NUM_AUDIO_CONTROL, ITF_NUM_AUDIO_STREAMING_OUT,
                          ITF_NUM_AUDIO_STREAMING_IN, AIO_STRID_AUDIO,
                          EPNUM_AUDIO_OUT, EPNUM_AUDIO_IN),
#endif
    UVC_MJPEG_DESCRIPTOR(ITF_NUM_VIDEO_CONTROL, ITF_NUM_VIDEO_STREAMING,
                         AIO_STRID_VIDEO, EPNUM_UVC_IN),
#if CONFIG_AIO_DEBUG_CDC
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 0, EPNUM_CDC_NOTIF, 8,
                       EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
#endif
};
```

（`AIO_AUDIO_DESC_LEN` 是新引入的一层薄封装：`#if AIO_HAS_AUDIO` 下 `= UAC1_AUDIO_DESC_LEN`，否则 `= 0`，与既有的 `AIO_CDC_DESC_LEN` 完全同构。本任务 `AIO_HAS_AUDIO` 恒为 1。）

对账断言：

```c
_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN,
               "USB 配置描述符长度不一致");
/* 描述符声明的 ISO 包大小与 tusb_config.h 给驱动的缓冲/封顶值必须**相等**，
 * 不是「小于等于」：小了会浪费 FIFO，大了会被 dwMaxPayloadTransferSize 悄悄
 * 截到缓冲大小 —— 两种都不报错，只是带宽莫名其妙少一截。 */
_Static_assert(UVC_EP_SIZE == CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE,
               "UVC ISO 端点大小必须与 CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE 完全相等");
_Static_assert(CFG_TUD_VIDEO == 1 && CFG_TUD_VIDEO_STREAMING == 1,
               "两个宏都要定义：只定义 CFG_TUD_VIDEO 会让 video_device.c 编成空文件");
```

- [x] **Step 6：编译并记录长度，提交**

预期：默认档 **7 接口 / 384 字节**（= 9 config + 23 vendor + 25 HID + 184 UAC1 + 143 UVC）。若 `_Static_assert` 报出别的数字，**先手算 UVC_DESC_LEN 的 12 项**再改代码，不要靠改常量凑。

```
git commit -m "feat(tab5-fw): 开启 CFG_TUD_VIDEO 并落 UVC MJPEG 640x360 描述符 (P4 Task1)"
```

---

## Task 2：`check_usb_desc.py` 扩展到 UVC（烧板前的闸门，不上板）

目标：把 UVC 那 143 字节在**烧板之前**验一遍。这是硬约束 A 的落点，也是这块板唯一能在上板前拦住描述符错误的地方。

**Files:** Modify `test/check_usb_desc.py`

- [x] **Step 1：成功判据**

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh
python3 test/check_usb_desc.py build/tab5_aio.elf     # → 打印描述符树 + OK
```

脚本必须打印 **7 个接口**（IF0 vendor / IF1 HID / IF2 AC / IF3 AS-out / IF4 AS-in / IF5 VC / IF6 VS）、**4 条 IN 端点**、**3 条 ISO 端点**（UAC 两条 + UVC 一条），且全部断言通过。

- [x] **Step 2：`EXPECT` 里补 UVC 的期望值**

沿用既有做法 —— **刻意重复一遍字面量**而不是去解析头文件：本脚本是独立的第二意见，跟着头文件一起改就失去了交叉检查的意义。

```python
    # ── UVC（P4）────────────────────────────────────────────────
    itf_vc=5, itf_vs=6,
    ep_uvc=0x84, ep_uvc_pkt=448,
    uvc_w=640, uvc_h=360, uvc_interval=1000000,   # 100 ns 单位 ⇒ 10 fps
    uvc_max_frame=65536,
    uvc_cam_term=1, uvc_out_term=2,
    # 调试档下 UVC 顶到 IF2/IF3（音频整体不编译），端点号**不变**
    itf_vc_dbg=2, itf_vs_dbg=3,
```

以及 UVC 的描述符子类型常量（照既有 UAC1 常量的写法）：

```python
# UVC VideoControl 的 CS 子类型
VC_HEADER, VC_INPUT_TERM, VC_OUTPUT_TERM = 0x01, 0x02, 0x03
# UVC VideoStreaming 的 CS 子类型
VS_INPUT_HEADER, VS_FORMAT_MJPEG, VS_FRAME_MJPEG, VS_COLORFORMAT = 0x01, 0x06, 0x07, 0x0D
VIDEO_ITT_CAMERA, VIDEO_TT_STREAMING = 0x0201, 0x0101
```

- [x] **Step 3：加一个 `check_uvc(items, itf_by, itf_eps, has_audio)` 函数**

断言清单（每一条都对应一种「烧了才发现」的错误）：

```python
def check_uvc(items, itf_by, itf_eps, has_audio):
    """UVC 段的全部跨描述符引用。每条断言都对应一种烧板后才会暴露的错误。"""
    vc_num = EXPECT['itf_vc'] if has_audio else EXPECT['itf_vc_dbg']
    vs_num = EXPECT['itf_vs'] if has_audio else EXPECT['itf_vs_dbg']

    # 1) IAD：uvcvideo 靠它把 VC+VS 成组绑定；bFunctionClass 必须是 VIDEO(0x0E)
    iad = next((d for _, t, d in items
                if t == DESC_IAD and d[4] == 0x0E), None)
    check(iad is not None, '缺 UVC 的 IAD（bFunctionClass=0x0E）')
    check(iad[2] == vc_num and iad[3] == 2,
          f'UVC IAD 应从 IF{vc_num} 起覆盖 2 个接口，实际 first={iad[2]} count={iad[3]}')
    check(iad[5] == 0x03, f'bFunctionSubClass 应为 VIDEO_INTERFACE_COLLECTION(3)，实际 {iad[5]}')

    # 2) VideoControl：**必须零端点**（第 5 条 IN 端点会撞 dcd_dwc2 的 TU_ASSERT，且无日志）
    vc = itf_by(vc_num)
    check(vc[4] == 0, f'VideoControl 的 bNumEndpoints={vc[4]}，必须是 0（IN 端点已用满 4/4）')
    check((vc[5], vc[6]) == (0x0E, 0x01), 'VideoControl 的 class/subclass 应为 0x0E/0x01')
    check(itf_eps[(vc_num, 0)] == set(), 'VideoControl 不得带任何端点')

    # 3) VC 头：bcdUVC、wTotalLength、baInterfaceNr
    vch = next((d for _, t, d in items
                if t == DESC_CS_INTERFACE and d[2] == VC_HEADER and len(d) >= 13
                and (d[3], d[4]) == (0x50, 0x01)), None)
    check(vch is not None, '缺 VideoControl 的 CS 头（bcdUVC 应为 0x0150）')
    n_coll = vch[11]
    check(n_coll == 1, f'bInCollection 应为 1（只有一个 VS 接口），实际 {n_coll}')
    check(vch[12] == vs_num, f'baInterfaceNr 应指向 IF{vs_num}，实际 {vch[12]}')
    # wTotalLength 少算一条，host 就在解析到一半时停下，后面的实体静默消失
    inner = sum(ln for ln, t, d in items
                if t == DESC_CS_INTERFACE and d[2] in (VC_INPUT_TERM, VC_OUTPUT_TERM)
                and len(d) > 3 and d[3] in (EXPECT['uvc_cam_term'], EXPECT['uvc_out_term']))
    check(u16(vch, 5) == len(vch) + inner,
          f'VC 头的 wTotalLength={u16(vch, 5)}，应为 {len(vch) + inner}（头 + 两个端子）')

    # 4) 端子链：Camera(ID1) → Output(ID2)，且 Output 的 bSourceID 指回 ID1
    cam = next((d for _, t, d in items if t == DESC_CS_INTERFACE
                and d[2] == VC_INPUT_TERM and d[3] == EXPECT['uvc_cam_term']), None)
    out = next((d for _, t, d in items if t == DESC_CS_INTERFACE
                and d[2] == VC_OUTPUT_TERM and d[3] == EXPECT['uvc_out_term']), None)
    check(cam is not None and u16(cam, 4) == VIDEO_ITT_CAMERA,
          'ID1 应为 Camera Terminal(wTerminalType=0x0201)')
    check(out is not None and u16(out, 4) == VIDEO_TT_STREAMING,
          'ID2 应为 USB Streaming 输出端子(wTerminalType=0x0101)')
    check(out[7] == EXPECT['uvc_cam_term'],
          f'输出端子的 bSourceID={out[7]}，应为 {EXPECT["uvc_cam_term"]}（视频链断了）')

    # 5) VideoStreaming：alt 0 零端点（带宽零和的落点）、alt 1 恰一条 ISO IN
    check(itf_eps[(vs_num, 0)] == set(),
          'VideoStreaming alt 0 必须零端点 —— host 不开摄像头时不预留 ISO 带宽')
    check(itf_eps[(vs_num, 1)] == {EXPECT['ep_uvc']},
          f'VideoStreaming alt 1 应恰有一条端点 0x{EXPECT["ep_uvc"]:02X}')
    ep = next(d for _, t, d in items if t == DESC_ENDPOINT and d[2] == EXPECT['ep_uvc'])
    check(ep[0] == 7,
          f'UVC 的 ISO 端点描述符应为 7 字节（标准端点），实际 {ep[0]} —— '
          '9 字节是 UAC1 的形式，说明有人手写错了')
    check(ep[3] & 0x03 == 0x01, 'UVC 端点必须是 isochronous')
    check((ep[3] >> 2) & 0x03 == 0x01,
          'UVC 端点的 sync 类型应为 asynchronous（TUD_VIDEO_DESC_EP_ISO 写死的值）')
    check(u16(ep, 4) == EXPECT['ep_uvc_pkt'],
          f'UVC 端点 wMaxPacketSize={u16(ep, 4)}，应为 {EXPECT["ep_uvc_pkt"]}；'
          'DWC2 的 dfifo 只剩 123 words=492 字节，超了会静默 STALL')
    check(ep[6] == 1, 'bInterval 应为 1（每个 USB 帧一包）')

    # 6) VS 输入头：bEndpointAddress、bTerminalLink、wTotalLength
    vsh = next((d for _, t, d in items if t == DESC_CS_INTERFACE
                and d[2] == VS_INPUT_HEADER), None)
    check(vsh is not None, '缺 VideoStreaming 的输入头')
    check(vsh[3] == 1, f'bNumFormats 应为 1，实际 {vsh[3]}')
    check(vsh[6] == EXPECT['ep_uvc'],
          f'VS 头里的 bEndpointAddress=0x{vsh[6]:02X}，应为 0x{EXPECT["ep_uvc"]:02X}')
    check(vsh[8] == EXPECT['uvc_out_term'],
          f'bTerminalLink={vsh[8]}，应指向输出端子 ID{EXPECT["uvc_out_term"]}')
    check(vsh[9] == 0, 'bStillCaptureMethod 应为 0（不做静态抓拍）')
    fmt = next(d for _, t, d in items if t == DESC_CS_INTERFACE and d[2] == VS_FORMAT_MJPEG)
    frm = next(d for _, t, d in items if t == DESC_CS_INTERFACE and d[2] == VS_FRAME_MJPEG)
    color = next(d for _, t, d in items if t == DESC_CS_INTERFACE and d[2] == VS_COLORFORMAT)
    check(u16(vsh, 4) == len(vsh) + len(fmt) + len(frm) + len(color),
          'VS 头的 wTotalLength 与「头 + 格式 + 帧 + 色彩匹配」不符')

    # 7) 格式与帧：MJPEG、640×360、单一离散帧间隔、dwMaxVideoFrameBufferSize
    check(fmt[3] == 1 and fmt[4] == 1, 'bFormatIndex/bNumFrameDescriptors 都应为 1')
    check(frm[3] == 1, 'bFrameIndex 应为 1')
    check(u16(frm, 5) == EXPECT['uvc_w'] and u16(frm, 7) == EXPECT['uvc_h'],
          f'帧尺寸应为 {EXPECT["uvc_w"]}×{EXPECT["uvc_h"]}，'
          f'实际 {u16(frm, 5)}×{u16(frm, 7)}')
    max_frame = int.from_bytes(frm[17:21], 'little')
    interval = int.from_bytes(frm[21:25], 'little')
    n_intv = frm[25]
    check(n_intv == 1,
          f'bFrameIntervalType 应为 1（单一离散间隔），实际 {n_intv} —— '
          '连续区间会让 video_device.c 的默认值协商走进"什么都不填"的分支')
    check(interval == EXPECT['uvc_interval'],
          f'dwDefaultFrameInterval={interval}，应为 {EXPECT["uvc_interval"]}'
          f'（{EXPECT["uvc_interval"] // 10000} ms ⇒ {10000000 // EXPECT["uvc_interval"]} fps）')
    check(int.from_bytes(frm[26:30], 'little') == interval,
          '唯一的那个离散帧间隔与 dwDefaultFrameInterval 不一致')
    check(max_frame == EXPECT['uvc_max_frame'],
          f'dwMaxVideoFrameBufferSize={max_frame}，应为 {EXPECT["uvc_max_frame"]}')
    # ★ 那条静默的带宽陷阱：max_frame/interval_ms + 2 必须 > 端点包大小，
    #   否则 TinyUSB 会把每包缩小，带宽白掉一截而哪里都不报错
    interval_ms = interval // 10000
    check(max_frame // interval_ms + 2 > EXPECT['ep_uvc_pkt'],
          f'dwMaxVideoFrameBufferSize 太小：{max_frame}/{interval_ms}+2='
          f'{max_frame // interval_ms + 2} ≤ {EXPECT["ep_uvc_pkt"]}，'
          'TinyUSB 会把 dwMaxPayloadTransferSize 缩到这个值（video_device.c:562-567）')
    check(color[3] == 0x01, 'bColorPrimaries 应为 BT.709')
```

- [x] **Step 4：`main()` 里挂上 UVC 检查，并把「IN 端点 ≤ 4」升级成「恰好 4 且含 0x84」**

既有那条 `check(len(in_eps) <= 4, ...)` 改成：

```python
    in_addrs = sorted(d[2] for d in eps if d[2] & 0x80)
    check(in_addrs == [0x81, 0x82, 0x83, 0x84],
          f'IN 端点应恰为 [0x81,0x82,0x83,0x84]（4/4 用满），实际 {[hex(a) for a in in_addrs]}')
    iso_in = [d for d in eps if d[2] & 0x80 and d[3] & 0x03 == 0x01]
    check(EXPECT['ep_uvc'] in {d[2] for d in iso_in},
          '0x84 必须是 UVC 的 ISO IN —— 它是最后一条可用 IN 端点')
```

以及在末尾的汇总行里加上 UVC 的一行输出：

```python
    print(f'  UVC: MJPEG {EXPECT["uvc_w"]}×{EXPECT["uvc_h"]} @ '
          f'{10000000 // EXPECT["uvc_interval"]} fps, ISO IN 0x{EXPECT["ep_uvc"]:02X} '
          f'× {EXPECT["ep_uvc_pkt"]} B/帧 = {(EXPECT["ep_uvc_pkt"] - 2) } B/ms 有效载荷')
```

- [x] **Step 5：跑一遍并提交**（本任务**不上板**）

```
git commit -m "feat(tab5-fw): check_usb_desc.py 扩展到 UVC 描述符 (P4 Task2)"
```

---

## Task 3：UVC 调试档（CDC 换掉音频）+ FIFO 实测代码（不上板）

目标：解决 `CONFIG_AIO_DEBUG_CDC` 与 UVC 抢 `0x84` 的冲突，并把 P3 一直没实现的「读 DWC2 寄存器实测 FIFO」补上 —— UVC 阶段正是余量真正吃紧的时候。

**Files:** Modify `main/usb_descriptors.{c,h}`、`main/Kconfig.projbuild`、`main/app_main.c`、`main/CMakeLists.txt`、`test/check_usb_desc.py`、`sdkconfig.defaults`

- [x] **Step 1：成功判据**（两档都编译 + 脚本两档都过，**不上板**）

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh
rm -f sdkconfig && idf.py build && python3 test/check_usb_desc.py build/tab5_aio.elf
# → 7 接口 / 384 字节 / IN=[81,82,83,84] / UVC ISO IN 0x84 / OK

idf.py fullclean && rm -f sdkconfig
sed -i.bak 's/^#CONFIG_AIO_DEBUG_CDC=y/CONFIG_AIO_DEBUG_CDC=y/' sdkconfig.defaults
idf.py build && python3 test/check_usb_desc.py build/tab5_aio.elf
# → 6 接口 / 259 字节 / IN=[81,82,83,84] / 无音频 IAD / UVC 在 IF2/IF3 / OK
mv sdkconfig.defaults.bak sdkconfig.defaults && idf.py fullclean && rm -f sdkconfig
```

> ⚠️ 改过 `Kconfig.projbuild` 之后**必须连 build 目录一起删**（`idf.py fullclean` 或 `rm -rf build sdkconfig`），
> 否则 `sdkconfig.h` 不重新生成，新配置项在 C 里报 `undeclared`。README 已有此条。

**外加一条硬判据（硬约束 D 的落点）**：默认档的 `aio_desc_configuration` 里，
**偏移 9 起的 232 字节（vendor 23 + HID 25 + UAC1 184）必须与 P3 的 HEAD 逐字节相同**。
用现成的脚本对比：

```bash
git stash && idf.py build && python3 - <<'EOF' > /tmp/p3.hex
import sys; sys.path.insert(0, 'test')
from check_usb_desc import symbol_bytes
print(symbol_bytes('build/tab5_aio.elf', 'aio_desc_configuration')[9:9+232].hex())
EOF
git stash pop && idf.py build && python3 - <<'EOF' > /tmp/p4.hex
import sys; sys.path.insert(0, 'test')
from check_usb_desc import symbol_bytes
print(symbol_bytes('build/tab5_aio.elf', 'aio_desc_configuration')[9:9+232].hex())
EOF
diff /tmp/p3.hex /tmp/p4.hex && echo "✅ vendor/HID/UAC 三段逐字节未变"
```

（`check_usb_desc.py` 目前在模块末尾直接 `main()`，本步顺手把它改成
`if __name__ == '__main__': main()` —— 这样它既能当脚本跑，也能被 import 复用
`symbol_bytes()`。这是本步唯一对脚本既有行为的改动。）

- [x] **Step 2：`usb_descriptors.h` 的 `AIO_HAS_AUDIO` 与调试档端点重排**

把 Task 1 那条临时 `#error` 换成真正的重排：

```c
/*
 * ── AIO_HAS_AUDIO：UVC 调试档为什么必须关掉音频 ─────────────────────
 *
 * 这块板现场没有开箱即用的串口（USJ 被 TinyUSB 收走、UART0 只在 M5-Bus 排针上），
 * 唯一不接外设的日志通道是 USB CDC —— 而 CDC 要 **2 条 IN 端点**（通知 + 数据）。
 *
 * P3 那一档的做法是「让出 vendor IN 0x81 + 借走 UVC 预留的 0x84」。**UVC 落地后
 * 这条路走不通了**：0x84 已经是视频流本身，借走它等于关掉被调试的对象。
 *
 * 新的账：让出 vendor IN(0x81) 腾 1 条 + **整个音频功能不编译**腾出 0x83，
 * CDC 拿 0x81(数据) 与 0x83(通知)，0x84 **原封不动留给 UVC**：
 *
 * | 0x81 | 0x82 | 0x83 | 0x84 |
 * |------|------|------|------|
 * | CDC 数据 IN | HID | CDC 通知 | **UVC 视频流（不变）** |
 *
 * FIFO 也宽裕（dfifo 顶 242 words）：
 *   RX 62 + EP0 16 + CDC 数据 IN 16 + HID 16 + CDC 通知(8B) 2 = 112
 *   ⇒ 余 130 words = 520 字节 ≥ UVC 要的 112 words，比默认档还多 7 words。
 *
 * ⚠️ **代价：这一档下完全没有音频** —— host 侧 /proc/asound/cards 里没有这块设备，
 *    aplay/arecord 都不列它，喇叭与双麦全不工作。这是排障档，不是产品档。
 * ⓘ **有 USB-TTL 就别用这一档**：接 UART0(G37/G38) 零端点代价、能抓上电最早的
 *    日志、而且默认档（音频在）也能用。本档是「手边只有一根 USB-C 线」时的替代品。
 */
#if CONFIG_AIO_DEBUG_CDC
#define AIO_HAS_AUDIO 0
#else
#define AIO_HAS_AUDIO 1
#endif

#define EPNUM_VENDOR_OUT 0x01
#if AIO_HAS_AUDIO
#define EPNUM_VENDOR_IN  0x81      /* 声明但从不使用，见下方 CONFIG_AIO_DEBUG_CDC 段 */
#define EPNUM_AUDIO_OUT  0x02      /* ISO OUT，播放 */
#define EPNUM_AUDIO_IN   0x83      /* ISO IN，录音 */
#endif
#define EPNUM_HID        0x82
#define EPNUM_UVC_IN     0x84      /* ISO IN，视频流。**两档都是这一条，不再出借** */

#if CONFIG_AIO_DEBUG_CDC
#define EPNUM_CDC_IN     0x81      /* 原 vendor IN 空出来的那一条 */
#define EPNUM_CDC_NOTIF  0x83      /* 原 UAC 录音空出来的那一条（音频整体不编译） */
#define EPNUM_CDC_OUT    0x03
#endif

/* 直接开 CONFIG_TINYUSB_CDC_ENABLED 仍然是编译期错误：esp_tinyusb 默认给它的
 * 端点是 0x83/0x84，与 UVC 直接撞号。正确入口是 CONFIG_AIO_DEBUG_CDC。 */
#if CONFIG_TINYUSB_CDC_ENABLED && !CONFIG_AIO_DEBUG_CDC
#error "要 USB 日志串口请开 CONFIG_AIO_DEBUG_CDC（Tab5 All-in-One 菜单里），它会让出 GUD 的 IN 端点并关掉音频来腾端点；不要直接开 CONFIG_TINYUSB_CDC_ENABLED（它默认占 0x83/0x84，与 UVC 撞号）"
#endif
#if CONFIG_AIO_DEBUG_CDC && !CONFIG_TINYUSB_CDC_ENABLED
#error "CONFIG_AIO_DEBUG_CDC 需要 CONFIG_TINYUSB_CDC_ENABLED（正常由 Kconfig 的 select 保证；手改 sdkconfig 时会掉）"
#endif
#if CONFIG_AIO_DEBUG_CDC && AIO_HAS_AUDIO
#error "UVC 调试档必须关掉音频才腾得出 IN 端点（0x83 要给 CDC 通知）"
#endif
```

`UAC_*` 那批参数常量与 `UAC_FU_ID_SPEAKER` **保持无条件定义**（它们只是数字，被 `#if` 掉的是描述符与代码）—— 这样 `codec_audio.c` 里那些 `_Static_assert` 不必也跟着加条件。

- [x] **Step 3：`usb_descriptors.c` / `app_main.c` / `CMakeLists.txt` 的音频条件编译**

三处，都用 `#if AIO_HAS_AUDIO` 包住，**函数体一行不改**：

1. `usb_descriptors.c`：`UAC1_AUDIO_DESCRIPTOR(...)` 那一项（Task 1 已做）+ 新增
   `#if AIO_HAS_AUDIO` / `#define AIO_AUDIO_DESC_LEN UAC1_AUDIO_DESC_LEN` / `#else` /
   `#define AIO_AUDIO_DESC_LEN 0` / `#endif`；UAC1 那一大段宏定义本身**不用包**
   （只是宏，不展开就不占空间）；
2. `app_main.c`：`codec_audio_init()` / `codec_audio_start()` / `codec_audio_report()`
   三处调用与 `#include "codec_audio.h"` 包进 `#if AIO_HAS_AUDIO`。
   **⚠️ `route_fsls_phy0_to_otg()` 与 `otg_fsls_pads_repair()` 一个都不要动** ——
   前者是 USB-C 能枚举的前提（与音频无关），后者虽然只在音频配过 G26/G27 时才有事可做，
   但它是幂等的，留着零成本，且日后有人在调试档下手工配那两个脚时它仍是唯一的救命稻草；
3. `CMakeLists.txt`：`codec_audio.c` / `audio_frame.c` / `uac_volume.c` 三个源文件
   在调试档下不编译。用 `if(NOT CONFIG_AIO_DEBUG_CDC)` 拼 `SRCS` 列表，
   并把 `esp_driver_i2s` 从 `PRIV_REQUIRES` 里一并去掉（省约 23 KB flash，
   顺带证明这一档真的没有音频）。

> ⓘ **为什么不给音频单独一个 Kconfig 开关**（比如 `CONFIG_AIO_NO_AUDIO`）：
> 那会造出第四种组合（无音频 + 无 CDC），它既没有用途也要跟着维护判据。
> P3 的教训写得很清楚 —— **分阶段旋钮只应在一次排障会话里存在**。
> 这里只有两档，`AIO_HAS_AUDIO` 是 `CONFIG_AIO_DEBUG_CDC` 的反相，不是独立自由度。

- [x] **Step 4：`Kconfig.projbuild` 改写说明**

把现有 `AIO_DEBUG_CDC` 的 prompt 与 help 改成 UVC 时代的版本（端点表换成新的、明写「本档下没有音频」、明写「有 USB-TTL 就接 UART0」）。prompt 改为：

```
config AIO_DEBUG_CDC
    bool "UVC 调试档：让出 GUD 的 IN 端点 + 关掉音频，换 USB CDC 日志串口"
```

- [x] **Step 5：`app_main.c` 加 DWC2 FIFO 占用实测**

P3 Task 6 Step 2 留着没实现的那段代码，本步真正落地 —— **UVC 阶段余量只剩 123 words，这是必须变成数字的时候**。代码照 P3 计划里那份，改三处：注释更新到 242 words 的口径、循环覆盖 `0x84`、并把「剩余是否够 UVC」直接判出来：

```c
#include "soc/usb_dwc_struct.h"

/*
 * 实测 DWC2 的 FIFO 分配。P4 全速控制器整块 SPRAM 只有 256 words(1 KB)，而且
 * **buffer DMA 模式下还要先扣掉 2×ep_count = 14 words**（dcd_dwc2.c:260-263，
 * is_dma 成立：CONFIG_TINYUSB_MODE_DMA=y 且 P4 的 OTG11_ARCHITECTURE=2=内部 DMA）
 * ⇒ 真正可分配的只有 **242 words**。这块要装下共享 RX FIFO + 每条 IN 端点的
 * TX FIFO。不够时 dfifo_alloc() 只是 TU_ASSERT 返回 false，**默认日志等级下
 * 一个字都不打** —— 症状是 SET_INTERFACE 被 STALL、某个接口静默不工作。
 *
 * 布局（dcd_dwc2.c 顶部大注释）：地址 0 起是 RX FIFO，顶部往下依次是 EP0 IN、
 * EP1 IN… 的 TX FIFO，中间那段是空闲。空闲 = 最低的 TX 起始地址 − RX 大小。
 *
 * ⚠️ 必须等 host 完成 SET_CONFIGURATION 之后再读：端点是那时才 open、
 *    FIFO 是那时才分配的。调用点在 app_main 末尾的空转循环里，tud_mounted() 后一次性触发。
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
    const unsigned free_words = (unsigned)(lowest - rx);
    ESP_LOGI(TAG, "FIFO: 已用 %u words，空闲 %u words (%u 字节)；UVC 端点占 %u words",
             used, free_words, free_words * 4,
             (unsigned)((UVC_EP_SIZE + 3) / 4));
    /* 静态验算说默认档应当是 已用 231 / 空闲 11。差得多就说明账算错了，
     * 或者有人偷偷加了端点 —— 把数字打出来比断言更有用，因为断言炸了也没人看得见。 */
}
```

- [x] **Step 6：`check_usb_desc.py` 支持两档**

脚本已经按「描述符里有没有 CDC IAD」自动判定档位（P3 就是这么写的）。本步把这个判定扩成三元组：

```python
    has_cdc   = any(t == DESC_IAD and d[4] == 0x02 for _, t, d in items)   # CDC 的 IAD
    has_audio = any(t == DESC_IAD and d[4] == 0x01 for _, t, d in items)   # AUDIO 的 IAD
    check(has_audio != has_cdc,
          '音频与 CDC 必须恰好有一个：默认档有音频无 CDC，UVC 调试档有 CDC 无音频'
          '（两者抢同一条 IN 端点 0x83）')
    print(f'  档位：{"UVC 调试档（无音频，CDC 日志串口）" if has_cdc else "默认档（GUD+HID+UAC+UVC）"}')
```

既有那批音频断言全部包进 `if has_audio:`；`n_itf` 期望值改成 `7 if has_audio else 6`；
CDC 的端点期望改成 `ep_cdc_notif = 0x83`（原来是 `0x84`）。

- [x] **Step 7：`sdkconfig.defaults` 的注释更新**

那段解释 `#CONFIG_AIO_DEBUG_CDC=y` 代价的注释要改：现在的代价是「让出 GUD 的 IN 端点 **+ 整个音频功能不编译**」，不再是「借走 UVC 的 0x84」。

- [x] **Step 8：两档编译 + 脚本 + 逐字节 diff，提交**

```
git commit -m "feat(tab5-fw): UVC 调试档改为让出音频换 CDC，0x84 永久归 UVC；补 DWC2 FIFO 实测 (P4 Task3)"
```

---

## Task 4：合成图案纯函数 + 静态测试图 JPEG（全宿主机，不上板）

目标：造出 Task 5 那张「假数据」。**这一步刻意不碰任何 ESP-IDF API** —— 它产出的东西有两个用途，一前一后：

1. **现在**：渲染成 PPM → 用 `ffmpeg` 压成一张 640×360 的 JPEG → 机械转成 `uvc_test_jpeg.h`，给 Task 5 的「静态图 MJPEG 流」当帧源；
2. **Task 6**：同一份 `uvc_pattern.c` 编进固件，在**片上**渲染 RGB565 喂给硬件 JPEG 编码器 —— 于是「静态图能显示」与「片上编码能显示」两步之间**只差编码器这一个变量**，出问题时可以直接归因。

抽成零依赖纯函数的理由与 `kbd_translate.c` / `touch_map.c` / `audio_frame.c` / `standby_screen.c` 完全一致：图案画错了在 host 侧只表现为「颜色不对 / 有一条黑边 / 方块跑到画面外」，从现象几乎反推不出来，而在宿主机上验几乎零成本 —— 而且能**直接看图**。

**Files:** Create `main/uvc_pattern.{c,h}`、`test/test_uvc_pattern.c`、`test/jpeg_to_header.py`、`main/uvc_test_jpeg.h`；Modify `main/CMakeLists.txt`

- [x] **Step 1：成功判据**

```bash
cd firmware/test
cc -std=c11 -Wall -Wextra -Werror -I../main test_uvc_pattern.c ../main/uvc_pattern.c \
    -o /tmp/tp && /tmp/tp /tmp/pattern.ppm
# → OK (N cases)，并导出 /tmp/pattern.ppm
```

1. 全部用例通过；
2. `/tmp/pattern.ppm` 用看图软件打开：**8 根竖直色条 + 一个白方块 + 底部一条随帧号变化的灰阶带**，无黑边、无错位；
3. 生成的 `main/uvc_test_jpeg.h` 里数组大小在 **12 KB–44 KB** 之间（下限是「JPEG 至少得有内容」，上限是硬约束 B 的每帧预算 44.6 KB）。

- [x] **Step 2：`main/uvc_pattern.h`**

```c
#pragma once
/*
 * UVC 测试图案：8 根竖直色条 + 一个随帧号右移的白方块 + 底部灰阶带。
 *
 * 纯函数，不依赖 ESP-IDF —— 与 kbd_translate.c / touch_map.c / audio_frame.c /
 * standby_screen.c 同样的理由：画错了在 host 侧只表现为「颜色不对 / 有黑边 /
 * 方块跑出画面」，从现象反推不出来；而在宿主机上不但能断言，还能直接导 PPM 看图。
 * 见 firmware/test/test_uvc_pattern.c。
 *
 * 两个用途，一前一后：
 *  ① 宿主机渲染 → ffmpeg 压成 JPEG → uvc_test_jpeg.h，给 P4 Task5 的静态图流用；
 *  ② P4 Task6 起编进固件，在片上渲染 RGB565 喂给硬件 JPEG 编码器。
 * 于是「静态图能显示」与「片上编码能显示」之间只差编码器一个变量。
 *
 * 图案的三个元素各有诊断用途，不是好看：
 *  - **色条**：颜色顺序错 ⇒ RGB565 的字节序或 R/B 通道搞反了（这在 host 侧
 *    只表现为"颜色怪怪的"，对着色条一眼可辨）；
 *  - **移动方块**：ffplay 里方块不动 ⇒ 帧根本没在更新（host 在重复显示同一帧）；
 *    方块跳跃/回退 ⇒ 丢帧；方块被撕成两半 ⇒ 帧缓冲在编码时被改写了；
 *  - **底部灰阶带**：每帧亮度加一档，截图就能读出帧号，用来核对实测帧率。
 */
#include <stdint.h>
#include <stddef.h>

/* 色条根数。640 = 8 × 80，每根 80 像素宽，整除，没有余数条。 */
#define UVC_PATTERN_BARS 8

/*
 * 把第 frame_no 帧渲染成紧凑排列的 RGB565（stride = w，无 padding，小端），
 * 写入 dst 的前 w*h 个 uint16_t。
 *
 * w 必须能被 UVC_PATTERN_BARS 整除，h 必须 ≥ 32（底部灰阶带占 16 行，
 * 方块 40×40 需要余下的空间）；不满足时**不写任何字节**并返回 false ——
 * 静默画半张图比不画更难查。
 * frame_no 只用于方块位置与灰阶带亮度，任意 uint32_t 都合法（自动回绕）。
 */
bool uvc_pattern_render(uint16_t *dst, int w, int h, uint32_t frame_no);

/* 方块左上角的 x 坐标（供测试断言与 host 侧核对）。纯算术，无副作用。 */
int uvc_pattern_square_x(int w, uint32_t frame_no);
```

- [x] **Step 3：`main/uvc_pattern.c`**

```c
#include "uvc_pattern.h"

#define SQ   40      /* 方块边长 */
#define BAND 16      /* 底部灰阶带高度 */
#define STEP 16      /* 方块每帧右移的像素数：10 fps 下 1.6 s 扫完 640 宽 */

/* RGB565 小端。与 display_dsi.c 的取用方式一致（BSP_LCD_BIGENDIAN=0），
 * 这里不做任何 byteswap —— 硬件 JPEG 编码器的 RGB565 输入也是小端。 */
static inline uint16_t rgb565(int r, int g, int b)
{
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3));
}

/* 标准彩条顺序（白→黄→青→绿→品红→红→蓝→黑）。顺序反了 ⇒ R/B 通道搞反。 */
static const uint16_t k_bars[UVC_PATTERN_BARS] = {
    0xFFFF,                    /* 白   */
    0xFFE0,                    /* 黄   R+G  */
    0x07FF,                    /* 青   G+B  */
    0x07E0,                    /* 绿   */
    0xF81F,                    /* 品红 R+B  */
    0xF800,                    /* 红   */
    0x001F,                    /* 蓝   */
    0x0000,                    /* 黑   */
};

int uvc_pattern_square_x(int w, uint32_t frame_no)
{
    const int span = w - SQ;                 /* 方块左上角的合法范围 [0, span] */
    if (span <= 0)
        return 0;
    /* 三角波：先右后左，永远不越界，也不会有"跳回原点"的突变（那会被误判成丢帧）。 */
    const uint32_t period = (uint32_t)(2 * span);
    const uint32_t t = (frame_no * (uint32_t)STEP) % period;
    return (int)(t < (uint32_t)span ? t : period - t);
}

bool uvc_pattern_render(uint16_t *dst, int w, int h, uint32_t frame_no)
{
    if (!dst || w <= 0 || h < 32 || (w % UVC_PATTERN_BARS) != 0)
        return false;

    const int bar_w = w / UVC_PATTERN_BARS;
    const int band_y = h - BAND;
    /* 灰阶带：每帧 +8，32 帧一循环。截图读亮度即可反推帧号。 */
    const int level = (int)((frame_no * 8u) & 0xFFu);
    const uint16_t band = rgb565(level, level, level);

    for (int y = 0; y < band_y; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = 0; x < w; x++)
            row[x] = k_bars[x / bar_w];
    }
    for (int y = band_y; y < h; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = 0; x < w; x++)
            row[x] = band;
    }

    /* 方块画在色条之上、灰阶带之上，纵向居中于色条区。 */
    const int sx = uvc_pattern_square_x(w, frame_no);
    const int sy = (band_y - SQ) / 2;
    for (int y = sy; y < sy + SQ; y++) {
        uint16_t *row = dst + (size_t)y * (size_t)w;
        for (int x = sx; x < sx + SQ; x++)
            row[x] = 0xFFFF;
    }
    return true;
}
```

- [x] **Step 4：`test/test_uvc_pattern.c`**

照 `test_standby_screen.c` 的形式：`main()` + `assert`，无框架，不挂 IDF 构建；带一个可选参数导出 PPM 供肉眼验收。用例至少覆盖：

1. **越界哨兵**：缓冲前后各放 8 个哨兵值，渲染后必须原样（`w*h` 之外一个字节都不许写）；
2. **拒绝非法参数**：`w` 不被 8 整除、`h < 32`、`dst == NULL` 三种情况都返回 `false` **且缓冲全是哨兵**（不是「画一半再返回」）；
3. **色条**：第 0 行上取 8 个采样点 `(bar_w/2 + i*bar_w, 0)`，逐个等于 `k_bars[i]`；且**相邻色条边界处的两个像素必须不同**（宽度算错时这条会炸）；
4. **灰阶带**：最后 16 行整行同色，且 `frame_no` 与 `frame_no+1` 的带色**不同**（否则截图读不出帧号）；
5. **方块**：`uvc_pattern_square_x()` 对 `frame_no = 0..1000` 全部落在 `[0, w-40]`（三角波不越界）；相邻帧的位移绝对值恒为 `STEP`（不许有跳变，那会被误判成丢帧）；方块四角在缓冲里确实是 `0xFFFF`；
6. **确定性**：同一个 `frame_no` 渲染两次逐字节相同（Task 6 会用它做「编码前后帧缓冲没被改写」的对照）。

PPM 导出（RGB565 → RGB888，与 `test_standby_screen.c` 同一段逻辑）：

```c
/* 用法：/tmp/tp [out.ppm]。给了路径才导出，不给就只跑断言 —— 与
 * test_standby_screen.c 一致。导出的是 frame_no = 3 那一帧（方块已经离开左边缘，
 * 灰阶带也不是全黑，一眼能看出三个元素都在）。 */
```

- [x] **Step 5：`test/jpeg_to_header.py` —— 机械转换，不手抄**

照 `panel_init_data.h` / `tab5_kbd_map.h` / `font8x16.h` 的先例：**vendor 进来的二进制一律用脚本转，不手抄**。

```python
#!/usr/bin/env python3
"""把一张 .jpg 机械转成 main/uvc_test_jpeg.h 的 C 数组。

为什么要有这个脚本而不是手贴：静态测试图有两万多字节，手工转换必然出错，
而错了的表现是 host 侧一张花图或者 ffplay 直接报 "Invalid JPEG"，
从现象反推不到"第 8137 个字节抄错了"。

生成流程（全部可重放，别改中间产物）：
    cd firmware/test
    cc -std=c11 -Wall -Wextra -Werror -I../main test_uvc_pattern.c \\
        ../main/uvc_pattern.c -o /tmp/tp && /tmp/tp /tmp/pattern.ppm
    ffmpeg -y -i /tmp/pattern.ppm -q:v 5 -pix_fmt yuvj422p /tmp/pattern.jpg
    python3 jpeg_to_header.py /tmp/pattern.jpg ../main/uvc_test_jpeg.h

    -q:v 5      ≈ 质量 70，与 cam_jpeg.c 的起始 image_quality 同档
    yuvj422p    与固件侧 JPEG_DOWN_SAMPLING_YUV422 一致（见计划的"子采样"一节）
"""
import pathlib
import sys

MIN_BYTES, MAX_BYTES = 12 * 1024, 44 * 1024


def main():
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    data = src.read_bytes()

    # JPEG 必须以 SOI(FFD8) 开头、EOI(FFD9) 结尾 —— uvcvideo 会把整个负载原样交给
    # 解码器，少了 EOI 的表现是"画面卡在半张图"，且没有任何错误信息。
    if data[:2] != b'\xff\xd8' or data[-2:] != b'\xff\xd9':
        raise SystemExit(f'{src} 不是完整的 JPEG（缺 SOI 或 EOI）')
    # 上限来自硬约束 B：10 fps × 446 B/ms ⇒ 每帧预算 44.6 KB。超了就是发不完，
    # 表现为实际帧率掉到声明值以下（而描述符仍然说 10 fps）。
    if not (MIN_BYTES <= len(data) <= MAX_BYTES):
        raise SystemExit(f'{src} 有 {len(data)} 字节，应落在 '
                         f'[{MIN_BYTES}, {MAX_BYTES}]（每帧带宽预算 44.6 KB）')

    rows = [', '.join(f'0x{b:02X}' for b in data[i:i + 12])
            for i in range(0, len(data), 12)]
    dst.write_text(
        '#pragma once\n'
        '/*\n'
        ' * UVC 静态测试图（MJPEG 640×360）。**机械生成，不要手改。**\n'
        ' *\n'
        ' * 来源：main/uvc_pattern.c 渲染 → ffmpeg -q:v 5 -pix_fmt yuvj422p\n'
        ' * 重新生成：见 test/jpeg_to_header.py 的文件头注释。\n'
        ' *\n'
        ' * 用途：P4 Task5 的「先用假数据把 USB 那一层证通」——\n'
        ' * 这一步里没有摄像头、没有 ISP、没有 JPEG 编码器，\n'
        ' * 只验证 TinyUSB 的 video class 能不能把一段现成的 JPEG 推给 uvcvideo。\n'
        ' */\n'
        '#include <stdint.h>\n\n'
        f'/* {len(data)} 字节，每帧带宽预算 44.6 KB（10 fps × 446 B/ms）。 */\n'
        'static const uint8_t k_uvc_test_jpeg[] = {\n'
        + ''.join(f'    {r},\n' for r in rows)
        + '};\n')
    print(f'OK — {len(data)} 字节 → {dst}')


if __name__ == '__main__':
    main()
```

> ⓘ **为什么静态图也要走 4:2:2**：Task 6 换成片上编码时，若两边的子采样不同，
> 「换了之后图变了」就同时有「编码器」与「子采样」两个变量。保持一致，只留一个变量。

- [x] **Step 6：`main/CMakeLists.txt` 加 `uvc_pattern.c`，编译 + 跑测试 + 提交**

```
git commit -m "feat(tab5-fw): UVC 测试图案纯函数与静态测试图 JPEG (P4 Task4)"
```

---

## Task 5：静态图 MJPEG 流上板 —— ⛔ **判定点**

目标：**只用假数据把 USB 那一层证通。** 这一步里**没有摄像头、没有 ISP、没有 JPEG 编码器、没有 PPA** —— 帧源是 flash 里那 20 KB 常量。过了这一步才动摄像头；过不去就按「放弃判定点」砍掉 UVC。

> 这是本项目反复验证过的教训（P1 的键盘映射、P2 的触摸 INT、P3 的 I2S 全双工都是这么定位的）：
> **UVC over TinyUSB 是 spec 明说的「全场风险最高」项，而摄像头 bring-up 本身也是个大工程。
> 两者同时上，出问题时无法归因。**

**Files:** Create `main/uvc_stream.{c,h}`；Modify `main/app_main.c`、`main/CMakeLists.txt`

- [x] **Step 1：成功判据（host 侧，三条，缺一不可）**

先在 **UVC 调试档**（`CONFIG_AIO_DEBUG_CDC=y`，有 CDC 日志、无音频）跑一遍拿 FIFO 数字与 TinyUSB 日志，再在**默认档**跑一遍做真正的判定。

```bash
# ── 默认档 ──
lsusb -v -d 16d0:10a9 | grep -A6 -iE "video|iad|isochronous"
sudo dmesg | grep -i uvcvideo          # uvcvideo: Found UVC 1.50 device flange Tab5 ...
ls /dev/video*
v4l2-ctl -d /dev/videoN --list-formats-ext
v4l2-ctl -d /dev/videoN --all | grep -iE "width|height|pixelformat|frames"
ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
```

判据：

1. `dmesg` 出现 `uvcvideo: Found UVC 1.50 device`，`/dev/videoN` 出现（**通常会出两个节点，videoN 与 videoN+1** —— 后者是 metadata 节点，正常现象，`v4l2-ctl --list-formats-ext` 在它上面会报空，别当故障）；
2. `v4l2-ctl --list-formats-ext` 报 `[0]: 'MJPG'` + `Size: Discrete 640x360` + `Interval: Discrete 0.100s (10.000 fps)`；
3. `ffplay` **稳定显示 Task 4 那张彩条图**（静态帧源 ⇒ 方块不动是**预期**的），连续 60 秒不断流、`dmesg` 无 `uvcvideo` 报错；
4. **GUD 显示、键盘、触摸、音频（默认档）全部照旧** —— `modetest -M gud` 出图、`evtest` 打字、`ABS_MT_*`、`aplay`/`arecord` 正常；
5. 调试档下 UART/CDC 打出的 `FIFO: 已用 … 空闲 …` 与静态验算吻合（默认档预期已用 **231** / 空闲 **11**；调试档预期已用 **224** / 空闲 **18**）。

- [x] **Step 2：`main/uvc_stream.h`**

```c
#pragma once
/*
 * UVC 视频流：把一份 JPEG 字节流按 10 fps 交给 TinyUSB 的 video class。
 *
 * 帧源是**可换的**，本文件只管「什么时候提交下一帧」与「提交给谁」：
 *   P4 Task5：flash 里的静态 JPEG（uvc_test_jpeg.h）—— 先用假数据把 USB 证通
 *   P4 Task6：片上硬件编码的合成图案（cam_jpeg.c + uvc_pattern.c）
 *   P4 Task9：真实摄像头（camera_csi.c → cam_jpeg.c）
 * 每一步只换帧源，USB 侧一行不动 —— 出问题时变量只有一个。
 */
#include "esp_err.h"
#include <stdbool.h>

/* 起帧泵任务。须在 tinyusb_driver_install() 之后调用（任务一起来就会调 tud_video_*）。
 * 与键盘/触摸/音频同一处置原则：失败只降级、不拦启动。 */
esp_err_t uvc_stream_start(void);

/* host 是否已选中 VideoStreaming 的 alt 1（= 摄像头真的被打开了）。
 * 实现就是一句 tud_video_n_streaming(0, 0)，单独暴露是为了让
 * uvc_stream_report() 与将来的自检有一个不必知道 ctl/stm 索引的入口。
 * ⓘ CSI 的按需启停（spec §2.1「带宽零和」在 PSRAM 侧的落点）在帧泵任务**内部**
 *   完成，直接用 tud_video_n_streaming()，不绕这个函数 —— 见 P4 Task9 Step4。 */
bool uvc_stream_is_streaming(void);

/* 自检快照打一遍（提交帧数、超期帧数、编码失败数、当前帧字节数）。
 * 与 codec_audio_report() 同构：默认档打一次，CDC 调试档下每 10 秒复读。 */
void uvc_stream_report(void);
```

- [x] **Step 3：`main/uvc_stream.c` 的类回调与帧泵**

```c
#define UVC_CTL_IDX   0    /* 只有一个 VideoControl 功能（CFG_TUD_VIDEO == 1） */
#define UVC_STM_IDX   0    /* 它下属唯一一个 VideoStreaming 接口 */

#define UVC_TASK_STACK_SIZE 4096
/*
 * 与 TinyUSB 的任务同优先级（esp_tinyusb 的 TINYUSB_DEFAULT_TASK_PRIO = 5），
 * 与 P3 的音频数据泵取同一个值、同一个理由：本任务绝大部分时间阻塞在
 * vTaskDelayUntil() 上，没有理由压过 USB 栈；同优先级下时间片轮转，都不会饿死。
 * 若 Task 10 的复合回归发现显示掉帧，降到 4 再测。
 */
#define UVC_TASK_PRIORITY   5

static volatile bool     s_xfer_in_flight;   /* 一帧在飞：video_device.c 一次只收一帧 */
static volatile uint32_t s_frames_sent, s_frames_late, s_frames_dropped;

/*
 * host 提交 COMMIT 时到。四个可选回调（video_device.c:205-227 全是 TU_ATTR_WEAK）
 * 里我们只实现两个：这一个用来把协商结果记下来，另一个用来放飞行标志。
 *
 * ⚠️ 这里**只记录、不做任何耗时的事**：它跑在 USB 控制传输的处理路径上，
 * 阻塞会让 SET_CUR 超时，host 侧表现为 "Failed to set VS commit" 然后放弃。
 * 真正的启停（CSI start/stop）交给帧泵任务按 tud_video_n_streaming() 判断。
 */
int tud_video_commit_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx,
                        video_probe_and_commit_control_t const *param)
{
    (void)ctl_idx; (void)stm_idx;
    /*
     * dwMaxPayloadTransferSize 是 TinyUSB **算出来**的（不是我们填的）：
     *     min(ceil(dwMaxVideoFrameSize/interval_ms) + 2, CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE)
     * 它就是每毫秒真正能发多少字节。**这条日志是那个静默带宽陷阱唯一的现场证据**：
     * 它若小于 UVC_EP_SIZE，说明 dwMaxVideoFrameBufferSize 声明小了，
     * 带宽白掉一截而哪里都不会报错（usb_descriptors.h 有 _Static_assert 守着，
     * 但 host 有权在 COMMIT 里填更小的 dwMaxVideoFrameSize，所以运行时也记一笔）。
     */
    s_commit_payload = param->dwMaxPayloadTransferSize;
    s_commit_frame_max = param->dwMaxVideoFrameSize;
    s_commit_interval = param->dwFrameInterval;
    return VIDEO_ERROR_NONE;
}

/* 一帧发完。只放标志，不在这里提交下一帧 —— 这个回调跑在 USB 中断上下文的
 * 延续里，提交下一帧意味着在这里做 memcpy/编码，会把 USB 栈钉住。 */
void tud_video_frame_xfer_complete_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx)
{
    (void)ctl_idx; (void)stm_idx;
    s_xfer_in_flight = false;
    s_frames_sent++;
}

static void uvc_pump_task(void *arg)
{
    (void)arg;
    TickType_t next = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(1000 / UVC_FPS);   /* 10 fps ⇒ 100 ms */

    while (1) {
        vTaskDelayUntil(&next, period);       /* 固定节拍，不受上一帧耗时影响 */

        if (!tud_mounted() || !tud_video_n_streaming(UVC_CTL_IDX, UVC_STM_IDX)) {
            /* host 停在 alt 0（没开摄像头）：什么都不做。ISO 带宽此刻**没有被预留**，
             * 12 Mbps 全归 GUD 的 bulk —— 这是 spec §2.1「带宽零和」的落点。 */
            s_xfer_in_flight = false;
            continue;
        }

        /*
         * 上一帧还没发完就跳过本拍，**不排队**。
         * 理由：video_device.c:1294 本来就会拒绝（stm->bufsize 非 0 时返回 false），
         * 而且视频丢一帧远比积压一串陈旧帧好 —— 积压会让画面越来越滞后，
         * 用户看到的是"延迟越来越大"，比掉帧难受得多，也难归因。
         * 20 KB 的帧在 446 B/ms 上要 45 ms，100 ms 的拍子有一倍余量；
         * 这个计数持续非零就说明帧太大了，去调 cam_jpeg.c 的 image_quality。
         */
        if (s_xfer_in_flight) {
            s_frames_late++;
            continue;
        }

        const uint8_t *buf; size_t len;
        if (!uvc_frame_source_get(&buf, &len)) {   /* Task5=静态图；Task6/9 换实现 */
            s_frames_dropped++;
            continue;
        }

        s_xfer_in_flight = true;
        if (!tud_video_n_frame_xfer(UVC_CTL_IDX, UVC_STM_IDX, (void *)buf, len)) {
            s_xfer_in_flight = false;
            s_frames_dropped++;
        }
    }
}
```

Task 5 的帧源实现就是两行（静态图**常驻 flash，不拷贝** —— `_prepare_in_payload()` 是
`memcpy` 取数，源在 flash 的 `.rodata` 里完全没问题）：

```c
#include "uvc_test_jpeg.h"

static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    *buf = k_uvc_test_jpeg;
    *len = sizeof(k_uvc_test_jpeg);
    return true;
}
```

> ⚠️ **`tud_video_n_frame_xfer()` 的缓冲在整帧发完之前不能被改写**（驱动只记指针，
> 分包时逐次 memcpy）。静态图在 flash 里天然满足；Task 6 起换成 PSRAM 缓冲时
> **必须双缓冲**，否则编码器会一边写、UVC 一边读同一块内存，表现为画面横向撕裂。
> 这条要在 Task 6 落地时写进 `cam_jpeg.c` 的注释。

- [x] **Step 4：`app_main.c` 调用**

在 `codec_audio_start()` 之后追加（处置原则与键盘/触摸/音频一致）：

```c
    err = uvc_stream_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "摄像头不可用(%s)，继续启动", esp_err_to_name(err));
```

并把 `uvc_stream_report()` 加进主循环里既有的那个 `#if CONFIG_AIO_DEBUG_CDC` 复读块，
以及默认档的那一次性打印（与 `codec_audio_report()` 并排）。

- [x] **Step 5：上板验证（先调试档，后默认档）**

按 Step 1 的两轮跑法。**两轮之间只改 `CONFIG_AIO_DEBUG_CDC` 一个变量**，别顺手改别的。

- [x] **Step 6：⛔ 判定点 —— 不成立时的排查顺序（穷尽这五步才允许宣布放弃）**

按「最可能 + 最便宜」排序，**不要跳步**：

1. **`lsusb -v` 根本没有 Video 段** ⇒ 描述符没进去。查 `check_usb_desc.py` 是否真的跑过这一版 ELF（`idf.py build` 之后重跑），以及 `CONFIG_TOTAL_LEN` 的 `_Static_assert` 有没有被 `idf.py build` 真正编译（`fullclean` 后重来）。
2. **`lsusb` 有 Video 段但 `dmesg` 没有 `uvcvideo`** ⇒ host 侧内核模块缺席。`modinfo uvcvideo`；缺就属 spec §9 那个阶段的工作（`flange_common.config` 的 `CONFIG_USB_VIDEO_CLASS`），**不是本阶段的固件缺陷**。先在一台有 `uvcvideo` 的机器上复验。
3. **`/dev/videoN` 出来了但 `ffplay` 无画面 / 立刻退出** ⇒ 分两种：
   - `dmesg` 报 `No valid video chain found` ⇒ 端子链断了（`bSourceID` / `bTerminalLink`），回 `check_usb_desc.py` 的第 4、6 条断言；
   - 报 `Failed to set VS commit` 或超时 ⇒ 协商失败。开调试档看 `tud_video_commit_cb` 的日志：`dwMaxPayloadTransferSize` 若不等于 448，就是 `dwMaxVideoFrameBufferSize` 那个陷阱（见「关键事实」）。
4. **协商过了但一帧都不出（`v4l2-ctl --stream-mmap` 卡住）** ⇒ 端点没开或 FIFO 没分到。看调试档的 `FIFO:` 那几行 —— **若 `EP4 IN` 那一行根本不出现，就是 `dfifo_alloc()` 静默失败了**，按硬约束 B 的降级阶梯把 `UVC_EP_SIZE` 降到 384 再试。这一条是本阶段最可能的真失败模式。
5. **出流但画面是花的 / 只有上半张** ⇒ JPEG 数据本身或分包。先用 `v4l2-ctl --stream-mmap --stream-to=/tmp/f.mjpg --stream-count=1` 抓一帧下来，`file /tmp/f.mjpg` 与 `ffmpeg -i` 验它是不是完整 JPEG；若抓下来的帧比 `sizeof(k_uvc_test_jpeg)` 短，就是 EOF 位没置（回看 `tud_video_frame_xfer_complete_cb` 有没有被调用、`s_frames_sent` 有没有涨）。

**五步走完仍不成立 ⇒ 触发「放弃判定点」**，按本计划开头那一节的动作执行，**并把这五步各自的实测现象写进 README 的「UVC 为什么砍掉」**（下一个人不该重走一遍）。

- [x] **Step 7：提交**

```
git commit -m "feat(tab5-fw): 静态图 MJPEG 流打通，host 侧出 /dev/videoN (P4 Task5)"
```

---

## Task 6：硬件 JPEG 编码器接入（片上编合成图案，**仍然没有摄像头**）

目标：把帧源从「flash 里的常量 JPEG」换成「片上实时编码的 JPEG」。**变量只有编码器一个** —— 图案是 Task 4 那份逐字节相同的 `uvc_pattern.c`，USB 侧一行没动。

判据变成「`ffplay` 里那个白方块**动起来了**」：静态图的方块是死的，片上编码的方块每帧右移 16 像素。**这是一条不需要任何日志就能看见的判据**，也是选这个图案的原因。

**Files:** Create `main/cam_jpeg.{c,h}`；Modify `main/uvc_stream.c`、`main/CMakeLists.txt`

- [x] **Step 1：成功判据**

```bash
ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
# 抓 100 帧统计实际帧率与帧大小
v4l2-ctl -d /dev/videoN --stream-mmap --stream-count=100 --stream-to=/tmp/s.mjpg
ls -l /tmp/s.mjpg    # ÷100 = 平均帧字节
```

1. `ffplay` 里**白方块以肉眼可见的速度左右往返**，色条与灰阶带正常，无横向撕裂；
2. `v4l2-ctl --stream-mmap --stream-count=100` 报的 fps **≥ 9.0**（声明 10 fps，允许 10% 余量）；
3. **平均帧 ≤ 30 KB、峰值帧 ≤ 44 KB**（`uvc_stream_report()` 打的 `frame_bytes` 峰值），`s_frames_late` 与 `s_frames_dropped` **都是 0**；
4. GUD / HID / 音频不回归。

- [x] **Step 2：`main/cam_jpeg.h`**

```c
#pragma once
/*
 * 把一帧 RGB565 用 P4 的**硬件** JPEG 编码器压成 MJPEG 负载。
 *
 * 为什么是硬件：640×360 的软件 JPEG 在 P4 上要几十毫秒且吃满一个核，
 * 而 10 fps 的拍子只有 100 ms —— 那点余量还要留给 GUD 收帧与 PPA。
 * esp_driver_jpeg 是 IDF 内置，不引入任何组件依赖。
 */
#include "esp_err.h"
#include <stdint.h>
#include <stddef.h>

/* 建编码器引擎与两块输出缓冲。幂等，重复调用返回 ESP_ERR_INVALID_STATE。 */
esp_err_t cam_jpeg_init(void);

/*
 * 编码一帧。src 是紧凑排列的 w×h 个 RGB565（stride = w，小端）。
 * 成功时 *out / *len 指向**内部双缓冲之一**，在下一次 cam_jpeg_encode() 之前有效。
 *
 * ⚠️ **双缓冲不是优化，是正确性要求**：tud_video_n_frame_xfer() 只记指针，
 *    整帧发完（10 fps 下最长 100 ms）之前驱动会持续从这块内存 memcpy 取数
 *    （video_device.c:898）。单缓冲会让编码器一边写、UVC 一边读同一块内存，
 *    表现是画面横向撕裂（上半是新帧、下半是旧帧），而且只在帧偏大时才出现 ——
 *    典型的"偶发、随内容变化"的疑难杂症。
 */
esp_err_t cam_jpeg_encode(const uint16_t *src, int w, int h,
                          const uint8_t **out, size_t *len);

/*
 * PPA 把 CAM_SENSOR_W×CAM_SENSOR_H 的 RGB565 精确缩小 0.5 倍到 UVC_W×UVC_H。
 * P4 Task9 才实现（Task6 的合成图案本来就是 640×360，不需要缩放）；
 * 声明放这里是因为 PPA client 与编码器同属"像素后处理"这一层，
 * 让 uvc_stream.c 只依赖一个头文件。
 */
esp_err_t cam_jpeg_downscale(const uint16_t *src, uint16_t *dst);

/* 统计快照：编码次数、失败次数、最近/峰值帧字节数、最近一次编码耗时(us)。 */
void cam_jpeg_stats(uint32_t *encoded, uint32_t *failed,
                    size_t *last_bytes, size_t *peak_bytes, uint32_t *last_us);
```

- [x] **Step 3：`main/cam_jpeg.c`**

```c
#include "driver/jpeg_encode.h"
#include "usb_descriptors.h"   /* UVC_MAX_FRAME_BYTES */

/*
 * 质量的起始值。**这不是听感/观感参数，是带宽参数**：
 * 10 fps × 446 B/ms ⇒ 每帧预算 44.6 KB，目标是平均 ≤30 KB、峰值 ≤44 KB。
 * 调法与判据见计划的 Task 6 Step 5，不许拍脑袋改。
 */
#define CAM_JPEG_QUALITY 70

/*
 * 子采样固定 4:2:2，**不是 4:2:0**。
 * 4:2:0 的 MCU 是 16×16，而 UVC_H = 360 不是 16 的倍数（360 = 16×22.5）；
 * 4:2:2 的 MCU 是 16×8，640 与 360 都整除，编码器不必补边。
 * 代价是比 4:2:0 大 20%–25%，按上面的余量付得起。
 * ⓘ RGB565 输入两种子采样都合法（jpeg_encode.c:145-147 只对 YUV422 **输入**
 *   强制 YUV422 子采样）。另注意 P4 rev <3.0 **不支持 YUV420/YUV444 输入**
 *   （jpeg_encode.c:186-198 的 #if），本固件正是 REV_MIN_100，所以输入只能是
 *   RGB888 / RGB565 / GRAY / YUV422 —— 我们用 RGB565（PPA 的输出色彩模式）。
 */
#define CAM_JPEG_SUBSAMPLE JPEG_DOWN_SAMPLING_YUV422

#define CAM_JPEG_BUFS 2

static jpeg_encoder_handle_t s_enc;
static uint8_t *s_out[CAM_JPEG_BUFS];
static size_t   s_out_cap[CAM_JPEG_BUFS];
static int      s_out_idx;

esp_err_t cam_jpeg_init(void)
{
    ESP_RETURN_ON_FALSE(!s_enc, ESP_ERR_INVALID_STATE, TAG, "已初始化");

    /* timeout_ms 必须大于一次编码的有效耗时。10 fps 的拍子是 100 ms，
     * 给 200 ms：超时了宁可返回错误也不要把帧泵任务永远钉住
     * （-1 = 永远等，那会让一次硬件异常变成"摄像头静默死掉"）。 */
    const jpeg_encode_engine_cfg_t eng = { .intr_priority = 0, .timeout_ms = 200 };
    ESP_RETURN_ON_ERROR(jpeg_new_encoder_engine(&eng, &s_enc), TAG, "jpeg engine");

    /* ⚠️ 输出缓冲**必须**用 jpeg_alloc_encoder_mem() 分配：
     * jpeg_encode.c:144 会断言 bit_stream 的地址按 cache line 对齐，
     * 普通 heap_caps_malloc() 出来的指针过不了那条检查（返回 ESP_ERR_INVALID_ARG，
     * 症状是"一帧都编不出来"而不是崩溃）。 */
    const jpeg_encode_memory_alloc_cfg_t mem = {
        .buffer_direction = JPEG_ENC_ALLOC_OUTPUT_BUFFER,
    };
    for (int i = 0; i < CAM_JPEG_BUFS; i++) {
        s_out[i] = (uint8_t *)jpeg_alloc_encoder_mem(UVC_MAX_FRAME_BYTES, &mem,
                                                     &s_out_cap[i]);
        ESP_RETURN_ON_FALSE(s_out[i], ESP_ERR_NO_MEM, TAG, "jpeg 输出缓冲 %d", i);
    }
    ESP_LOGI(TAG, "JPEG 编码器就绪：%dx%d 4:2:2 q=%d，双缓冲各 %u 字节",
             UVC_W, UVC_H, CAM_JPEG_QUALITY, (unsigned)s_out_cap[0]);
    return ESP_OK;
}

esp_err_t cam_jpeg_encode(const uint16_t *src, int w, int h,
                          const uint8_t **out, size_t *len)
{
    ESP_RETURN_ON_FALSE(s_enc && src && out && len, ESP_ERR_INVALID_ARG, TAG, "参数");

    /* 轮转到另一块缓冲：上一帧可能还在被 UVC 分包读取（见 cam_jpeg.h 的 ⚠️）。 */
    s_out_idx = (s_out_idx + 1) % CAM_JPEG_BUFS;
    uint8_t *dst = s_out[s_out_idx];

    const jpeg_encode_cfg_t cfg = {
        .width = (uint32_t)w, .height = (uint32_t)h,
        .src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
        .sub_sample = CAM_JPEG_SUBSAMPLE,
        .image_quality = CAM_JPEG_QUALITY,
    };
    uint32_t produced = 0;
    const int64_t t0 = esp_timer_get_time();
    /* 同步阻塞调用（内部 xSemaphoreTake + 等中断），所以必须在自己的任务里跑，
     * 绝不能放进 USB 回调。输入侧的 cache 回写由驱动自己做
     * （jpeg_encode.c:252 的 esp_cache_msync(..., C2M | UNALIGNED)）。 */
    esp_err_t err = jpeg_encoder_process(s_enc, &cfg, (const uint8_t *)src,
                                         (uint32_t)w * (uint32_t)h * 2,
                                         dst, s_out_cap[s_out_idx], &produced);
    s_last_us = (uint32_t)(esp_timer_get_time() - t0);
    if (err != ESP_OK || produced == 0 || produced > UVC_MAX_FRAME_BYTES) {
        /*
         * **可见的失败路径，不截断。** 超过 UVC_MAX_FRAME_BYTES 的帧发不完
         * （每帧预算 44.6 KB），截成半张的 JPEG 在 host 侧表现为下半屏纯绿/纯灰，
         * 极难归因；丢掉这一帧只是画面卡一拍，而且 s_failed 计数会说出真相。
         */
        s_failed++;
        return err != ESP_OK ? err : ESP_ERR_INVALID_SIZE;
    }
    s_encoded++;
    s_last_bytes = produced;
    if (produced > s_peak_bytes) s_peak_bytes = produced;
    *out = dst;
    *len = produced;
    return ESP_OK;
}
```

> ⓘ **若实测发现 JPEG 的头部正常、尾部是上一帧的旧数据**，那是输出缓冲的
> M2C（DMA→CPU）cache 失效没做。先确认 `jpeg_encoder_process()` 内部是否已处理；
> 没有就在这里补一次 `esp_cache_msync(dst, produced, ESP_CACHE_MSYNC_FLAG_DIR_M2C)`
> **并把结论写进注释**（"实测需要/不需要"，别留成猜测）。

- [x] **Step 4：`uvc_stream.c` 换帧源**

把 Task 5 那两行静态图换成「渲染 + 编码」，**其余一行不改**：

```c
/* 640×360 RGB565 = 460,800 字节，放 PSRAM（内部 RAM 只剩约 474 KB，见 README
 * 的资源占用一节，这块必须在 PSRAM）。硬件 JPEG 编码器从 PSRAM 直读没有问题：
 * 它走 2D-DMA，驱动自己做输入侧 cache 回写。 */
static uint16_t *s_rgb;
static uint32_t  s_frame_no;

static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    if (!uvc_pattern_render(s_rgb, UVC_W, UVC_H, s_frame_no++))
        return false;
    size_t n = 0;
    if (cam_jpeg_encode(s_rgb, UVC_W, UVC_H, buf, &n) != ESP_OK)
        return false;
    *len = n;
    return true;
}
```

`uvc_stream_start()` 里追加 `s_rgb = heap_caps_malloc(UVC_W * UVC_H * 2, MALLOC_CAP_SPIRAM)`
与 `cam_jpeg_init()`，失败则整体返回错误（帧泵不起来，host 侧表现为「有 `/dev/videoN`
但取不到流」——**这是可见的**，比带病运行好）。

- [x] **Step 5：调质量参数（有判据，不是拍脑袋）**

跑 Step 1 的 `--stream-count=100`，读 `uvc_stream_report()` 打出的峰值帧字节：

| 实测峰值 | 动作 |
|---|---|
| > 44 KB | `CAM_JPEG_QUALITY` **−10**，重测。同时确认 `s_frames_late` 是否非零 |
| 30–44 KB | 保持。但要记录，Task 11 写进 README |
| < 20 KB | 可以 **+10** 换画质，但**只在 `s_frames_late == 0` 且 fps ≥ 9.5 时**才动 |

**每次改完都要重跑 Step 1 的全部四条判据**，并把最终取值与实测三个数字（平均帧、峰值帧、实测 fps）写进 `cam_jpeg.c` 的注释 —— 下一个人才知道 70 这个数是怎么来的。

- [x] **Step 6：编译 + 上板验证 + 提交**

```
git commit -m "feat(tab5-fw): 硬件 JPEG 编码器接入，片上实时编码合成图案 (P4 Task6)"
```

---

## Task 7：引入 `esp_cam_sensor` 并探到 SC202CS（**只探测，不取流**）

目标：把摄像头的电与 SCCB 通路坐实，并确认依赖树没被污染。**本任务不碰 CSI、不碰 ISP、不碰 UVC。**

> ⚠️ **本任务起，判据落在日志上** —— 传感器探测的结果没有任何 host 侧出口。
> 所以从这里到 Task 9，**全程在 UVC 调试档（`CONFIG_AIO_DEBUG_CDC=y`）下做**，
> 或者接 UART0(G37/G38) + USB-TTL。这正是 Task 3 那一档存在的理由。
> 每个任务的最后一步再切回默认档确认不回归。

**Files:** Modify `main/idf_component.yml`、`main/board_power.{c,h}`、`main/tab5_pins.h`、`main/CMakeLists.txt`、`sdkconfig.defaults`；Create `main/camera_csi.{c,h}`（本任务只写探测部分）

- [x] **Step 1：成功判据**

1. `idf.py reconfigure` 后 `managed_components/` **只多出三个目录**：
   `espressif__esp_cam_sensor`、`espressif__esp_sccb_intf`、`espressif__cmake_utilities`；
   **不得出现** `esp_video`、`usb_host_uvc`、`esp_h264`、`esp_ipa`、`lvgl`、`m5stack_tab5`；
2. `idf.py build` 通过，`idf.py size` 增量记下来；
3. 上板（调试档）日志打出 `SC202CS 探测成功 PID=0xeb52`。

- [x] **Step 2：`idf_component.yml` 加 `esp_cam_sensor`**

```yaml
  # SC202CS 的 MIPI 模式寄存器序列（四张表，含大量无文档项）。这是**芯片驱动**组件，
  # 与已在用的 esp_lcd_ili9881c / esp_lcd_touch_gt911 / esp_io_expander_pi4ioe5v6408 /
  # esp_codec_dev 同一性质，**不是** esp-bsp 板级组件。
  #
  # ⚠️ **刻意不引 espressif/esp_video**（spec §8.1 的依赖表把阶段 5 写成 esp_video，
  #    本阶段订正）：实测它 2.3.0 的 manifest 强制依赖
  #      espressif/usb_host_uvc  ← USB **Host** 栈
  #      espressif/esp_h264      ← 软件 H.264 编码器
  #      espressif/esp_ipa
  #    在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB Host 栈，
  #    既违反 spec §8.1「不引入 usb-host 依赖」，也与本产品形态毫无关系。
  #    而 esp_cam_sensor 的依赖只有 cmake_utilities(构建期) + esp_sccb_intf(零外部依赖)。
  #    我们只需要「一个固定模式、拿到一帧 RGB565」，esp_video 那层 V4L2 语义用不上。
  espressif/esp_cam_sensor: "~2.4.0"
```

`sdkconfig.defaults` 追加（把组件裁到只剩要用的那一个传感器、那一个模式）：

```
# esp_cam_sensor 默认会把二十多颗传感器全编进来。Tab5 只有 SC202CS，
# 且只用得上 1280×720 RAW8 那一个模式（其余模式要么超出 P4 ISP 的 1920×1080
# 上限，要么裁不出 4:3，见 P4 计划的「关键事实」）。
CONFIG_CAMERA_SC202CS=y
CONFIG_CAMERA_SC202CS_MIPI_RAW8_1280X720_30FPS=y
CONFIG_CAMERA_SC202CS_MIPI_RAW8_1600X1200_30FPS=n
CONFIG_CAMERA_SC202CS_MIPI_RAW10_1600X1200_30FPS=n
CONFIG_CAMERA_SC202CS_MIPI_RAW10_1600X900_30FPS=n
CONFIG_CAMERA_SC202CS_MIPI_DEFAULT_FMT_RAW8_1280X720_30FPS=y
# 我们直接调 sc202cs_detect()，不用 esp_video 那套链接段自动探测。
CONFIG_CAMERA_SC202CS_AUTO_DETECT_MIPI_INTERFACE_SENSOR=n
```

> ⚠️ 改了 `sdkconfig.defaults` **必须 `rm -f sdkconfig` 再 build**，否则 defaults 不重新生效。
> ⚠️ 上面这批 Kconfig 名以 `managed_components/espressif__esp_cam_sensor/**/Kconfig*` 实际有的为准：
> `idf.py build` 会对不存在的项报 warning，按 warning 增删 —— **不要留下拼错的行**，那只是静默无效。

`main/CMakeLists.txt` 的 `PRIV_REQUIRES` 追加 `esp_driver_cam esp_driver_isp esp_driver_jpeg`
（`esp_driver_ppa` 已在）。

- [x] **Step 3：`board_power.{c,h}` 加摄像头使能（配好但**保持关闭**）**

与背光、功放**完全同构**：`board_power_init()` 只把引脚配成推挽输出并保持 0，真正打开归摄像头域。

```c
/* 开关摄像头电源（IO 扩展 0x43 的 PIN6）。与背光、功放同构：board_power_init()
 * 只把引脚配好并**保持关闭**，真正打开归 camera_csi.c。
 *
 * 不变式：**摄像头上电 ⟺ 马上就要探测/取流**。它常开着会一直耗电（这是一块
 * 有电池的板子），而且 SC202CS 上电后 MIPI 的差分对就一直在动。
 *
 * ⚠️ 与 LCD_EN(PIN4) / TOUCH_EN(PIN5) / SPEAKER_EN(PIN1) 同在 **0x43 那一颗**
 * PI4IOE5V6408 上，必须复用 board_power.c 已有的 s_ioexp 句柄 ——
 * 新建一个 expander 会重置整颗芯片的方向/输出寄存器，把面板与触摸的电一起断掉。 */
void board_camera_enable(bool on);
```

`board_power_init()` 里在 `TOUCH_EN` / `SPEAKER_EN` 之后追加
`ESP_RETURN_ON_ERROR(ioexp_out(IOEXP_PIN_CAMERA_EN, 0), TAG, "CAMERA_EN");`。

- [x] **Step 4：`camera_csi.c` 的探测部分**

```c
#include "esp_sccb_intf.h"
#include "esp_sccb_i2c.h"
#include "sc202cs.h"

static esp_cam_sensor_device_t *s_sensor;

esp_err_t camera_sensor_probe(void)
{
    /* 上电 → 等稳。esp-bsp 的 bsp_camera_start() 在 feature_enable 之后
     * vTaskDelay(100ms)，照抄这个数：SC202CS 的内部 LDO 与 24 MHz 晶振起振
     * 都需要时间，探早了读回来的 PID 是 0。 */
    board_camera_enable(true);
    vTaskDelay(pdMS_TO_TICKS(100));

    /* SCCB 就是 I2C。复用内部总线句柄，**绝不新建 master** ——
     * 与 touch_hid.c / codec_audio.c 同一处置（board_i2c_bus()）。 */
    const sccb_i2c_config_t sccb_cfg = {
        .scl_speed_hz = 100000,          /* 与总线上其它器件共存，取保守值 */
        .device_address = SC202CS_I2C_ADDR7,   /* ⚠️ esp_sccb_intf 收 **7 bit** */
        .addr_bits_width = 16,           /* SC202CS 的寄存器地址是 16 位(0x3107 等) */
        .val_bits_width  = 8,
    };
    esp_sccb_io_handle_t sccb = NULL;
    ESP_RETURN_ON_ERROR(sccb_new_i2c_io(board_i2c_bus(), &sccb_cfg, &sccb),
                        TAG, "sccb io");

    esp_cam_sensor_config_t cfg = {
        .sccb_handle = sccb,
        .reset_pin   = -1,      /* Tab5 没有 RESET 引脚（esp-bsp: BSP_CAMERA_RST = NC） */
        .pwdn_pin    = -1,
        .xclk_pin    = -1,      /* 24 MHz 由板上晶振提供（BSP_CAMERA_GPIO_XCLK = NC） */
        .sensor_port = ESP_CAM_SENSOR_MIPI_CSI,
    };
    s_sensor = sc202cs_detect(&cfg);
    ESP_RETURN_ON_FALSE(s_sensor, ESP_ERR_NOT_FOUND, TAG,
                        "SC202CS 探测失败：先查 CAMERA_EN(0x43 PIN6) 与 100ms 延时");
    ESP_LOGI(TAG, "SC202CS 探测成功 PID=0x%04x（期望 0x%04x）",
             s_sensor->id.pid, SC202CS_PID_EXPECT);
    return ESP_OK;
}
```

> ⓘ **字段名以组件头文件为准**（组件此时才刚被拉下来）。先跑一遍：
> ```bash
> grep -n "sccb_i2c_config_t\|sccb_new_i2c_io\|esp_cam_sensor_config_t" \
>     firmware/managed_components/espressif__esp_sccb_intf/include/*.h \
>     firmware/managed_components/espressif__esp_cam_sensor/include/*.h
> ```
> **判据**：`sccb_new_i2c_io()`、`sc202cs_detect()`、`SC202CS_SCCB_ADDR == 0x36`、
> `SC202CS_PID == 0xeb52` 四项都在。字段名对不上就按头文件改，**并把差异记进注释**。

- [x] **Step 5：依赖树核实（硬判据）**

```bash
cd firmware && . $HOME/esp/esp-idf/export.sh && rm -f sdkconfig && idf.py reconfigure
ls managed_components/
```

**判据**：新增目录只有 `espressif__esp_cam_sensor` / `espressif__esp_sccb_intf` /
`espressif__cmake_utilities` 三个。出现 `esp_video` / `usb_host_uvc` / `esp_h264` /
`esp_ipa` / `lvgl` 中的任何一个 ⇒ **退回本步**，改为按 `sc202cs.c` 的寄存器表自己写薄驱动
（那张 1280×720 RAW8 的表约 100 条，可以接受；其余三张不抄）。

- [x] **Step 6：上板（调试档）验证 + 切默认档确认不回归 + 提交**

```
git commit -m "feat(tab5-fw): 引入 esp_cam_sensor 并探到 SC202CS (P4 Task7)"
```

---

## Task 8：MIPI-CSI + ISP 取流（1280×720 RGB565，**仍不接 UVC**）

目标：拿到真实的一帧 RGB565。**不接 UVC** —— 判据是日志里的两个数字，靠「拿手挡住镜头」制造一个物理上无可辩驳的变化。

**Files:** Modify `main/camera_csi.{c,h}`

- [x] **Step 1：成功判据（调试档，日志）**

上板后日志每秒打一条：

```
cam: 帧 #300 30.1 fps  平均亮度 118/255  (1280x720 RGB565)
```

1. **帧率稳定在 29–31 fps**（传感器模式是 30 fps 固定）；
2. **拿手完全挡住镜头 ⇒ 平均亮度掉到 40 以下；拿开 ⇒ 回到 80 以上**，反复三次都跟手 ——
   这条排除了「取到的是一块没人写过的零缓冲」和「取到的是同一帧反复」；
3. 用手电照 ⇒ 亮度冲到 200 以上（排除「亮度算的是常量」）；
4. `esp_get_free_heap_size()` 与 PSRAM 剩余量记进日志（Task 11 要写 README）；
5. **GUD 显示不出现撕裂/花屏** —— 这是本任务最需要盯的回归项（CSI 每秒往 PSRAM 写 55 MB，
   而 DPI 面板刷新每秒要从 PSRAM 读约 110 MB，见硬约束 D 第 2 条）。

- [x] **Step 2：`camera_csi.h`**

```c
#pragma once
/*
 * SC202CS → MIPI-CSI → ISP → 1280×720 RGB565（PSRAM）。
 *
 * **薄板级驱动，不引 esp_video。** 依赖只有 IDF 内置的 esp_driver_cam(CSI) /
 * esp_driver_isp，加上 espressif/esp_cam_sensor 提供的寄存器序列 ——
 * 与 §3.3 的面板（esp_lcd_ili9881c + 我们自己的 display_dsi.c）、§6 的音频
 * （esp_codec_dev + 我们自己的 codec_audio.c）完全同构。
 * esp_video 强制拖进 usb_host_uvc / esp_h264 / esp_ipa，与本产品形态无关，
 * 且违反 spec §8.1，详见 P4 计划的「依赖树评估」。
 *
 * ⚠️ **只在 host 真的打开摄像头时才 start。** CSI 每秒往 PSRAM 写 55 MB，
 * 而 DPI 面板刷新每秒要从 PSRAM 读约 110 MB —— 常开会挤 DPI 的带宽，
 * 表现为屏幕撕裂/花屏。启停由 uvc_stream.c 按 uvc_stream_is_streaming() 驱动。
 */
#include "esp_err.h"
#include <stdint.h>

/* 探测传感器（P4 Task7）。 */
esp_err_t camera_sensor_probe(void);

/* 建 CSI 控制器 + ISP + 帧缓冲。须在 camera_sensor_probe() 成功之后。 */
esp_err_t camera_csi_init(void);

/* 开/关取流。幂等。关流时会 board_camera_enable(false)。 */
esp_err_t camera_csi_start(void);
esp_err_t camera_csi_stop(void);

/*
 * 阻塞取一帧。成功时 *fb 指向 CAM_SENSOR_W×CAM_SENSOR_H 个 RGB565（紧凑排列）。
 * 该缓冲在下一次 camera_csi_get_frame() 之前有效。
 */
esp_err_t camera_csi_get_frame(const uint16_t **fb, uint32_t timeout_ms);
```

- [x] **Step 3：CSI 控制器 + ISP**

```c
#include "esp_cam_ctlr_csi.h"
#include "esp_cam_ctlr.h"
#include "driver/isp.h"

#define CAM_FB_BYTES  ((size_t)CAM_SENSOR_W * CAM_SENSOR_H * 2)   /* RGB565 ⇒ 1.84 MB */
#define CAM_FB_COUNT  2

static esp_cam_ctlr_handle_t s_cam;
static isp_proc_handle_t     s_isp;
static uint16_t             *s_fb[CAM_FB_COUNT];
static int                   s_fb_idx;

esp_err_t camera_csi_init(void)
{
    /*
     * 参数全部来自 esp_cam_sensor 的模式表 sc202cs_format_info[0]
     * （"MIPI_1lane_24Minput_RAW8_1280x720_30fps"）：
     *   mipi_info.lane_num = 1、mipi_info.mipi_clk = 576000000
     * lane_bit_rate_mbps 的换算照 esp_video 的 esp_video_csi_device.c:158：
     *   lane_bit_rate_mbps = mipi_clk / 1e6 = 576
     * bayer 顺序取自 sc202cs_isp_info[0].bayer_type = ESP_CAM_SENSOR_BAYER_BGGR。
     *
     * ⚠️ 这是**唯一可用**的传感器模式：1600×1200 的 1200 行超出 P4 ISP 的
     *    1920×1080 输入上限，1600×900 裁不出 4:3。见 P4 计划的「关键事实」。
     */
    const esp_cam_ctlr_csi_config_t csi_cfg = {
        .ctlr_id  = 0,
        .clk_src  = MIPI_CSI_PHY_CLK_SRC_DEFAULT,
        .h_res    = CAM_SENSOR_W,
        .v_res    = CAM_SENSOR_H,
        .data_lane_num      = CAM_MIPI_LANES,      /* 1 */
        .lane_bit_rate_mbps = CAM_MIPI_MBPS,       /* 576 */
        /* ⛔ 实施订正：这两行是错的，实机死在 esp_cam_new_csi_ctlr() =
         *    ESP_ERR_NOT_SUPPORTED。**两个都必须填 RGB565**（桥直通），详见下面
         *    「实施订正汇总」第 ①/② 条。 */
        .input_data_color_type  = CAM_CTLR_COLOR_RAW8,
        .output_data_color_type = CAM_CTLR_COLOR_RGB565,  /* 经 ISP 去马赛克后的输出 */
        .queue_items  = 1,
        .byte_swap_en = false,
        /* 关掉备份缓冲：它会再吃 1.84 MB PSRAM 与一份写带宽，而我们的取帧循环
         * 一直有缓冲排着（双缓冲轮转）。若实测出现 "no available buffer" 类错误，
         * 把它改回 false 并在这里记下结论。 */
        .bk_buffer_dis = true,
    };
    ESP_RETURN_ON_ERROR(esp_cam_new_csi_ctlr(&csi_cfg, &s_cam), TAG, "csi ctlr");

    /*
     * ISP：把 RAW8 去马赛克成 RGB565。**不做 AE/AWB 闭环** ——
     * 闭环控制律要么引 espressif/esp_ipa（会把 esp_video 的一半拖进来），
     * 要么自己写；本阶段用 esp_cam_sensor 模式表里的默认曝光与增益
     * （sc202cs_isp_info[0] 的 exp_def = 0x3dc、gain_def = 0）。
     *
     * ⚠️ **代价必须写进 README**：固定室内光照下画面正常，但**换光照环境会
     *    过曝或欠曝，且不会自动恢复**。对「USB 瘦终端顺带一个摄像头」的定位
     *    可以接受；真要自动曝光，下一阶段优先自己写 30 行 P 控制器，别引 esp_ipa。
     */
    const esp_isp_processor_cfg_t isp_cfg = {
        .clk_hz  = 80 * 1000 * 1000,
        .input_data_source     = ISP_INPUT_DATA_SOURCE_CSI,
        .input_data_color_type = ISP_COLOR_RAW8,
        .output_data_color_type = ISP_COLOR_RGB565,
        .has_line_start_packet = false,
        .has_line_end_packet   = false,
        .h_res = CAM_SENSOR_W,
        .v_res = CAM_SENSOR_H,
        .bayer_order = COLOR_RAW_ELEMENT_ORDER_BGGR,
    };
    ESP_RETURN_ON_ERROR(esp_isp_new_processor(&isp_cfg, &s_isp), TAG, "isp");
    ESP_RETURN_ON_ERROR(esp_isp_enable(s_isp), TAG, "isp enable");

    for (int i = 0; i < CAM_FB_COUNT; i++) {
        s_fb[i] = heap_caps_aligned_calloc(64, 1, CAM_FB_BYTES,
                                           MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA);
        ESP_RETURN_ON_FALSE(s_fb[i], ESP_ERR_NO_MEM, TAG, "帧缓冲 %d (1.84MB)", i);
    }
    ESP_LOGI(TAG, "CSI+ISP 就绪：%dx%d RAW8→RGB565，%d 块帧缓冲各 %u 字节",
             CAM_SENSOR_W, CAM_SENSOR_H, CAM_FB_COUNT, (unsigned)CAM_FB_BYTES);
    return ESP_OK;
}

/* ⛔ 实施订正：整个函数起不来 —— `esp_cam_ctlr_receive()` 是**提交缓冲**
 *    （内部 `xQueueSend`），不是阻塞取帧；完成通知只走 `on_trans_finished` 回调。
 *    实际实现是「回调把填好的缓冲推进 s_done_q，本函数 xQueueReceive」，
 *    外加一次手动 `esp_cache_msync(..., M2C)`。详见「实施订正汇总」第 ③ 条。 */
esp_err_t camera_csi_get_frame(const uint16_t **fb, uint32_t timeout_ms)
{
    s_fb_idx = (s_fb_idx + 1) % CAM_FB_COUNT;
    esp_cam_ctlr_trans_t trans = {
        .buffer = s_fb[s_fb_idx], .buflen = CAM_FB_BYTES,
    };
    ESP_RETURN_ON_ERROR(esp_cam_ctlr_receive(s_cam, &trans, timeout_ms),
                        TAG, "cam receive");
    ESP_RETURN_ON_FALSE(trans.received_size == CAM_FB_BYTES, ESP_ERR_INVALID_SIZE,
                        TAG, "收到 %u 字节，期望 %u（分辨率或色彩格式配错了）",
                        (unsigned)trans.received_size, (unsigned)CAM_FB_BYTES);
    *fb = s_fb[s_fb_idx];
    return ESP_OK;
}
```

- [x] **Step 4：启停顺序（这一步决定会不会把显示弄花）**

```c
esp_err_t camera_csi_start(void)
{
    ESP_RETURN_ON_ERROR(esp_cam_ctlr_enable(s_cam), TAG, "cam enable");
    /* 传感器最后开：它一 stream on，MIPI 差分对就开始送数据，
     * 控制器没 enable 的话那些数据无处可去（表现为 CSI 的 error 中断刷屏）。 */
    ESP_RETURN_ON_ERROR(esp_cam_ctlr_start(s_cam), TAG, "cam start");
    int en = 1;
    ESP_RETURN_ON_ERROR(esp_cam_sensor_set_para_value(s_sensor,
                        ESP_CAM_SENSOR_PARA_STREAM, &en, sizeof(en)), TAG, "stream on");
    return ESP_OK;
}
/* 关流严格反序：先让传感器停止送数据，再停控制器，最后断电。
 * 顺序反了会在 CSI 上留下半帧数据，下次 start 时第一帧是错位的。 */
```

> ⓘ `esp_cam_sensor_set_para_value` / `ESP_CAM_SENSOR_PARA_STREAM` 的确切符号名
> 以组件头文件为准（`esp_cam_sensor.h` / `esp_cam_sensor_types.h`），落地时
> `grep -n "PARA_STREAM\|set_para_value\|set_format" managed_components/espressif__esp_cam_sensor/include/*.h` 一次对齐。
> 同一处还要调 `esp_cam_sensor_set_format()` 选中那唯一一个模式 —— 若组件已按
> `CONFIG_CAMERA_SC202CS_MIPI_IF_FORMAT_INDEX_DEFAULT` 在 detect 里设好，就不必重复设，
> **把实测结论写进注释**。
>
> ⛔ **实测结论（两条都与上面这段不符）**：
> ① **`ESP_CAM_SENSOR_PARA_STREAM` 这个符号不存在。** stream on/off 走
>    `esp_cam_sensor_ioctl(s, ESP_CAM_SENSOR_IOC_S_STREAM, &en)`。
> ② **`esp_cam_sensor_set_format()` 必须调，不能省** —— `sc202cs_detect()` 只把
>    `cur_format` 指过去，**一个寄存器都没写**。
> 见「实施订正汇总」第 ④/⑤ 条。

- [x] **Step 5：临时自检任务（本任务结束时删掉）**

```c
/*
 * ⚠️ **临时代码，Task 9 接上 UVC 时必须删掉。**
 * P3 的教训写得很清楚：分阶段旋钮/自检只应在一次排障会话里存在，定位完立刻删除。
 * 它存在的唯一理由是：本任务没有任何 host 侧出口，而「取到的到底是不是真画面」
 * 必须有一个物理上无可辩驳的判据 —— 拿手挡住镜头，平均亮度必须跟着掉。
 */
static void cam_selftest_task(void *arg)
{
    (void)arg;
    ESP_ERROR_CHECK(camera_csi_start());
    uint32_t frames = 0, total = 0, sum_lum = 0, samples = 0;
    int64_t t0 = esp_timer_get_time();

    while (1) {
        const uint16_t *fb;
        if (camera_csi_get_frame(&fb, 200) != ESP_OK) {
            ESP_LOGW(TAG, "cam: 取帧超时");
            continue;
        }
        frames++; total++;
        /* 亮度只采样 1/64 的像素（每 8 行取一行、行内每 8 个取一个）：
         * 全采样 92 万个像素每帧要几毫秒，会自己变成被观测的干扰源。
         * 取 RGB565 的绿色分量近似亮度（G 占 6 bit，左移 2 位归一到 0..255）。 */
        for (int y = 0; y < CAM_SENSOR_H; y += 8) {
            const uint16_t *row = fb + (size_t)y * CAM_SENSOR_W;
            for (int x = 0; x < CAM_SENSOR_W; x += 8) {
                sum_lum += ((row[x] >> 5) & 0x3F) << 2;
                samples++;
            }
        }
        const int64_t now = esp_timer_get_time();
        if (now - t0 >= 1000000) {
            ESP_LOGI(TAG, "cam: 帧 #%u %.1f fps  平均亮度 %u/255  (%dx%d RGB565)",
                     (unsigned)total, frames * 1e6 / (double)(now - t0),
                     (unsigned)(samples ? sum_lum / samples : 0),
                     CAM_SENSOR_W, CAM_SENSOR_H);
            frames = 0; sum_lum = 0; samples = 0; t0 = now;
        }
    }
}
```

- [x] **Step 6：上板验证（三个物理动作各做三次）+ 切默认档确认 GUD 不花屏 + 提交**

```
git commit -m "feat(tab5-fw): MIPI-CSI + ISP 取流，SC202CS 出 1280x720 RGB565 (P4 Task8)"
```

---

## Task 9：PPA 2× 缩小 + 接入 UVC 流 + 帧率实测

目标：把 Task 8 的真实帧接到 Task 6 已经打通的编码/USB 链路上。**变量只有 PPA 缩放 + 帧源切换这一处。**

**Files:** Modify `main/cam_jpeg.{c,h}`、`main/uvc_stream.c`

- [x] **Step 1：成功判据**

```bash
ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
v4l2-ctl -d /dev/videoN --stream-mmap --stream-count=100 --stream-to=/tmp/cam.mjpg
```

1. `ffplay` 显示**真实画面**，方向正确（不是上下颠倒/左右镜像）、颜色正常（人脸不是蓝的 ⇒ 没有 R/B 互换）；
2. 实测 fps **≥ 9.0**，`s_frames_late` / `s_frames_dropped` / `cam_jpeg` 的 `failed` **都是 0**；
3. 平均帧 ≤ 30 KB、峰值 ≤ 44 KB（真实画面比合成色条**更难压**，这里很可能要回头调 `CAM_JPEG_QUALITY`，按 Task 6 Step 5 的表格来）；
4. **未打开摄像头时** GUD 帧率与 P3 相同（这是「带宽零和」的正面验证，见 Step 5）;
5. GUD / HID / 音频不回归。

- [x] **Step 2：`cam_jpeg.c` 加 PPA 缩放**

```c
/*
 * 1280×720 → 640×360，**精确 0.5**。
 *
 * 为什么必须是 0.5：PPA SRM 的缩放比粒度是 1/16，0.5 = 8/16 精确可表达；
 * 而 spec §7 原本想要的 640×480 需要「裁 960×720 再乘 2/3」，2/3 表达不出来
 * （最近的 11/16 给出 660×495）。加上 P4 的 ISP **没有缩放器**
 * （esp_driver_isp 只有 isp_crop.h），这条路上 640×360 是唯一精确的输出尺寸。
 * 详见 P4 计划的「参数选定」。
 *
 * ⚠️ **注册自己的 PPA client，不共用 display_dsi.c 那个。**
 * 共用会让摄像头的缩放与 GUD 的脏矩形在同一个 client 上排队
 * （两边都用 PPA_TRANS_MODE_BLOCKING），显示延迟直接翻倍。
 * PPA 引擎本身仍是共享硬件，所以 Task 10 要实测帧率影响。
 */
static ppa_client_handle_t s_ppa;

/* 由 cam_jpeg_init() 在建编码器引擎之后调用一次（本任务给它加这一句）。 */
static esp_err_t cam_ppa_init(void)
{
    const ppa_client_config_t cfg = {
        .oper_type = PPA_OPERATION_SRM,
        .max_pending_trans_num = 1,   /* 本 client 只有帧泵任务一个提交者 */
    };
    return ppa_register_client(&cfg, &s_ppa);
}

esp_err_t cam_jpeg_downscale(const uint16_t *src, uint16_t *dst)
{
    const ppa_srm_oper_config_t op = {
        .in = { .buffer = (void *)src,
                .pic_w = CAM_SENSOR_W, .pic_h = CAM_SENSOR_H,
                .block_w = CAM_SENSOR_W, .block_h = CAM_SENSOR_H,
                .block_offset_x = 0, .block_offset_y = 0,
                .srm_cm = PPA_SRM_COLOR_MODE_RGB565 },
        .out = { .buffer = dst, .buffer_size = (size_t)UVC_W * UVC_H * 2,
                 .pic_w = UVC_W, .pic_h = UVC_H,
                 .block_offset_x = 0, .block_offset_y = 0,
                 .srm_cm = PPA_SRM_COLOR_MODE_RGB565 },
        .rotation_angle = PPA_SRM_ROTATION_ANGLE_0,   /* 摄像头不转向，只缩小 */
        .scale_x = 0.5f, .scale_y = 0.5f,
        .mode = PPA_TRANS_MODE_BLOCKING,
    };
    /* 输入输出的 cache 同步由 PPA 驱动自己做（ppa_srm.c 提交 DMA 前做输入 C2M
     * 回写与输出 M2C 失效），此处不用管 —— 与 display_dsi.c 同一条结论。 */
    /* ⛔ 实施订正：cache **同步**确实不用管，但 **对齐**要管 ——
     *    `ppa_srm.c:186-189` 对 `out.buffer` 的**地址与长度都硬性检查 cache line
     *    对齐**，不过就 ESP_ERR_INVALID_ARG，症状是「一帧都出不来」。
     *    所以 `s_rgb` 必须用 MALLOC_CAP_CACHE_ALIGNED 分配。本计划漏了这条，
     *    见「实施订正汇总」第 ⑥ 条。 */
    return ppa_do_scale_rotate_mirror(s_ppa, &op);
}
```

> ⓘ **方向**：与显示链路不同，摄像头这条**不做旋转**（`ROTATION_ANGLE_0`）。
> 显示要转 90° 是因为面板是竖屏而 host 画的是横向内容；摄像头的输出直接交给 host，
> 由 host 决定怎么显示。esp-bsp 的 `BSP_CAMERA_ROTATION = 270` 是给「在本机竖屏上
> 预览」用的，**与本产品形态无关，刻意不照抄**。若实机发现画面是倒的（模组装配朝向），
> 再改这里的 `rotation_angle`，**并在注释里写明是实测决定的**。

- [x] **Step 3：`uvc_stream.c` 换帧源（第三次，也是最后一次）**

```c
static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    const uint16_t *raw;
    /* 超时取传感器周期的 3 倍（30 fps ⇒ 100 ms）：真丢帧时宁可跳一拍，
     * 也不要把帧泵任务钉在这里 —— 那会让 UVC 侧连"没有新帧"都表达不出来。 */
    if (camera_csi_get_frame(&raw, 100) != ESP_OK)
        return false;
    if (cam_jpeg_downscale(raw, s_rgb) != ESP_OK)
        return false;
    size_t n = 0;
    if (cam_jpeg_encode(s_rgb, UVC_W, UVC_H, buf, &n) != ESP_OK)
        return false;
    *len = n;
    return true;
}
```

**同时删掉 Task 6 的合成图案帧源与 Task 8 的自检任务。** `uvc_pattern.{c,h}` 与
`test/test_uvc_pattern.c` **保留**（宿主机测试仍然有价值，而且它是静态测试图的生成源），
但固件里不再调用 —— `uvc_pattern.c` 从 `CMakeLists.txt` 的 `SRCS` 里去掉。

- [x] **Step 4：CSI 的按需启停（「摄像头不开对显示零影响」的实现落点）**

帧泵任务里，在 `tud_video_n_streaming()` 的判断处加启停：

```c
        const bool want = tud_mounted() && tud_video_n_streaming(UVC_CTL_IDX, UVC_STM_IDX);
        if (want != s_cam_running) {
            /* host 选中 alt 1 才开 CSI。不流时传感器断电、CSI 不写 PSRAM ——
             * 那 55 MB/s 的写带宽是 DPI 面板刷新（约 110 MB/s 读）的直接竞争者。
             * 这是 spec §2.1「带宽是零和的」在 PSRAM 侧的对应物：USB 侧靠
             * alt 0 不预留 ISO 带宽，PSRAM 侧靠这里不启动 CSI。 */
            (void)(want ? camera_csi_start() : camera_csi_stop());
            s_cam_running = want;
            ESP_LOGI(TAG, "摄像头取流 %s", want ? "开始" : "停止");
        }
        if (!want) { s_xfer_in_flight = false; continue; }
```

- [x] **Step 5：帧率实测（两组数字，都要记）**

| 场景 | 测什么 | 怎么测 |
|---|---|---|
| **A：摄像头关，GUD 跑** | GUD 帧率**必须与 P3 相同** | `gst-launch-1.0 videotestsrc ! ... ! kmssink driver-name=gud`，用固件侧 `display_blit()` 次数/秒统计 |
| **B：摄像头开 + GUD 跑** | GUD 帧率掉多少、UVC 实测 fps | 同上 + `v4l2-ctl --stream-mmap --stream-count=100` |

**判据**：场景 A 与 P3 的数字**一致**（这是「零影响」的正面证明）；场景 B 的两个数字**如实记录**，
不许估算 —— 带宽账预测 GUD 的理论上限从约 1364 B/ms 掉到约 916 B/ms（−33%），
实测比这更差就说明瓶颈不在带宽（多半是 PSRAM 或 PPA 争用），按 Task 10 Step 3 归因。

- [x] **Step 6：上板验证 + 提交**

```
git commit -m "feat(tab5-fw): PPA 2x 缩小接入 UVC，摄像头实时画面打通 (P4 Task9)"
```

---

## Task 10：五项能力的复合回归 + 端点/FIFO 实测

> ⏳ **本任务尚未执行 —— 六个 Step 一个都没勾。**
> 五项能力**各自**都已实机验证（且每次新增能力时都复验过前面几项无回归），
> 但「五项同时全开压 10 分钟」这一场没跑，**所以下列数字至今没有**：
> 摄像头开着时 GUD 的实测帧率、PSRAM 带宽争用的实测值、
> 长时间稳定性（含 P3 欠的账：全双工同时收发、无反馈端点的时钟漂移）、
> 拔插与热切换的行为。
> **Task 11 的文档里凡是依赖这些数字的地方，一律标成「⏳ 未测」而不是填推算值。**
>
> ⓘ Step 2 的一部分**已经顺带做到了**：`FIFO: EP4 IN=112 words` 与两档的
> `已用/空闲`（默认 231/11、调试 224/18，分母 242）在 bring-up 过程中就读到了，
> 已回填 `firmware/README.md` 的「端点预算」。但该 Step 的 host 侧 `lsusb -v`
> 对照与「五项同跑」下的复读没做，故不勾。

目标：证明 UVC 没有把已交付的四项能力弄坏。这是硬约束 D 的落点，也是 spec §10 对阶段 5 的验证要求。

> ⏳ **顺带补上 P3 欠的账**：P3 的 Task 9（音频与 GUD/HID 的复合回归）**从未执行**，
> 所以「全双工长时间稳定性」「音频对 GUD 帧率的影响」「无反馈端点的时钟漂移」
> 三项至今没有实测数据。本任务把音频一并纳入，一次把两阶段的债还清。

**Files:** 无（纯验证；发现问题则回到对应任务）

- [ ] **Step 1：前置检查（做之前先确认，别做到一半才发现缺工具）**

```bash
which aplay arecord speaker-test evtest modetest gst-launch-1.0 ffplay v4l2-ctl
sox --version || true
dpkg -l | grep -E "alsa-utils|gstreamer1.0-tools|libdrm-tests|evtest|v4l-utils|ffmpeg"
gst-inspect-1.0 kmssink        # 在 gstreamer1.0-plugins-bad 里，常常不随 -tools 一起装
modinfo uvcvideo snd-usb-audio hid-multitouch drm_gud
```

缺什么装什么：

```bash
sudo apt-get install -y alsa-utils evtest sox libdrm-tests v4l-utils ffmpeg \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad
```

**判据**：8 个命令全部能找到，4 个内核模块全部存在。`uvcvideo` / `hid-multitouch` /
`snd-usb-audio` 缺席属 spec §9 那个阶段的工作（`flange_common.config`），**不是本阶段的固件缺陷**。

- [ ] **Step 2：端点与 FIFO 实测（先做这个，它最便宜且能解释后面的一切）**

默认档上板，读 `log_usb_fifo_usage()` 打出的行（调试档也跑一遍）：

| 档 | 预期 RX | 预期各 TX | 预期已用 / 空闲 |
|---|---|---|---|
| 默认档 | 62 | EP0 16 / EP1 16 / EP2 16 / EP3 9 / **EP4 112** | **231 / 11** |
| UVC 调试档 | 62 | EP0 16 / EP1 16 / EP2 16 / EP3 2 / **EP4 112** | **224 / 18** |

**判据**：`EP4 IN=112 words` 那一行**必须出现**（不出现 = `dfifo_alloc()` 静默失败了），
且「已用 + 空闲」= 242（不是 256 —— 若打出来是 256 的口径，说明 `is_dma` 判断与本计划
硬约束 B 的推导不符，**立刻停下来重算整份 FIFO 账**，因为端点大小是按 242 选的）。

同时 host 侧对照：

```bash
lsusb -v -d 16d0:10a9 | grep -E "bEndpointAddress|wMaxPacketSize|bInterfaceNumber"
```

**判据**：IN 端点恰为 `0x81/0x82/0x83/0x84` 四条，`0x84` 的 `wMaxPacketSize` 是 `0x01c0`（448）。

把这两组数字**回填 `firmware/README.md` 的「端点预算」章节**（那里现在只有静态验算与
一组只覆盖 CDC 场景的旧数字，且把 CDC 通知记成了 16 words）。

- [ ] **Step 3：五项同跑，连续 10 分钟**

在同一台 host 上同时跑：

```bash
# 终端 1：GUD 显示实时内容
gst-launch-1.0 videotestsrc ! videoconvert ! videoscale ! \
  video/x-raw,width=640,height=360 ! kmssink driver-name=gud connector-id=<id> force-modesetting=true
# 终端 2：播放
speaker-test -D hw:<card>,0 -F S16_LE -c 1 -r 16000 -t sine -f 440
# 终端 3：录音
arecord -D hw:<card>,0 -f S16_LE -c 1 -r 16000 -d 600 /tmp/soak.wav
# 终端 4：摄像头
ffplay -f v4l2 -input_format mjpeg -video_size 640x360 -framerate 10 /dev/videoN
# 终端 5：键盘与触摸
sudo evtest       # 交替选键盘那份与触摸那份，各敲/点若干次
# 终端 6：盯着重新枚举
sudo dmesg -w
```

判据：

1. 10 分钟内 **没有 USB 重新枚举**（`dmesg -w` 全程无新的 `usb ... new full-speed USB device`）；
2. 摄像头画面持续更新、无长时间卡顿；实测 fps ≥ 9.0；
3. 音频**无周期性爆音、无停声**，`/tmp/soak.wav` 全程有内容（`sox /tmp/soak.wav -n stat` 的 RMS 合理）；
4. 画面持续更新；**GUD 帧率如实记录**（预期比不开摄像头时明显低，见 Task 9 Step 5 的带宽账）；
5. 键盘能打字、触摸有 `ABS_MT_*`，两者都不卡键 —— P1/P2 踩过的「丢释放报告」在端点最忙时最容易复现，这里是它的压力测试；
6. 固件侧日志：`LZ4 解压失败` / `ppa srm 失败` / 音频欠载与溢出 / `uvc` 的 late+dropped / `cam_jpeg` 的 failed **全部为 0**（少量非零可接受，但**要如实记录数字，不许四舍五入成 0**）。

- [ ] **Step 4：拔插与热切换（UVC 特有的两个状态机）**

1. `ffplay` 起停各 5 次 ⇒ 每次都能重新出流，`uvc_stream_report()` 的计数连续、无泄漏；
   **且每次停掉 `ffplay` 后日志出现「摄像头取流 停止」** —— 这是「不用时零占用」的落点；
2. `ffplay` 运行中拔掉 USB-C 再插回 ⇒ 全部五项能力都恢复；
3. `ffplay` 与 `speaker-test` 同时起停交错若干次 ⇒ 不出现「声卡消失」或「视频节点消失」。

- [ ] **Step 5：若显示明显变慢，先归因再改**

带宽账预测 GUD 的理论上限从约 1364 掉到约 916 B/ms（−33%）。**掉得比这更多**才需要归因，候选按可能性排序：

1. **PSRAM 带宽争用**（最可能）—— DPI 读 110 MB/s + CSI 写 55 MB/s + PPA 读写 + JPEG 读。
   验证法：把 `camera_csi_stop()` 掉只留 UVC 发静态图（Task 5 的帧源），GUD 帧率若恢复 ⇒ 坐实；
2. **PPA 引擎争用** —— 摄像头每 100 ms 提交一次 1280×720 的 SRM，GUD 的脏矩形要排队。
   验证法：把摄像头的缩放改成 `PPA_TRANS_MODE_NON_BLOCKING` 或降到 5 fps 再测；
3. **任务优先级** —— `UVC_TASK_PRIORITY` 与 `TINYUSB_DEFAULT_TASK_PRIO` 同为 5，降到 4 再测；
4. **JPEG 编码耗时** —— 看 `cam_jpeg_stats()` 的 `last_us`；若单帧超过 30 ms，说明质量参数过高。

**把归因结论写进 README，不要只写「调了 X 就好了」。**

- [ ] **Step 6：结论产出（本步只产数据，改文档在 Task 11）**

---

## Task 11：文档与收尾

> ✅ **已完成**，但有两处**没能照本任务原样办到**，因为它们依赖未执行的 Task 10：
>
> - **Step 3 要求的「Task 10 实测的那两组数字」不存在** —— 端点/FIFO 那组
>   （`EP4 IN=112 words`、默认 231/11、调试 224/18）在 bring-up 时顺带读到了，已回填；
>   但**摄像头开着时的 GUD 帧率、PSRAM 带宽争用实测值没有**，README 里写成「⏳ 未测」
>   并明确标注「以下是推算，不是实测」。
> - **Step 4 要求「补上开摄像头时 GUD 帧率的实测变化」** —— 同理，包级 README 里
>   给的是带宽推算（周期性 172 → 584 B/ms，GUD 理论上限 −33%）并显式声明未实测。
>
> 另：Step 1 的清单里「不做 AE/AWB 闭环的代价」一条**已作废**（闭环做了），
> 改写成了 AE / AWB 两节 + 白平衡标定流程 + `cam_tune.h` 参数表，
> 并把 **AWB 未上板**这一限定在三份文档里都写明。

- [x] **Step 1**：`firmware/README.md` 加「UVC 摄像头」章节，至少覆盖：
  - **分辨率为什么是 640×360 而不是 spec 原写的 640×480** —— 那三条像素管线约束（传感器唯一可用模式 1280×720 / P4 的 ISP 没有缩放器 / PPA 缩放粒度 1/16），并说明**带宽上 640×480 本来是够的**，别让人以为是带宽不够；
  - **端点与 FIFO 的完整账**：dfifo 顶是 **242 words 而不是 256**（buffer DMA 模式下扣 2×ep_count），默认档余量 123 words = 492 字节，为什么取 448 而不取满，以及 Task 10 实测的那两组数字。**顺手改掉现有那处「CDC 通知 16 words」的笔误（实际 2 words）**；
  - **`dwMaxVideoFrameBufferSize` 那个静默带宽陷阱**（声明小了会让每包缩水而哪里都不报错）；
  - **`CFG_TUD_VIDEO` 与 `CFG_TUD_VIDEO_STREAMING` 必须同时定义**，只定义前者的症状是链接期缺 6 个符号；
  - **「带宽是零和的」的两个落点**：USB 侧 alt 0 不预留 ISO 带宽、PSRAM 侧 CSI 按需启停；以及**打开摄像头会让显示明显变慢**（用大白话写，附 Task 10 实测的 GUD 帧率），并写明「这是全速口的物理上限，不是 bug」；
  - **依赖树评估**：为什么用 `esp_cam_sensor` 而不是 `esp_video`（后者强制拖 `usb_host_uvc` / `esp_h264` / `esp_ipa`），以及 Task 7 Step 5 的判据；
  - **不做 AE/AWB 闭环的代价**：换光照环境会过曝/欠曝且不会自动恢复；
  - `CAM_JPEG_QUALITY` 的取值与实测的三个数字（平均帧、峰值帧、实测 fps）；
  - host 侧验证命令（`v4l2-ctl --list-formats-ext`、`ffplay`、`--stream-mmap` 统计帧率）；
  - **两个 `/dev/video*` 节点是正常现象**（后一个是 metadata 节点）。
- [x] **Step 2**：`firmware/README.md` 的「日志」章节**整段改写** —— `CONFIG_AIO_DEBUG_CDC` 的语义变了：
  - 新端点表（`0x81` CDC 数据 / `0x82` HID / `0x83` CDC 通知 / `0x84` **UVC，不再出借**）；
  - **代价从「借走 UVC 的 0x84」变成「整个音频功能不编译」**，并列出这一档下不可用的能力清单；
  - **优先接 UART0 + USB-TTL**：零端点代价、能抓上电最早的日志、默认档也能用。CDC 档是「手边只有一根 USB-C 线」时的替代品；
  - 两档的接口数/描述符长度更新为 **7 / 384** 与 **6 / 259**。
- [x] **Step 3**：`firmware/README.md` 的「端点预算」「资源占用」「文件」三节更新：
  - 端点表加 `0x84`，并把「余 1 条」改成「**4/4 用满**」；
  - Flash/DIRAM/PSRAM 增量（`idf.py size` 实测），PSRAM 要单列摄像头的大头：CSI 帧缓冲 2×1.84 MB + 缩放后 460 KB + JPEG 双缓冲 2×64 KB ≈ **4.3 MB**；
  - 文件表补 `uvc_stream.{c,h}` / `uvc_pattern.{c,h}` / `uvc_test_jpeg.h` / `camera_csi.{c,h}` / `cam_jpeg.{c,h}` / `test/test_uvc_pattern.c` / `test/jpeg_to_header.py` 七行。
- [x] **Step 4**：`components/packages/tab5-all-in-one/README.md` 状态清单：UVC 摄像头从「⏳ 规划中」移到 ✅（如实机通过），写明 **MJPEG 640×360 @ 10 fps**，并把「带宽是零和的」这条既有提示补上具体数字（开摄像头时 GUD 帧率的实测变化）。「文档」一节补本计划的链接。
- [x] **Step 5**：spec 回填：
  - **§7 订正**：`640×480` → **`640×360`**，补上三条像素管线约束；`esp_video` → **`esp_cam_sensor` + IDF 内置 CSI/ISP/JPEG/PPA**，并说明 `esp_video` 为什么不能用；补上「不做 AE/AWB 闭环」这条本阶段的取舍；
  - **§8.1 订正**：依赖表阶段 5 那一行从 `esp_video` 改成 `esp_cam_sensor`（并注明它的传递依赖只有 `esp_sccb_intf` + `cmake_utilities`）；
  - **§2 订正**：端点表补 `0x84` 已落地；**并订正 FIFO 口径 —— 可分配的是 242 words 不是 256**；
  - **§2 补充**：`CONFIG_AIO_DEBUG_CDC` 的新语义（关音频换 CDC，`0x84` 永久归 UVC），以及「有 USB-TTL 就接 UART0」；
  - **§10 阶段 5** 的验证标准勾掉，并把实测的 fps / 帧大小 / GUD 帧率影响写进去；
  - **§11 风险登记**：「TinyUSB UVC device 不可用」那条改成实测结论；新增一条「PSRAM 带宽争用」。
- [x] **Step 6**：提交。

```
git commit -m "docs(tab5): 补 UVC 摄像头的实现说明与实机验证结论 (P4 Task11)"
```

---

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **TinyUSB 的 UVC device 在这块板上跑不通**（spec 明说的「全场风险最高」项） | 摄像头功能落空 | **Task 5 是判定点**：用 flash 里的静态 JPEG 把 USB 那一层单独证通，此时没有摄像头/ISP/JPEG 编码器三个变量。Step 6 给了五步排查顺序；穷尽后仍不成立就按开头那节砍掉，**不阻塞已交付的四项** |
| **FIFO 装不下 448 B 的 ISO 端点**（可分配的只有 242 words，余量 123） | `SET_INTERFACE` 被 STALL，**`dfifo_alloc()` 失败无日志** | 取值 448 在 `is_dma` 真/假两种假设下都成立；Task 3 落地寄存器实测代码，Task 5/Task 10 读实际数字；硬约束 B 给了四级降级阶梯 |
| **`dwMaxVideoFrameBufferSize` 声明小了 ⇒ 每包缩水** | 带宽白掉三分之一，**哪里都不报错** | `usb_descriptors.h` 的 `_Static_assert`、`check_usb_desc.py` 的第 7 条断言、`tud_video_commit_cb()` 里把 `dwMaxPayloadTransferSize` 打进日志，三道 |
| **只定义 `CFG_TUD_VIDEO` 忘了 `CFG_TUD_VIDEO_STREAMING`** | `video_device.c` 编成空文件 ⇒ 链接期缺 6 个符号 | Task 1 Step 4 的注释写明机理；`usb_descriptors.c` 有 `_Static_assert` 守着两个宏都为 1 |
| **PSRAM 带宽争用把 DPI 显示弄花**（CSI 写 55 MB/s vs DPI 读 110 MB/s） | 屏幕撕裂/花屏 —— **这是最可能弄坏已验证功能的一条** | CSI **只在 host 选中 alt 1 时才 start**（Task 9 Step 4），不流时零占用；Task 8 Step 1 的第 5 条判据专盯这个；Task 10 Step 5 给了按可能性排序的归因清单 |
| **摄像头开着时 GUD 明显变慢** | 用户当成 bug 报 | 这是全速口的物理必然（带宽零和）：周期性从 172 B/ms 涨到 584 B/ms，留给 bulk 的理论上限 −33%。Task 9 Step 5 要实测两组数字，Task 11 要用大白话写进两个 README |
| **`CONFIG_AIO_DEBUG_CDC` 与 UVC 抢 `0x84`** | 一开日志就没摄像头，而摄像头 bring-up 恰恰最需要日志 | Task 3 把这一档重新定义为「关音频换 CDC」，`0x84` 永久归 UVC；FIFO 复算显示这一档反而多 7 words 余量；编译期 `#error` 守着三个组合 |
| **UVC 调试档下没有音频，有人拿它当产品档** | 用户报「插上没声音」 | Kconfig prompt/help、README 的日志章节、`sdkconfig.defaults` 的注释三处都写明「排障档，不是产品档」；且它同时让出 GUD 的 IN 端点，与产品档差别明显 |
| **`esp_video` 会拖进 `usb_host_uvc` / `esp_h264` / `esp_ipa`** | 依赖树污染，违反 spec §8.1 | 已查证 manifest（本计划「依赖树评估」一节），改用 `esp_cam_sensor`；Task 7 Step 5 有明确判据，不通过就退回自己写薄驱动 |
| **单缓冲导致画面横向撕裂** | 偶发、随内容变化，典型疑难杂症 | `tud_video_n_frame_xfer()` 只记指针、整帧发完前持续 memcpy 取数 —— `cam_jpeg.c` 双缓冲轮转，理由写在 `cam_jpeg.h` 的 ⚠️ 里 |
| **真实画面比合成色条难压，帧超 44 KB** | 实际帧率掉到声明值以下（描述符仍说 10 fps） | Task 6 Step 5 给了带判据的调参表（平均 ≤30 KB / 峰值 ≤44 KB）；Task 9 Step 1 要求在真实画面上重跑一遍；`cam_jpeg_encode()` 对超限帧走**可见的失败路径**（丢帧 + 计数），不截断 |
| **不做 AE/AWB 闭环** | 换光照环境过曝/欠曝且不自动恢复 | 明确写成本阶段的取舍（Task 8 Step 3 的注释 + README）；Task 8 的判据里**不含**「不同光照都正常」；下一阶段优先自己写 P 控制器，别引 `esp_ipa` |
| **传感器/CSI/ISP 的字段名与本计划写的对不上**（组件落地时才拉下来） | 编译不过 | Task 7 Step 4 / Task 8 Step 4 都要求先 `grep` 头文件对齐签名，**并把差异记进注释** |
| **接口号变动碰坏已验证功能** | GUD/HID/音频回归 | 端点号刻意不动，只在枚举末尾追加两项；Task 3 Step 1 有「vendor/HID/UAC 三段逐字节未变」的 diff 判据；每个上板任务的判据都含那四项 |
| **摄像头电源与面板/触摸同一颗 IO 扩展** | 新建 expander 句柄会把面板与触摸的电一起断掉 | `board_camera_enable()` 复用 `board_power.c` 已有的 `s_ioexp`，与背光/功放完全同构；`tab5_pins.h` 的注释写明后果 |
| 每帧路径打日志把视频饿死 | 观测干扰被观测 | 计数只累加，`uvc_stream_report()` 默认档打一次、CDC 档每 10 秒一次（与 `codec_audio_report()` 同构）；Task 8 的自检任务是**临时的，Task 9 必须删掉**（P3 的分档旋钮教训） |
