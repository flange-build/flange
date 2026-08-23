> [!NOTE]
> # ⓘ 返工说明（2026-08-23）：**本文关于官方管线的重建仍然有效**
>
> 本文写作时的目的是「为自研管线向官方对齐提供对照基线」，而那条路已经被返工推翻 ——
> 提交 `a98886fb` 把 Tab5 的全部自研画质控制律删除，改为**直接引入官方
> `espressif/esp_ipa` 2.3.0**，由官方闭源算法库接管 AE/AWB/CCM/gamma/降噪/锐化/LSC。
>
> **但本文的内容没有失效**：它重建的是**官方**的逻辑（`esp_video` + `esp_ipa` +
> `sc202cs_default.json` 的逐级行为），而返工正是把这套官方逻辑原样搬了进来 ——
> 本文因此从「对齐前的对照基线」变成了「**现在跑在板子上的那套算法的说明书**」。
> 读它仍然是理解 `main/cam_ipa.c` 每一段在做什么的最好途径。
>
> **需要更正的只有一处判断**（本文与当时全部文档共有）：
> 「引 `esp_ipa` 会把 `esp_video` + `usb_host_uvc` + `esp_h264` 拖进来」——
> 事实是对的（`esp_video` 确实依赖那三个），但**推论方向反了**：
> `esp_ipa` 自己只依赖 `cmake_utilities` + `idf>=5.4`，**可以单独引**。
> 这条未经回头验证的前提导致了那一整轮自研，详见
> `docs/superpowers/plans/2026-08-21-tab5-isp-align-with-official.md` 顶部的返工说明。
>
> **返工后的实际实现**：`components/packages/tab5-all-in-one/firmware/main/cam_ipa.{c,h}`
> 与 `camera_csi.c`；文档见同目录 `firmware/README.md` 的「画质：官方 `esp_ipa` 接管」一章。
> ⚠️ **返工后的固件一次都没有烧过板。**

---

# ESP32-P4 官方摄像头 ISP 管线逻辑重建

> 日期：2026-08-19
> 目的：在把 Tab5 自研摄像头管线（SC202CS → CSI → ISP → PPA → JPEG → UVC）与 Espressif 官方对齐之前，
> 先把**官方逻辑本身**逐级重建出来，作为对照基线。
> **本文只做重建，不做评价、不提改进建议、不涉及本仓库自研代码的好坏。**

## 0. 证据等级约定

全文每条结论都标注来源等级：

| 标记 | 含义 |
|------|------|
| **[确证]** | 直接从源码 / 寄存器定义 / 配置文件读出，给出文件路径+行号或 JSON 字段路径 |
| **[反推]** | 由头文件、schema、数值关系推断，附推断依据与验证方法 |
| **[缺口]** | 查不到。如实留白，不用推测填补 |

芯片前提：**ESP32-P4 rev v1.0**（`efuse_hal_chip_revision()` 返回 `100`，`< 300`）。

### 0.1 材料来源清单

| 编号 | 来源 | 路径 / URL |
|------|------|-----------|
| S1 | ESP-IDF v6.0.2 ISP 驱动 | `/Users/eki/esp/esp-idf/components/esp_driver_isp/` |
| S2 | ESP-IDF v6.0.2 ISP HAL/LL | `/Users/eki/esp/esp-idf/components/esp_hal_cam/` |
| S3 | ESP32-P4 ISP 寄存器定义（双版本） | `/Users/eki/esp/esp-idf/components/soc/esp32p4/register/hw_ver1/soc/isp_struct.h`、`.../hw_ver3/soc/isp_struct.h` |
| S4 | IDF ISP 编程指南（含官方管线框图） | `/Users/eki/esp/esp-idf/docs/en/api-reference/peripherals/isp.rst` |
| S5 | IDF 官方 ISP 示例 | `/Users/eki/esp/esp-idf/examples/peripherals/isp/multi_pipelines/` |
| S6 | SC202CS 官方标定文件 | `.../managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/sc202cs_default.json` |
| S7 | esp_cam_sensor 标定文件选择逻辑 | `.../managed_components/espressif__esp_cam_sensor/project_include.cmake` |
| S8 | 其他传感器 eco4/eco5 双份标定 | `.../sensors/{sc2336,os02n10,ov9281}/cfg/*_p4_eco{4,5}.json` |
| S9 | SC202CS 传感器驱动 | `.../sensors/sc202cs/sc202cs.c` |
| S10 | esp-video-components（commit `1f652ce5`，esp_video 2.4.0 / esp_ipa 2.3.0） | `https://github.com/espressif/esp-video-components` |
| S11 | esp_video ISP metadata device | `esp_video/src/device/esp_video_isp_device.c` |
| S12 | esp_video ↔ esp_ipa 桥接层 | `esp_video/src/esp_video_isp_pipeline.c` |
| S13 | esp_video 能力门控 | `esp_video/include/esp_video_caps.h` |

> S10~S13 由联网调研取得（raw.githubusercontent.com）。本仓库 **未 vendored** esp_video / esp_ipa，
> 只 vendored 了 `esp_cam_sensor`（commit `8fc93163`）。四对标定文件的字节大小与 master 一致，
> 已本地核对 **[确证]**。

---

## 摘要：逐级对照清单

一页纸的对照锚点。每一行的详细依据见对应小节。

| 级 | 官方位置 | 数据域 | rev v1.0 | 官方默认 | 参数来源 |
|----|----------|--------|----------|----------|----------|
| BLC | ①最前 | RAW | ❌ | rev≥3 才配 | `acc.blc` |
| DPC | ② | RAW | 寄存器有、无 API | 不配 | — |
| BF | ③ | RAW | ✅ | 配 | `adn.bf`（按 gain 7 档） |
| LSC | ④ | RAW | ✅ | 配 | `acc.lsc`（按 CT 9 档，273 格） |
| Demosaic | ⑤ | RAW→RGB | ✅ | 配 | `adn.demosaic`（按 gain 4 档） |
| Median | ⑥ | RGB | 寄存器有、无 API | 不配 | — |
| CCM | ⑦ | RGB 线性 | ✅ 但 S2.10(±4) | 配 | `acc.ccm`（按 CT 19 档） |
| Gamma | ⑧ | RGB 线性→gamma | ✅ | 配 | `aen.gamma`（按 env.luma 4 档） |
| RGB2YUV | ⑨ | RGB→YUV | ✅ | 隐式 | 处理器配置 |
| Sharpen | ⑩ | YUV(Y) | ✅ | 配 | `aen.sharpen`（按 gain 4 档） |
| Color | ⑪ | YUV | ✅ 但 hue 8bit | 配 | `aen.contrast` + `acc.saturation` |
| YUV2RGB | ⑫ | YUV→out | ✅ | 隐式 | 处理器配置 |
| CROP | ⑬最后 | out | ❌（静默 no-op） | 不配 | — |
| WBG | 位置见 §A.3 | RAW | ❌ | rev<3 折进 CCM | AWB 输出 |

| 统计块 | 采样点 | 色彩域 | 分块 | rev v1.0 |
|--------|--------|--------|------|----------|
| AE | demosaic 后（esp_video 硬编码） | 线性 RGB 亮度 | 5×5 | ✅ |
| AWB | CCM 前（esp_video 硬编码） | 线性 RGB | 主窗 + 5×5 子窗 | ✅ 主窗；❌ 子窗 |
| HIST | LSC 后 / demosaic 后 / RGB2YUV 后（三选一） | RAW / RGB / YUV | 16 bin，5×5 加权 | ✅ |
| AF | RGB2YUV 后（固定） | Y | 3 窗 | ✅（输出非 RAW 时） |

| 环路 | 输入统计 | 输出落点 | 更新频率 |
|------|----------|----------|----------|
| AGC（AE） | AE 5×5 亮度 | **传感器**：`V4L2_CID_EXPOSURE` / `V4L2_CID_GAIN`（或 `CAMERA_GROUP` 原子写） | 每帧 |
| AWB | AWB 主窗 sum_r/g/b | **ISP**：rev≥3 → WBG；**rev<3 → 乘进 CCM 第 0/2 列** | 每帧 |
| ADN / ACC / AEN | 无（开环前馈） | ISP 各块 | 每帧（按 gain / ct / luma 查表） |

---

## A. 硬件管线的级序

### A.1 官方权威框图

IDF 编程指南给出的 ISP 管线框图（`S4:38-60`）**[确证]**：

```
ISP Header → BLC → BF → LSC → Demosaic → CCM → Gamma → RGB2YUV → SHARP
           → Contrast&Hue&Saturation → YUV Limit / YUV2RGB → CROP → ISP Tail
```

统计块的抽头（同一框图，`S4:52-59`）**[确证]**：

```
LSC      → HIST
Demosaic → AWB,  Demosaic → AE,  Demosaic → HIST
CCM      → AWB
Gamma    → AE
RGB2YUV  → HIST,  RGB2YUV → AF
```

### A.2 寄存器侧的交叉验证

`ISP_CNTL` 寄存器的使能位排列顺序与框图一致，且比框图多出两级（DPC、Median）
（`S3` hw_ver1 `isp_struct.h:115-213`）**[确证]**：

| bit | 字段 | 说明 |
|-----|------|------|
| 0 | `mipi_data_en` | MIPI 输入数据使能 |
| 1 | `isp_en` | ISP 全局使能（复位默认 1） |
| 2 | `blc_en` | BLC |
| 3 | `dpc_en` | DPC（坏点校正） |
| 4 | `bf_en` | BF（Bayer 域降噪） |
| 5 | `lsc_en` | LSC |
| 6 | `demosaic_en` | 去马赛克（复位默认 1） |
| 7 | `median_en` | 中值滤波 |
| 8 | `ccm_en` | CCM |
| 9 | `gamma_en` | Gamma |
| 10 | `rgb2yuv_en` | RGB→YUV（复位默认 1） |
| 11 | `sharp_en` | 锐化 |
| 12 | `color_en` | 色彩（对比度/饱和度/色调/亮度） |
| 13 | `yuv2rgb_en` | YUV→RGB（复位默认 1） |
| 14 | `ae_en` | AE 统计 |
| 15 | `af_en` | AF 统计 |
| 16 | `awb_en` | AWB 统计 |
| 17 | `hist_en` | 直方图统计 |
| 18 | `crop_en` | **仅 hw_ver3（rev≥3.0）存在** |
| 19 | `wbg_en` | **仅 hw_ver3（rev≥3.0）存在** |
| 24 | `byte_endian_order` | bypass 时的字节序 |
| 26:25 | `isp_data_type` | 输入位宽 0:RAW8 1:RAW10 2:RAW12 |
| 28:27 | `isp_in_src` | 输入源 0:CSI HOST 1:CAM 2:DMA |
| 31:29 | `isp_out_type` | 输出格式 0:RAW8 1:YUV422 2:RGB888 3:YUV420 4:RGB565（复位默认 2） |

hw_ver1 在 bit18 处是 `reserved_18:6`，hw_ver3 才展开为 `crop_en` / `wbg_en`
（`diff hw_ver1/isp_struct.h hw_ver3/isp_struct.h`）**[确证]**。

### A.3 逐级重建表

WBG 的位置：`isp_wbg.c` 调用的全部 LL 函数命名为 `isp_ll_awb_set_wb_gain*`、
`isp_ll_awb_enable_wb_gain`，即 WBG 与 AWB 统计共用一组寄存器域
（`S1:src/isp_wbg.c:39,63,66`，`S2:esp32p4/include/hal/isp_ll.h:1738-1788`）**[确证]**；
`ISP_CNTL.wbg_en` 位于 bit19（`crop_en` 之后）**[确证]**，但位序不代表流水线位置。
WBG 在 RAW 域施加 R/G/B 通道增益，按 Bayer 域增益的通行做法应在 demosaic 之前
**[反推]**；官方框图未画出 WBG，**其精确插入点为 [缺口]**。

| # | 级 | 位置（前 / 后） | 输入域 | 输出域 | rev<3.0 可用？ | 官方默认配不配 | 源码依据 |
|---|-----|-----------------|--------|--------|----------------|----------------|----------|
| 1 | **BLC**（黑电平校正） | ISP Header 之后 / DPC 之前 | RAW Bayer | RAW Bayer | ❌ **不可用** | eco5 配，eco4 不配 | `S1:src/isp_blc.c:27-33` 显式 `ESP_ERR_NOT_SUPPORTED`；`S5:example_pipelines.c:55` `#if CONFIG_ESP32P4_REV_MIN_FULL >= 300` |
| 2 | **DPC**（坏点校正） | BLC 之后 / BF 之前 | RAW Bayer | RAW Bayer | 寄存器存在（hw_ver1 `dpc_en` bit3）**[确证]**；IDF v6.0.2 **无 `esp_isp_dpc_*` 驱动 API** **[确证]** | 不配（无 API） | `S3:hw_ver1/isp_struct.h:131-134`；`S1:include/driver/` 无 `isp_dpc.h` |
| 3 | **BF**（Bayer 域双边降噪） | DPC 之后 / LSC 之前 | RAW Bayer | RAW Bayer | ✅ 可用 | 配 | `S4:50`；`S1:src/isp_bf.c`；`S6:.adn.bf` |
| 4 | **LSC**（镜头阴影校正） | BF 之后 / Demosaic 之前 | RAW Bayer（R/Gr/Gb/B 四通道独立增益） | RAW Bayer | ✅ **可用**（门限是 rev≥**1.0**，不是 3.0） | 配（SC202CS 有 9 档色温表） | `S1:src/isp_lsc.c:55-60` `ESP_CHIP_REV_ABOVE(chip_version, 100)`；`S6:.acc.lsc` |
| 5 | **Demosaic**（去马赛克） | LSC 之后 / Median、CCM 之前 | RAW Bayer | RGB（线性） | ✅ 可用 | 配（`gradient_ratio` 按增益分档） | `S4:50`；`S1:src/isp_demosaic.c`；`S6:.adn.demosaic` |
| 6 | **Median**（中值滤波） | Demosaic 之后 / CCM 之前 | RGB | RGB | 寄存器存在（`median_en` bit7）**[确证]**；**无驱动 API** **[确证]** | 不配 | `S3:hw_ver1/isp_struct.h:147-150` |
| 7 | **CCM**（色彩校正矩阵） | Demosaic 之后 / Gamma 之前 | RGB 线性 | RGB 线性 | ✅ 可用，但**定点格式不同**：rev<3.0 = S2.10（±4.0），rev≥3.0 = S4.8（±16.0） | 配（19 档色温表） | `S2:isp_ll.h:138-145`；`S5:example_pipelines.c:263-266`；`S6:.acc.ccm` |
| 8 | **Gamma** | CCM 之后 / RGB2YUV 之前 | RGB 线性 | RGB（gamma 后） | ✅ 可用 | 配（R/G/B 各 16 点折线） | `S1:src/isp_gamma.c`；`S6:.aen.gamma` |
| 9 | **RGB2YUV** | Gamma 之后 / SHARP 之前 | RGB（gamma 后） | YUV | ✅ 可用（复位默认 en=1） | 由 `esp_isp_processor_cfg_t` 的输入/输出色彩格式隐式决定 | `S3:hw_ver1/isp_struct.h:159-162`；`S1:src/isp_core.c:141-148` |
| 10 | **SHARP**（锐化） | RGB2YUV 之后 / Color 之前，作用于 **Y 分量** | YUV（Y） | YUV（Y） | ✅ 可用 | 配（按增益 4 档） | `S4:50`；`S1:src/isp_sharpen.c`；`S6:.aen.sharpen` |
| 11 | **Color**（对比度/色调/饱和度/亮度） | SHARP 之后 / YUV2RGB 之前 | YUV | YUV | ✅ 可用，但**色调精度不同**：rev<3.0 只有 8 bit（驱动内部做 `hue*256/360` 折算），rev≥3.0 有 9 bit 可直接写 0~359 | 配（对比度按增益 4 档、饱和度按色温 2 档） | `S2:isp_hal.c:217-221`；`S2:isp_ll.h:1107-1113`；`S6:.aen.contrast`、`.acc.saturation` |
| 12 | **YUV Limit / YUV2RGB** | Color 之后 / CROP 之前 | YUV | RGB 或 YUV | ✅ 可用 | 由输出格式隐式决定；`yuv_std` / `yuv_range` 在 `esp_isp_new_processor` 里配 | `S1:src/isp_core.c:165-169` |
| 13 | **CROP**（裁剪） | YUV2RGB 之后 / ISP Tail 之前 | 输出域 | 输出域 | ❌ **不可用** | rev<3.0 不配 | `S1:src/isp_crop.c:26-32`；`S2:isp_ll.h:2634-2672` 为空实现桩 |
| — | **WBG**（白平衡增益） | 见上文说明 | RAW Bayer **[反推]** | RAW Bayer **[反推]** | ❌ **不可用** | rev<3.0 不配 | `S1:src/isp_wbg.c:27-33` |

