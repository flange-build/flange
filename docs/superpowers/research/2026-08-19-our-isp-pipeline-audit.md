# 我们现有的 Tab5 摄像头 ISP 管线（对齐前基线审计）

> **性质：如实记录，不作评价。** 本文只回答「我们实际配了什么、没配什么、数值是多少、在哪一行」。
> 任何「这样对不对 / 应该怎么改」的判断都不属于本文范围，留给后续与官方管线的逐级对照。
> 另一路正在重建 Espressif 官方管线；本文的章节与表格按「每行一级」组织，供逐行对照。

审计日期：2026-08-19
审计对象：`components/packages/tab5-all-in-one/firmware/`
所有行号均为审计当日 `main` 分支（`31f422b3`）工作树的行号。

## 0. 审计范围与环境

| 项 | 值 | 出处 |
|---|---|---|
| SoC | ESP32-P4 **rev v1.0** | `sdkconfig.defaults:12-13`（`CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`、`CONFIG_ESP32P4_REV_MIN_100=y`） |
| ESP-IDF | v6.0（`~/esp/esp-idf`，`git describe` = `v6.0`） | — |
| 传感器组件 | `espressif/esp_cam_sensor` **2.4.0**（约束 `~2.4.0`） | `main/idf_component.yml:32`；`managed_components/espressif__esp_cam_sensor/idf_component.yml` |
| **未引入** | `espressif/esp_video`、`espressif/esp_ipa` | `main/CMakeLists.txt:10`；`main/idf_component.yml:28-31` |
| 参与摄像头链路的源文件 | `uvc_stream.c` `cam_jpeg.c` `camera_csi.c` `cam_frame_stats.c` `cam_tune.c` | `main/CMakeLists.txt:7-8` |
| PSRAM | 32 MB HEX，200 MHz | `sdkconfig.defaults:36-38` |

**一个对齐时必须先说清的事实**：`esp_cam_sensor` 组件自带一份官方 IPA 调校参数
`managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/sc202cs_default.json`
（229 KB，含 AE 权重表/环境亮度曲线、色温 bp 曲线、CCM 表、gamma、去噪、锐化等），
由 `CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_CONFIGURATION_FILE=y`（`sdkconfig:3995`）选中。
**本工程一行都没有读它** —— 它只有 `esp_ipa` 会消费，而我们没引 `esp_ipa`。
即：官方的整套 SC202CS 调校数据在树里，但不在我们的运行路径上。

**确证程度标记**（全文通用）：
- **【码】** = 直接从源码读到的常量/调用/参数，确证。
- **【推】** = 由源码推算出的数（展开宏、算乘除），算式一并给出。
- **【测】** = 需要上板运行才知道，本文只记录「哪个日志字段会告诉你」。

---

## A. 管线级序：我们实际配了什么

### A.1 总表（每行一级，从出光到 UVC 送出）

| # | 级 | 我们做了什么 | 数据格式 / 色彩域 | 关键参数（实际数值） | 文件:行 |
|---|---|---|---|---|---|
| 0 | 摄像头供电 | IO 扩展 0x43 PIN6 拉高 + 延时 100 ms | — | `IOEXP_PIN_CAMERA_EN = IO_EXPANDER_PIN_NUM_6` | `camera_csi.c:56-57`；`tab5_pins.h:158` |
| 1 | SCCB 通道 | 复用内部 I2C（G31/G32）建 SCCB io，**不新建 master** | — | 7-bit 地址 `0x36`、100 kHz、寄存器地址 16 位 / 值 8 位 | `camera_csi.c:72-80`；`tab5_pins.h:166,179` |
| 2 | 传感器探测 | 自己读 PID（0x3107/0x3108）→ `sc202cs_detect()` | — | 期望 PID `0xeb52`；`reset_pin=-1` `pwdn_pin=-1` `xclk_pin=-1` `xclk_freq_hz=0` `sensor_port=ESP_CAM_SENSOR_MIPI_CSI` | `camera_csi.c:100-115`；`tab5_pins.h:167,174-175` |
| 3 | 传感器模式下发 | `esp_cam_sensor_set_format(dev, NULL)` → 组件写 **130 条**寄存器 | 输出 **RAW8 Bayer BGGR** | 模式 `MIPI_1lane_24Minput_RAW8_1280x720_30fps`（index 0） | `camera_csi.c:572`；`sc202cs.c:1326-1352` |
| 4 | MIPI D-PHY / CSI host | `esp_cam_new_csi_ctlr()` | RAW8 over CSI-2（DT 0x2A） | `ctlr_id=0`、`data_lane_num=1`、`lane_bit_rate_mbps=576`、`h_res=1280`、`v_res=720`、`clk_src=MIPI_CSI_PHY_CLK_SRC_DEFAULT` | `camera_csi.c:430-448` |
| 5 | **ISP 输入段** | `esp_isp_new_processor()` | RAW8 → 内部 | `clk_hz=80 000 000`、`input_data_source=ISP_INPUT_DATA_SOURCE_CSI`、`input_data_color_type=ISP_COLOR_RAW8`、`h_res=1280`、`v_res=720`、`bayer_order=COLOR_RAW_ELEMENT_ORDER_BGGR`、`has_line_start_packet=false`、`has_line_end_packet=false` | `camera_csi.c:206,521-532` |
| 6 | **去马赛克（demosaic）** | **隐式打开**：`output_data_color_type=ISP_COLOR_RGB565` 让驱动把 `cntl.demosaic_en=1` 一起置上；我们**没调** `esp_isp_demosaic_configure()`/`_enable()` | RAW8 → RGB（**线性域**） | 参数（梯度阈值 `grad_ratio`、去噪等级、padding）**一个都没设**，停在寄存器复位值 | `camera_csi.c:525`；IDF `isp_core.c:146` → `isp_ll.h:475-478` |
| 7 | **CCM（我们唯一配的画质级）** | `esp_isp_ccm_configure()` + `esp_isp_ccm_enable()` | 线性 RGB → 线性 RGB | 对角阵 `diag(R/1000, 1.000, B/1000)`；开机初值 **R×1.700 / G×1.000 / B×1.550**；`saturation=true`；`flags.update_once_configured=1`；非对角项全 `0.0f` | `camera_csi.c:290-307,552-557`；`cam_tune.h:111-113` |
| 8 | ISP 内部 RGB↔YUV 往返 | 未主动配置：`ISP_COLOR_RGB565` 使 `rgb2yuv_en=1` 且 `yuv2rgb_en=1` | RGB→YUV→RGB | `yuv_std` 零初始化 ⇒ **BT.601**（`ISP_YUV_CONV_STD_BT601 == 0`）；`yuv_range` 仅 YUV 输出时才写，本配置不写 | `camera_csi.c:521-531`（未列字段）；IDF `isp_core.c:166-169`；`hal/color_types.h:205` |
| 9 | ISP shadow 更新模式 | 未主动配置，驱动固定写 | — | `ISP_SHADOW_MODE_UPDATE_ONLY_NEXT_VSYNC` | IDF `isp_core.c:178` |
| 10 | ISP 输出格式 | `output_data_color_type=ISP_COLOR_RGB565` | **RGB565**（`isp_out_type=4`） | — | `camera_csi.c:525` |
| 11 | CSI 桥 | **直通**：`input_data_color_type == output_data_color_type == CAM_CTLR_COLOR_RGB565` | RGB565 搬运 | `byte_swap_en=false`、`queue_items=3`、`bk_buffer_dis=true` | `camera_csi.c:439-446` |
| 12 | DW-GDMA → PSRAM | 3 块帧缓冲轮转（free/done 两个队列 + `s_held`） | RGB565 紧凑排列 | 每块 `1280×720×2 = 1 843 200` B，`heap_caps_aligned_calloc(64, …, SPIRAM\|DMA)`，共 **5.27 MB** | `camera_csi.c:194-202,462-485` |
| 13 | 取帧 | `camera_csi_get_frame()`：`xQueueReceive(done)` + 自己做 `esp_cache_msync(M2C)` | RGB565 | 超时 `UVC_CAM_WAIT_MS = 100` ms | `camera_csi.c:719-755`；`uvc_stream.c:66` |
| 14 | 帧内容统计 | `cam_frame_stats_rgb565()` 全帧、**每帧一次** | RGB565 → 8 位分量 | `step=8`（采 1/64 像素 = 14 400 个）；亮度 `(77R+150G+29B)>>8` | `uvc_stream.c:70,191-197,238`；`cam_frame_stats.c:13-58` |
| 15 | AE / AWB 走一拍 | `camera_csi_tune_tick()` → 先 AE 后 AWB | — | 详见 §B | `camera_csi.c:823-848` |
| 16 | 下 1/8 统计 | `cam_frame_stats_rgb565()` 只扫最后 90 行，**每 10 帧一次**（1 秒） | RGB565 | 判 DMA 截断专用，不参与控制 | `uvc_stream.c:201-209,242-245` |
| 17 | **PPA SRM 缩放** | `ppa_do_scale_rotate_mirror()`，独立 client | RGB565 → RGB565 | `scale_x=scale_y=0.5`（= 8/16）；1280×720 → **640×360**；`rotation_angle=0`；`mirror_x/y=false`；`byte_swap=false`；`mode=BLOCKING`；`max_pending_trans_num=1` | `cam_jpeg.c:68-69,143-147,156-210` |
| 18 | **硬件 JPEG 编码** | `jpeg_encoder_process()` | RGB565 → JPEG（编码器内部 RGB→YCbCr） | `src_type=JPEG_ENCODE_IN_FORMAT_RGB565`、`sub_sample=JPEG_DOWN_SAMPLING_YUV422`（4:2:2）、`image_quality=70`、`width=640`、`height=360`；引擎 `intr_priority=0`、`timeout_ms=200`；双输出缓冲各 65 536 B（`jpeg_alloc_encoder_mem`，PSRAM） | `cam_jpeg.c:35,50,52,125-138,227-233,245-248` |
| 19 | UVC 送帧 | `tud_video_n_frame_xfer()` | MJPEG | 640×360 @ **10 fps**；ISO IN 0x84，`UVC_EP_SIZE=448` B/ms，`UVC_PAYLOAD_HDR=2`，`UVC_MAX_FRAME_BYTES=65536` | `uvc_stream.c:328`；`usb_descriptors.h:215-217,234,236,248` |
| 20 | 取流启停 | 由 host 的 alt 0/1 驱动：`tud_video_n_streaming()` 边沿 → `camera_csi_start()/stop()` | — | 帧泵周期 `100 ms`（`vTaskDelayUntil`），任务优先级 5、栈 4096 | `uvc_stream.c:41,48,261,282-306` |

### A.2 逐级细节补充

#### 级 3 —— 传感器寄存器表（我们没有自己写一个字节）

- 表文件：`managed_components/espressif__esp_cam_sensor/sensors/sc202cs/private_include/sc202cs_mipi_1lane_24Minput_1280x720_raw8_30fps.h`，**130 条**寄存器写（末尾另有一条 `{SC202CS_REG_END, 0x00}` 作结束标记）。
- 表头注释：`cleaned_0x18_FT_SC2356_24Minput_576Mbps_1lane_8bit_1280x720_30fps`（该文件第 6 行）。
- 表里带的曝光/增益默认值：`{0x3e00,0x00} {0x3e01,0x3d} {0x3e02,0xc0} {0x3e09,0x00}` ⇒ 曝光 = `0x3dc` = **988 行**，模拟增益 = 0。
- 表里**注释掉**的一行：`// {0x3902, 0x80}, // blc disable. 0xc0 enable`（同文件倒数第 3 行）—— 传感器侧 BLC 既没显式开也没显式关，停在芯片上电默认。**【码】**
- 下发路径：`esp_cam_sensor_set_format(s_sensor, NULL)`（`camera_csi.c:572`）→ `sc202cs_set_format()`（`sc202cs.c:1326`）→ `sc202cs_write_array()` 逐条 `esp_sccb_transmit_reg_a16v8()`（`sc202cs.c:1048-1061`）。

#### 级 4/11 —— 为什么 CSI 的 input/output 都填 RGB565

代码里已写明理由并有实机证据（`camera_csi.c:391-429`）：本板 rev v1.0，桥的颜色转换硬件不存在，
`input != output` 会让 `esp_cam_new_csi_ctlr()` 返回 `ESP_ERR_NOT_SUPPORTED`。
两个字段在本配置下只用于算两个字节数：
- `in_bpp=16` → `csi_transfer_size = 1280×720×16/64`
- `out_bpp=16` → `fb_size_in_bytes = 1280×720×16/8 = 1 843 200` **【推】**

#### 级 7 —— CCM 的定点表达

rev < 3.0 的 CCM 格式是「2 位整数 + 10 位小数 + 1 位符号」（`hal/isp_ll.h:138-144`）⇒ **系数上限 ±4.0，步进 1/1024**。
我们写下去的初值量化后：
- R 1.700 → `round(1.700×1024)=1741` → 实际 **1.70020** **【推】**
- G 1.000 → 1024 → 1.00000
- B 1.550 → `round(1.550×1024)=1587` → 实际 **1.54980** **【推】**

`esp_isp_ccm_configure()` 全文无芯片版本门（IDF `isp_ccm.c:20-46`），只做范围检查 + `isp_hal_ccm_set_matrix` + `isp_ll_shadow_update_ccm`。
`esp_isp_ccm_enable()` 有 FSM 门（`isp_ccm.c:48-59`），所以运行期重配只调 `configure`、不再调 `enable`（`camera_csi.c:286-288,301`）。

#### 级 18 —— 色彩域的接力

- ISP 输出是 **gamma 前的线性 RGB**（级 6 之后没有任何传递函数，见 §A.3 gamma 行）。
- PPA 只做双线性缩放，不改色彩域。
- JPEG 编码器把 RGB565 按 JPEG 标准的 RGB→YCbCr 线性矩阵变换（BT.601 全量程）后做 DCT ——
  **这是一个矩阵，不是传递函数**，所以 UVC 送出去的 MJPEG 里的码值仍然是线性光的码值。
  （编码器行为依据 IDF `esp_driver_jpeg` 与 JPEG 标准，非本仓代码 —— 标 **【推】**。）

### A.3 我们完全没碰的 ISP 级 —— 逐个确认「没配」还是「配了默认值」

> ⚠️ **本节已被 2026-08-23 的 ISP 对齐工程整体推翻，见文末 §F。**
> 下表记录的是**对齐前**的基线（`43288ae9`），作为历史基线仍然有效；
> 但「我们调了吗」那一列现在几乎每一行都变成了「是」。