### A.4 统计块的采样位置

统计块不改数据，只旁路取样。取样点决定了统计量所在的色彩域，这是对齐时最容易错的地方。

| 统计块 | 取样点（可选） | 统计量所在色彩域 | 输出结构 | 分块数 | 依据 |
|--------|----------------|------------------|----------|--------|------|
| **AE** | `ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC` / `ISP_AE_SAMPLE_POINT_AFTER_GAMMA` | 线性 RGB 亮度 / gamma 后亮度 | `isp_ae_result_t.luminance[5][5]` | 5×5 = 25 | `S2:include/hal/isp_types.h:110-113`；`S4:54,57` |
| **AWB** | `ISP_AWB_SAMPLE_POINT_BEFORE_CCM` / `ISP_AWB_SAMPLE_POINT_AFTER_CCM` | demosaic 后线性 RGB / CCM 后 RGB | `isp_awb_stat_result_t{white_patch_num, sum_r, sum_g, sum_b}` + 5×5 子窗 | 主窗 1 + 子窗 5×5 | `S2:isp_types.h:139-142`；`S1:include/driver/isp_awb.h:22-29`；`S4:53,56` |
| **HIST** | RAW（`RAW_R/GR/GB/B`）/ RGB / YUV（`Y/U/V`） | 分别对应 LSC 后、Demosaic 后、RGB2YUV 后 | `isp_hist_result_t.hist_value[16]` | 16 段；窗内 5×5 子块各带权重 | `S2:isp_types.h:319-328`；`S1:include/driver/isp_hist.h:30-37`；`S4:52,55,58` |
| **AF** | RGB2YUV 之后（**固定**，无采样点选项） | YUV 的 Y 分量 | `isp_af_result_t{definition[3], luminance[3]}` | 3 个窗 | `S2:isp_types.h:37-40`；`S4:59` |

要点 **[确证]**：

* **AWB 的采样点选择直接决定白平衡增益写到哪里。** `isp_awb.h:22-29` 的注释说明了官方意图：
  “若相机支持手动设置 RGB 通道增益，则采样点选 before CCM，把增益写进**相机寄存器**；
  若相机不支持手动增益或不想改相机配置，则采样点选 after CCM，把算得的增益写进 **CCM**。”
* **AE 窗口划分**：`isp_hal_ae_window_config()` 把用户给的窗按 `SOC_ISP_AE_BLOCK_X_NUMS=5` /
  `Y_NUMS=5` 均分成 25 块，并写入 `subwin_pixnum` 的倒数用于硬件求平均
  （`S2:isp_hal.c:31-43`）。
* **AWB 子窗（subwindow）在 rev<3.0 上不可用**：`isp_awb.c:81-89` —
  “Subwindow feature is only supported on REV >= 3.0”，rev<3.0 会打 warning 并跳过配置。
  即 rev<3.0 只有 AWB **主窗**的 4 个累加值（`white_patch_num`/`sum_r`/`sum_g`/`sum_b`），
  拿不到 5×5 空间分布 **[确证]**。
* 统计结果通过 **ISP 中断 + 回调**送出，回调在 ISR 上下文运行
  （`S1:src/isp_core.c:270-274` 分别检查 `AF/AWB/AE/SHARP/HIST` 事件掩码）**[确证]**。
  连续统计模式下每帧回调一次；env detector 模式下按 `interval`（单位：帧）触发
  （`S1:include/driver/isp_ae.h:131-135`）**[确证]**。

### A.5 影子寄存器（shadow register）机制 —— rev<3.0 的隐性差异

* rev≥3.0：BLC/DPC/BF/WBG/CCM/SHARPEN/COLOR 七个块各有一组影子寄存器，
  `isp_ll_shadow_set_mode(hw, ISP_SHADOW_MODE_UPDATE_ONLY_NEXT_VSYNC)`
  使参数在**下一个 VSYNC 边界原子生效**；驱动 API 的
  `flags.update_once_configured` 用来强制立即生效
  （`S2:isp_ll.h:1875-2090`；`S1:src/isp_core.c:178`）**[确证]**。
* rev<3.0：`isp_ll_shadow_update_*()` 全部是"for compatibility"的空桩，直接返回 true
  （`S2:isp_ll.h:2092-2134`）**[确证]**。
  → **参数写入即刻生效，没有帧边界原子性**。在帧中途改 CCM/gamma 会出现单帧撕裂
  **[反推，依据是空桩不写任何硬件寄存器]**。

### A.6 上电默认状态

`isp_ll_init()` 做的是 `hw->cntl.val = 0`（`S2:isp_ll.h:337-342`）**[确证]** ——
把**所有**级都关掉，包括复位默认为 1 的 demosaic / rgb2yuv / yuv2rgb。
随后 `esp_isp_new_processor()` 只设输入源、输入/输出色彩格式、Bayer order、
h/v 分辨率、YUV 标准与范围（`S1:src/isp_core.c:140-178`）**[确证]**。
所以：**除非应用逐块调用 `esp_isp_xxx_enable()`，ISP 不做任何处理。**
唯一的例外是 DVP + RGB 输出时的 workaround：`isp_ll_color_enable(hw, true) // workaround for DIG-474`
（`S1:src/isp_core.c:172`）**[确证]**。

### A.7 rev<3.0 的其他硬件差异

| 差异项 | rev<3.0 | rev≥3.0 | 依据 |
|--------|---------|---------|------|
| 中断源掩码 | `ISP_LL_EVENT_ALL_MASK = 0x1FFFFFFF`（29 位） | `0xFFFFFFFF`（32 位） | `S2:isp_ll.h:74-78` **[确证]** |
| CCM 系数定点 | S2.10，范围 ±4.0 | S4.8，范围 ±16.0 | `S2:isp_ll.h:138-145` **[确证]** |
| 色调位宽 | 8 bit（`hue*256/360`） | 9 bit（0~359 直写） | `S2:isp_hal.c:217-221` **[确证]** |
| AWB 子窗 | 不支持 | 支持 5×5 | `S1:src/isp_awb.c:81-89` **[确证]** |
| BLC / WBG / CROP | 无（寄存器位都不存在） | 有 | `S3` 两版 `isp_struct.h` 对比 **[确证]** |
| 影子寄存器 | 无 | 有 | `S2:isp_ll.h:1875 / 2092` **[确证]** |
| LSC | **有**（门限 rev≥1.0） | 有 | `S1:src/isp_lsc.c:55-60` **[确证]** |

### A.8 硬件常量（ESP32-P4）

`/Users/eki/esp/esp-idf/components/soc/esp32p4/include/soc/soc_caps.h:344-380` **[确证]**：

| 常量 | 值 |
|------|-----|
| `SOC_ISP_AE_BLOCK_X_NUMS` / `Y_NUMS` | 5 / 5 |
| `SOC_ISP_AWB_WINDOW_X_NUMS` / `Y_NUMS` | 5 / 5 |
| `SOC_ISP_AF_WINDOW_NUMS` | 3 |
| `SOC_ISP_HIST_BLOCK_X_NUMS` / `Y_NUMS` | 5 / 5 |
| `SOC_ISP_HIST_SEGMENT_NUMS` / `INTERVAL_NUMS` | 16 / 15 |
| `SOC_ISP_BF_TEMPLATE_X_NUMS` / `Y_NUMS` | 3 / 3 |
| `SOC_ISP_SHARPEN_TEMPLATE_X_NUMS` / `Y_NUMS` | 3 / 3 |
| `SOC_ISP_CCM_DIMENSION` | 3 |
| `ISP_GAMMA_CURVE_POINTS_NUM` | 16 |
| `ISP_LL_HSIZE_MAX` / `VSIZE_MAX` | 1920 / 1080 |
| `ISP_LL_LSC_GRID_WIDTH` / `HEIGHT` | 32 / 32 |

定点格式（`S2:include/hal/isp_types.h`）**[确证]**：

| 参数 | 整数位 | 小数位 | 备注 |
|------|--------|--------|------|
| Demosaic `grad_ratio` | 2 | 4 | `isp_demosaic_grad_ratio_t` |
| Sharpen `h_freq_coeff` / `m_freq_coeff` | 3 | 5 | |
| LSC gain | 2 | 8 | |
| Hist weight / coeff | 8 | 7 | 各权重小数和应为 256 |
| Color contrast / saturation | 1 | 7 | 范围 0~1（小数部 0~127） |
| CCM | 2（rev<3）/ 4（rev≥3） | 10 / 8 | |

---

## B. 标定文件字段映射（`sc202cs_default.json`）

### B.1 顶层结构与缩写

文件顶层是 `{"version": 1, "SC202CS": {...}}`，传感器名作为唯一的算法命名空间键
（`S6:.version`、`.SC202CS`）**[确证]**。

六个二级键的含义 —— 均以 **`i`/`a` + 两字母**命名，对应 esp_ipa 的一个算法模块：

| 键 | 全称（反推） | 管哪些 ISP 级 | 依据 |
|----|--------------|---------------|------|
| `ian` | **I**mage **AN**alysis（图像分析/环境量估计） | 不直接写 ISP。产出**环境亮度 `env.luma.*`** 与**色温 CT**，供其他模块查表 | `S6:.ian` 只含 `luma`（AE/env 权重）与 `color_temp`（白点轨迹+CCT 模型），无任何 ISP 块参数 **[反推]** |
| `awb` | **A**uto **W**hite **B**alance | 白平衡增益（R/B gain） | `S6:.awb.min_red_gain_step`、`.min_blue_gain_step`、`.range.rg/bg` **[确证]** |
| `agc` | **A**uto **G**ain **C**ontrol（含 AE） | 写**传感器**曝光行数与增益 | `S6:.agc.exposure.frame_delay`、`.gain.min_step`、`.anti_flicker` **[确证]** |
| `adn` | **A**uto **D**e**N**oise | ISP 的 **BF** 与 **Demosaic** | `S6:.adn.bf`、`.adn.demosaic` **[确证]** |
| `acc` | **A**uto **C**olor **C**orrection | ISP 的 **BLC / Saturation / CCM / LSC** | `S6:.acc.blc`、`.saturation`、`.ccm`、`.lsc` **[确证]** |
| `aen` | **A**uto **EN**hancement | ISP 的 **Gamma / Sharpen / Contrast** | `S6:.aen.gamma`、`.sharpen`、`.contrast` **[确证]** |

**注意**：`awb` 与 `agc` 是"往回写传感器/白平衡增益"的闭环，`adn`/`acc`/`aen` 是"按当前工作点查表配 ISP"的开环前馈。这条分工在字段结构上一目了然：后三者的表全部以 `gain`（传感器总增益）或 `color_temp` / `luma` 为索引，没有任何误差项或步长限制字段 **[反推]**。

### B.2 `ian` —— 环境量估计

```
ian.luma.ae.weight        : int[25]   —— AE 5×5 分块的权重（本文件全 1，即均值）
ian.luma.env.k            : 250000
ian.luma.env.speed_param  : float[16] —— 对称低通 FIR 系数
ian.luma.env.weight       : int[25]   —— env 亮度 5×5 分块权重（全 1）
ian.color_temp.bp         : dict[16]{a0, a1}  —— 白点轨迹 16 点
ian.color_temp.model      : 2
ian.color_temp.m_2        : {a0, a1, a2}
ian.color_temp.g          : {a0: -0.332, a1: -0.1858, a2: float[4]}
ian.color_temp.f_n0       : 0.0033
ian.color_temp.min_step   : 1
```

#### B.2.1 `ian.luma` **[确证 + 反推]**

* `ae.weight[25]` / `env.weight[25]`：对应 AE 统计的 5×5 分块（`SOC_ISP_AE_BLOCK_X/Y_NUMS=5`）。
  SC202CS 两张表都是全 1，即**未加权的算术平均** **[确证]**。
  区分两张表说明官方有两个亮度量：`ae.luma.*`（AE 用的即时亮度）与 `env.luma.*`（环境亮度）**[反推，依据见 B.5 的 `luma_env` 引用名]**。
* `env.speed_param[16]`：
  `[-0.005463, -0.010018, 0.0, 0.033241, 0.085583, 0.136704, 0.160734, 0.148777,`
  ` 0.148777, 0.160734, 0.136704, 0.085583, 0.033241, 0.0, -0.010018, -0.005463]`
  —— 完全对称、两端有负旁瓣、中心最大，是典型的**窗函数低通 FIR 核**，
  用于对 env 亮度做时域平滑（抗跳变/抗振荡）。系数和 ≈ 1.099 **[反推]**。
  **[缺口]**：这 16 个抽头是按帧滑动还是按其他索引，查不到。
* `env.k = 250000`：量纲上像是把 `luma /(曝光时间 × 增益)` 归一化成"环境照度"的比例常数
  **[反推]**，**[缺口]**：无公式来源。

#### B.2.2 `ian.color_temp.bp` —— 16 点白点轨迹（本节是重点）

`bp` 是 16 个 `{a0, a1}` 对。**数值上可以完全确定它们是什么** **[确证]**：

| | `bp[0]` | `bp[15]` | `awb.range` |
|---|---|---|---|
| `a0` | 0.879032 | 0.380952 | `rg.max = 0.879`，`rg.min = 0.3801` |
| `a1` | 0.290323 | 0.658730 | `bg.min = 0.2903`，`bg.max = 0.6587` |

即 **`a0 = R/G 比，`a1 = B/G 比**，而 `awb.range.rg` / `awb.range.bg`
恰好是这 16 点的**包围盒**（四舍五入到 4 位小数）**[确证，数值恒等]**。

16 点按 `a0` 单调递减、`a1` 单调递增排列 —— 这就是 (R/G, B/G) 色度平面上从
**低色温（偏红：高 R/G、低 B/G）到高色温（偏蓝：低 R/G、高 B/G）** 的**白点轨迹**
（plankian locus 在该相机 raw 色度空间的投影）**[确证]**。

**`model` 与 `m_*` 的关系** **[确证，数值验证]**：

`model = 2` 时用 `m_2 = {a0, a1, a2}`，它是对 `bp` 轨迹做的**二次最小二乘拟合**：

```
B/G = m_2.a0 · (R/G)² + m_2.a1 · (R/G) + m_2.a2
    = -0.229169·(R/G)² - 0.446364·(R/G) + 0.859552
```

对全部 16 个 `bp` 点回代，残差全部 ≤ 0.0072（多数 < 0.003）—— 拟合关系成立。
旁证：`os02n10_default_p4_eco4.json` 里同时存在 `ian.color_temp.m_1.{a0,a1}`（两系数=一次拟合）
与 `m_2.{a0,a1,a2}`，`model` 选用哪一套 **[确证]**。

**`g` —— 色度到 CCT 的转换** **[反推，数值验证]**：

`g.a0 = -0.332`、`g.a1 = -0.1858`，正好是 **McCamy CCT 公式的 epicentre 坐标
(xe, ye) = (0.3320, 0.1858)** 取负号 **[反推]**。
`g.a2` 是 4 个系数的**三次多项式** `[-237.746, 2177.004, -5984.610, 8062.352]`
（结构上对应 McCamy 的 `449n³ + 3525n² + 6823.3n + 5520.33`，系数是针对本机重新拟合过的）。

按 McCamy 的形式代入验证：

```
n   = (R/G + g.a0) / (B/G + g.a1)          # 即 (rg - 0.332)/(bg - 0.1858)
CCT = ((g.a2[0]·n + g.a2[1])·n + g.a2[2])·n + g.a2[3]
```

对 16 个 `bp` 点求值，得到 **单调递增**的 CCT 序列：

| bp | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|----|---|---|---|---|---|---|---|---|
| CCT(K) | 2289 | 3025 | 3010 | 3644 | 4215 | 4701 | 5157 | 5531 |

| bp | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|----|---|---|---|---|---|---|---|---|
| CCT(K) | 5892 | 6204 | 6473 | 6644 | 6854 | 6989 | 7121 | 7466 |

范围 **2289 K ~ 7466 K**，恰好与 `acc.lsc` 的 9 档色温 **2410 ~ 8200 K**
以及 `acc.ccm` 19 档的中段吻合。**这条链路成立** **[反推，数值一致性强]**。
（`bp[1]`/`bp[2]` 之间有 15 K 的轻微非单调，属拟合噪声。）

**所以 `ian.color_temp` 的输入/输出是：**

* **输入**：AWB 统计给出的当前白点 (R/G, B/G)
* **输出**：一个 **CCT 值（开尔文）**
* **`bp` 的作用**：给出合法白点轨迹（同时定义 `awb.range` 的搜索包围盒），
  把落在轨迹外的观测点**投影/约束**回轨迹上再算 CCT **[反推]**
* `min_step = 1`：CCT 变化小于 1 K 不更新 **[反推]**
* `f_n0 = 0.0033`：与 `awb.min_red_gain_step` / `min_blue_gain_step` 同值，
  是增益/比值的最小量化步（1/303 ≈ 1/300）**[反推]**

**[缺口]**：`bp` 究竟是"最近点投影"还是"沿某方向拉回"，从 JSON 看不出来；
`model = 0` / `model = 1` 分别对应什么拟合阶次，只能从 `m_1`(2 系数)/`m_2`(3 系数) 反推。

### B.3 `awb` —— 白平衡

```
awb.model                  : 1
awb.min_red_gain_step      : 0.0033
awb.min_blue_gain_step     : 0.0033
awb.min_counted            : 1200
awb.range.green.{max,min}  : 210 / 98
awb.range.rg.{max,min}     : 0.879 / 0.3801
awb.range.bg.{max,min}     : 0.6587 / 0.2903
awb.green_luma_env         : "dummy_awb_luma"
awb.green_luma_init        : 200
awb.green_luma_step_ratio  : 0.3
```

**[确证]** 与 ISP 驱动 `esp_isp_awb_config_t`（`S1:include/driver/isp_awb.h:42-57`）的一一对应：

| JSON 字段 | 驱动字段 | 含义 |
|-----------|----------|------|
| `range.green.{min,max}` | `white_patch.luminance.{min,max}` | 白块亮度筛选范围。驱动注释说范围是 `[0, 255*3]`（R+G+B 之和）；但此处 98/210 更像**单通道 G** 的范围 —— 字段名是 `green` 而非 `luminance` **[反推]** |
| `range.rg.{min,max}` | `white_patch.red_green_ratio.{min,max}` | R/G 比筛选范围，硬件范围 [0, 4.0) |
| `range.bg.{min,max}` | `white_patch.blue_green_ratio.{min,max}` | B/G 比筛选范围 |
| `min_counted = 1200` | —（算法侧） | `isp_awb_stat_result_t.white_patch_num` 低于此值则判定统计不可信，保持当前增益。可与 `S5:example_awb.c:131-134` 的 `white_patch_num == 0` 判据对照 **[反推]** |
| `min_red_gain_step` / `min_blue_gain_step = 0.0033` | —（算法侧） | 增益最小更新步长，防抖 |

* `green_luma_env = "dummy_awb_luma"`：**命名环境变量的引用**。
  与 `acc.ccm.low_luma.luma_env = "ae.luma.avg"`、`aen.gamma.luma_env = "env.luma.avg"`
  同一机制 —— esp_ipa 内部有一个**具名量的注册表/发布订阅**，JSON 用字符串挂接。
  `"dummy_awb_luma"` 字面上是占位/停用 **[反推]**。
  旁证：sc2336 从 eco4 到 eco5，`acc.ccm.low_luma.luma_env` 由 `"ae.luma.avg"` 改成 `"env.luma.avg"`，
  说明这是可切换的具名量 **[确证]**。
* `green_luma_init = 200` / `green_luma_step_ratio = 0.3`：G 通道亮度参考值的初值与
  一阶低通更新系数（新值权重 0.3）**[反推]**。
* `awb.model = 1`：**[缺口]**，取值语义查不到。
  （sc2336 eco5 的 `awb` 多出 `new_w`/`prev_w`/`red_gain_scale`/`blue_gain_scale`/
  `export_ct`/`outlier_rg`/`outlier_bg`/`type_counter_max`/`zones`/`ref_points`，
  是更新一代的分区/参考点 AWB；SC202CS 用的是老一代 **[确证]**。）

### B.4 `agc` —— 自动曝光 / 增益

```
agc.exposure.frame_delay        : 3       agc.exposure.adjust_delay : 0
agc.gain.min_step               : 0.03    agc.gain.frame_delay      : 3
agc.anti_flicker.mode           : "part"  agc.anti_flicker.ac_freq  : 50
agc.f_n0                        : 0.32    agc.f_m0                  : 0.42
agc.mode                        : "high_light_priority"
agc.luma_adjust.{target_low, target, target_high}   : 56 / 62 / 64
agc.luma_adjust.{low_threshold, low_regions}        : 14 / 5
agc.luma_adjust.{high_threshold, high_regions}      : 239 / 3
agc.luma_adjust.weight[25]
agc.high_light_priority         : {low_threshold:119, high_threshold:202, weight_offset:5,  luma_offset:-3}
agc.low_light_priority          : {low_threshold:48,  high_threshold:56,  weight_offset:5,  luma_offset:1}
agc.light_threshold_priority[5] : [{luma_threshold, weight_offset}, ...]
```

#### B.4.1 目标亮度与死区 **[反推]**

`target_low = 56 < target = 62 < target_high = 64`：
典型的**带死区的目标值**——加权平均亮度落在 [56, 64] 内不动作，
超出则朝 `target = 62` 收敛。这是标准的 AE 防振荡结构 **[反推]**。

#### B.4.2 `weight[25]` —— AE 分块权重

```
1 1 2 1 1
1 2 3 2 1
1 3 4 3 1
1 2 3 2 1
1 1 2 1 1
```

5×5 中心加权（金字塔形，中心权 4、四角权 1），对应 AE 统计的 5×5 分块
（`SOC_ISP_AE_BLOCK_X/Y_NUMS = 5`）**[确证]**。
注意这与 `ian.luma.ae.weight`（全 1）**是两张不同的表**：
`ian` 用均值算"场景亮度"，`agc` 用中心加权算"AE 控制量" **[反推]**。

#### B.4.3 `low_threshold` / `low_regions` 与 `high_threshold` / `high_regions` **[反推]**

* `low_threshold = 14`，`low_regions = 5`：25 个分块中，亮度低于 14 的块数 ≥ 5 时触发"欠曝保护"分支
* `high_threshold = 239`，`high_regions = 3`：亮度高于 239 的块数 ≥ 3 时触发"过曝保护"分支

`regions` 的量纲是"块数"（0~25），`threshold` 的量纲是 8-bit 亮度（0~255）**[反推]**。
旁证：ov9281 从 eco4 到 eco5，这四个值同步调整
（`low_threshold 16→6`、`low_regions 8→9`、`high_threshold 216→212`、`high_regions 4→5`），
呈现"阈值放宽 / 块数要求提高"的成对调整，符合"计数触发"的语义 **[确证]**。

**[缺口]**：触发后具体做什么（是改目标亮度、还是改权重、还是切模式），JSON 里看不出来。

#### B.4.4 三种优先级模式 **[反推]**

`agc.mode = "high_light_priority"`，可选值至少还有 `"low_light_priority"`
（两者的参数块都在文件里）**[确证]**。

| | `low_threshold` | `high_threshold` | `weight_offset` | `luma_offset` |
|---|---|---|---|---|
| `high_light_priority` | 119 | 202 | 5 | **−3** |
| `low_light_priority` | 48 | 56 | 5 | **+1** |

* `high_light_priority`（高光优先）：`luma_offset = −3` → 把目标亮度**压低** 3，保高光不过曝
* `low_light_priority`（暗部优先）：`luma_offset = +1` → 目标亮度**抬高** 1，保暗部细节
* `weight_offset = 5`：对落在 [low_threshold, high_threshold] 区间内的块，权重**加 5**
  —— 即"把注意力集中到这个亮度区间的块上" **[反推]**

`light_threshold_priority[5]` 是一张 **(亮度阈值 → 权重加成) 的阶梯表** **[确证结构]**：

| `luma_threshold` | 20 | 55 | 95 | 155 | 235 |
|---|---|---|---|---|---|
| `weight_offset` | 1 | 2 | 3 | 4 | 5 |

即块亮度越高，权重加成越大（本表在 `high_light_priority` 语义下）**[反推]**。
sc2336 eco5 版本给每个条目加了 `env_luma_threshold` 并新增
`light_threshold_priority_use_env_luma` 开关，说明该表可以按 env 亮度而非块亮度索引 **[确证]**。

#### B.4.5 时序与防抖 **[确证字段，反推语义]**

| 字段 | 值 | 含义 |
|------|----|----|
| `exposure.frame_delay` | 3 | 写入传感器曝光寄存器后，**3 帧**才在图像上生效 —— AE 环路必须为此留死区，否则会过冲 |
| `exposure.adjust_delay` | 0 | 曝光调整的额外延迟帧数 |
| `gain.frame_delay` | 3 | 同上，增益 3 帧生效 |
| `gain.min_step` | 0.03 | 增益最小更新步长（线性倍数），< 0.03 不动作 |
| `anti_flicker.mode` | `"part"` | 抗工频闪烁模式；`"part"` = 部分/分段（另有全开/关档位）**[缺口：取值枚举查不到]** |
| `anti_flicker.ac_freq` | 50 | 市电频率 50 Hz → 曝光时间量化到 10 ms 的整数倍 **[反推]** |
| `f_n0` | 0.32 | **[缺口]** |
| `f_m0` | 0.42 | **[缺口]** |

**曝光/增益的执行侧 [确证]**（`S9:sc202cs.c`）：

* 曝光单位是**行**，通过 `sc202cs_set_exp_val()` 写 `{0x3e00, 0x3e01, 0x3e02}`；
  上限 = `vts - 6`（`s_sc202cs_exp_vts_offset`），`vts = 1250`，`tline = 26666 ns`
  → 最长曝光 ≈ (1250−6)×26.666 µs ≈ 33.2 ms（`S9:sc202cs.c:877-892, 1192, 1139`）
* 增益是**索引**（0~196），通过 `sc202cs_set_total_gain_val()` 写 `{0x3e06, 0x3e07, 0x3e09}`；
  `sc202cs_abs_gain_val_map[]` 给出每档的绝对倍数 ×1000，
  从 `1000`（1.000×）到 `63008`（**63.008×**），共 197 档（`S9:sc202cs.c:475-676, 1163-1178`）

> 这一点直接解释了 `adn`/`aen`/`acc` 里 `gain` 索引的量纲：**线性总增益倍数**。
> SC202CS 的表用到 1 / 4 / 8 / 12 / 16 / 24 / 32 / 64 / 65 —— 最后两个超出 63.008×，是"到顶"哨兵 **[反推]**。

### B.5 `adn` —— 自动降噪（BF + Demosaic）

```
adn.bf       : [{gain, param:{level, matrix[9]}} × 7]
adn.demosaic : [{gain, gradient_ratio} × 4]
```

**按传感器总增益分档的查表前馈** **[确证]**：

| `gain` | 1 | 4 | 8 | 16 | 24 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| `bf.param.level` | 2 | 4 | 5 | 8 | 9 | 10 | 10 |
| `bf.param.matrix` | `2,4,2,4,5,4,2,4,2` | `1,3,1,3,4,3,1,3,1` | `1,3,1,3,4,3,1,3,1` | `2,3,2,3,5,3,2,3,2` | `1,2,1,2,3,2,1,2,1` | `1,2,1,2,2,2,1,2,1` | `1,2,1,2,3,2,1,2,1` |

* `level` → `esp_isp_bf_config_t::denoising_level`，驱动注释：范围 **2~20**，越大降噪越强、细节越差
  （`S1:include/driver/isp_bf.h:24`）**[确证]**。增益越高（越暗）→ level 越大，符合直觉。
* `matrix[9]` → `esp_isp_bf_config_t::bf_template[3][3]`（`ISP_BF_TEMPLATE_X/Y_NUMS = 3`）**[确证]**。
  文档说可填高斯或均值模板（`S4:514`）。表中随增益升高，模板由 `[2,4,2;4,5,4;2,4,2]`
  逐步变平（中心权重相对下降），即**从锐利高斯趋向均值滤波** **[反推]**。