判定方法：ESP-IDF 的 ISP 子模块**全部**是独立的 `esp_isp_<x>_configure()` / `esp_isp_<x>_enable()` /
`esp_isp_new_<x>_controller()` 入口（IDF `components/esp_driver_isp/src/*.c`）。
`esp_isp_new_processor()`（`isp_core.c:75-190`）**只**做这几件事：认领处理器与 CSI 桥、配时钟、
设输入/输出色彩格式、设输入源、行首/行尾包、H/V 分辨率、bayer 顺序、`yuv_std`、
（仅 DVP 输入时）`isp_ll_color_enable(true)`、`byte_swap`、shadow 模式。
**它不给任何画质子模块写参数。** 所以下表里凡是我们没调 API 的，硬件寄存器就停在**复位值**。

| ISP 级 | IDF 入口 | 我们调了吗 | 硬件状态 | 依据 |
|---|---|---|---|---|
| **BLC** 黑电平校正 | `esp_isp_blc_configure/enable` | **否** | `cntl.blc_en` 停在复位值；本板 rev v1.0 该 API 直接返回不支持（`isp_blc.c:29-30` 要求 rev ≥ 3.0） | `cam_tune.h:11-12` 已记录版本门 |
| **LSC** 镜头阴影校正 | `esp_isp_lsc_configure/enable` | **否** | 未使能。注意：版本门是 rev ≥ **1.00**（`isp_lsc.c:57-58`），本板**满足**，是「可用但没用」 | `cam_tune.h:14-16` |
| **BF** 双边滤波去噪 | `esp_isp_bf_configure/enable` | **否** | `cntl.bf_en` 停在复位值，sigma/模板系数从未写入 | `isp_bf.c:24-63`；`isp_ll.h:824-827` |
| **Demosaic 参数** | `esp_isp_demosaic_configure/enable` | **否**（但 `demosaic_en` 位被级 10 隐式置 1） | 去马赛克**在工作**，其梯度阈值/去噪等级/padding 停在复位值 | `isp_ll.h:475-478,1810-1813`；`isp_demosaic.c:23-57` |
| **Gamma** | `esp_isp_gamma_configure/enable`（含 `esp_isp_gamma_fill_curve_points`） | **否** | `cntl.gamma_en` 停在复位值，R/G/B 三条曲线的分段点从未写入 ⇒ **输出是线性域** | `isp_gamma.c:28-84`；`isp_ll.h:2361-2364` |
| **Sharpen** 锐化 | `esp_isp_sharpen_configure/enable` | **否** | `cntl.sharp_en` 停在复位值 | `isp_sharpen.c:23-66`；`isp_ll.h:2155-2158` |
| **Color** 对比度/饱和度/色调/亮度 | `esp_isp_color_configure/enable` | **否** | `cntl.color_en` 停在复位值。⚠️ 驱动只在 **DVP 输入**时自动 `isp_ll_color_enable(true)`（DIG-474 workaround），我们是 **CSI 输入**，这条不生效 | `isp_core.c:171-173`；`isp_color.c:24-63` |
| **WBG** 白平衡增益 | `esp_isp_wbg_configure/enable/set_wb_gain` | **否** | 本板 rev v1.0 该 API 直接返回不支持（`isp_wbg.c:29-30` 要求 rev ≥ 3.0）。白平衡改用 **CCM 对角线** 顶替 | `cam_tune.h:11,17-21` |
| **Crop** | `esp_isp_crop_*` | **否** | 要求 rev ≥ 3.0（`isp_crop.c:29-30`） | — |
| **硬件 AE 统计**（5×5 窗口亮度块） | `esp_isp_new_ae_controller` + `..._start_continuous_statistics` + 环境检测器 | **否** | 从未创建控制器。AE 反馈量改用**软件全帧均值** | `isp_ae.c:74-268`；`camera_csi.c:512-514` |
| **硬件 AWB 统计**（白点筛选） | `esp_isp_new_awb_controller` + `..._start_continuous_statistics` | **否** | 从未创建控制器。**这是主动取舍不是能力缺失** —— 该模块在本板可用，只有 subwindow 子功能在 rev < 3.0 被砍（`isp_awb.c:82` 仅打 warning） | `cam_tune.h:44-70`；`camera_csi.c:499-506` |
| **硬件 AF 统计** | `esp_isp_new_af_controller` | **否** | 从未创建。SC202CS 是定焦模组，无对焦马达 | `isp_af.c:80-289` |
| **Histogram 直方图** | `esp_isp_new_hist_controller` | **否** | 从未创建 | `isp_hist.c:102-270` |
| **Bypass ISP** | `esp_isp_processor_cfg_t.flags.bypass_isp` | **否**（零初始化 = false） | ISP 在管线内 | `camera_csi.c:521-531` |
| **byte_swap** | `esp_isp_processor_cfg_t.flags.byte_swap_en` | **否**（零初始化 = false） | 不交换 | 同上 |
| **ISP 事件回调** | `esp_isp_register_event_callbacks` | **否** | 无 ISP 中断回调 | `isp_core.c:213+` |

**传感器侧同样没碰的**（`esp_cam_sensor` 暴露但我们不设）：

| 参数 | ID | 我们设了吗 | 默认值 | 依据 |
|---|---|---|---|---|
| 水平镜像 | `ESP_CAM_SENSOR_HMIRROR` | 否 | 0（`sc202cs.c:1213-1218`） | 寄存器 0x3221 bit1-2 未写 |
| 垂直翻转 | `ESP_CAM_SENSOR_VFLIP` | 否 | 0 | 寄存器 0x3221 bit5-6 未写 |
| 测试图案 | `sc202cs_set_test_pattern`（priv ioctl） | 否 | 关（0x4501 bit3 未写） | `sc202cs.c:1078-1081` |
| 曝光（微秒口径） | `ESP_CAM_SENSOR_EXPOSURE_US` | 否，走寄存器口径 | — | 见 §C.3 |

---

## B. 我们的 AE / AWB 闭环结构

### B.0 结构总览

```
每取到一帧（10 fps）
  └─ cam_frame_stats_rgb565(raw, 1280, 720, step=8)        ← 唯一的反馈量来源
       ├─ lum_mean  → camera_ae_tick()  → cam_ae_step()    → SCCB 写传感器曝光+增益
       └─ r/g/b_mean→ camera_awb_tick() → cam_awb_step()   → esp_isp_ccm_configure()
```

调用顺序在 `camera_csi.c:842-847`：**先 AE 后 AWB**（AWB 要读到本帧刚更新的 `cam_ae_converged()`）。
两者都在 `uvc_stream.c:239` 每帧被调一次；频率限制在控制律内部，不由调用方判断。

### B.1 输入（统计量）

| 项 | 值 | 依据 |
|---|---|---|
| 采样位置 | **ISP 输出之后、PPA 缩放之前**的 1280×720 RGB565 原帧（PSRAM） | `uvc_stream.c:226-245`（`frame_stats_sample` 排在 `cam_jpeg_downscale` 之前） |
| 采样密度 | `step=8` ⇒ 每 8 行取 1 行、行内每 8 个取 1 个 = **1/64**；实采 `160×90 = 14 400` 像素/帧 **【推】** | `uvc_stream.c:70,193` |
| 采样区域 | **全画面均匀**，无权重、无窗口、无中心加权 | `cam_frame_stats.c:32-48` |
| 采样频率 | **每帧一次** = 10 Hz（帧泵 100 ms 一拍） | `uvc_stream.c:238,261` |
| 亮度口径 | `lum = (77·R8 + 150·G8 + 29·B8) >> 8`（BT.601 整数近似，权重和 = 256） | `cam_frame_stats.c:37` |
| 分量展开 | RGB565 的 5/6 位分量按「高位复制到低位」扩到 8 位：`R8=(r5<<3)\|(r5>>2)`、`G8=(g6<<2)\|(g6>>4)`、`B8=(b5<<3)\|(b5>>2)` ⇒ 满量程 → 255 | `cam_frame_stats.c:9-11` |
| 通道均值 | `r_mean/g_mean/b_mean` = 三个 8 位展开值的算术平均，与亮度**同一次扫描**算出 | `cam_frame_stats.c:39-41,55-57` |
| 门槛 | `samples == 0`（参数非法）时整拍不走；`!s_streaming` 时整拍不走 | `camera_csi.c:827-840` |