| `gain` | 1 | 4 | 8 | 12 |
|---|---|---|---|---|
| `demosaic.gradient_ratio` | 1.5 | 1.25 | 1.05 | 1.0 |

→ `esp_isp_demosaic_config_t::grad_ratio`（定点 2 整数位 + 4 小数位）**[确证]**。
驱动注释的判据：`gradient_x * grad_ratio < gradient_y` 用 X 方向插值，反之用 Y，否则取平均
（`S1:include/driver/isp_demosaic.h:20-24`）**[确证]**。
比值趋近 1.0 意味着高增益（噪声大）时**放弃方向判定、直接取双向平均** **[反推]**。

### B.6 `acc` —— 自动色彩校正（BLC / Saturation / CCM / LSC）

#### B.6.1 `acc.blc`

```json
{"model": 0, "stretch": false,
 "blc_table": [{"gain": 1,
   "blc_param": {"blc_top_left": 16, "blc_top_right": 16,
                 "blc_bottom_left": 16, "blc_bottom_right": 16}}]}
```

四个角名对应 Bayer 2×2 的四个通道，与 `esp_isp_blc_config_t` 的
`top_left_chan / top_right_chan / bottom_left_chan / bottom_right_chan` 一一对应
（`S1:include/driver/isp_blc.h:24-40`）**[确证]**。
值 16 是黑电平偏移量（8-bit 域）**[反推]**；`stretch: false` → 四个通道的
`esp_isp_blc_stretch_t` 都为 false，不做 0~255 拉伸 **[确证]**。
`blc_table` 也是按 `gain` 索引的（此处只有 1 档）；ov9281 eco5 有 2 档 **[确证]**。
`model: 0`：**[缺口]**。

> ⚠️ **关键**：SC202CS 的这份 `acc.blc` 在 rev<3.0 的芯片上**无法应用**（见 §D）。

#### B.6.2 `acc.saturation`

```json
[{"color_temp": 0, "value": 128}, {"color_temp": 4500, "value": 130}]
```

**按色温索引**的查表 **[确证]**。`value` 对应 `isp_color_saturation_t`
（1 整数位 + 7 小数位）→ **128 = 1.0×**，130 ≈ 1.0156×
（`S2:include/hal/isp_types.h:395-402`）**[确证]**。
即：色温 < 4500 K 用 1.000×，≥ 4500 K 用 1.0156×。

#### B.6.3 `acc.ccm` —— 19 档色温 CCM

```
acc.ccm.low_luma : {luma_env: "ae.luma.avg", threshold: 28, matrix: [单位阵]}
acc.ccm.table    : [{color_temp, matrix[9]} × 19]
```

19 档色温（`S6:.acc.ccm.table[*].color_temp`）**[确证]**：

```
1200, 2292, 2517, 2780, 3055, 3473, 3800, 4193, 4583, 5040,
5090, 5210, 5476, 5770, 6000, 6554, 7020, 7265, 12000
```

* 两端的 **1200 K 与 12000 K 都是单位阵** `[1,0,0, 0,1,0, 0,0,1]` **[确证]** ——
  即轨迹外的**钳位守卫**：色温落到标定范围之外就不做色彩校正 **[反推]**。
* 中间 17 档是实测标定矩阵，例如 5040 K：
  `[2.0601, -0.7831, -0.2770, -0.4029, 1.6290, -0.2261, -0.3123, -0.5083, 1.8205]`，
  行和均 ≈ 1.0（保持白点中性）**[确证，数值可验]**。
* `matrix[9]` 按**行主序**填 `esp_isp_ccm_config_t::matrix[3][3]`
  （R 行 = RR,RG,RB；G 行；B 行；见 `S5:example_pipelines.c:258-261`）**[确证]**。

**选档/插值** **[反推]**：
19 档不等距（5040 与 5090 只差 50 K，5090 与 5210 差 120 K，7265 到 12000 跳 4735 K），
这种**非均匀密集采样**的常规用法是**在相邻两档之间按色温线性插值**，
而不是最近邻选档 —— 否则 5040/5090 两档没有意义。
**[缺口]**：插值是线性还是别的、是否对矩阵元素逐个插值，从 JSON 无法确定；
esp_ipa 的实现是闭源的（见 §C）。

`low_luma` 分支 **[确证结构，反推语义]**：
当具名量 `"ae.luma.avg"`（AE 平均亮度）低于 `threshold = 28` 时，
改用 `low_luma.matrix`（**单位阵**）—— 即**暗场下关闭 CCM**，
避免在低信噪比下被矩阵放大噪声 **[反推]**。
sc2336 eco5 把这里的引用从 `"ae.luma.avg"` 改成 `"env.luma.avg"` **[确证]**。

#### B.6.4 `acc.lsc` —— 9 档色温镜头阴影表

```
acc.lsc.model         : 0
acc.lsc.img_w         : 1280
acc.lsc.img_h         : 720
acc.lsc.lsc_tbl_size  : 273
acc.lsc.table         : [{ct, calibrations_r_tbl[273], calibrations_gr_tbl[273],
                          calibrations_gb_tbl[273], calibrations_b_tbl[273]} × 9]
```

9 档色温：`2410, 4015, 4637, 5210, 5925, 6254, 6746, 7378, 8200` **[确证]**。

**`lsc_tbl_size = 273` 可以精确推导出来** **[确证]**：
驱动的网格计算是（`S1:src/isp_lsc.c:26`）

```c
#define ISP_LSC_GET_GRIDS(res)  (((res) - 1) / 2 / ISP_LL_LSC_GRID_HEIGHT + 2)
```

`ISP_LL_LSC_GRID_WIDTH = HEIGHT = 32`（`S2:isp_ll.h:132-133`）**[确证]**：

* X：`(1280-1)/2/32 + 2 = 639/32 + 2 = 19 + 2 = 21`
* Y：`(720-1)/2/32 + 2 = 359/32 + 2 = 11 + 2 = 13`
* **21 × 13 = 273** ✅ 与 `lsc_tbl_size` 完全一致

所以 `img_w`/`img_h` 是**标定时的分辨率**，表尺寸与之绑定；换分辨率必须重算表。
四条表分别对应 `esp_isp_lsc_gain_array_t` 的 `gain_r / gain_gr / gain_gb / gain_b`
（`S1:include/driver/isp_lsc.h:23-28`）**[确证]**。
表值是浮点增益（首元素 ~1.2~1.37，即四角/边缘的提亮倍数），
写入硬件时转成 `isp_lsc_gain_t`（2 整数位 + 8 小数位）**[确证]**。
`model: 0`：**[缺口]**。

### B.7 `aen` —— 自动增强（Gamma / Sharpen / Contrast）

#### B.7.1 `aen.gamma` —— 4 档亮度 × 16 点曲线

```
aen.gamma.use_gamma_param : true
aen.gamma.luma_env        : "env.luma.avg"
aen.gamma.luma_min_step   : 3.0
aen.gamma.table           : [{luma, gamma_param, y[16]} × 4]
```

| 档 | `luma` | `gamma_param` | `y[16]` |
|----|--------|---------------|---------|
| 0 | 15.1 | 0.5 | `0,19,35,65,107,138,160,178,192,204,213,221,228,240,248,255` |
| 1 | 30.1 | 0.56 | 同上 |
| 2 | 90.1 | 0.605 | `0,18,36,55,97,128,142,168,189,200,210,220,228,240,248,255` |
| 3 | 300.1 | 0.655 | 同上 |

**按亮度选曲线的机制** **[确证结构 + 反推语义]**：

* 索引量是 `luma_env` 指向的具名量 **`env.luma.avg`**（环境平均亮度，来自 `ian.luma.env`），
  **不是** AE 的即时亮度 —— 这样 gamma 才不会跟着 AE 抖 **[反推]**。
* `luma` 字段是各档的**亮度断点**（15.1 / 30.1 / 90.1 / 300.1）。
  注意 300.1 远超 8-bit 的 255，说明 `env.luma` **不是 0~255 的像素亮度**，
  而是带 `ian.luma.env.k = 250000` 归一化的**环境照度量** **[反推]**。
  旁证：os02n10 从 eco4 到 eco5，第 3 档 `luma` 由 100.1 改成 360.1；
  ov9281 用到 490 / 400 **[确证]** —— 量纲确实不是像素值。
* `luma_min_step = 3.0`：亮度变化小于 3.0 不切换曲线（**迟滞/防抖**）**[反推]**。
* `use_gamma_param = true`：用 `gamma_param`（幂指数 γ = 0.5 / 0.56 / 0.605 / 0.655）
  **解析生成**曲线，而不是直接用 `y[16]` 采样点；
  若为 false 则用 `y[16]`。**[反推]** —— 依据是这个布尔字段的名字与两者并存的冗余结构；
  且 `y[16]` 正好是 `ISP_GAMMA_CURVE_POINTS_NUM = 16` 个 y 值，
  对应 `isp_gamma_curve_points_t.pt[16].y`（`S2:isp_types.h:274-283`）**[确证]**。
* 生成曲线的方式与官方示例一致：`esp_isp_gamma_fill_curve_points()` 接受一个
  `uint32_t f(uint32_t)` 函数指针，示例用的正是 `pow(x/256, 0.7) * 256`
  （`S5:example_pipelines.c:18-21, 318`）**[确证]**。
* 曲线的 x 坐标受硬件约束：`pt[0].x = 2^a[0]`，`pt[n].x - pt[n-1].x = 2^a[n]`，
  `a[n] ∈ [0,7]`，末点 `pt[15].x = 255`（`S2:isp_types.h:270-277`）**[确证]**。
  这也是 JSON 里**只存 y、不存 x** 的原因 **[反推]**。
* R/G/B 三通道用**同一条**曲线（JSON 只有一组 `y`；官方示例也是三通道同曲线，
  `S5:example_pipelines.c:324-340`）**[确证]**。

γ 值 0.5 → 0.655 随亮度**升高**：暗环境用更强的提亮（γ 更小），亮环境接近线性 **[反推]**。

#### B.7.2 `aen.sharpen` —— 按增益 4 档

| `gain` | 1 | 8 | 12 | 65 |
|---|---|---|---|---|
| `h_thresh` | 16 | 20 | 16 | 20 |
| `l_thresh` | 5 | 5 | 5 | 5 |
| `h_coeff` | 1.625 | 1.625 | 1.625 | 1.625 |
| `m_coeff` | **1.525** | **1.425** | **1.325** | **1.225** |
| `matrix` | `1,2,1,2,1,2,1,2,1` | `2,2,2,2,1,2,2,2,2` | 全 1 | 全 1 |

字段与 `esp_isp_sharpen_config_t` 一一对应（`S1:include/driver/isp_sharpen.h:20-29`）**[确证]**：

* `h_thresh` / `l_thresh` → 高/低阈值：像素值 > `h_thresh` 乘 `h_freq_coeff`；
  介于两者之间乘 `m_freq_coeff`；低于 `l_thresh` 置 0
* `h_coeff` / `m_coeff` → `isp_sharpen_h_freq_coeff_t` / `isp_sharpen_m_freq_coeff`
  （3 整数位 + 5 小数位）
* `matrix[9]` → `sharpen_template[3][3]`（`ISP_SHARPEN_TEMPLATE_X/Y_NUMS = 3`）

`m_coeff` 随增益单调下降 1.525 → 1.225：**高增益（暗光噪声大）时减弱中频锐化**，
避免放大噪声 **[反推]**。锐化作用在 **Y 分量**（位于 RGB2YUV 之后）**[确证，见 §A]**。

#### B.7.3 `aen.contrast` —— 按增益 4 档

| `gain` | 1 | 16 | 24 | 65 |
|---|---|---|---|---|
| `value` | 132 | 130 | 128 | 126 |

→ `isp_color_contrast_t`（1 整数位 + 7 小数位），**128 = 1.0×** **[确证]**。
即：低增益 132 ≈ 1.031×（提对比度），高增益 126 ≈ 0.984×（降对比度）**[确证，数值]**。

### B.8 字段映射完成度小结

| 段 | 已搞清 | 未搞清 |
|----|--------|--------|
| `ian.luma` | 权重表尺寸与含义、两套亮度量的区分 | `k = 250000` 的公式、`speed_param` 的滑动索引 |
| `ian.color_temp` | `bp` 是 (R/G, B/G) 白点轨迹；`m_2` 是它的二次拟合（数值验证）；`g` 是 McCamy 式 CCT 三次多项式（数值验证，2289~7466 K）；`awb.range` 是 `bp` 的包围盒（数值恒等） | `model` 取值枚举；轨迹投影方式；`f_n0` 的确切用途 |
| `awb` | 与 `esp_isp_awb_config_t` 的字段对应、`min_counted` 的门限语义 | `model = 1` 的语义；`green_luma_*` 的更新式 |
| `agc` | 目标亮度死区、5×5 中心权重、三种优先级模式的方向、`frame_delay` 的物理含义、曝光/增益执行侧的寄存器与量纲 | `f_n0` / `f_m0`；`anti_flicker.mode` 枚举；`low/high_regions` 触发后的具体动作 |
| `adn` | 完全搞清：按增益查表 → BF `denoising_level`+`bf_template`、Demosaic `grad_ratio` | 表间是否插值 |
| `acc.blc` | 四角对应 Bayer 四通道、`stretch` 对应驱动字段 | `model = 0` 语义 |
| `acc.saturation` | 按色温 2 档，128 = 1.0× | — |
| `acc.ccm` | 19 档色温、两端单位阵钳位、行主序、`low_luma` 暗场旁路 | **选档/插值算法（闭源）** |
| `acc.lsc` | 9 档色温、273 = 21×13 网格（精确推导）、四通道对应 | `model = 0` 语义；色温间是否插值 |
| `aen.gamma` | 4 档 `env.luma` 断点、迟滞、γ 参数、16 点 y 与硬件 x 约束、三通道同曲线 | `use_gamma_param` 的确切分支行为（反推）；`env.luma` 的绝对量纲 |
| `aen.sharpen` | 完全搞清：与 `esp_isp_sharpen_config_t` 一一对应 | 表间是否插值 |
| `aen.contrast` | 完全搞清：128 = 1.0× | — |

---

## C. 算法闭环的结构

### C.0 官方软件栈的分层与开闭源边界

官方的完整闭环**不在 ESP-IDF 里**，而在 `esp-video-components` 仓库
（`https://github.com/espressif/esp-video-components`）**[确证]**。分三层：

```
  传感器 (esp_cam_sensor)  ──V4L2──┐
                                    │
  ISP 硬件 (esp_driver_isp)         │
        │ 统计中断(ISR)             │
        ▼                           │
  esp_video / ISP metadata device   │   /dev/video20，V4L2_META_FMT_ESP_ISP_STATS ('ESTA')
        │ VIDIOC_DQBUF (每帧 1 次)  │
        ▼                           │
  esp_video_isp_pipeline.c  ────────┘   桥接层（开源）
        │ esp_ipa_pipeline_process()
        ▼
  esp_ipa  ── libesp_ipa.a （**闭源预编译静态库**）
```

**开闭源边界** **[确证]**：

| 部分 | 状态 |
|------|------|
| `esp_video/src/device/esp_video_isp_device.c`（2538 行） | 开源 |
| `esp_video/src/esp_video_isp_pipeline.c`（1975 行，桥接层） | 开源 |
| `esp_video/include/esp_video_caps.h`（rev 门控总闸） | 开源 |
| `esp_ipa/include/*.h`（`esp_ipa_types.h`、`esp_ipa_cmd.h` 等） | 开源 |
| `esp_ipa/tools/config/*.py`（JSON→C 代码生成器） | 开源 |
| `esp_ipa/src/version.c`、`esp_ipa_detect.c` | 开源 |
| **`esp_ipa/lib/esp32p4/*/libesp_ipa.a`（约 210~218 KB）** | **闭源预编译** |

> **AE 收敛、AWB 估计、色温计算、CCM 插值、AF 爬山 —— 全部在 `libesp_ipa.a` 内部，
> 无法反汇编级重建。本节到此为止的部分会明确标注。**

参考版本：`esp-video-components` commit `1f652ce5`（2026-08-18），
`esp_video` 2.4.0，`esp_ipa` 2.3.0。
本仓库 vendored 的 `esp_cam_sensor` 是 commit `8fc93163`
（`.../espressif__esp_cam_sensor/idf_component.yml`）**[确证]**，
但四对标定文件的**字节大小与内容与 master 完全一致**
（sc2336 eco4 10147 B / eco5 308419 B、os02n10 60300/296064、ov9281 9274/9553、
sc202cs 234332，本地 `ls -l` 核对）**[确证]**。

### C.1 IPA 流水线的组成与调度

`esp_ipa_config_t` 持有一个**有序的 `names[]` 数组** + 每个算法一份配置指针
（`ian, agc, awb, acc, adn, aen, af, atc, ext`）**[确证]**。
每帧按 `names[]` 顺序依次调用各 IPA 的 `process()`，
**它们全部写入同一个 `esp_ipa_metadata_t`，并 OR 各自的 flag 位** ——
**排在后面的 IPA 可以覆盖前面的结果** **[确证]**。

内置算法名 **[确证]**：

| 名 | 职责 |
|----|------|
| `esp_ipa_ian` | image analyze（图像分析，产出亮度/色温等中间量） |
| `esp_ipa_agc` | AE / 增益 |
| `esp_ipa_awb` | 自动白平衡 |
| `esp_ipa_acc` | 色彩：CCM / 饱和度 / LSC / BLC |
| `esp_ipa_adn` | 降噪：BF / demosaic |
| `esp_ipa_aen` | 增强：gamma / sharpen / contrast |
| `esp_ipa_af` | 自动对焦 |
| `esp_ipa_atc` | 传感器自带 AE 的目标电平控制 |
| `esp_ipa_ext` | 静态常量注入 |
| `customized_ipa_*` | 用户自定义 |

> **这正好解释了 `sc202cs_default.json` 的六个二级键 `ian / awb / agc / adn / acc / aen`
> —— 它们就是这六个 IPA 模块的名字，JSON 里的键顺序即流水线执行顺序。** **[确证]**
> SC202CS 的键序是 `ian → awb → agc → adn → acc → aen`
> （Python `json` 保序读取，`S6`）**[确证]**。

**流水线顺序的意义** **[确证 + 反推]**：
`ian` 排第一，先算出 `env.luma.avg` / `ae.luma.avg` / `ct` 这些中间量；
`awb` 第二，产出白平衡增益并 `export_ct`；
`agc` 第三；随后 `adn` / `acc` / `aen` 才能用前面算好的 `gain` / `ct` / `luma` 去查表。
**这是一条硬性的次序依赖** **[反推，依据是 JSON 的 `luma_env` 字符串引用只能读到已发布的量]**。

**配置的生成方式** **[确证]**：
`esp_ipa/tools/config/esp_ipa_config.py` 在**构建期**读取 IDF build property
`ESP_IPA_JSON_CONFIG_FILE_PATH` 列出的所有 JSON，生成 `esp_video_ipa_config.c`，
其中定义 `esp_ipa_pipeline_get_config(const char *name)`，
按**传感器名**（JSON 顶层键，如 `"SC202CS"`）索引。
→ **标定文件是编译进固件的静态 C 数组，不是运行期加载的。**

### C.2 具名中间量的注册表

JSON 里的字符串引用（`"ae.luma.avg"`、`"env.luma.avg"`、`"dummy_awb_luma"`）
对应 IPA 之间的**内部 key-value map** **[确证]**：

* 色温以字符串键 **`"ct"`** 在 IPA 之间传递（`awb` 侧的 `export_ct` 发布，
  `acc` 侧消费，用于 CCM / 饱和度 / LSC 选档）**[确证]**
* 亮度以 **`"ae.luma.avg"`** / **`"env.luma.avg"`** 传递 **[确证]**
* **这些量在 V4L2 层完全不可见** —— `esp_ipa_metadata_t` **没有色温字段** **[确证]**

> 这印证了 §B.5 / §B.6.3 / §B.7.1 中对 `luma_env` 的反推。
> **[缺口]**：可发布的具名量全集在闭源库里，无法枚举。

### C.3 统计量的产生：ISR 聚合 → 每帧一个 metadata buffer

**机制是"ISR 回调聚合进 V4L2 metadata buffer，由 `VIDIOC_DQBUF` 取走"，
既不是 event，也不是轮询** **[确证]**。

* AWB / AE / HIST / AF 四个 controller 各注册 `on_statistics_done`
  / `on_env_statistics_done`，然后 `..._start_continuous_statistics()`
* Sharpen 不是 controller，而是**处理器级事件**
  `esp_isp_evt_cbs_t{.on_sharpen_frame_done = ...}`，
  必须**在启动流水线之前**注册（源码原注释：*"This should be done before start ISP pipeline"*）
* 五个回调全部汇入同一个聚合函数 `isp_stats_done()`（`esp_video_isp_device.c:456`）

聚合逻辑 **[确证]**：

```c
uint32_t target_flags = ISP_STATS_FLAGS;         /* = AE | HIST */
...
if (isp_video->sharpen_started) target_flags |= ISP_STATS_SHARPEN_FLAG;
if (isp_video->af_started)      target_flags |= ISP_STATS_AF_FLAG;
if (isp_video->awb_started)     target_flags |= ISP_STATS_AWB_FLAG;
if ((isp_video->stats_buffer->flags & target_flags) == target_flags) {
    isp_video->stats_buffer->seq = isp_video->seq++;
    META_VIDEO_DONE_BUF(...);          /* 本帧统计凑齐，交付 */
    isp_video->stats_buffer = NULL;
}
```

要点 **[确证]**：

* 运行在 **ISR 上下文**（`portENTER_CRITICAL` + spinlock）
* 一个 buffer 累积**本帧全部已启用**的统计类型，**凑齐 `target_flags` 才交付**
* `target_flags` 的基线是 **AE | HIST** ——
  **这就是 `isp_init_params()` 里默认把 AE 和 HIST 都打开的原因：
  任一关闭都会导致 buffer 永远凑不齐、整条 IPA 流水线停摆** **[确证]**
* 没有排队的 buffer 时统计**直接丢弃**（`ESP_ERR_NO_MEM`）
* buffer 深度 = **2**（`ISP_METADATA_BUFFER_COUNT 2`）
* 交付速率 = **每帧一次**（各 controller 都在 continuous 模式）

传输结构 **[确证]**：

```c
typedef struct esp_video_isp_stats {
    uint32_t flags;
    uint64_t seq;
    esp_isp_ae_env_detector_evt_data_t ae;
    esp_isp_awb_evt_data_t             awb;
    esp_isp_hist_evt_data_t            hist;
    esp_isp_sharpen_evt_data_t         sharpen;
    esp_isp_af_env_detector_evt_data_t af;
} esp_video_isp_stats_t;
```

`ESP_VIDEO_ISP_STATS_FLAG_{AE,AWB,HIST,SHARPEN,AF,AWB_SUBWIN}` = bit 0..5 **[确证]**。
随后 `isp_stats_to_ipa_stats()` 转成 `esp_ipa_stats_t`：
AE 5×5 → 扁平 `ae_stats[25].luminance`；AWB `white_patch_num → counted` + `sum_r/g/b`；
HIST 16 bin；sharpen `high_freq_pixel_max → value`；AF 3 窗 × `{definition, luminance}`。
**注意 IPA 侧的 flag 位定义与 video 侧不同**（`IPA_STATS_FLAGS_AWB = 1<<0`、
`IPA_STATS_FLAGS_AE = 1<<1`，AE/AWB 互换），转换函数是从 0 重建的，所以行为正确 **[确证]**。

### C.4 主循环

`esp_video_isp_pipeline.c` 起一个独立任务 `"isp_task"`，**优先级 11、栈 4096** **[确证]**。
它同时持有**两个 fd**：`isp_fd` = `/dev/video20`（ISP 统计），
`cam_fd` = `/dev/video0`（CSI/传感器）**[确证]**。

```c
while (1) {
    ioctl(isp->isp_fd, VIDIOC_DQBUF, &buf);            /* 阻塞等本帧统计 */
    get_sensor_state(isp, buf.index);                   /* 读回当前曝光/增益 */
    isp_stats_to_queue(isp, isp->isp_stats[buf.index]); /* 可选的应用侧抓取 */
    isp_stats_to_ipa_stats(isp->isp_stats[buf.index], &isp->ipa_stats);
    ioctl(isp->isp_fd, VIDIOC_QBUF, &buf);              /* 立刻还 buffer */
    isp->metadata.flags = 0;                            /* ← 每帧清零 */
    esp_ipa_pipeline_process(isp->ipa_pipeline, &isp->ipa_stats,
                             &isp->sensor, &isp->metadata);
    config_isp_and_camera(isp, &isp->metadata);         /* 下发 */
}
```

`metadata.flags = 0` 每帧清零 **[确证]** ——
所以 flags 严格表示"**本帧有变化**"，所有下发函数都是 `if (flags & IPA_METADATA_FLAGS_xx)`。
**更新频率 = 帧率**（1080p30 → 每秒 30 次 IPA 迭代）**[确证]**。

### C.5 下发顺序与"写到哪里"

`config_isp_and_camera()`（`esp_video_isp_pipeline.c:860`）**[确证]**：

```c
config_statistics_region(isp, metadata);
if (!isp->sensor_attr.awb) { config_white_balance(isp, metadata); }
config_bayer_filter(isp, metadata);
config_demosaic(isp, metadata);
config_sharpen(isp, metadata);
config_gamma(isp, metadata);
config_ccm(isp, metadata);
config_color(isp, metadata);
#if ESP_VIDEO_ISP_DEVICE_LSC
config_lsc(isp, metadata);
#endif
config_awb(isp, metadata);
config_af(isp, metadata);
#if ESP_VIDEO_ISP_DEVICE_BLC
config_blc(isp, metadata);
#endif
config_sensor_ae_target_level(isp, metadata);
config_exposure_and_gain(isp, metadata);
```

**次序要求：ISP 侧全部先写，传感器侧（AE 电平、曝光/增益、对焦）最后写** **[确证]**。

**输出路由表（哪个 knob 写到哪个 fd）** **[确证]**：

| flag | 字段 | 目标 fd | V4L2 控制 |
|------|------|---------|-----------|
| `..._ET` (1<<3) | `exposure`（µs） | **cam_fd（传感器）** | `V4L2_CID_EXPOSURE` |
| `..._GN` (1<<4) | `gain`（float 倍数） | **cam_fd（传感器）** | `V4L2_CID_GAIN`（menu index） |
| ET+GN 同时 | 二者 | **cam_fd** | `V4L2_CID_CAMERA_GROUP`（**原子**写） |
| `..._AETL` (1<<15) | `ae_target_level` | **cam_fd** | `V4L2_CID_CAMERA_AE_LEVEL` |
| `..._FP` (1<<18) | `focus_pos` | **cam_fd** | `V4L2_CID_FOCUS_ABSOLUTE` |
| `..._RG`/`_BG` (1<<1,1<<2) | `red_gain`/`blue_gain` | **isp_fd** | `V4L2_CID_USER_ESP_ISP_WB` 或 `V4L2_CID_RED/BLUE_BALANCE` |
| `..._BF` (1<<5) | `bf` | isp_fd | `V4L2_CID_USER_ESP_ISP_BF` |
| `..._SH` (1<<6) | `sharpen` | isp_fd | `V4L2_CID_USER_ESP_ISP_SHARPEN` |
| `..._GAMMA` (1<<7) | `gamma` | isp_fd | `V4L2_CID_USER_ESP_ISP_GAMMA_EXT` |
| `..._CCM` (1<<8) | `ccm` | isp_fd | `V4L2_CID_USER_ESP_ISP_CCM` |
| `..._BR/CN/ST/HUE` (1<<9..12) | 亮度/对比度/饱和度/色调 | isp_fd | `V4L2_CID_BRIGHTNESS/CONTRAST/SATURATION/HUE` |
| `..._DM` (1<<13) | `demosaic` | isp_fd | `V4L2_CID_USER_ESP_ISP_DEMOSAIC` |
| `..._LSC` (1<<14) | `lsc` | isp_fd | `V4L2_CID_USER_ESP_ISP_LSC` |
| `..._AWB` (1<<0) | `awb`（**统计范围**，非增益） | isp_fd | `V4L2_CID_USER_ESP_ISP_AWB` |
| `..._SR` (1<<16) | `stats_region` | isp_fd | AF+AWB+AE+HIST 四个窗 |
| `..._AF` (1<<17) | `af` | isp_fd | `V4L2_CID_USER_ESP_ISP_AF` |
| `..._BLC` (1<<19) | `blc` | isp_fd | `V4L2_CID_USER_ESP_ISP_BLC` |

> 与 §B.1 的模块分工完全吻合：
> **`agc` 的输出走传感器（曝光/增益），`awb` 的输出走 ISP（WB 增益或 CCM），
> `adn`/`acc`/`aen` 的输出全部走 ISP。**

### C.6 AE 闭环（AGC）

* **输入**：`esp_ipa_stats_t.ae_stats[25].luminance`
  —— 来自 ISP AE 统计块，采样点固定为 **`ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC`**
  （`esp_video_isp_device.c:879`，硬编码）**[确证]**
  → **官方 AE 采的是 demosaic 之后、gamma 之前的线性 RGB 亮度**，
  而不是最终显示域亮度。这一点对对齐至关重要。
* **输出**：`metadata.exposure`（µs）与 `metadata.gain`（float 倍数）→ **传感器寄存器**
* **控制律**：**在 `libesp_ipa.a` 内部，闭源，无法重建** **[缺口]**。
  JSON 侧可见的结构（§B.4）表明它至少包含：带死区的目标亮度、
  5×5 加权测光、高/低光优先模式、按块计数的过/欠曝保护、
  `frame_delay = 3` 的执行延迟补偿、`gain.min_step = 0.03` 的最小步长死区。