**关键口径说明（决定两边数字能否直比）**：
统计发生在 **CCM 之后**（CCM 在 ISP 内、统计在 ISP 输出上），
所以 `r/g/b_mean` 是**已经施加了当前 CCM 增益**的值 —— `cam_awb_suggest()` 的公式因此要乘回当前增益才幂等（`cam_tune.h:338-348`）。
统计也发生在 **gamma 之前**（我们没开 gamma），所以这些均值是**线性光**的均值，
与任何在 gamma 后取统计的管线**不可直接比较**。

### B.2 输出（执行器）

| 环 | 写到哪 | API | 单位 | 依据 |
|---|---|---|---|---|
| AE | 传感器寄存器 0x3e00/01/02（曝光）+ 0x3e06/07/09（数字粗/细增益 + 模拟增益） | `esp_cam_sensor_set_para_value(dev, ESP_CAM_SENSOR_GROUP_EXP_GAIN, &v, sizeof v)`，`v = {exposure_us=0, exposure_val=st.exposure, gain_index=st.gain_index}` | 曝光 = **行**；增益 = 增益表**下标** | `camera_csi.c:777-783`；`sc202cs.c:1163-1183`（增益）、`:1139-1161`（曝光）、`:1272+`（GROUP 入口） |
| AWB | ISP 的 CCM 矩阵对角线 | `esp_isp_ccm_configure(s_isp, &ccm_cfg)`（只 configure，不再 enable） | 系数 = 1/1000 | `camera_csi.c:290-307,805` |

AE 每次下发 = **6 次 SCCB 写**（曝光 3 + 增益 3）；AWB 每次下发 = **1 次 CCM 重配**（9 个系数寄存器）。

### B.3 AE 控制律与全部参数

**结构**：曝光与增益被合成一个标量 `ev = exposure × gain_milli / 1000`（`cam_tune.c:7-10`），
对 `ev` 做带 4 道闸的比例（P）控制，再由 `cam_ae_split()` 按「曝光时间优先、增益垫底」拆回两个旋钮。

| 宏 | 值 | 含义 | 定义位置 |
|---|---|---|---|
| `CAM_AE_TARGET` | **120** | 目标亮度均值（0..255，BT.601 口径） | `cam_tune.h:121` |
| `CAM_AE_DEADBAND` | **12** | 死区：\|mean − 120\| ≤ 12（即落在 **[108, 132]**）完全不动 **【推】** | `cam_tune.h:128` |
| `CAM_AE_DAMP_NUM` / `CAM_AE_DAMP_DEN` | **1 / 2** | 阻尼：每次只走到理论值的 **50%** | `cam_tune.h:136-137` |
| `CAM_AE_STEP_MAX` | **2** | 单步限幅：一拍最多 ×2 或 ÷2 | `cam_tune.h:145` |
| `CAM_AE_GAIN_MAX_MILLI` | **16000** | 增益上限 16.000×（传感器表本身能到 63.008×） | `cam_tune.h:153` |
| `CAM_AE_INTERVAL_TICKS` | **3** | 更新周期 = 3 拍 = **300 ms**（一拍 100 ms） **【推】** | `cam_tune.h:167` |
| `CAM_AE_CONVERGE_TICKS` | **3** | 连续 3 次落在死区内 ⇒ 报「收敛」（纯观测量） | `cam_tune.h:170` |

**每一拍的执行顺序**（`cam_tune.c:75-139`）：

| 步 | 动作 | 行 |
|---|---|---|
| 1 | 记 `st->last_mean = lum_mean`（无条件） | `cam_tune.c:80` |
| 2 | **闸4 频率**：`settle` 非零则 `settle--` 并 return false | `cam_tune.c:83-87` |
| 3 | **闸1 死区**：`diff ∈ [−12, +12]` ⇒ `in_band++`（封顶 3），return false | `cam_tune.c:90-95` |
| 4 | 理论值：`want = ev × 120 / max(mean,1)` | `cam_tune.c:100-101` |
| 5 | **闸2 阻尼**：`next = ev + (want − ev)×1/2` | `cam_tune.c:104-105` |
| 6 | **闸3 限幅**：`next` 钳到 `[ev/2, ev×2]` | `cam_tune.c:108-113` |
| 7 | 物理限：钳到 `[ev_min, ev_max]` | `cam_tune.c:116-124` |
| 8 | `cam_ae_split(next)` 拆成 (exposure, gain_index) | `cam_tune.c:127` |
| 9 | 与上次相同 ⇒ return false（不打扰 I2C） | `cam_tune.c:130-131` |
| 10 | 提交，**并把 `ev` 存成量化后的实际值** `exposure × gain_map[idx] / 1000` | `cam_tune.c:133-138` |

**`cam_ae_split()` 的分配策略**（`cam_tune.c:18-51`）：
先把 `ev` 全部当成曝光行数并钳到 `[exp_min, exp_max]`；
剩下的倍数 `need = ev×1000/exp` 交给增益；
增益取「表中不超过 `need` 且不超过 16000 的**最大**一档」（线性扫描，`cam_tune.c:43-47`）。

**本板实际的数值边界**（由传感器运行时查得，见 §C）：

| 量 | 值 | 算式 |
|---|---|---|
| `exp_min` | **8** 行 | `s_sc202cs_exp_min = 0x08`（`sc202cs.c:66`） |
| `exp_max` | **1244** 行 | `vts(1250) − s_sc202cs_exp_vts_offset(6)`（`sc202cs.c:67,1192`） **【推】** |
| `exp_def` | **988** 行 ≈ **26.3 ms** | `0x3dc`；`988/1250 × 33.33 ms` **【推】** |
| `gain_count` | **192** | 增益表全长（见 §C.4） |
| `gain_def` | 下标 **0** ⇒ 1.000× | `isp_v1_info.gain_def = 0`（`sc202cs.c:885`） |
| AE 实际可用的最高增益档 | 下标 **128** = 16.000× | 表中 `[128] == 16000`，`[129] == 16257 > 16000` 被 `CAM_AE_GAIN_MAX_MILLI` 截断 **【推】** |
| `ev_min` | **8** | `8 × 1000/1000` |
| `ev_max` | **19 904** | `1244 × 16000/1000` **【推】** |
| 开机 `ev` | **988** | `988 × 1000/1000` **【推】** |
| 总动态范围 | **2488×** ≈ 11.3 EV **【推】** | `19904 / 8` |

**AE 关闭的条件**（`camera_csi.c:589-619`）：`esp_cam_sensor_query_para_desc()` 任一失败，
或 `gain.enumeration.elements == NULL`、`count == 0`、`exp.minimum == 0`、`exp.maximum < exp.minimum` ⇒
`s_ae_ready = false`，曝光永远停在 `exp_def`（988 行），此时 `s_st_ae` 若为 `ESP_OK` 会被改写成 `ESP_ERR_INVALID_RESPONSE`。