* **单位换算（开源桥接层）** **[确证]**：
  * 曝光 µs → 行数：
    ```c
    exposure_val = (uint32_t)((double)metadata->exposure * 1000 / isp->sensor_tline_ns + 0.5);
    exposure_val = exposure_val / qctrl.step * qctrl.step;   /* 对齐 step */
    exposure_val = CLAMP(exposure_val, qctrl.minimum, qctrl.maximum);
    ```
    `sensor_tline_ns` 取自 `sensor_format.isp_info->isp_v1_info.tline_ns`
    （SC202CS = **26666 ns**，`S9:sc202cs.c:884`）**[确证]**
  * 增益 float → menu index：**对传感器的 `V4L2_CTRL_TYPE_INTEGER_MENU` 做二分查找**
    （`esp_video_isp_pipeline.c:487-600`），相邻两档时取更接近的一个 **[确证]**
* **防重复写**：若换算后的值与上一帧相同，**清掉对应 flag，不发 ioctl**
  （`if (isp->prev_gain_index == gain_index) metadata->flags &= ~IPA_METADATA_FLAGS_GN;`）**[确证]**
* **原子性**：曝光与增益同时变化且传感器支持 `V4L2_CID_CAMERA_GROUP` 时，
  打包成 `esp_cam_sensor_gh_exp_gain_t` **一次写入**；否则拆成两次 ioctl，**曝光先写** **[确证]**
* **能力协商**：传感器不支持增益/曝光控制时，桥接层会主动清掉对应 flag 并打 warning **[确证]**

### C.7 AWB 闭环

* **输入**：`esp_ipa_stats_t` 的 AWB 部分（`counted`、`sum_r/g/b`，
  rev≥3.0 另有 `awb_subwin[5][5]`）
  —— 来自 ISP AWB 统计块，采样点在 `esp_video` 里**硬编码为
  `ISP_AWB_SAMPLE_POINT_BEFORE_CCM`**
  （`esp_video_isp_device.c:639` `isp_init_awb_param()`）**[确证]**
  → **官方 AWB 采的是 demosaic 之后、CCM 之前的线性 RGB。**
* **白块筛选窗的推导方式很特别** **[确证，原文]**：
  ```c
  awb_config->white_patch.luminance.max = (float)awb->green_max * (1 + awb->rg_max + awb->bg_max);
  awb_config->white_patch.luminance.min = (float)awb->green_min * (1 + awb->rg_min + awb->bg_min);
  awb_config->white_patch.red_green_ratio.max = awb->rg_max;   /* 等等 */
  ```
  → **亮度上下限不是独立配置的，而是由 `green` 范围和 rg/bg 比范围推导出来的
  `G × (1 + R/G + B/G)` = R+G+B。**
  这正好解释了 §B.3 里 `awb.range.green = {98, 210}` 为什么是**单通道 G** 的范围，
  而驱动 `esp_isp_awb_config_t::white_patch.luminance` 却是 `[0, 255*3]` 的三通道和 **[确证]**。
  对 SC202CS 代入：
  `lum_max = 210 × (1 + 0.879 + 0.6587) = 532.7`，
  `lum_min = 98 × (1 + 0.3801 + 0.2903) = 164.7`。
* **输出**：`metadata.red_gain` / `blue_gain` → **ISP**（WBG 或 CCM，见 C.8）
* **控制律**：**闭源** **[缺口]**。
  JSON 侧可见：`min_counted` 门限、`min_red/blue_gain_step` 死区、
  `green_luma_step_ratio` 一阶低通、`model` 选择估计器、
  eco5 世代还有 `zones[]` / `ref_points[]` 的分区投票 + `new_w`/`prev_w` 时域加权。
  开源的同类参考实现见 §D.6（IDF `example_awb.c`：5 帧平均 + P=0.5 比例控制器）。
* **与其他模块的关系** **[确证]**：
  * `awb` 通过 `export_ct` 把估得的**色温**发布到内部 map 的 `"ct"` 键；
    `acc` 用它选 CCM / 饱和度 / LSC 档 → **`acc` 依赖 `awb`，必须排在其后**
  * **若传感器自带 AWB**（`ESP_CAM_SENSOR_STATS_FLAG_WB_GAIN`），
    桥接层会**整条跳过 ISP 的白平衡路径**：
    ```c
    if (!isp->sensor_attr.awb) { config_white_balance(isp, metadata); }
    ```
    并在 `get_sensor_state()` 里把 ISP 自己的 AWB 统计 flag 抹掉、
    改填传感器上报的 WB 均值（`white_patch_num = 1`）**[确证]**。
    SC202CS 不上报 WB 统计，走 ISP 路径 **[反推]**。

### C.8 白平衡增益的落点（rev 相关，本节是 §D 的源码级证据）

`isp_init_ccm_param()`（`esp_video_isp_device.c:789`）**[确证，原文]**：

```c
#ifndef ESP_VIDEO_ISP_DEVICE_WBG          /* ← rev < 3.0 */
    if (isp_video->ccm_enable) {
        memcpy(ccm_config->matrix, isp_video->ccm_matrix, sizeof(ccm_config->matrix));
        /* Apply red and blue balance */
        for (int i = 0; i < ISP_CCM_DIMENSION; i++) {
            if (isp_video->red_balance_enable)  ccm_config->matrix[i][0] *= isp_video->red_balance_gain;
            if (isp_video->blue_balance_enable) ccm_config->matrix[i][2] *= isp_video->blue_balance_gain;
        }
    } else {
        ccm_config->matrix[0][0] = 1.0;  ccm_config->matrix[1][1] = 1.0;  ccm_config->matrix[2][2] = 1.0;
        if (isp_video->red_balance_enable)  ccm_config->matrix[0][0] = isp_video->red_balance_gain;
        if (isp_video->blue_balance_enable) ccm_config->matrix[2][2] = isp_video->blue_balance_gain;
    }
#else                                      /* ← rev >= 3.0 */
    if (isp_video->ccm_enable) {
        memcpy(ccm_config->matrix, isp_video->ccm_matrix, sizeof(ccm_config->matrix));
    }
#endif
```

**这是官方 rev<3.0 降级路径的核心，把 §D.5 的反推坐实了** **[确证]**：

* **rev < 3.0**：R/B 增益**乘进 CCM 矩阵的第 0 列和第 2 列**
  （若 CCM 未启用，则退化成对角阵 `diag(red_gain, 1, blue_gain)`）
* **rev ≥ 3.0**：R/B 增益走独立的 **WBG** 块，
  `isp_start_wbg()` 做 `gain × 256`（`ESP_VIDEO_ISP_WBG_DEC_BITS = 8`），G 固定为 `1<<8` **[确证]**

**rev<3.0 由此引入的三个结构性后果** **[反推，依据是上述代码 + §A 的级序]**：

1. 白平衡从 **Bayer 域（demosaic 之前）** 挪到了 **RGB 域（demosaic 之后）**
2. AWB 的采样点是 `BEFORE_CCM`，而增益作用在 **CCM 之内** ——
   **统计环路不再穿过它所控制的那个块**（开环点在环外）
3. 可达增益被 CCM 的定点范围 **±4.0（S2.10）** 钳住，且 **WB 与 CCM 相互耦合**

另外 `V4L2_CID_RED_BALANCE` 的语义在两条路径下不同 **[确证]**：
有 WBG 时 `value <= 0` 表示**把增益重置为 1.0 并重新下发**；
无 WBG 时表示**清掉 `red_balance_enable` 并重配 CCM**。

### C.9 其他模块的闭环结构

| 模块 | 输入 | 输出 | 控制律 |
|------|------|------|--------|
| `ian` | AE 统计 + 当前曝光/增益 | 内部 map：`ae.luma.avg`、`env.luma.avg`、（经 `color_temp` 模型）色温 | 闭源；JSON 侧可见 5×5 权重、16 抽头时域 FIR、白点轨迹二次拟合 + McCamy 式 CCT 三次多项式（§B.2） |
| `adn` | 当前**增益**（来自 `agc`） | `metadata.bf`、`metadata.demosaic` → ISP | **纯查表前馈**，按 gain 分档（§B.5）。表间是否插值 **[缺口]** |
| `acc` | **`ct`**（来自 `awb`）+ `ae.luma.avg` | `metadata.ccm`、`saturation`、`lsc`、`blc` → ISP | 按色温选档 + 暗场旁路（§B.6）。**选档/插值算法闭源 [缺口]** |
| `aen` | **`env.luma.avg`**（来自 `ian`）+ 当前增益 | `metadata.gamma`、`sharpen`、`contrast` → ISP | 按亮度选 gamma 曲线（带 `luma_min_step` 迟滞）+ 按增益选锐化/对比度（§B.7） |
| `af` | AF 统计 `definition[3]`、`luminance[3]`（RGB2YUV 后的 Y 域） | `metadata.focus_pos` → **传感器/马达** | 闭源。全仓库只有 `ov5647` 一个传感器配置启用了 `af` **[确证]** |
| `atc` | — | `metadata.ae_target_level` → **传感器**（供传感器自带 AE 用） | 全仓库只有 `ov2710` 启用 **[确证]** |

**依赖次序总结** **[反推，依据是数据流]**：

```
ian ──(env.luma / ae.luma)──┬──> aen (gamma)
                            └──> acc (low_luma 旁路)
awb ──(ct)─────────────────────> acc (CCM / saturation / LSC 选档)
agc ──(gain)───────────────┬──> adn (BF / demosaic 分档)
                           └──> aen (sharpen / contrast 分档)
```

### C.10 esp_video ISP device 的默认状态（对齐时的关键基线）

`isp_init_params()`（`esp_video_isp_device.c:2310`）是**全部**编译期默认值 **[确证，原文]**：

```c
/* Keep AE/HIST enabled by default to preserve previous pipeline behavior. */
isp_video->ae_config.enable   = true;
isp_video->hist_config.enable = true;
isp_video->red_balance_gain   = 1.0;
isp_video->blue_balance_gain  = 1.0;
isp_video->ccm_matrix[0][0]   = 1.0;
isp_video->ccm_matrix[1][1]   = 1.0;
isp_video->ccm_matrix[2][2]   = 1.0;
isp_video->color_config.color_contrast.val   = ISP_CONTRAST_DEFAULT;    /* 128 = 1.0x */
isp_video->color_config.color_saturation.val = ISP_SATURATION_DEFAULT;  /* 128 = 1.0x */
isp_video->color_config.color_hue            = ISP_HUE_DEFAULT;         /* 0 */
isp_video->color_config.color_brightness     = ISP_BRIGHTNESS_DEFAULT;  /* 0 */
isp_video->isp_raw_bypass = true;
```

> **BF / sharpen / gamma / demosaic / CCM / LSC / BLC / AWB / AF 的 `enable` 全部默认为 0。**
> 开箱状态下 ISP 只跑 **AE + 直方图 + color** 三样，
> **所有画质块都是黑的，直到 IPA（或应用）通过 ext-ctrl 写进来。**
> 也就是说：**BF 模板、锐化系数、gamma 曲线、CCM 的"默认值"全部来自标定 JSON，
> 不来自任何 C 代码。** **[确证]**

其他硬编码默认 **[确证]**：

* 直方图：`hist_mode` 默认 `ISP_HIST_SAMPLING_RGB`；
  RGB 系数各 `85/256 ≈ 1/3`；5×5 权重轻微中心加权（10/256 为主，内十字 11，中心 12）；
  15 个分段阈值 = `{16, 32, ..., 240}`（16 的整数倍）
  > ⛔ **这两组数不能照抄，见 §F.1 的纠正 #1 / #2**（2026-08-23 实施回填）：
  > 权重那组加起来是 **260**，而驱动硬性要求 `weight_sum == 256` ⇒ **配上去直接
  > `ESP_ERR_INVALID_ARG`**；RGB 三个 85 之和是 255 而不是 256。
* AE：`sample_point = ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC`
* AWB：`sample_point = ISP_AWB_SAMPLE_POINT_BEFORE_CCM`
* CCM：`ccm_config->saturation = true`（越界饱和而非报错）
* BF / demosaic / sharpen 的 padding：一律 `..._EDGE_PADDING_MODE_SRND_DATA`，tail valid 0/0
* BLC：窗口为整帧（且注释特别说明**右下角不减 1**），`filter_enable = false`
* 统计窗：AE / AWB / HIST / AF **共用同一个窗**，默认**整帧**
  （`isp_init_stats_windows()`，注释 *"Use the full resolution of the sensor for statistics."*）
* AF 可用性依赖格式：`if (raw_in && !raw_out) af_support = 1;`
  —— **输出 RAW8/10/12 时 AF 不可用** **[确证]**

### C.11 到此为止 —— 闭源边界清单

以下内容**无法重建**，只能从 JSON schema 和头文件反推方向，
具体数学在 `libesp_ipa.a` 里：

| 项 | 状态 |
|----|------|
| AE 的收敛律（比例？PID？状态机？） | **[缺口]** |
| AWB 的白点估计算法（`model` 0/1/2 各是什么） | **[缺口]** |
| 色温从 `ian.color_temp` 到 `"ct"` 的完整计算 | **[反推，数值验证，见 §B.2.2]**；确切实现 **[缺口]** |
| `acc.ccm.table` 19 档的选档/插值 | **[缺口]** |
| `acc.lsc` 9 档色温的选档/插值 | **[缺口]** |
| `adn` / `aen` 各表在 `gain` 断点之间是否插值 | **[缺口]** |
| `agc.f_n0` / `f_m0` / `acc.blc.model` / `acc.lsc.model` / `awb.model` 的语义 | **[缺口]** |
| 可发布具名量的全集 | **[缺口]** |
| AF 的爬山策略 | **[缺口]** |


## D. rev<3.0 的官方降级路径

### D.1 选择机制：一个 Kconfig 开关切换整份标定文件

`esp_cam_sensor` 的 `project_include.cmake` 在**构建期**按芯片版本选标定文件
（`S7:project_include.cmake`）**[确证]**：

```cmake
if(CONFIG_CAMERA_SC2336)
    if(CONFIG_CAMERA_SC2336_DEFAULT_IPA_JSON_CONFIGURATION_FILE)
        if (CONFIG_ESP32P4_SELECTS_REV_LESS_V3)
            idf_build_set_property(ESP_IPA_JSON_CONFIG_FILE_PATH ".../sc2336_default_p4_eco4.json" APPEND)
        else()
            idf_build_set_property(ESP_IPA_JSON_CONFIG_FILE_PATH ".../sc2336_default_p4_eco5.json" APPEND)
        endif()
    ...
```
（`S7:9-19`；os02n10 见 `S7:21-31`；ov9281 见 `S7:81-91`）

* 开关是 **`CONFIG_ESP32P4_SELECTS_REV_LESS_V3`**（IDF 的目标芯片版本选择）**[确证]**
* eco4 = rev **< 3.0**，eco5 = rev **≥ 3.0** **[确证]**
* **只有 3 个传感器有这一对文件：`sc2336`、`os02n10`、`ov9281`** **[确证，本地 find 结果 + `S7` 中只有这三处 `if (CONFIG_ESP32P4_SELECTS_REV_LESS_V3)`]**

### D.2 SC202CS **没有** eco4/eco5 双份配置 —— 这是本次重建最重要的一条

```cmake
if(CONFIG_CAMERA_SC202CS)
    if(CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_CONFIGURATION_FILE)
        idf_build_set_property(ESP_IPA_JSON_CONFIG_FILE_PATH
            "${COMPONENT_PATH}/sensors/sc202cs/cfg/sc202cs_default.json" APPEND)
    elseif(...)
```
（`S7:65-71`）**[确证]** —— **无 rev 分支**。

`sensors/sc202cs/cfg/` 下只有 `sc202cs_default.json` 一个文件 **[确证，本地 ls]**。

而这份唯一的文件**包含 `acc.blc` 段**（`S6:.acc.blc`）**[确证]**：

```json
"blc": {"model": 0, "stretch": false,
        "blc_table": [{"gain": 1, "blc_param": {"blc_top_left": 16, "blc_top_right": 16,
                                                "blc_bottom_left": 16, "blc_bottom_right": 16}}]}
```

**结论**：从文件结构看，`sc202cs_default.json` 属于 **eco5（rev≥3.0）世代**的配置形态，
但官方**没有**为 SC202CS 提供 rev<3.0 的降级版本，也没有加 rev 分支 ——
不论芯片版本，官方都下发同一份含 `acc.blc` 的配置。
**[确证：文件清单 + `project_include.cmake` 无分支]**

**[缺口]**：在 rev<3.0 上，esp_ipa 拿到这份带 `acc.blc` 的配置后到底怎么处理
（是运行期跳过、还是调用 `esp_isp_blc_configure()` 拿 `ESP_ERR_NOT_SUPPORTED` 后忽略），
需要看 esp_ipa 的实现 —— 见 §C。

### D.3 eco4↔eco5 的差异：官方降级策略的直接证据

对三对文件做全叶子节点 diff。**`ov9281` 是最干净的最小对照对**（文件仅 9.3 KB → 9.6 KB）：

**ov9281 eco4 vs eco5 —— 结构性差异只有一处** **[确证]**：

| 只在 eco5（rev≥3）出现 | 只在 eco4（rev<3）出现 |
|---|---|
| `acc.blc.model`<br>`acc.blc.stretch`<br>`acc.blc.blc_table[0].gain` + `blc_param.{blc_top_left, blc_top_right, blc_bottom_left, blc_bottom_right}`<br>`acc.blc.blc_table[1].*` | `aen.contrast[3].*`<br>`aen.sharpen[3].*`（gain=65 那一档被删） |

其余 19 处是数值重调（AE 目标 41→19、gamma 断点、权重表等），**与 rev 无关，属于重新调校**。

**os02n10 eco4 vs eco5 —— 结构性新增同样只有 `acc.blc`** **[确证]**：

只在 eco5 出现的结构：
* `acc.blc.{model, stretch, blc_table[0].gain, blc_table[0].blc_param.*}` ← **rev 相关**
* `acc.lsc.table[1..5]`（LSC 色温档从 1 档扩到 6 档）← 标定加密，与 rev 无关
* `acc.ccm.table[5..9]`（CCM 从 5 档扩到 10 档）← 同上
* `adn.bf[4..6]`、`aen.contrast[3]` ← 分档加密
* `ian.luma.env.{k, speed_param, weight}` ← 新增"环境亮度"量（新特性）

只在 eco4 出现的结构：
* `ian.color_temp.m_1.{a0, a1}`（一次拟合形式，eco5 只保留 `m_2` 二次形式）
* `ian.color_temp.bp[8..15]`（eco4 有 16 点，eco5 缩到 8 点 —— 因为改用二次模型）

> ⚠️ 注意 `acc.lsc` 在 **eco4（rev<3.0）中就已存在**（`os02n10_default_p4_eco4.json` 有
> `acc.lsc.{model,img_w,img_h,lsc_tbl_size,table[0]}`）**[确证]**。
> 这与驱动侧一致：LSC 的门限是 **rev ≥ 1.0**，不是 3.0（`S1:src/isp_lsc.c:55-60`）**[确证]**。
> **LSC 在我们的 rev v1.0 芯片上是可用的。**

**sc2336 eco4 vs eco5 —— 不是干净的对照对** **[确证]**：
两份文件跨了 esp_ipa 的世代（eco5 新增 `awb.{zones, ref_points, new_w, prev_w,
red_gain_scale, blue_gain_scale, export_ct, outlier_rg, outlier_bg, type_counter_max}`、
`agc.luma_pwl`、`agc.light_threshold_priority_use_env_luma`、`acc.lsc` 整段、
`agc.mode` 由 `high_light_priority` 改成 `light_threshold_priority`）。
所以**不能**把 sc2336 的 diff 直接当作"rev 降级差异"来读 —— 里面混了大量特性演进。

sc2336 eco4 的 `acc` 段只有 281 字节，退化到**单一固定 CCM + 单一饱和度 + 灰世界 AWB** **[确证]**：

```json
"acc": {"saturation": [{"color_temp": 0, "value": 136}],
        "ccm": {"table": [{"color_temp": 0,
                "matrix": [1.408, -0.094, -0.314, -0.13, 1.28, -0.15, -0.072, -0.173, 1.245]}]}}
```
（`awb.model = 0`、`min_counted = 2000`；eco5 则是 `model = 2`、`min_counted = 10`、
CCM 12 档 `[1200…12000]`、LSC 7 档 `[2379…9473]`，`lsc_tbl_size = 558` @ 1920×1080）

> ⚠️ **但这个"塌缩"不能全部归因于芯片版本。**
> `os02n10_default_p4_eco4.json`（同样是 rev<3.0）就有完整的
> `ian.color_temp`（16 点 bp）、`acc.ccm`（5 档色温）、`acc.lsc`（1 档）**[确证]**。
> 说明**色温自适应链路在 rev<3.0 上是可以跑的**，sc2336 eco4 的简陋是因为那份文件
> **被冻结在旧世代、没有跟进重新标定**，而不是被刻意降级 **[反推]**。

**三对文件的公共交集，也就是唯一稳定的 rev 相关结论**：

> **官方 rev<3.0 的配置侧降级动作 = 整段删掉 `acc.blc`。**
> **[确证：三对文件中 `acc.blc` 一致地只出现在 eco5；
> 而 `acc.lsc` / `ian.color_temp` / 多档 CCM 在 os02n10 eco4 中都存在]**

### D.4 驱动侧的降级：官方在 rev<3.0 上具体怎么做

| 能力 | rev<3.0 的官方行为 | 源码依据 |
|------|--------------------|----------|
| **BLC** | `esp_isp_blc_configure()` 直接返回 `ESP_ERR_NOT_SUPPORTED`，日志 "BLC is not supported on ESP32P4 chips prior than v3.0" | `S1:src/isp_blc.c:27-33` **[确证]** |
| **WBG** | `esp_isp_wbg_configure()` 直接返回 `ESP_ERR_NOT_SUPPORTED`，日志 "WBG is not supported on ESP32P4 chips prior than v3.0" | `S1:src/isp_wbg.c:27-33` **[确证]** |
| **CROP** | `esp_isp_crop_configure()` 直接返回 `ESP_ERR_NOT_SUPPORTED` | `S1:src/isp_crop.c:26-32` **[确证]** |
| **AWB 子窗** | **不报错**，打 warning "Subwindow feature is not supported on REV < 3.0, subwindow will not be configured" 后跳过；主窗统计照常工作 | `S1:src/isp_awb.c:81-89` **[确证]** |
| **影子寄存器** | `isp_ll_shadow_update_*()` 全部是 "for compatibility" 空桩返回 true；写入立即生效，无帧边界原子性 | `S2:isp_ll.h:2092-2134` **[确证]** |
| **CCM 精度** | 定点由 S4.8（±16.0）降为 **S2.10（±4.0）**；范围检查用 `ISP_LL_CCM_MATRIX_INT_BITS` | `S2:isp_ll.h:138-145`；`S1:src/isp_ccm.c:24-32` **[确证]** |
| **色调精度** | HAL 内部做 `(hue * 256) / 360` 折算成 8 bit 写入 | `S2:isp_hal.c:217-221` **[确证]** |
| **中断源** | 掩码 `0x1FFFFFFF`（29 位）而非 32 位 | `S2:isp_ll.h:74-78` **[确证]** |
| **LSC** | ✅ 正常可用（门限 rev≥1.0） | `S1:src/isp_lsc.c:55-60` **[确证]** |
| **官方示例** | `example_pipelines.c` 用 `#if CONFIG_ESP32P4_REV_MIN_FULL >= 300` 包住 BLC，`>= 100` 包住 LSC；不满足时打 warning 并 `return ESP_ERR_NOT_SUPPORTED`。注意 `example_isp_init_all_pipelines()` 用 `ESP_ERROR_CHECK()` 调 BLC —— 在 rev<3.0 上会**直接 abort** | `S5:example_pipelines.c:55, 113-116, 167, 205-208, 489` **[确证]** |

### D.4b esp_video 侧的 rev 门控总闸

`esp_video` 把**所有** rev 判断收敛到一个头文件
`esp_video/include/esp_video_caps.h` **[确证，原文]**：

```c
#if CONFIG_IDF_TARGET_ESP32P4

#if CONFIG_ESP32P4_REV_MIN_FULL >= 100
#if CONFIG_SOC_ISP_LSC_SUPPORTED
#define ESP_VIDEO_ISP_DEVICE_LSC    1
#endif
#endif /* CONFIG_ESP32P4_REV_MIN_FULL >= 100 */

#if CONFIG_ESP32P4_REV_MIN_FULL >= 300
#if CONFIG_SOC_ISP_WBG_SUPPORTED
#define ESP_VIDEO_ISP_DEVICE_WBG    1
#define ESP_VIDEO_ISP_WBG_DEC_BITS  8
#endif
#if CONFIG_SOC_ISP_BLC_SUPPORTED
#define ESP_VIDEO_ISP_DEVICE_BLC    1
#endif
#if CONFIG_SOC_ISP_CROP_SUPPORTED
#define ESP_VIDEO_ISP_DEVICE_CROP   1
#endif
#if (...IDF 版本判断...)
#define ESP_VIDEO_ISP_DEVICE_AWB_SUBWIN  1
#define ESP_VIDEO_ISP_DEVICE_ONCE_CONFIG 1
#endif
#if CONFIG_SOC_JPEG_CODEC_SUPPORTED
#define ESP_VIDEO_JPEG_DEVICE_YUV420    1
#define ESP_VIDEO_JPEG_DEVICE_YUV444    1
#endif
#endif /* CONFIG_ESP32P4_REV_MIN_FULL >= 300 */
```

要点 **[确证]**：

* **全仓库没有任何运行期芯片版本检测** —— 搜遍 `esp_chip_info` / `efuse` /
  `ESP_CHIP_REV` / `chip_revision` 零命中。**全部是编译期 Kconfig 门控。**
  想要一份镜像同时支持两种 rev 是**不可能**的，必须分别构建。
* 门限就两档：**rev ≥ 1.0 → LSC**；**rev ≥ 3.0 → WBG / BLC / CROP /
  AWB 子窗 / once-config / JPEG YUV420·YUV444**
* 注意耦合：`ESP_VIDEO_JPEG_DEVICE_YUV420` 与 `YUV444` 也被塞进了
  `>= 300` 块 —— **rev<3.0 上 esp_video 的 JPEG 设备不支持 YUV420/YUV444**
* `esp_video_isp_device.c` 里 BLC 相关的**结构体成员、qctrl 表项、
  set/get case、start/stop/reconfigure 函数全部在 `#if ESP_VIDEO_ISP_DEVICE_BLC` 内**
  → rev<3.0 上 `V4L2_CID_USER_ESP_ISP_BLC` 落到 `default:` 返回 `ESP_ERR_NOT_SUPPORTED`，
  **且没有任何软件替代**，黑电平只能靠传感器自己处理

**一个需要留意的陷阱** **[确证]**：CROP 与 BLC 的降级方式**不一样**。
`isp_start_crop()` 在 rev<3.0 上**仍然存在、仍然返回 `ESP_OK`**：

```c
static esp_err_t isp_start_crop(struct isp_video *isp_video, const struct v4l2_rect *crop_rect)
{
    esp_err_t ret = ESP_OK;
#if ESP_VIDEO_ISP_DEVICE_CROP
    ... configure + enable ...
#endif
    return ret;
}
```

→ **调用方请求裁剪会拿到"成功"，但实际没有裁剪**（静默 no-op）。

### D.5 没有 WBG 时，白平衡增益写到哪里

这是 rev<3.0 降级路径里最关键的一环。官方在驱动头文件里直接写明了两条路
（`S1:include/driver/isp_awb.h:22-29`）**[确证，原文]**：

> `ISP_AWB_SAMPLE_POINT_BEFORE_CCM`: sample before Color Correction Matrix(CCM).
> `ISP_AWB_SAMPLE_POINT_AFTER_CCM`: sample after Color Correction Matrix(CCM).
> **If your camera support to set the manual gain to the RGB channels, then you can choose to
> sample before CCM, and set the gain to the camera registers.**
> **If your camera doesn't support the manual gain or don't want to change the camera
> configuration, then you can choose to sample after CCM, and set the calculated gain to the CCM.**

即：**WBG 不可用时，白平衡增益要么下沉到传感器寄存器，要么上折进 CCM 矩阵。**

* SC202CS 的驱动**没有** R/B 通道手动增益的 V4L2 控制项 —— 它只暴露
  `exposure` 与 `gain_index`（`S9:sc202cs.c:1188-1284`，`ESP_CAM_SENSOR_EXPOSURE_VAL`
  / `..._GAIN` / `..._GROUP_EXP_GAIN`）**[确证]**。
* 因此在 SC202CS + rev<3.0 上，**唯一可用的白平衡执行点是把增益折进 CCM**。
  **这条反推已由 esp_video 的源码坐实** —— `isp_init_ccm_param()` 在
  `#ifndef ESP_VIDEO_ISP_DEVICE_WBG` 分支里把 `red_gain` 乘进 CCM 第 0 列、
  `blue_gain` 乘进第 2 列（CCM 未启用时退化为 `diag(red_gain, 1, blue_gain)`）。
  **完整代码与三个结构性后果见 §C.8** **[确证]**。
* 官方 IDF 示例 `example_awb.c` 走的是另一条（WBG）路：
  它把增益写进 `esp_isp_wbg_set_wb_gain()`，并且默认 `sample_point = AFTER_CCM`
  （`S5:example_awb.c:42, 99-115`）**[确证]** ——
  **这个示例在 rev<3.0 上跑不了 WBG 部分。**

### D.6 官方 AWB 控制律（开源部分，来自 IDF 示例）

esp_ipa 的 AWB 是闭源的（见 §C），但 IDF 自带的 `example_awb.c` 是开源的、
可以作为"官方风格"的参考实现 **[确证]**（`S5:main/example_awb.c`）：

```c
#define AWB_GAIN_UPDATE_COUNT    5      // 累积 5 帧统计再更新一次
#define AWB_GAIN_NORM            256    // 1.0 增益的归一化值
#define AWB_P_GAIN               0.5f   // 比例增益
```