### B.4 AWB 控制律与全部参数

**假设**：灰世界（Gray World）。**执行器**：CCM 对角线的 R 与 B，G 恒为 1.000 作基准。

| 宏 | 值 | 含义 | 定义位置 |
|---|---|---|---|
| `CAM_AWB_ENABLE` | **1** | 总开关；为 0 时 AWB 相关代码在 `camera_csi.c` 里整段 `#if` 掉 | `cam_tune.h:180` |
| `CAM_CCM_GAIN_R_MILLI` | **1700** | R 增益开机初值 1.700× | `cam_tune.h:111` |
| `CAM_CCM_GAIN_G_MILLI` | **1000** | G 恒定 1.000×（**不参与闭环**） | `cam_tune.h:112` |
| `CAM_CCM_GAIN_B_MILLI` | **1550** | B 增益开机初值 1.550× | `cam_tune.h:113` |
| `CAM_AWB_INTERVAL_TICKS` | **10** | 更新周期 10 拍 = **1 秒** **【推】** | `cam_tune.h:193` |
| `CAM_AWB_DEADBAND_PCT` | **5** | 死区：建议值与当前值相差 ≤5% 就不动（R、B **都**满足才算） | `cam_tune.h:200` |
| `CAM_AWB_DAMP_NUM` / `_DEN` | **1 / 2** | 阻尼 50% | `cam_tune.h:207-208` |
| `CAM_AWB_STEP_MAX_PCT` | **25** | 单步限幅：一周期内增益最多变 ±25% | `cam_tune.h:216` |
| `CAM_AWB_LUM_MIN` | **40** | 防护①：`lum_mean < 40` ⇒ 暗场，不更新 | `cam_tune.h:248` |
| `CAM_AWB_LUM_MAX` | **200** | 防护②：`lum_mean > 200` ⇒ 过亮（削顶），不更新 | `cam_tune.h:249` |
| `CAM_AWB_CAST_MAX_PCT` | **200** | 防护③：`max(r,g,b)/min(r,g,b) > 2.00×` ⇒ 判为单色场景，不更新；任一通道为 0 也拦下 | `cam_tune.h:250` |
| `CAM_AWB_GAIN_MIN_MILLI` | **1000** | 防护④下界：**建议值** < 1.000× ⇒ 整拍不更新 | `cam_tune.h:251` |
| `CAM_AWB_GAIN_MAX_MILLI` | **3000** | 防护④上界：**建议值** > 3.000× ⇒ 整拍不更新 | `cam_tune.h:252` |
| `CAM_AWB_CONVERGE_TICKS` | **3** | 连续 3 个周期落在死区 ⇒ 报「收敛」（纯观测量） | `cam_tune.h:255` |
| `CAM_CCM_MIN_MILLI` | **250** | `cam_awb_suggest()` 输出钳位下界（0.250×） | `cam_tune.c:147` |
| `CAM_CCM_MAX_MILLI` | **4000** | `cam_awb_suggest()` 输出钳位上界（4.000× = 硬件定点上限） | `cam_tune.c:148` |

**建议值公式**（`cam_tune.c:150-170`）：
```
sug_R = clamp(cur_R × g_mean / r_mean, 250, 4000)
sug_B = clamp(cur_B × g_mean / b_mean, 250, 4000)
（r_mean 或 b_mean 为 0 时该通道保持 cur 不变）
```
乘上 `cur_*` 是因为统计取在 CCM 之后 —— 这让公式在系数正确时**幂等**。

**每一拍的判据顺序**（`cam_tune.c:226-302`，与自检行的直方图顺序一致）：

| 序 | 判据 | 不通过时的返回值 | 消耗 `settle` 吗 | 行 |
|---|---|---|---|---|
| 0 | 记 `last_r/g/b`（无条件） | — | — | `cam_tune.c:233-235` |
| 1 | `ae_converged` 为假 | `CAM_AWB_SKIP_AE` | 否 | `cam_tune.c:245-246` |
| 2 | `lum_mean < 40` | `CAM_AWB_SKIP_DARK` | 否 | `cam_tune.c:247-248` |
| 3 | `lum_mean > 200` | `CAM_AWB_SKIP_BRIGHT` | 否 | `cam_tune.c:249-250` |
| 4 | `hi/lo > 2.00×` 或 `lo == 0` | `CAM_AWB_SKIP_CAST` | 否 | `cam_tune.c:254-260` |
| 5 | `settle` 非零 | `CAM_AWB_SKIP_PERIOD` | **是**（`settle--`） | `cam_tune.c:263-267` |
| 6 | 建议值出 `[1000, 3000]`（R 或 B 任一） | `CAM_AWB_SKIP_RANGE` | 已消耗 | `cam_tune.c:278-280` |
| 7 | R、B 建议值都在 5% 死区内 | `CAM_AWB_SKIP_BAND`（`in_band++`） | 已消耗 | `cam_tune.c:283-288` |
| 8 | 阻尼+限幅后整数落回原值 | `CAM_AWB_SKIP_QUANT` | 已消耗 | `cam_tune.c:294-295` |
| 9 | 否则 | `CAM_AWB_APPLIED`（`updates++`、`in_band=0`） | 已消耗 | `cam_tune.c:297-301` |

`awb_next()`（`cam_tune.c:199-215`）顺序：阻尼 → ±25% 限幅 → 钳到 `[1000, 3000]`。

**`ae_converged` 的传入值**（`camera_csi.c:799`）：
```c
const bool ae_stable = !s_ae_ready || cam_ae_converged(&s_ae);
```
即 **AE 关闭时传 true**（曝光恒定 ⇒ 亮度稳定）。

**写 CCM 失败时的回滚**（`camera_csi.c:805-819`）：把 `s_awb.gain_r/b_milli` 回滚到 `s_ccm_r/s_ccm_b`（硬件里实际生效的那一对）。

### B.5 两环的相互关系与时序

| 机制 | 内容 | 依据 |
|---|---|---|
| 解耦① 归一化 | AWB 的反馈量是通道**比值**，AE 改亮度时三通道同比例变 ⇒ 建议值不变 | `cam_tune.h:400-408` |
| 解耦② 时间尺度分离 | AE 周期 300 ms（3 拍），AWB 周期 1000 ms（10 拍），比值 **1:3.33** | `cam_tune.h:167,193` |
| 解耦③ 收敛闸 | AWB 只在 `cam_ae_converged()` 为真时才动 | `cam_tune.c:245-246` |
| 调用顺序 | 同一帧内先 AE 后 AWB | `camera_csi.c:842-847` |
| AE 滞后预算（代码里的推导） | 传感器应用 1~2 帧 @30fps = 33~66 ms + CSI 积压 ≤66 ms + 帧泵 ≤100 ms ≈ **230 ms** ⇒ 取 300 ms | `cam_tune.h:159-166` |
| AE 最坏收敛步数（代码里的推导） | 60× 场景骤变，2× 限幅 ⇒ 约 6 步 ≈ **2 秒** | `cam_tune.h:141-144,189` |

---

## C. 传感器侧

### C.1 模式

| 项 | 值 | 依据 |
|---|---|---|
| 模式名 | `MIPI_1lane_24Minput_RAW8_1280x720_30fps` | `sc202cs.c:931` |
| 模式下标 | **0**（`CONFIG_CAMERA_SC202CS_MIPI_IF_FORMAT_INDEX_DEFAULT=0`） | `sdkconfig:3987` |
| 编进固件的模式 | **只有这一个**（其余 3 个 `=n`） | `sdkconfig.defaults:79-82` |
| 像素格式 | `ESP_CAM_SENSOR_PIXFORMAT_RAW8` | `sc202cs.c:932` |
| 分辨率 / 帧率 | 1280×720 @ 30 fps | `sc202cs.c:935-936,939` |
| XCLK | 24 MHz（板载晶振，**无 XCLK 引脚**） | `sc202cs.c:934`；`tab5_pins.h:149-151` |
| MIPI | `mipi_clk = 576 000 000`、`lane_num = 1`、`line_sync_en = false` | `sc202cs.c:942-945` |
| VTS / HTS | **1250 / 1920** | `sc202cs.c:882-883` |
| Bayer | `ESP_CAM_SENSOR_BAYER_BGGR` | `sc202cs.c:887` |
| 我们照抄进 ISP 的 bayer | `COLOR_RAW_ELEMENT_ORDER_BGGR`（**按名字抄，两个枚举数值顺序相反**） | `camera_csi.c:530`；注释见 `camera_csi.c:516-519` |
| 一行时长 | **26.67 µs** = `33.33 ms / 1250` **【推】** | — |

### C.2 寄存器表来源

- 文件：`managed_components/espressif__esp_cam_sensor/sensors/sc202cs/private_include/sc202cs_mipi_1lane_24Minput_1280x720_raw8_30fps.h`
- 条数：**130**（不含 `SC202CS_REG_END` 结束标记）
- 来源标注：`cleaned_0x18_FT_SC2356_24Minput_576Mbps_1lane_8bit_1280x720_30fps`
- **我们没有对这张表做任何修改、追加或覆盖**。**【码】**

### C.3 我们通过 `esp_cam_sensor` 设了哪些 / 没设哪些

| 操作 | 调了吗 | 参数 | 位置 |
|---|---|---|---|
| `sc202cs_detect()` | 是 | 见 §A.1 级 2 | `camera_csi.c:115` |
| `esp_cam_sensor_set_format(dev, NULL)` | 是 | NULL ⇒ 组件自选 index 0 | `camera_csi.c:572` |
| `esp_cam_sensor_query_para_desc(EXPOSURE_VAL)` | 是 | 取 min/max/default | `camera_csi.c:591` |
| `esp_cam_sensor_query_para_desc(GAIN)` | 是 | 取 elements/count/default | `camera_csi.c:593` |
| `esp_cam_sensor_ioctl(IOC_S_STREAM, 1/0)` | 是 | 写 0x0100 = 1/0 | `camera_csi.c:644,697`；`sc202cs.c:1119-1128` |
| `esp_cam_sensor_set_para_value(GROUP_EXP_GAIN)` | 是，AE 每次下发 | `{0, exposure, gain_index}` | `camera_csi.c:777-783` |
| `ESP_CAM_SENSOR_EXPOSURE_US` | **否** | 走寄存器口径，`exposure_us=0` 明确表示「用 `exposure_val`」 | `camera_csi.c:778` |
| `ESP_CAM_SENSOR_HMIRROR` / `VFLIP` | **否** | — | — |
| 测试图案 / 软复位 / 硬复位 | **否**（`reset_pin=-1` ⇒ `sc202cs_hw_reset()` 是空操作） | — | `sc202cs.c:1083-1092` |
| 帧率 / VTS / vblank 调整 | **否** | 固定 30 fps | — |

### C.4 曝光/增益的下发路径与单位

**曝光**（`sc202cs.c:1139-1161`）：
```
u32_val → clamp[8, exposure_max=1244] → 0x3e00 = (v>>12)&0xF
                                        0x3e01 = (v>>4)&0xFF
                                        0x3e02 = (v&0xF)<<4
```
合成后寄存器域 = `v << 4`，而 SC202CS 的曝光寄存器以 **1/16 行**为单位
⇒ **`exposure_val` 的单位是「行」**。**【推】**
交叉验证：`EXPOSURE_SC202CS_TO_V4L2(1244)` = `1244×10⁶/30/1250/100` ≈ **331**（单位 100 µs）= 33.1 ms ≈ 一整帧。✔

**增益**（`sc202cs.c:1163-1183`）：
```
gain_index → clamp MIN(idx, s_limited_abs_gain_index) → sc202cs_gain_map[idx]
             0x3e06 = dgain_coarse
             0x3e07 = dgain_fine
             0x3e09 = analog_gain
```

**增益表**（本工程编进去的那一张）：

| 项 | 值 | 依据 |
|---|---|---|
| 策略 | `CONFIG_CAMERA_SC202CS_DIG_GAIN_PRIORITY=y`（数字增益优先，Kconfig 默认，我们没显式改） | `sdkconfig:3991-3993` |
| 上限配置 | `CONFIG_CAMERA_SC202CS_ABSOLUTE_GAIN_LIMIT=63008`（Kconfig 默认） | `sdkconfig:3989` |
| 表长 | **192** 项 | `sc202cs.c:475-673` |
| 值域 | `[0]=1000`（1.000×） … `[191]=63008`（63.008×） | 同上 |
| `s_limited_abs_gain_index` | **192**（表中无一项 > 63008 ⇒ `sc202cs.c:1528-1532` 的循环从不 `break`，停在 `ARRAY_SIZE`） **【推】** | `sc202cs.c:1501,1528-1532` |
| `query_para_desc` 报出的 `count` | **192** ⇒ 我们的 `s_ae_lim.gain_count = 192`，合法下标 0..191 | `sc202cs.c:1205-1206` |
| 我们自己保证下标合法 | 是（`cam_ae_split()` 只在 `i < gain_count` 内取，且 `cam_ae_init()` 会钳） | `cam_tune.c:43-47,63-64` |

> 记录（不作评价）：`sc202cs_set_total_gain_val()`（`sc202cs.c:1166`）的 `MIN(u32_val, s_limited_abs_gain_index)` 在
> `s_limited_abs_gain_index == 192` 时会放行下标 192，而表长也是 192。我们的代码在
> `cam_tune.h:300-306` 明确记录了这一点并自行保证传入值 ≤ 191。

---

## D. 观测与判据（我们现在能看到哪些数字）

复读节奏：`app_main.c:411-436` 的 10 秒循环里，**host 挂载过一次之后**（`fifo_logged == true`，`app_main.c:417-419,434`）
每 10 秒打一遍 `uvc_stream_report()` + `camera_csi_report()`（`app_main.c:435-436`）。
`camera_sensor_report()` 只在 `CONFIG_AIO_DEBUG_CDC` 档下复读（`app_main.c:459`，默认关）。
默认档这些行走 UART0（G37/G38）。

### D.1 `[自检] SCCB` 行 —— `camera_csi.c:176-178`

| 字段 | 采自 | 口径 |
|---|---|---|
| `SCCB(0x36)=` | `sccb_new_i2c_io()` 返回值 | 三态：`未运行`（`STEP_NOT_RUN = INT32_MIN`）/ 错误码 / `ESP_OK` |
| `pid_rd=` | 我们自己两次 `esp_sccb_transmit_receive_reg_a16v8()` 的返回值 | 同上 |
| `pid=` | 0x3107<<8 \| 0x3108 | 字符串；「未读到」与任何数值严格区分 |
| `detect=` | `sc202cs_detect() != NULL` | 0/1 |