* **统计输入**：`isp_awb_stat_result_t{white_patch_num, sum_r, sum_g, sum_b}`，
  ISR 回调里 `xQueueSendFromISR()` 丢给任务，**每帧一次**（`example_awb.c:74-86`）
* **有效性判据**：`white_patch_num == 0` 或 `sum_r == 0` 或 `sum_b == 0` → 保持当前增益不动
  （`example_awb.c:131-141`）
* **目标增益**（灰世界，以 G 为参考）：
  ```c
  gain_r = (sum_g / sum_r) * 256;
  gain_g = 256;
  gain_b = (sum_g / sum_b) * 256;
  ```
  （`example_awb.c:144-150`）
* **抗振荡**：先对连续 5 帧的目标增益取算术平均，再过一个**纯 P 控制器**
  （注释明说 I 项预留未用）：
  ```c
  new_gain_r = current_gain_r + 0.5f * (target_gain_r - current_gain_r);
  ```
  （`example_awb.c:88-115, 194-199`）
* **窗口**：主窗取图像中间 80%（`0.2*res` ~ `0.8*res - 1`），亮度上限 `220*3`
  避免过曝像素污染统计；R/G、B/G 比范围 [0.5, 1.999]（`example_awb.c:44-62`）
* **执行**：`esp_isp_wbg_set_wb_gain()`（`example_awb.c` 引用 `driver/isp_wbg.h`）

> 与 `sc202cs_default.json` 的对照：JSON 里的 `awb.min_counted = 1200` 相当于把示例的
> `white_patch_num == 0` 判据换成一个实用门限；`min_red_gain_step`/`min_blue_gain_step = 0.0033`
> 相当于给 P 控制器加了个死区 **[反推]**。

### D.7 rev<3.0 降级路径 —— 结论

| 项 | 结论 |
|----|------|
| 选择机制 | 构建期 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3` 切换整份 JSON |
| 覆盖范围 | 仅 `sc2336` / `os02n10` / `ov9281` 三个传感器有双份配置 |
| **SC202CS** | **没有 rev<3.0 的降级配置**；唯一那份 `sc202cs_default.json` 含 `acc.blc` |
| 配置侧降级动作 | 整段删掉 `acc.blc`（三对文件的一致交集） |
| LSC | **不降级**，rev v1.0 就可用，官方 eco4 配置里也有 LSC 表 |
| BLC | 驱动 + esp_video 双层拒绝（`ESP_ERR_NOT_SUPPORTED`），**无软件替代**，只能靠传感器 |
| WBG 替代路径 | **官方实现 = 把 R/B 增益乘进 CCM 的第 0 / 第 2 列**（§C.8 源码确证）；理论上另一条是写传感器寄存器，但 SC202CS 不暴露该控制项 |
| CROP | esp_video 里是**静默 no-op**（返回 `ESP_OK` 但不裁），只能靠上游/下游（如 PPA）裁 |
| 精度损失 | CCM ±4.0/10 位小数（而非 ±16.0/8 位）；色调 8 bit |
| 原子性损失 | 无影子寄存器（且 esp_video 的 `ONCE_CONFIG` 也被门在 rev≥3.0），参数改动立即生效 |
| 统计能力损失 | AWB 无 5×5 子窗，只有主窗 4 个累加值 |
| 环路结构损失 | WB 从 Bayer 域挪到 RGB 域；AWB 采样点 `BEFORE_CCM` 而增益作用在 CCM 内 → **统计环路不穿过被控块**；WB 与 CCM 耦合 |
| 其他连带 | esp_video 的 JPEG 设备在 rev<3.0 上不支持 YUV420 / YUV444 |
| 切换粒度 | **编译期**。全仓库零运行期版本检测 → 一份镜像只能服务一种 rev |

---

## E. 未解问题与后续可查方向

| # | 问题 | 为什么查不到 | 可能的下一步 |
|---|------|--------------|--------------|
| 1 | `agc.f_n0` / `f_m0` 的含义 | 闭源 | 看 `esp_ipa/tools/config/isp/agc.py` 生成器读了哪些键、编成什么 C 结构 |
| 2 | `acc.ccm.table` 19 档的选档/插值算法 | 闭源 | 同上（`acc.py`）；或实测扫色温看 CCM 寄存器 |
| 3 | `awb.model` / `acc.blc.model` / `acc.lsc.model` / `ian.color_temp.model` 的取值枚举 | 闭源 | 生成器脚本 + `esp_ipa/README.md` |
| 4 | `adn` / `aen` 各表在 `gain` 断点之间是否插值 | 闭源 | 生成器脚本；或实测扫增益 |
| 5 | `ian.luma.env.k = 250000` 的公式与 `env.luma` 的绝对量纲 | 闭源 | 生成器脚本 |
| 6 | `ian.color_temp.bp` 的投影方式（最近点？沿某方向？） | 闭源 | 生成器脚本 |
| 7 | `anti_flicker.mode` 的枚举值 | 闭源 | 生成器脚本 |
| 8 | 可发布具名量（`"ae.luma.avg"` 等）的全集 | 闭源 | `nm libesp_ipa.a` 看导出符号 / 字符串表 |
| 9 | WBG 在硬件流水线上的精确插入点 | 官方框图未画 | ESP32-P4 TRM 的 ISP 章节 |
| 10 | rev<3.0 上 esp_ipa 拿到含 `acc.blc` 的 JSON（SC202CS 情形）如何处理 | 闭源 + 无双份配置 | 实测：看 rev v1.0 上是否有 `ESP_ERR_NOT_SUPPORTED` 日志 |
| 11 | `esp_video/CHANGELOG.md` 中 "ECO4" 一处指代 rev≥3.0，与 CMake 映射矛盾 | 官方文档笔误（疑） | 以 `project_include.cmake` 的映射为准：**eco4 = rev<3.0，eco5 = rev≥3.0** |

### 命名对照备注 **[确证]**

`project_include.cmake` 的映射是权威的：

```
CONFIG_ESP32P4_SELECTS_REV_LESS_V3 = y  →  *_p4_eco4.json   （rev < 3.0）
CONFIG_ESP32P4_SELECTS_REV_LESS_V3 = n  →  *_p4_eco5.json   （rev ≥ 3.0）
```

`esp_video/CHANGELOG.md` 有一条把 rev ≥ 3.0 写成 "ECO4"，与上式矛盾；
同文件其余各条（"Supported only on ESP32-P4 ECO5 and later"）与上式一致。
**按 CMake 为准。**

---

## F. 实施回填（2026-08-23，来自 ISP 对齐工程 T0–T13）

> **性质**：本节是**事后**回填。上面 §A–§E 写于 2026-08-19，依据是通读源码与标定 JSON；
> 下面这些是把它真正实现一遍（`components/packages/tab5-all-in-one`，ESP32-P4 **rev v1.0**）
> 之后发现的偏差。
>
> ⚠️ **回填的依据仍然是源码与宿主机验证，不是实机实测** —— 这轮实现一次都还没烧过板。
> 凡是需要实机才能定论的，下面明确标出「待实测」，**不要当成已确证**。
>
> 实施计划：`docs/superpowers/plans/2026-08-21-tab5-isp-align-with-official.md`（§H 有更细的原始记录）。

### F.1 纠正（原文与源码不符）

| # | 原文 | 实际 | 影响 |
|---|---|---|---|
| 1 | §C.10：esp_video 的直方图默认 5×5 权重是「10/256 为主，内十字 11，中心 12」 | 这组数**加起来是 260**（16×10 + 8×11 + 12），而 `s_esp_isp_hist_config_hardware()` 硬性要求 `weight_sum == 256` ⇒ 这组权重**配不上去**（`ESP_ERR_INVALID_ARG`）。要么原文对 esp_video 那段的描述不精确，要么 esp_video 用的是另一组数 | **照抄会直接失败。** 本次实现改用 IDF 测试的 `24×10 + 中心 16 = 256` |
| 2 | §C.10：直方图 RGB 系数「各 85/256 ≈ 1/3」 | 三个 85 之和是 **255** 不是 256。驱动只检查**权重和**、**不检查系数和**，所以 85/85/85 能配上，但原文说的「和应为 256」与它自己给的默认值对不上 | 本次实现用 **86/85/85**，让它精确为 256 |
| 3 | §A.7 / §A.3：rev<3.0 的 CCM 是「S2.10，范围 ±4.0」 | 驱动的范围检查确实是**闭区间** `[-4.0, +4.0]`（`isp_ccm.c:25-31`），但 2 整数位 + 10 小数位实际能表达的最大值是 `4095/1024 = **3.9990**` | **恰好写 4.0 会通过驱动检查、然后在 HAL 里被 `saturation = true` 悄悄改掉且不报错** ⇒ 硬件里的矩阵与日志打出来的不是同一个。本次实现的钳制阈值取 **3990 milli**，不贴 4.0 |

### F.2 补充（原文标 [缺口]，本次给出依据）

| # | 缺口 | 本次结论 | 证据强度 |
|---|---|---|---|
| 4 | §E #5 / §B.2.1：`ian.luma.env.k = 250000` 的公式与 `env.luma` 的绝对量纲 | `env.luma ≈ 250000 / ev`（`ev = 曝光行数 × 增益`）。把四个 gamma 断点 15.1 / 30.1 / 90.1 / 300.1 代入得 `ev = 16556 / 8306 / 2775 / 833`，**全部落在实际 ev 值域 `[8, 19904]` 内且分布合理** | **[反推，数值一致性]**。四个断点同时命中一个两位数量级的窗口，不像巧合，但 **⏳ 待实测确认**（判据：从明亮日光走到昏暗室内，四档里至少用得到两档） |
| 5 | §B.7.1：`use_gamma_param` 的确切分支行为 | JSON 里的 `y[16]` 与 `γ` **不自洽**：γ=0.5 那档在 `x = 16, 32, …` 栅格上应给出 `64, 90, 111, …`，而 JSON 里是 `0, 19, 35, …`；反解出的 x 也不是任何 2 的幂栅格。⇒ `y[16]` **不是**驱动 x 栅格上的采样，`use_gamma_param = true` 时**必须**用 γ 解析生成 | **[反推，排除法]**。加强了原文的判断 |
| 6 | §E #6 / §B.2.2：`ian.color_temp.bp` 的投影方式 | 用 `m_2` 二次拟合把 bg 投影回轨迹后，CCT 与实测 bg 算出的相差 **≤ 55 K**（16 点全验）⇒ CCT 实质上是 **rg 的单变量函数**。但该函数在 `rg > 0.78` 处**不单调**（2955 K → 3631 K 回折） | **[确证，数值]**。⇒ 本次实现不在运行期算多项式，改成 **16 点查表 + 提取期强制单调**（`rg = 0.7907` 的 CCT 由 3025 K 压到 3009 K，唯一的人工干预） |
| 7 | §E #4：`adn` / `aen` 各表在 `gain` 断点之间是否插值 | **仍是缺口**，但本次实现**决定不插值**：`adn.bf` 的模板是整数矩阵，插值无物理意义 | **[取舍，非确证]** |

### F.3 需注意（不是错，但实施时会踩）

| # | 事项 |
|---|---|
| 8 | §B.4 说 `sc202cs_abs_gain_val_map[]` 有 **197** 档（1000~63008）。`sc202cs.c` 里有**两份同名表**，由 `CONFIG_CAMERA_SC202CS_DIG_GAIN_PRIORITY` 二选一（`:73` 与 `:475`），长度分别是 197 / **192**。**跨文档引用增益表长度时必须说明是哪一份。** 另有 `sc202cs.c:1167` 的上游 off-by-one（增益下标会越界读） |
| 9 | §A.4 说统计通过「ISP 中断 + 回调」送出。补充一条实施细节：`esp_isp_awb_controller_get_oneshot_statistics()` 在 `timeout_ms = 0` 时**没用** —— 它会跳过等待、立刻 `isp_ll_awb_enable(false)`，统计根本来不及完成，回调也不会触发。（AE 的 oneshot 文档说 `timeout_ms = 0` 可以在回调里拿结果，**AWB 这条路走不通**。）⇒ AWB oneshot **必须给正的超时** |
| 10 | §A.3 说 LSC「门限是 rev ≥ 1.0」。补充：`esp_isp_lsc_allocate_gain_array()` 要求 `lsc_fsm == INIT` ⇒ **必须在 `esp_isp_lsc_enable()` 之前分配**；而 `esp_isp_lsc_configure()` **没有** FSM 门 ⇒ 取流中可重配（按 CCT 换档依赖这一点） |
| 11 | `esp_isp_bf_configure(proc, NULL)` 会在 `else` 分支之后**无条件**求值 `config->flags.update_once_configured` ⇒ 传 NULL 是**空指针解引用**，不是优雅的禁用。`sharpen` / `color` 同样的写法。**全程不许传 NULL** |
| 12 | AE / AWB 的 `intr_priority` 与处理器不一致时，驱动走的是 `ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, …)` —— 传给它的是一个**布尔值 1**，于是函数返回 `1` 而不是任何 `esp_err_t`。自检行会打出一个 `esp_err_to_name()` 认不出的码，**别往别处查** |
| 13 | 官方 LSC 表的增益值域实测为 **0.993 ~ 3.323（R 通道四角）**，而硬件 `isp_lsc_gain_t` 是 2 整数位 + 8 小数位 ⇒ 上限 3.996。**余量只有 17%**（定点 851 / 1023）。本文与审计文档都没提这个数，提取脚本必须带断言 |
| 14 | §A.3 说 Demosaic「可用、官方配」。补充：它已被 `output = RGB565` **隐式打开** ⇒ **只 `configure`、不 `enable`**，调 `enable` 会撞 FSM 门拿到 `INVALID_STATE`，让人误以为参数没配上 |
| 15 | §A.5（rev<3.0 无影子寄存器）在实现上的后果比原文写的更重：**每一个按增益/色温换档的画质级都必须自带迟滞**，否则 AE 在档位断点上抖一下就重配，会撕出「偶发横向亮带」。LSC 尤甚（273×2 条 LUT 写），本次实现给它的迟滞是别处的**两倍** |
| 16 | `esp_isp_gamma_fill_curve_points()` 实际用不了：它要函数指针（⇒ 运行期 `powf`），且它的 `y < 256` 检查会**拒掉以 256 归一的末点**。直接填算好的 `y[16]` 即可，但要满足驱动的两条硬要求：**每段段长必须是 2 的幂**、**末点 x 恰好 255** |
| 17 | 对比度 / 饱和度的 `val` 是 1 整数位 + 7 小数位 ⇒ **128 就是 1.0×**。标定文件里的 132 / 130 / 128 / 126 **就是这个 `val` 的原值，直接写、不做换算**（乘 1000 写进去会拿到 `INVALID_ARG`） |
| 18 | 统计窗口不写就是 `bsize = 0`（现场表现是「25 块全 0」/「16 个 bin 全 0」）。两个块的**窗口口径不同**：AE 的窗按 `SOC_ISP_AE_BLOCK_*_NUMS = 5` 分块（写 1280×720，整除）；**AWB 的窗是把四个坐标原样写进 `lpoint`/`rpoint` 的闭区间 ⇒ 要写 1279/719** |