### D.2 `[自检] CSI` 行 —— `camera_csi.c:969-977`

| 字段 | 采自 | 口径 |
|---|---|---|
| `fb= ctlr= cbs= isp= fmt= start=` | 六个初始化步骤各自的返回值，**不共用哨兵** | `camera_csi.c:246-251` |
| `取流中=` | `s_streaming` | 0/1 |
| `帧=` | `s_frames_done`：`received_size` 校验通过并成功入 done 队列 | 中断里累加，`camera_csi.c:362-363` |
| `抢缓冲=` | `s_frames_reused`：空闲队列见底，把正在写的那块又借给 DMA，这一帧**不交出去** | `camera_csi.c:348-352` |
| `丢弃=` | `s_frames_dropped`：done 队列满 | `camera_csi.c:365` |
| `取帧超时=` | `s_get_timeouts`：`camera_csi_get_frame()` 超时（100 ms） | `camera_csi.c:733` |
| `帧长不符=` / `实收` | `s_size_mismatch` / `s_last_size`：驱动交回的 `received_size ≠ 1 843 200` | `camera_csi.c:353-359` |

### D.3 `[自检] 画质` 行 —— `camera_csi.c:873-882`

| 字段 | 采自 | 口径 |
|---|---|---|
| `CCM=` | `s_st_ccm`（configure + enable 的合并结果） | 错误码 |
| `当前 R× G× B×` | `s_ccm_r` / `CAM_CCM_GAIN_G_MILLI` / `s_ccm_b`，**此刻真正写进硬件的那一对** | 千分数打成 `x.yyy` |
| `通道均值 R G B` | `s_last_stats.r/g/b_mean` —— **最近一帧**的 1/64 采样均值 | 0..255，**CCM 之后、gamma 之前（无 gamma）、线性光** |
| `建议 R× B×` | `cam_awb_suggest(r,g,b, s_ccm_r, s_ccm_b)` | **绝对**建议值（已含当前 CCM），非增量 |

### D.4 `[自检] AWB` 行 —— `camera_csi.c:906-918`（`CAM_AWB_ENABLE=1` 时）

| 字段 | 采自 |
|---|---|
| `R× B×` | `s_awb.gain_r_milli` / `gain_b_milli` |
| `已收敛/调整中` | `cam_awb_converged()`（`in_band >= 3`） |
| `下发=` | `s_awb.updates`（真正改过增益的次数） |
| `最近=名(错误码)` | `cam_awb_reason_str(s_awb.last)` + `s_awb_last_err` |
| `未更新：AE未稳/暗场/过亮/色偏过大/未到周期/死区内/增益越界/量化无变化` | `s_awb.reasons[]` 八个计数器，**完整直方图**（每拍恰好计一次，`cam_tune.c:186-191`） |

### D.5 `[自检] AE` 行 —— `camera_csi.c:936-942`

| 字段 | 采自 | 口径 |
|---|---|---|
| `AE=` | `s_st_ae` | 错误码 / `未运行` |
| `曝光=x/y` | `s_ae.exposure` / `s_ae_lim.exp_max` | **行**（本模式下 1 行 = 26.67 µs） |
| `增益=n.nnn×(第 k 档)` | `s_ae_lim.gain_map[s_ae.gain_index]` / `gain_index` | 绝对增益（1/1000）+ 下标 |
| `曝光量=` | `s_ae.ev` | `exposure × gain_milli / 1000`，量化后的实际值 |
| `亮度 m→目标 120(±12)` | `s_ae.last_mean` | BT.601 整数近似，1/64 采样，全画面均匀 |
| `已收敛/调整中` | `cam_ae_converged()`（`in_band >= 3`） | |
| `下发=` / `最近=` | `s_ae.updates` / `s_ae_last_err` | |

### D.6 `[自检] streaming / 编码 / 缩放 / 画面` 四行 —— `uvc_stream.c:359-433`

| 行 | 字段 | 口径 |
|---|---|---|
| streaming | `提交/完成/拒收`、`commit×`、`payload`（应为 448）、`frame_max`、`interval` | 提交 = `tud_video_n_frame_xfer()` 成功；完成 = host 收全；`interval` 单位 100 ns |
| 编码 | `编码/失败`、`帧字节 最近/平均/峰值`、`峰值占 N/100 ms`、`编码耗时 µs` | `N = ceil(peak / (448−2))`（一包 = 一毫秒）；耗时用 `esp_timer` 包住 `jpeg_encoder_process()` |
| 缩放 | `缩放/失败/耗时 µs`、`实测 fps`、`摄像头启停=` | fps 用**完成**帧数差 ÷ 时间差算，非提交数 |
| 画面 | `采样`、`均值/最暗/最亮`、`下1/8 均值/最亮`、`历史最亮 全帧/下1/8`、`校验和`、`PSRAM 读 空载/取流中/停流后 MB/s` | 全帧统计 = 1/64 采样、每帧；下 1/8 = 最后 90 行、1/64 采样、每秒；校验和 = 采样像素原始 16 位值的 **FNV-1a 32**（逐字节、顺序敏感） |

**自动判读**（`uvc_stream.c:437-439`）：`s_full_max_ever > 16 && s_bottom_max_ever == 0` ⇒ 打 ERROR「DMA 只填了上半张」。

### D.7 统计口径小结（跨管线比较时必须对齐的四件事）

1. **亮度定义**：`(77R + 150G + 29B) >> 8`，即 BT.601 的 `0.30R + 0.586G + 0.113B`（整数近似，非 `0.299/0.587/0.114` 的精确值，也**不是** BT.709）。`cam_frame_stats.c:37`
2. **取样点**：ISP 输出（CCM 之后、**gamma 之前 —— 我们没有 gamma 级**）的 RGB565，1280×720 原帧。**线性光域**。
3. **采样密度与权重**：1/64 均匀采样（160×90 = 14 400 点），**无中心加权、无窗口分块**。
4. **量化**：先把 RGB565 的 5/6 位分量高位复制扩到 8 位再统计 ⇒ 三个通道均值可直接比大小；均值本身是 8 位整数（`sum/n` 截断）。

---

## E. 确证 / 待实测清单

**确证（源码读到）**：本文所有 §A/§B/§C 的参数与调用、§D 的字段来源。

**待实测（必须上板才知道）**：

| 项 | 由哪个字段告诉你 |
|---|---|
| CCM 是否真的配上 | `[自检] 画质 CCM=` |
| 通道均值的实际比例（白平衡准不准） | `[自检] 画质 通道均值 R G B` |
| AE 是否收敛、稳定在什么曝光/增益上 | `[自检] AE 曝光= 增益= 已收敛` |
| AWB 主要被哪道防护挡住 | `[自检] AWB 未更新：…` 八个计数器 |
| 去马赛克/BF/gamma 复位值下的实际画面表现 | 只能看画面 + `最暗/最亮/校验和` |
| JPEG 帧大小是否落在 20~44 KB 预算 | `[自检] 编码 帧字节 峰值` |
| PSRAM 带宽被这条链路吃掉多少 | `[自检] 画面 PSRAM 读 空载→取流中→停流后` |
| 实际帧率 | `[自检] 缩放 … 实测 x.y fps` |

**本文未能从代码确定的**（对齐时如需要，得查 TRM 或实测寄存器）：
ISP 各未配置子模块（BF / demosaic 参数 / gamma / sharpen / color / BLC）的**寄存器复位值**具体是多少。
代码只能证明「我们没写」，不能证明「硬件上是 0 还是某个非零默认」。

---

## F. 实施回填（2026-08-23，ISP 对齐工程 T0–T13 之后）

> **本文 §A–§E 是「对齐前基线」，作为历史记录**（对应 `main` 分支 `31f422b3`，
> 画质配置等价于 `43288ae9`）**仍然准确**。
> 本节记录对齐之后哪些结论**不再成立**，以及审计当时的哪些判断被推翻。
>
> ⚠️ **对齐后的实现一次都没有烧过板** —— 下面凡是说「现在配了 X」的，
> 都只表示**代码里配了**，不表示实机验证过。逐项状态见
> `components/packages/tab5-all-in-one/firmware/README.md` 的状态表与「上板验证清单」。

### F.1 §A.3 那张「我们完全没碰的 ISP 级」表 —— 大部分行已失效

| ISP 级 | 审计时 | 现在 | 开关 |
|---|---|---|---|
| BLC | 否（rev v1.0 不可用） | 仍然否。**但多了一条替代路**：SC202CS 传感器自带 BLC（`0x3902`），默认**只读不写** | `CAM_SENSOR_BLC_ENABLE`（默认 **0**） |
| **LSC** | 否 —— 「可用但没用」 | **配了**：官方 273 格 × 4 通道，按 CCT 3 档最近邻 | `CAM_LSC_ENABLE` |
| **BF** | 否 | **配了**：按增益 7 档 | `CAM_ADN_ENABLE` |
| **Demosaic 参数** | 否（`demosaic_en` 被隐式置 1） | **configure 了**（仍不 `enable`，见 §F.3 #3）：`gradient_ratio` 按增益 4 档 | `CAM_ADN_ENABLE` |
| **Gamma** | 否 ⇒ **输出是线性域** | **配了**：官方 4 档曲线，按 `env.luma` 动态选。**且统计侧建了逆表**，让 AE/AWB 的反馈量继续留在线性域 | `CAM_GAMMA_ENABLE` / `CAM_GAMMA_ADAPTIVE` |
| **Sharpen** | 否 | **配了**：按增益 4 档 | `CAM_AEN_ENABLE` |
| **Color** | 否 | **配了**：对比度按增益 4 档、饱和度按 CCT 2 档；色调/亮度写 0（官方标定里没有这两个字段 ⇒ **写 0 就是对齐**） | `CAM_AEN_ENABLE` |
| WBG / Crop | 否（rev v1.0 不可用） | 仍然否 | — |
| **硬件 AE 统计** | 否 ⇒ AE 用软件全帧均值 | **建了**（连续模式），且 **AE 反馈量已切过去** | `CAM_AE_STAT_ENABLE` / `CAM_AE_SOURCE` |
| **硬件 AWB 统计** | 否 —— **「这是主动取舍不是能力缺失」** | **建了**（oneshot，1 秒一次），且 **AWB 估计器已切过去** | `CAM_AWB_STAT_ENABLE` / `CAM_AWB_SOURCE` |
| **Histogram** | 否 | **建了**（oneshot，与 AWB 错开半周期） | `CAM_HIST_ENABLE` |
| 硬件 AF 统计 | 否 | 仍然否（定焦模组） | — |
| **ISP 事件回调** | 否 —— 「无 ISP 中断回调」 | **有了**：三个统计块共用一个 ISP 中断（`intr_priority` 全写 0） | — |

### F.2 被推翻的判断

| # | 审计/当时的说法 | 现在 | 为什么变 |
|---|---|---|---|
| 1 | `cam_tune.h` 那节「**为什么不挂硬件 AWB 统计**」的四条理由 | **落脚点那条不成立了** | 原论证的落脚点是「白点框本身要靠色卡标定，拿不准的参数换不来更可信的统计」。T0 把官方 `awb.range` 机械提取进 `cam_isp_cal.h`，且它与我们的采样点**同域**（官方在未做 WB 的 raw 色度空间里标的，`rg ∈ [0.38, 0.88]`；本板同样没有 WBG、同样采在 CCM 之前）⇒ **那条论证自己写明的失效条件被触发了**。另外三条的下场：subwindow 仍然没有（所以只用主窗）、软件四道防护一行不删（回退路径）、仍不新增组件目录 |
| 2 | §B.4：AWB 是「灰世界 + 四道防护」的**闭环** | 默认路径变成**开环前馈** | 统计采样点从 ISP 输出（CCM 下游）搬到 `BEFORE_CCM` ⇒ 改增益不再影响统计 ⇒ **建议值公式必须从 `cur × g/x` 换成 `Σg/Σx`**。这是拓扑改动不是参数改动，误用旧公式会「增益单调发散而所有计数器显示正常」 |
| 3 | §B.3：AE 目标 120、死区 ±12 | 官方 **62**、非对称 **[56, 64]** | 120 是拍脑袋定的，而这颗传感器室内线性均值只到 45 ⇒ AE 永远够不着 ⇒ 曝光顶格、增益推满。62 = 官方 `agc.luma_adjust.target`。⚠️ 连带 `CAM_AE_DEADBAND` 12→6、`CAM_AWB_LUM_MIN` 40→20 **必须跟着缩**（不缩就是隐蔽的行为退化） |
| 4 | §A.2：「输出是线性域」是既成事实 | **改掉了** | 主机把 MJPEG 一律按 sRGB（≈ γ 2.2）解释 ⇒ 直出线性光等于又被压暗 50 倍。gamma 单独一项就把画面从「几乎全黑」拉到大致正常，**它不是画质微调，是这条链路上缺的一个必需环节** |
| 5 | §D：自检行共 6 行（`camera` 2 组 + `uvc` 4 行） | 现在是 **四组十几行** | 新增 `CCM` / `黑位` / `AWB统计` ×2 / `AE统计` ×2 / `HIST` ×2 / `ENV` / `ADN` / `LSC` / `AEN` / `GAMMA`。§D 那几个「`camera_csi.c:NNN`」的行号**已全部失效** |
| 6 | §E 待实测表 | 仍然全部待实测，**且条目变多了** | 新增三个**判定点**：ρ ≈ 0.79（决定 `CAM_AE_SOURCE` 的整段论证）、`env.luma` 重建（决定 gamma 动态选档）、黑电平基座（决定 CCM 强度）。见 `firmware/README.md` 的「上板验证清单」 |

### F.3 §A.3 表里几处需要补正的细节

1. **LSC 的版本门**：原文写「门限是 rev ≥ **1.00**，本板满足」是对的，但没写分配顺序 ——
   `esp_isp_lsc_allocate_gain_array()` 要求 `lsc_fsm == INIT` ⇒ **必须在 `enable` 之前**；
   而 `configure()` 没有 FSM 门 ⇒ 取流中可重配。
2. **BF 的禁用方式**：`esp_isp_bf_configure(proc, NULL)` 是**空指针解引用**
   （`else` 分支之后仍无条件求值 `config->flags`），不是优雅的禁用。`sharpen` / `color` 同样。
3. **Demosaic 只能 `configure` 不能 `enable`**：它已被 `output = RGB565` 隐式打开，
   调 `enable` 会撞 FSM 门拿到 `INVALID_STATE`，让人误以为参数没配上。
4. **`esp_cam_sensor_set_format()` 会重写整张模式寄存器表** ⇒ 任何「读传感器某个寄存器
   看它的上电默认」的操作（本次是 `0x3902`）**必须排在它之后**，早读会被它盖掉。
