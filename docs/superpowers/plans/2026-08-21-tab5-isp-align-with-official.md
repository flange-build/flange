# Tab5 摄像头 ISP 向官方全面对齐 —— 实施计划（L1 结构 + L2 环路 + L3 参数）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `superpowers:subagent-driven-development` 逐任务实施。
> 步骤用 `- [ ]` 复选框跟踪。硬件在环：subagent 写码 + 容器外
> `. $HOME/esp/esp-idf/export.sh && idf.py build` 编译验证 + 宿主机 `cc` 跑纯逻辑测试；
> 烧板、看图、读自检行、host 侧 V4L2 验证由人工控制者做。
> **每个任务只引入一个变量**，判据不成立就先归因、不要往下走。

**Goal:** 把 Tab5 自研摄像头管线（SC202CS → CSI → ISP → PPA → JPEG → UVC）在**三层**上与 Espressif 官方（`esp_video` + `esp_ipa` + `sc202cs_default.json`）对齐：

- **L1 结构对齐** —— 补上官方配而我们没配、且 ESP32-P4 **rev v1.0** 可用的 ISP 级：
  **BF 去噪 / LSC 暗角 / Gamma / SHARP 锐化 / Color(对比度·饱和度) / Demosaic 梯度参数**。
- **L2 环路对齐** —— 控制环的**统计源与拓扑**改成与官方一致：AE 吃 ISP 硬件 5×5 分块统计
  （采样点 demosaic 后）、AWB 吃 ISP 硬件白点筛选统计（**采样点 CCM 之前**）、直方图用于
  背光检测与 gamma 选档。
- **L3 参数对齐** —— 消费官方标定数据 `sc202cs_default.json`：白点轨迹 → CCT 估计 →
  按色温选 CCM / LSC / 饱和度；按 gain 选 BF / SHARP / 对比度；按环境亮度选 Gamma。

**且不破坏任何一项已实机验证的能力**：GUD 显示、HID 键盘、HID 多点触摸、UAC1 音频（含硬件音量）、UVC 出图、AE 闭环。**USB 描述符 / 端点 / FIFO 一字不动。**

**Architecture:** 对齐后的管线（粗体 = 本计划新增，`[Tn]` = 由哪个任务引入）：

```
SC202CS RAW8 1280×720@30
   │
   ▼  MIPI-CSI 1 lane 576 Mbps（不动）
┌──────────────────────── ESP32-P4 ISP（rev v1.0）────────────────────────┐
│  BLC ❌不可用 → 改用**传感器自带 BLC(0x3902)** [T7]                        │
│  **BF**(按 gain 7 档) [T2] → **LSC**(273 格 ×4 通道) [T3][T13]            │
│  → Demosaic(**grad_ratio 按 gain 4 档**) [T2]  ──┬──▶ **AE 5×5 统计** [T5]│
│                                                  ├──▶ **HIST 16 bin** [T11]│
│                                                  └──▶ **AWB 白点统计** [T8]│
│  → CCM(**官方 19 档按 CCT 插值 + WB 折叠 + 强度钳制**) [T10]               │
│  → **Gamma**(4 档 γ) [T12] → RGB2YUV                                     │
│  → **SHARP**(按 gain 4 档) [T4] → **Color**(对比度按 gain / 饱和度按 CT) [T4][T13]│
│  → YUV2RGB → RGB565 out                                                  │
└───────────────────────────────────────────────────────────────────────────┘
   │
   ▼ PPA ×0.5 → 硬件 JPEG 4:2:2 → UVC ISO IN 0x84（**整段不动**）

控制环（全部在 uvc_stream.c 的 100 ms 帧泵里走一拍）：
  AE   ：硬件 5×5 亮度 →官方权重表 + 过暗/过亮块 quorum 剔除→ 传感器曝光/增益 [T6]
  AWB  ：硬件白点 sum_r/g/b（CCM 前）→ 绝对增益 kr=Σg/Σr, kb=Σg/Σb → CCM 折叠 [T9]
  CCT  ：kr/kb → rg=1/kr → 官方 16 点白点轨迹查表 → CCT(K) → 选 CCM/LSC/饱和度 [T10][T13]
  env  ：HIST 场景均值 + ev → env.luma → 选 gamma 档 [T12]；背光 → 切 AE 目标 [T12]
```

**Tech Stack:** ESP-IDF v6.0.2 内置 `esp_driver_isp`（`isp_bf` / `isp_lsc` / `isp_demosaic` / `isp_ccm` / `isp_gamma` / `isp_sharpen` / `isp_color` / `isp_ae` / `isp_awb` / `isp_hist`）+ `esp_driver_cam` + `esp_driver_ppa` + `esp_driver_jpeg`；托管组件仅 `espressif/esp_cam_sensor`（提供 SC202CS 寄存器序列与官方标定 JSON）。**不引入 `esp_video` / `esp_ipa`，`managed_components/` 保持 12 个目录。** 标定数据由宿主机 Python 脚本机械提取成 C 头文件；纯逻辑抽成不依赖 IDF 的函数 + 宿主机 `cc` 回归测试。

---

## 0. 依据与前提

本计划的**每一条**都可追溯到下面两份基线文档，正文用 `[官§x]` / `[审§x]` 标注：

| 标记 | 文档 |
|------|------|
| `[官§x]` | `docs/superpowers/research/2026-08-19-esp32p4-official-isp-pipeline.md`（官方管线重建，1465 行） |
| `[审§x]` | `docs/superpowers/research/2026-08-19-our-isp-pipeline-audit.md`（我们现状审计，481 行） |

工作树：`components/packages/tab5-all-in-one/firmware/`，分支 `main`（HEAD `801c10e1`）。
芯片：**ESP32-P4 rev v1.0**（`CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`）`[审§0]`。

**不做**（明确排除，避免范围蔓延）：

- 不引 `esp_video` / `esp_ipa`（硬约束 4）；不做 V4L2 / metadata device / IPA pipeline 那套分层。
- 不做 AF（SC202CS 定焦，无马达）`[审§A.3]`；不做 DPC / Median（IDF v6.0 无驱动 API）`[官§A.3]`。
- 不做 CROP（rev v1.0 静默 no-op）、WBG、ISP BLC（rev v1.0 直接 `ESP_ERR_NOT_SUPPORTED`）`[官§D.4]`。
- 不做 UVC 侧的 Processing Unit 控制、不改分辨率/帧率/描述符。
- 不做官方 `agc` 的两张权重加成表（`high_light_priority.weight_offset` 与
  `light_threshold_priority[5]`）——**触发条件与叠加方式闭源不可知** `[官§B.4.4 缺口]`，
  猜错的加权比不加权更坏。只取其中语义明确的 `luma_offset`（见 §E.2）。

---

## A. 三层目标 → 任务映射（自查表一）

| 层 | 目标项 | 任务 | 上板 |
|----|--------|------|------|
| L1 | BF 去噪 | T2 | ✅ |
| L1 | Demosaic 梯度参数 | T2 | ✅ |
| L1 | LSC 暗角 | T3（固定档） / T13（按 CT 选档） | ✅ |
| L1 | SHARP 锐化 | T4 | ✅ |
| L1 | Color 对比度 | T4 | ✅ |
| L1 | Color 饱和度 | T4（固定档） / T13（按 CT 选档） | ✅ |
| L1 | Color 色调 | **不做**：官方 SC202CS 标定里**没有 hue 字段** `[官§B.7]`，写 0 即对齐 | — |
| L1 | Gamma | T12 | ✅ |
| L2 | AE 硬件 5×5 分块统计（demosaic 后） | T5（观测） + T6（切换） | ✅ |
| L2 | AE 加权表 + 过暗/过亮块 quorum 剔除 | T6 | ✅ |
| L2 | AWB 硬件白点筛选统计 | T8（观测） + T9（切换） | ✅ |
| L2 | AWB 采样点设在 **CCM 之前** | T8 / T9 | ✅ |
| L2 | 直方图 → 背光检测 | T11（观测） + T12（用起来） | ✅ |
| L2 | 直方图 → gamma 选档 | T11 + T12 | ✅ |
| L3 | 白点轨迹 → CCT 估计 | T0（提取） + T10 | ✅ |
| L3 | 按色温选 CCM | T10 | ✅ |
| L3 | 按色温选 LSC | T13 | ✅ |
| L3 | 按色温选饱和度 | T13 | ✅ |
| L3 | 按 gain 选 BF | T2 | ✅ |
| L3 | 按 gain 选 SHARP / 对比度 | T4 | ✅ |
| L3 | 按亮度选 Gamma | T12 | ✅ |

---

## B. 七条硬约束 → 落实位置（自查表二）

| # | 硬约束 | 落实在哪 | 判据 |
|---|--------|----------|------|
| 1 | rev v1.0 上 BLC / WBG / CROP 不可用；**LSC 可用**（门 rev≥1.0） | 全程不调这三个 API；LSC 走 T3。T7 用**传感器自带 BLC** 顶替 ISP BLC | T3 的 `LSC=ESP_OK`；全程无 `ESP_ERR_NOT_SUPPORTED` |
| 2 | CCM 定点 S2.10，上限 4.0；官方 2292 K 档含 **4.5445**，本身就超限 | §D 的**强度参数 t 二分钳制**；`cam_ccm_fold_wb()` | T10 自检行打 `CCM 强度=t%`，且 `esp_isp_ccm_configure()` 恒 `ESP_OK` |
| 3 | 唯一那份 `sc202cs_default.json` 含 `acc.blc`，是为 rev≥3.0 标定的；CCM 行和为 1 的前提是 WB 由 WBG 做 | §D.1（行和不变式**被右乘保持**）+ §D.3（黑电平的三条处置）+ T7 实测 | T7 盖镜头实测黑电平；T10 白纸拍摄三通道均值差 <5% |
| 4 | 算法闭源，不引 `esp_ipa`/`esp_video`，依赖树保持 12 个目录 | 控制律全在 `cam_isp_map.c` / `cam_tune.c`（纯逻辑）；`main/CMakeLists.txt` 的 `aio_reqs` 只增不改类别 | 每个上板任务都跑一次 `ls managed_components \| wc -l` == **12** |
| 5 | 不破坏 GUD / HID 键盘 / HID 触摸 / UAC1（含硬件音量） / UVC 出图 / AE 闭环；USB 描述符一字不动 | 本计划**不碰** `usb_descriptors.*` / `tusb_config.h` / `uvc_stream.c` 的端点与提交逻辑 | 每个上板任务跑 `git diff --stat` 确认这三个文件为 0 改动；T14 做五项复合回归 |
| 6 | 摄像头不取流（alt 0）时零影响：统计块与算法都不跑 | 统计控制器在 `camera_csi_init()` 建、但 `start_continuous_statistics` / oneshot 触发**只在 `camera_csi_start()` 之后**；`camera_csi_stop()` 先停统计再 `esp_isp_disable()` | alt 0 下自检行 `AE统计=0 AWB统计=0 HIST=0`；`PSRAM 读 空载` 与改动前同量级 |
| 7 | 帧率 ≥ 9 fps，`拒收` 保持 0 | AWB 用 **oneshot**（约 35 ms 阻塞，1 秒一次）而非连续模式；LSC 重配只在 CT 档变化时做 | 每个上板任务读 `[自检] 缩放 … 实测 x.y fps` ≥ 9.0 且 `拒收=0` |

---

## C. 实现级陷阱 → 对应步骤（自查表三）

| 陷阱（基线已查证） | 出处 | 落实 |
|---|---|---|
| 三个统计块共用一个 ISP 中断，`intr_priority` 必须一致 | `[官§A.4]`；`isp_ae.c` 的 `ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, …)` | T5/T8：AE / AWB 的 `intr_priority` 一律填 **0**（= `ESP_INTR_FLAG_LOWMED`），与 `esp_isp_processor_cfg_t.intr_priority`（我们零初始化 ⇒ 也是 0）一致。**HIST 的 config 结构体根本没有这个字段**，不会冲突。⚠️ 冲突时驱动返回的是 **`1`（不是 esp_err_t）**，自检行会打成一个怪码，别以为是别的错 |
| rev v1.0 上 AWB 的 ISR **无条件**读 25 个 subwindow LUT（100 次寄存器往返 + 416 B ISR 内拷贝） | `[官§A.4/D.4]`；`isp_awb.c` 的 `esp_isp_awb_isr()` | T8：**AWB 只用 oneshot，绝不 `start_continuous_statistics()`**，1 秒触发一次；AE 用连续模式（它的 ISR 只有 25 次寄存器读，无 LUT） |
| 统计 window 全零能过参数校验但 `bsize=0`，拿到全 0 | `[官§C.10]`；`isp_hal_ae_window_config()` / `isp_hal_hist_window_config()` 都做 `/5` | T5/T11：AE 与 HIST 的 window 显式写 `{{0,0},{1280,720}}`（bsize = 256×144，整除）；AWB 主窗写 `{{0,0},{1279,719}}`（它不做除法，是绝对坐标） |
| 直方图 25 个权重之和必须**精确等于 256** | `[官§C.10]`；`s_esp_isp_hist_config_hardware()` 的 `weight_sum == 256` | T11：用 `16 + 24×10 = 256`（中心块 16，其余 24 块各 10）；RGB 系数用 `86/85/85 = 256`。⚠️ 三个 `integer` 域必须为 0，`segment_threshold` 必须**严格落在 (0,256)** —— 写 0 会被拒 |
| gamma 的 x 间隔必须是 2 的幂 | `[官§B.7.1]`；`esp_isp_gamma_configure()` 的校验 | T12：x 固定取 `16,32,…,240,255`（末段 `256-240=16`），与 `esp_isp_gamma_fill_curve_points()` 生成的栅格完全一致 |
| `esp_isp_ccm_configure()` 无 FSM 检查，取流中可随时重配 | `[审§A.2 级7]` | T10 的运行期重配沿用现有 `camera_ccm_apply()` 路径（只 configure、不再 enable）。**同理已核对：`esp_isp_bf_configure` / `sharpen` / `color` / `demosaic` / `lsc_configure` 也都没有 FSM 门**，取流中可重配；但 `esp_isp_lsc_allocate_gain_array()` **要求 `lsc_fsm == INIT`**，必须在 `esp_isp_lsc_enable()` 之前分配 |
| 无影子寄存器（rev<3.0），写入立即生效、无帧边界原子性 | `[官§A.5]` | 所有重配都低频（CCM ≤1 Hz、LSC 只在 CT 档跳变时、BF/SHARP/对比度只在 gain 档跳变时），且都带迟滞；自检行打出「本秒重配了几个块」，撕裂可归因 |
| 我们现有 AWB 公式**依赖统计采在 CCM 之后**（乘回 `cur` 才幂等）；采样点改到 CCM 前后公式必须跟着改 | `[审§B.1/B.4]` | **§E.3 专门处理**；T9 引入新函数 `cam_awb_step_hw()`，公式改成**绝对增益**（不乘 `cur`），旧函数 `cam_awb_step()` 原样保留给 `CAM_AWB_SOURCE=0` 的回退路径 |
| `esp_isp_bf_configure(proc, NULL)` 会解引用 `config->flags` | 本次实施新查（`isp_bf.c` 的 `config->flags.update_once_configured` 在 `else` 分支之后无条件求值） | 全程**不传 NULL**，一律传一份完整 config |

---

## D. 本计划最硬的一处：CCM 超 4.0 与「标定前提矛盾」的解法

### D.1 矛盾是什么

官方 `acc.ccm.table` 的 19 个矩阵，**每一行系数之和 ≈ 1.0** `[官§B.6.3]`。这个前提成立的条件是：**白平衡由 WBG 在 RAW 域先做掉**，进 CCM 的中性色已经是 `(1,1,1)`，CCM 只负责把传感器光谱响应映到 sRGB 而**不再改白点**。

我们没有 WBG（rev v1.0 不可用），只能照官方 rev<3.0 的降级路径把 R/B 增益**乘进 CCM 的第 0 列与第 2 列** `[官§C.8 源码确证]`：

```
P = M · W ,   W = diag(kr, 1, kb)
```

于是两件事同时发生：

1. **色度前提没有被破坏**（这是好消息，下面证明）；
2. **系数范围被破坏**（这是要解决的问题）。

### D.2 为什么「行和为 1」这个前提**被右乘保持**

传感器看到中性面时，demosaic 输出是 `w = (1/kr, 1, 1/kb)ᵀ · L`（这正是 `kr`/`kb` 的定义）。代入：

```
P · w = M · diag(kr,1,kb) · (1/kr, 1, 1/kb)ᵀ · L = M · (1,1,1)ᵀ · L = (行和, 行和, 行和)ᵀ · L = (1,1,1)ᵀ · L
```

**中性面出来仍然精确中性，且增益精确为 1。** 也就是说：把 WB 折进 CCM **不是**对官方标定前提的违反，恰恰是它的等价实现 —— 因为 WBG 与 demosaic 都是逐通道线性算子，二者可交换 `[官§A.3 反推]`。

> ⇒ **结论一：官方 CCM「行和为 1、由 WBG 保白」的前提，在我们把 WB 右乘进 CCM 之后依然成立，不需要重新标定、不需要归一化行和。** 真正被破坏的只有**定点范围**。

### D.3 但黑电平这一条**真的**被破坏了（必须单独处置）

上面的推导假设输入是纯乘性的。若 RAW 数据带一个**通道相等的黑电平基座 p**（官方 `acc.blc` 给的正是 `p = 16`，四个 Bayer 通道相同 `[官§B.6.1]`），而我们又用不了 ISP BLC：

```
P · (p,p,p)ᵀ = M · (p·kr, p, p·kb)ᵀ ≠ p·(1,1,1)ᵀ
```

代入 5040 K 的官方矩阵与典型增益 `kr=1.8, kb=1.85`、`p=16`，算出黑场偏移约 **(+23, −8, +21)** —— 一个肉眼可见的**品红色黑位**。（WB 把等值基座变成了不等值基座，CCM 的大负非对角项再把它放大。）

**三条处置，按优先级**：

1. **首选：打开传感器自带的 BLC。** SC202CS 的寄存器表里有一行被注释掉的
   `// {0x3902, 0x80}, // blc disable. 0xc0 enable` `[审§A.2 级3]` —— 也就是说这颗传感器**自己**有 BLC，只是我们没显式开也没显式关，停在上电默认。**T7 先实测**（盖住镜头读通道均值），基座 ≈ 0 就什么都不用做；基座 ≈ 16 就写 `0x3902 = 0xc0` 再测一次。这是对硬约束 3（"官方没给 rev<3.0 版本、`acc.blc` 我们用不了"）唯一**真正解决**而不是绕过的路。
2. **次选：统计侧软件 BLC。** 硬件 AWB 统计给出 `white_patch_num` 与 `sum_r/g/b`，可以精确地做
   `sum_x' = sum_x − p × white_patch_num`。这能修正**白点估计**（进而修正 kr/kb 与 CCT），但**修不了画面**。
3. **兜底：降 CCM 强度。** 若 1 和 2 都不成立，把 §D.4 的强度上限 `CAM_CCM_STRENGTH_MAX` 从 256 调小（例如 192 = 75%），黑位色偏按 t 线性缩小。

> ⇒ **结论二：`acc.blc` 那段数据我们不是"用不了"，而是"换个执行点用"** —— 数值 16 从 ISP BLC 挪到传感器 BLC（T7）或统计侧减法（T9 Step 5）。这份"为 rev≥3.0 标定的"数据里，除 `acc.blc` 之外的每一段（`ian` / `awb` / `agc` / `adn` / `acc.{ccm,lsc,saturation}` / `aen`）**都与 rev 无关**，官方三对 eco4/eco5 文件的一致交集也正是"rev<3.0 只删 `acc.blc` 一段" `[官§D.3]`。所以直接消费它是有据的，不是将就。

### D.4 系数超限的解法：**强度参数 t 的二分钳制**

先看问题有多大。用官方白点轨迹 `ian.color_temp.bp` 反推每个色温档上**物理自洽**的 `kr, kb`（`kr=1/rg`、`kb=1/bg`，见 §E.4），再算 `P = M·W` 的最大绝对系数：

| CT(K) | kr | kb | max\|M\| | max\|M·W\| | 需要的 t（可行上限） |
|-------|------|------|---------|-----------|------------------|
| 1200 | 1.138 | 3.444 | 1.000 | 3.444 | **1.00**（单位阵，钳位守卫） |
| **2292** | 1.138 | 3.441 | **4.545** | **15.639** | **0.04** |
| 2517 | 1.174 | 3.192 | 3.454 | 11.026 | 0.10 |
| 2780 | 1.219 | 2.944 | 2.919 | 8.593 | 0.18 |
| 3055 | 1.392 | 2.389 | 2.604 | 6.221 | 0.42 |
| 3473 | 1.483 | 2.229 | 2.215 | 4.936 | 0.65 |
| 3800 | 1.547 | 2.120 | 2.063 | 4.375 | 0.83 |
| 4193 | 1.607 | 2.006 | 2.084 | 3.915 | **1.00** |
| 4583 | 1.685 | 1.932 | 2.050 | 3.619 | **1.00** |
| 5040 | 1.786 | 1.858 | 2.060 | 3.680 | **1.00** |
| 5090 | 1.798 | 1.851 | 2.061 | 3.707 | **1.00** |
| 5210 | 1.826 | 1.830 | 2.026 | 3.700 | **1.00** |
| 5476 | 1.886 | 1.780 | 2.077 | 3.916 | **1.00** |
| 5770 | 1.965 | 1.738 | 2.012 | 3.953 | **1.00** |
| 6000 | 2.033 | 1.709 | 2.024 | 4.115 | 0.94 |
| 6554 | 2.224 | 1.648 | 1.906 | 4.239 | 0.88 |
| 7020 | 2.403 | 1.572 | 2.085 | 5.012 | 0.61 |
| 7265 | 2.522 | 1.546 | 2.134 | 5.381 | 0.51 |
| 12000 | 2.625 | 1.518 | 1.000 | 2.625 | **1.00** |

**读法**：**4193 K ~ 5770 K 这一整段（日常室内 + 日光的绝大多数）原样就装得下，一点不用钳。** 需要钳的是 <3800 K 的暖光端与 >6000 K 的冷光端，而 2292 K 那一档（含 4.5445，本身就超限）几乎退化成单位阵。

**钳制方式：不缩放矩阵，而是把矩阵朝单位阵混合。**

```
M(t) = (1−t)·I + t·M ,  t ∈ [0,1] ,  P(t) = M(t)·W
```

选**满足 `max|P(t)| ≤ 3.99` 的最大 t**。为什么是这个而不是"整体乘一个 α 缩小"：

| | 朝单位阵混合 M(t) | 整体缩放 α·M |
|---|---|---|
| 中性面还中性吗 | ✅ 精确（`M(t)` 行和恒为 `(1−t)+t·1 = 1`） | ✅ |
| 整体增益 | ✅ **精确为 1**，不损失一点亮度 | ❌ 变成 α，AE 要多加 1/α 的曝光或增益（2292 K 档 α=0.256 ⇒ **多 2 EV 噪声**） |
| 退化到底是什么 | **`t=0` ⇒ `P = diag(kr,1,kb)` = 今天已实机验证过的那条对角阵路径** | 一个更暗的画面 |
| 代价 | 色彩还原变弱（饱和度略低），单调、可解释 | 噪声，且在最暗的场景（低色温多半也暗）上加噪声 |

**`t=0` 恰好落回今天的行为**，这条连续性是选它的决定性理由：钳制的"最坏情况"就是"回到已验证状态"，不存在新的失败模式。

**可行域是区间、二分有效**：`P(t)` 的每个元素都是 t 的线性函数，`|线性|` 是凸函数，`max` 取凸函数的上包络仍是凸函数 ⇒ `{t : max|P(t)| ≤ B}` 是一个区间；而 `t=0` 必然可行（`max(kr,1,kb) ≤ 3.445 < 3.99`，见 §E.4 的增益范围），所以可行域是 `[0, t*]`，**二分查最大可行 t 是正确的**。

实现见 T1 的 `cam_ccm_fold_wb()`（8 次二分，全整数，宿主机可测）。自检行打 `CCM 强度=87%`，现场一眼看出这一帧的色彩还原被削了多少。

---

## E. 其余关键推导（每条都给数值依据）

### E.1 AE 的目标亮度为什么能直接用官方的 62

官方 `agc.luma_adjust.{target_low, target, target_high} = 56 / 62 / 64` `[官§B.4.1]`，量纲是 **8 bit**，测在 **`ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC`**（线性 RGB 亮度）`[官§C.6]`；硬件寄存器 `ae_b_mean` 就是 `uint8_t`（本次实施核对 `isp_struct.h:2290`）。

我们今天的 `CAM_AE_TARGET = 120` 测在 **ISP 输出**（CCM 之后、**无 gamma**）`[审§B.1]` —— 同样是线性域，但**多乘了一遍 CCM**，且是全画面均匀采样而非中心加权。两者不能直接互换，所以：

- **T6**（只换统计源）把目标改成 `120 × ρ`，ρ = T5 实测的「硬件加权均值 ÷ 软件全帧均值」。预估 ρ ≈ 0.79（CCM 对角阵 R×1.7/B×1.55 给亮度的增益 = `0.30×1.7 + 0.586×1 + 0.113×1.55 ≈ 1.27`，取倒数），**以实测为准**。
- **T12**（加 gamma）才把目标换成官方的 **56 / 62 / 64**。这两件事**必须同时改**：γ=0.605 时 `255×(62/255)^0.605 ≈ 110`，与今天的观感（线性域 120）接近；若只加 gamma 不改目标，`255×(120/255)^0.605 ≈ 152`，画面会明显过亮。

### E.2 `high_light_priority` 只取 `luma_offset`

官方 `agc.mode = "high_light_priority"`，该块含 `{low_threshold:119, high_threshold:202, weight_offset:5, luma_offset:−3}` `[官§B.4.4]`。其中 `luma_offset` 语义明确（把目标压低 3，保高光）；`weight_offset` 的触发与叠加方式是 **[缺口]**。

⇒ 我们只实现 `luma_offset`：`高光优先 ⇒ 目标 62−3 = 59`；`暗部优先 ⇒ 目标 62+1 = 63`（官方 `low_light_priority.luma_offset = +1`）。两个模式之间由 **T12 的背光判据**切换 —— 官方的模式选择器本身也是 [缺口]，我们用直方图给出一个**可解释**的选择器，并在自检行里打出来。

### E.3 采样点搬到 CCM 之前 ⇒ AWB 公式必须换（本计划最容易出错的一处）

| | 今天（`CAM_AWB_SOURCE=0`） | T9 之后（`=1`） |
|---|---|---|
| 统计在哪 | ISP 输出，**CCM 之后** | ISP 内部，**CCM 之前**（`ISP_AWB_SAMPLE_POINT_BEFORE_CCM`） |
| 反馈量 | 软件全帧 1/64 采样的 `r/g/b_mean` | 硬件白点筛选后的 `sum_r/g/b` + `white_patch_num` |
| 建议值公式 | `sug = cur × g_mean / chan_mean`（**必须乘 cur** 才幂等）`[审§B.4]` | `sug = Σg / Σchan`（**绝不能乘 cur**） |
| 是不是闭环 | 是。改 CCM 会改统计 ⇒ 阻尼/限幅是**环路稳定性**需要 | **否**。改 CCM 不影响统计 ⇒ 估计是开环前馈；阻尼/限幅只是**估计噪声的时域平滑** |
| 幂等性从哪来 | 靠公式里的 `cur` | 结构上自带（统计不随执行量变化） |

**若把旧公式原样搬到新采样点上，每一拍都会把已经生效的增益再乘一遍，增益单调发散直到撞上限位** —— 这是本计划最容易犯且现场最难归因的错（画面会缓慢变得越来越红/越来越蓝，而所有计数器都显示"正常更新中"）。

**防呆措施（必须做，不是可选）**：

1. 新公式写成**独立函数** `cam_awb_step_hw()`，签名收的是 `cam_awb_hw_stat_t`（`counted/sum_r/sum_g/sum_b`），**根本拿不到 `cur_r/cur_b`** —— 类型系统上就写不出乘 `cur` 的代码。
2. 旧函数 `cam_awb_step()` 与 `cam_awb_suggest()` **一行不改**，继续给 `CAM_AWB_SOURCE=0` 的回退路径用，并继续跑它原有的 281 个宿主机用例。
3. 宿主机测试加一条**发散判据**：把同一份 `sum_r/g/b` 连喂 200 拍，增益必须收敛到不动点并停住（`|Δ| = 0`）。旧公式若被误用，这条用例会立刻发散到限位。

### E.4 CCT 估计：把官方的三段数学**在提取期算完**，运行期只查表

官方链路是 `(rg,bg) → bp 轨迹投影 → McCamy 式三次多项式 → CCT` `[官§B.2.2]`。本次实施验证了两件事：

1. 用 `m_2` 的二次拟合把 bg 投影回轨迹后，CCT 与直接用实测 bg 算出的值**相差 ≤55 K**（16 个 bp 点全验）—— 说明 CCT 实际上是 **rg 的单变量函数**。
2. 但该函数在 `rg > 0.78` 处**不单调**（`rg=0.78 → 2955 K`，`rg=0.86 → 3631 K` 又拐回去），拿它做选档标量会在暖光端来回跳。

⇒ **我们不在运行期算多项式。** 提取脚本用官方公式在 16 个 `bp` 点上算出 CCT（`2289…7466 K`，`[官§B.2.2]` 的表可逐值核对），**强制成单调序列**后写成 `cam_cct_rg[16]` / `cam_cct_k[16]` 两张表；运行期只做「按 rg 线性插值 + 两端钳位」。

- 单调化只动一个点：`bp[1]=3025 K` 与 `bp[2]=3010 K` 之间有 15 K 的拟合噪声反转 `[官§B.2.2 原文已注明]`，脚本把 `bp[2]` 抬到 `3026 K`。这是**唯一**的人工干预，脚本里显式打印出来。
- 由 `bp` 反推的物理自洽增益范围：`kr = 1/rg ∈ [1.138, 2.625]`、`kb = 1/bg ∈ [1.518, 3.445]`。
  ⇒ `CAM_AWB_GAIN_MAX_MILLI` 从今天的 **3000 改成 3445**（今天的 3000 会在 2400 K 以下的白炽灯下把 B 增益顶住，表现为"暖光下永远偏黄"）。上限 3.445 < 4.0，CCM 的 `t=0` 退化路径永远可行（§D.4）。
- 白点筛选框直接用官方 `awb.range`：`rg ∈ [0.3801, 0.879]`、`bg ∈ [0.2903, 0.6587]`，亮度窗按官方桥接层的推导式 `[官§C.7]`
  `lum_max = 210×(1+0.879+0.6587) = 532.7`、`lum_min = 98×(1+0.3801+0.2903) = 164.7` ⇒ 取整 **[165, 533]**。
  ⚠️ 这三个框是官方在**未做 WB 的 raw 色度空间**里标的（`rg` 0.38~0.88 明显是未白平衡的值），与我们 `BEFORE_CCM` 的采样点**恰好同域**，可以直接用 —— 这也是"官方 rev<3.0 降级路径与我们同构"的又一处印证。

### E.5 `ian.luma.env.k = 250000` 的重建（基线标为 [缺口]，本次实施补上）

官方 gamma 用 `env.luma.avg` 选档，断点 `15.1 / 30.1 / 90.1 / 300.1`，且 300.1 远超 8 bit ⇒ 不是像素亮度 `[官§B.7.1]`。若取最自然的形式 `env ≈ k / ev`（`ev = 曝光行数 × 增益`，正是我们 `cam_ae_ev()` 的量），把 `k = 250000` 代入四个断点：

| 断点 env | 15.1 | 30.1 | 90.1 | 300.1 |
|---|---|---|---|---|
| 对应 ev | 16556 | 8306 | 2775 | 833 |

我们的 ev 值域是 **[8, 19904]**（`exp∈[8,1244]`，增益上限 16×）`[审§B.3]` —— **四个断点全部落在值域内**，且分布合理（833 = 明亮日光，16556 = 接近增益上限的暗场）。这个数值一致性太强，不像巧合。

⇒ 定义 `cam_env_luma_q1(ev, scene_mean) = 250000 × 10 × scene_mean / (CAM_AE_TARGET × ev)`（单位 1/10，AE 收敛时 `scene_mean ≈ target` ⇒ 退化成 `250000/ev`），断点用官方原值 `151 / 301 / 901 / 3001`，迟滞用官方 `luma_min_step = 3.0 ⇒ 30`。

`scene_mean` 取**直方图**的场景均值（近似均匀权重）而不是 AE 的中心加权均值 —— 这正是官方 `ian.luma.env.weight`（全 1）与 `agc.luma_adjust.weight`（中心加权金字塔）分成**两张表**的原因 `[官§B.4.2]`。

> ⚠️ 标为 **[反推，数值一致性]**，不是 [确证]。判据在 T11：AE 收敛后 `env` 应随环境光单调变化，且遮挡镜头时能跨过 151 那个断点。若实测发现 `env` 跑到 3001 以上或 15 以下（即四档只用得到一档），说明重建错了 ⇒ 回退到「按 `ev` 直接四分位选档」，gamma 仍然可用，只是断点变成我们自己定的。

---

## F. 新增/改动文件与回退矩阵

**新增**

| 文件 | 内容 | 谁用 |
|---|---|---|
| `test/isp_cal_extract.py` | 从 `managed_components/.../sc202cs_default.json` 机械提取 → 生成 `main/cam_isp_cal.h`；带 `--check` 复现校验 | T0，人工/CI |
| `main/cam_isp_cal.h` | 官方标定数据（只读常量表，约 **7.2 KB** flash） | `cam_isp_map.c` |
| `main/cam_isp_map.h` / `.c` | **纯逻辑**：gain 选档 / CCT 查表 / CCM 插值 + WB 折叠 + t 钳制 / AE 加权 + quorum / 直方图统计 / env.luma / gamma 选档。**不含任何 ESP-IDF 头** | `camera_csi.c`、宿主机测试 |
| `test/test_cam_isp_map.c` | 上述全部函数的宿主机回归（无框架，`main()` + `assert()`，直接编译真实源码） | T1 起每个任务都要跑 |

**改动**：`main/cam_tune.h`（新增开关与常量，逐个写取值理由）、`main/cam_tune.c`（新增 `cam_awb_step_hw()`）、`main/camera_csi.c`（IDF 侧的配置与统计管线）、`main/CMakeLists.txt`（加两个源文件）、`README.md`（T14）。

**不动**：`usb_descriptors.*`、`tinyusb_config/tusb_config.h`、`uvc_stream.c` 的端点与提交逻辑、`cam_jpeg.c`、`cam_frame_stats.{c,h}`、`display_dsi.c`、`codec_audio.c`、`kbd_*`、`touch_*`。

**回退矩阵（全部在 `cam_tune.h`，改一行 + 重编即可回到已验证状态）**

| 开关 | 默认 | =0 时回到 | 引入任务 |
|---|---|---|---|
| `CAM_ADN_ENABLE` | 1 | BF / demosaic 参数停在寄存器复位值（今天） | T2 |
| `CAM_LSC_ENABLE` | 1 | 不配 LSC（今天） | T3 |
| `CAM_AEN_ENABLE` | 1 | 不配 SHARP / Color（今天） | T4 |
| `CAM_AE_SOURCE` | 1 | AE 吃软件全帧均值（今天） | T6 |
| `CAM_SENSOR_BLC_ENABLE` | 由 T7 实测定 | 不写 `0x3902`（今天） | T7 |
| `CAM_AWB_SOURCE` | 1 | AWB 吃软件灰世界（今天，281 用例已覆盖） | T9 |
| `CAM_CCM_MODE` | 1 | CCM 用对角阵 `diag(kr,1,kb)`（今天） | T10 |
| `CAM_CCM_STRENGTH_MAX` | 256 | 调小 ⇒ 全局压低色彩还原强度（黑位色偏、噪声放大的总闸） | T10 |
| `CAM_HIST_ENABLE` | 1 | 不建直方图控制器 | T11 |
| `CAM_GAMMA_ENABLE` | 1 | 不配 gamma，输出仍是线性域（今天） | T12 |
| `CAM_GAMMA_ADAPTIVE` | 1 | gamma 钉在 `CAM_GAMMA_SLOT_FIXED` 档 | T12 |
| `CAM_BACKLIGHT_ENABLE` | 1 | AE 目标恒为高光优先档 | T12 |
| `CAM_LSC_BY_CT` / `CAM_SAT_BY_CT` | 1 | LSC / 饱和度钉在中间档 | T13 |

---

## G. 每个任务的通用收尾（**每个上板任务都要做，不再逐条重复**）

- [ ] `. $HOME/esp/esp-idf/export.sh && idf.py build` 通过，**无新增 warning**
- [ ] `cd test && cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_isp_map.c ../main/cam_isp_map.c -o /tmp/t && /tmp/t` 打印 `OK (N cases)`
- [ ] `cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_tune.c ../main/cam_tune.c -o /tmp/t2 && /tmp/t2` 仍然全过（**281 用例一条都不许掉**）
- [ ] `python3 test/check_usb_desc.py build/tab5_aio.elf` → OK（描述符没被误伤）
- [ ] `ls managed_components | wc -l` == **12**（硬约束 4）
- [ ] `git diff --stat` 里**没有** `usb_descriptors.*` / `tusb_config.h`（硬约束 5）
- [ ] 烧板后读自检行：`实测 fps ≥ 9.0`、`拒收=0`、`编码 失败=0`、`缩放 失败=0`（硬约束 7）
- [ ] alt 0（host 不开摄像头）下静置 30 s：新加的统计计数器**全部不涨**（硬约束 6）
- [ ] GUD 显示无撕裂/花屏，HID 键盘与触摸可用，`aplay`/`arecord` 可用（硬约束 5 的快速版；完整回归在 T14）

---

## Task 0：标定数据提取脚本 + `cam_isp_cal.h`（**不上板**，纯宿主机）

目标：把 234 KB 的官方标定 JSON 里**我们真正要用的那一小部分**机械提取成一个可复现、可核对、注明来源与许可的 C 头文件。做法照本仓已有的两个先例：`main/panel_init_data.h`（从 esp-bsp 逐字节搬 + 注明来源）与 `main/tab5_kbd_map.h`（脚本抽取 + 逐字节 diff 核对）。

**Files:** Create `test/isp_cal_extract.py`, `main/cam_isp_cal.h`

- [ ] **Step 1：成功判据**

1. `python3 test/isp_cal_extract.py --check` 打印 `OK: main/cam_isp_cal.h 与 JSON 一致（md5 0f32b06f…）` 并以 0 退出；
2. 故意改 `cam_isp_cal.h` 里任意一个数字，`--check` 必须**失败**并打出 diff；
3. 头文件里**每一张表**都能在 JSON 里找到对应字段路径（脚本把路径写进注释）；
4. 头文件总字节数 ≈ **7.2 KB**（`ls -l`），其中 LSC 占 6552 B。

- [ ] **Step 2：先确认源文件在位并核对指纹**

```bash
cd components/packages/tab5-all-in-one/firmware
ls -l managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/sc202cs_default.json
md5 -q managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/sc202cs_default.json
# 期望：234332 字节，md5 = 0f32b06f7201d8cbee993126fd2ff277
```

> ⚠️ `managed_components/` 在 `.gitignore` 里（`firmware/.gitignore:3`）——**JSON 不在仓库里**。
> 所以：**生成物 `cam_isp_cal.h` 必须提交**，脚本只是它的"可复现证明"，跑脚本的前提是先
> `idf.py build` 拉过组件。这与 `panel_init_data.h`（esp-bsp 也没 vendored）的处置完全一致。

- [ ] **Step 3：`test/isp_cal_extract.py`**

脚本骨架（**关键在于每张表都从 JSON 字段路径直接取，不允许出现任何手抄的数字**）：

```python
#!/usr/bin/env python3
"""
从 espressif/esp_cam_sensor 的官方 SC202CS 标定文件机械提取 ISP 参数，生成
main/cam_isp_cal.h。**不手抄任何数字**：每一张表都由本脚本从 JSON 字段路径读出。

用法:
  python3 test/isp_cal_extract.py            # 生成/覆盖 main/cam_isp_cal.h
  python3 test/isp_cal_extract.py --check    # 只校验：重新生成到内存并与磁盘上的比对

源文件指纹在下面写死。上游换版本 ⇒ 指纹对不上 ⇒ 脚本拒绝运行，
逼人去看 CHANGELOG 而不是默默生成一份不同的表（tab5_kbd_map.h 那轮的教训）。
"""
import hashlib, json, math, os, sys, difflib

SRC = ("managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/"
       "sc202cs_default.json")
SRC_MD5  = "0f32b06f7201d8cbee993126fd2ff277"
SRC_SIZE = 234332
OUT = "main/cam_isp_cal.h"

# 选进固件的 LSC 色温档（9 档全带 = 19656 B；这 3 档 = 6552 B）。
# 取舍依据见头文件注释与计划 §T0 Step 5。
LSC_CTS = (2410, 5210, 8200)

def load():
    raw = open(SRC, "rb").read()
    md5 = hashlib.md5(raw).hexdigest()
    if md5 != SRC_MD5 or len(raw) != SRC_SIZE:
        sys.exit(f"源文件指纹不符：{len(raw)} B / {md5}\n"
                 f"期望：{SRC_SIZE} B / {SRC_MD5}\n"
                 f"上游改过标定文件，先读 esp_cam_sensor 的 CHANGELOG，再改本脚本的指纹。")
    return json.loads(raw)["SC202CS"], md5
```

- [ ] **Step 4：各段的提取规则（逐段写，每段一个 `emit_*` 函数）**

| 段 | JSON 路径 | 输出 C 符号 | 定点/单位 | 字节 |
|---|---|---|---|---|
| BF | `.adn.bf[*]` | `cam_cal_bf[7]` = `{gain_milli, level, matrix[9]}` | gain ×1000；level 原值（2~20）；matrix 原值 | 77 |
| Demosaic | `.adn.demosaic[*]` | `cam_cal_demosaic[4]` = `{gain_milli, grad_ratio_milli}` | ×1000（1500/1250/1050/1000） | 8 |
| SHARP | `.aen.sharpen[*]` | `cam_cal_sharpen[4]` = `{gain_milli, h_thresh, l_thresh, h_coeff_milli, m_coeff_milli, matrix[9]}` | 系数 ×1000 | 56 |
| 对比度 | `.aen.contrast[*]` | `cam_cal_contrast[4]` = `{gain_milli, val}` | val 原值（132/130/128/126，**128 = 1.0×**） | 8 |
| 饱和度 | `.acc.saturation[*]` | `cam_cal_saturation[2]` = `{cct_k, val}` | 同上（128/130） | 4 |
| Gamma | `.aen.gamma.table[*]` | `cam_cal_gamma_luma_q1[4]`、`cam_cal_gamma_y[4][16]` | 断点 ×10（151/301/901/3001）；y 由脚本按 `y=round(255·(x/255)^γ)` 在 `x=16,32,…,240,255` 上算出 | 8+64 |
| CCM | `.acc.ccm.table[*]` | `cam_cal_ccm_cct[19]`、`cam_cal_ccm[19][9]` | 系数 ×1000（`int16_t`，2292 档的 4545 装得下） | 38+342 |
| CCT 轨迹 | `.ian.color_temp.{bp,g}` | `cam_cal_cct_rg[16]`（×10000，升序）、`cam_cal_cct_k[16]`（降序） | 见 §E.4：脚本用官方 McCamy 式算 CCT 并强制单调 | 64 |
| 白点框 | `.awb.range`、`.awb.min_counted` | `CAM_CAL_RG_MIN/MAX`、`CAM_CAL_BG_MIN/MAX`（×10000）、`CAM_CAL_LUM_MIN/MAX`、`CAM_CAL_MIN_COUNTED` | 亮度窗按 `[官§C.7]` 的推导式算出 165/533 | — |
| AE 权重 | `.agc.luma_adjust.weight[25]` | `cam_cal_ae_weight[25]` | 原值（金字塔 1..4） | 25 |
| AE 阈值 | `.agc.luma_adjust.{low,high}_{threshold,regions}`、`.target*` | `CAM_CAL_AE_*` 一组宏 | 原值（14/5/239/3/56/62/64） | — |
| 优先级偏移 | `.agc.{high,low}_light_priority.luma_offset` | `CAM_CAL_AE_HL_OFFSET`(−3) / `CAM_CAL_AE_LL_OFFSET`(+1) | 原值 | — |
| env 归一化 | `.ian.luma.env.k`、`.aen.gamma.luma_min_step` | `CAM_CAL_ENV_K`(250000)、`CAM_CAL_GAMMA_MIN_STEP_Q1`(30) | 原值 | — |
| LSC | `.acc.lsc.table[ct∈LSC_CTS].calibrations_{r,gr,gb,b}_tbl` | `cam_cal_lsc[3][4][273]`（`uint16_t`，2.8 定点） | `round(v·256)`，脚本断言 `< 1024`（硬件 2 整数位 + 8 小数位） | 6552 |

CCT 轨迹那段的**完整**实现（这是全脚本唯一有数学的地方，必须写死在脚本里而不是手算）：

```python
def emit_cct_locus(s, out):
    ct = s["ian"]["color_temp"]
    g  = ct["g"]                                   # McCamy epicentre 取负 + 三次多项式
    pts = []
    for bp in ct["bp"]:                            # bp[0] rg 最大(暖) … bp[15] rg 最小(冷)
        rg, bg = bp["a0"], bp["a1"]
        n = (rg + g["a0"]) / (bg + g["a1"])        # n = (rg-0.332)/(bg-0.1858)
        a = g["a2"]
        k = ((a[0]*n + a[1])*n + a[2])*n + a[3]
        pts.append((rg, k))
    pts.sort(key=lambda p: p[0])                   # 按 rg 升序 ⇒ CCT 降序
    # 强制单调：bp[1]/bp[2] 之间有 15 K 的拟合噪声反转（官方文档 §B.2.2 已注明）
    fixed = []
    for i, (rg, k) in enumerate(pts):
        if i and k >= fixed[-1][1]:
            k = fixed[-1][1] - 1
            print(f"  [单调化] rg={rg:.4f} 的 CCT 被压到 {k:.0f} K", file=sys.stderr)
        fixed.append((rg, k))
    out.append("/* 官方白点轨迹 .ian.color_temp.bp（16 点）→ CCT。rg 升序、CCT 降序。 */")
    out.append("static const uint16_t cam_cal_cct_rg[16] = {" +
               ", ".join(str(round(rg*10000)) for rg, _ in fixed) + "};")
    out.append("static const uint16_t cam_cal_cct_k[16] = {" +
               ", ".join(str(round(k))        for _, k  in fixed) + "};")
```

跑出来应当是（**实施时用这组数核对脚本**，两边不一致就是脚本写错了）：

```
rg  : 3810 4077 4186 4286 4435 4553 4766 5000 5267 5512 5846 6210 6562 7231 7907 8790
CCT : 7466 7121 6989 6854 6644 6473 6204 5892 5531 5157 4701 4215 3644 3025 3024 2289
                                                                              ^^^^ 单调化后（原 3010→3024）
```

- [ ] **Step 5：LSC 为什么只取 3 档**

实测三档之间的差（脚本会打印）：

```
r  通道：max|2410 − 8200| = 0.711    gr/gb/b 三通道：≤ 0.203
r  通道：max|2410 − 5210| = 0.357    max|5210 − 8200| = 0.354
LSC 增益值域：中心恒为 1.000，四角 2.60 ~ 3.32（R 通道最大 3.323）
```

- 只有 R 通道随色温有明显差异，取 `2410 / 5210 / 8200` 三档后**最大残差 ≈ 0.36**，落在一个 ~3× 的提亮上 ≈ 12%，在四角、且被后面的 CCM/AWB 部分吸收 ⇒ 看不出来。
- 9 档全带是 19656 B 且每次切换要写 273×2 条 LUT 命令；3 档 6552 B。
- **`LSC_CTS` 是脚本顶部的一个常量**，将来要全带 9 档只改这一行重跑。

⚠️ 脚本必须断言 `round(v*256) < 1024`（硬件 `isp_lsc_gain_t` 是 2 整数位 + 8 小数位，最大 3.996）。实测最大 3.323 ⇒ 850，通过，但**余量只有 20%**：将来换标定文件时这条断言是唯一的守门人。

⚠️ 表的排布：驱动按 `i = y*num_grids_x + x` 写 LUT（`isp_lsc.c:76-83`），`num_grids_x = (1280−1)/2/32+2 = 21`、`num_grids_y = (720−1)/2/32+2 = 13`，`21×13 = 273` 与 `lsc_tbl_size` 精确相等 `[官§B.6.4]`。**JSON 里 273 个数的排布顺序（x 快变还是 y 快变）是 [缺口]**，脚本按 `x` 快变原样搬运；T3 上板时若出现"暗角修正方向是横竖颠倒的"（画面上下亮、左右暗），把脚本里的转置开关打开重跑 —— 这是 T3 明确列出的两个失败归因之一。

- [ ] **Step 6：`--check` 模式**

```python
def main():
    s, md5 = load()
    text = build_header(s, md5)                    # 纯函数：JSON → 完整头文件文本
    if "--check" in sys.argv:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            sys.stdout.writelines(difflib.unified_diff(
                cur.splitlines(True), text.splitlines(True),
                fromfile=OUT + "（磁盘）", tofile=OUT + "（由 JSON 重新生成）"))
            sys.exit(f"FAIL: {OUT} 与 JSON 不一致，请重跑 python3 {sys.argv[0]}")
        print(f"OK: {OUT} 与 JSON 一致（md5 {md5}）")
        return
    open(OUT, "w").write(text)
    print(f"已生成 {OUT}（{len(text)} 字节，源 md5 {md5}）")
```

- [ ] **Step 7：头文件的头部注释（照 `panel_init_data.h` / `tab5_kbd_map.h` 的规格）**

```c
#pragma once
/*
 * SC202CS 官方 ISP 标定数据（节选）。
 *
 * ⚠️ **本文件由 test/isp_cal_extract.py 机械生成，不要手改。**
 *    改了就跑 `python3 test/isp_cal_extract.py --check`，它会失败并打出 diff。
 *
 * 来源：espressif/esp_cam_sensor 2.4.0
 *       sensors/sc202cs/cfg/sc202cs_default.json
 *       234332 字节，md5 0f32b06f7201d8cbee993126fd2ff277
 * SPDX-FileCopyrightText: Espressif Systems (Shanghai) CO LTD
 * SPDX-License-Identifier: Apache-2.0   （随组件 LICENSE，Apache-2.0）
 *
 * ⓘ 该 JSON 在上游只被 esp_ipa 的构建期代码生成器消费，而本工程**不引 esp_ipa**
 *   （依赖树要保持 12 个目录），所以自带这个提取脚本。**只提取用得到的部分**：
 *   234 KB 里绝大多数是 LSC 的 9 档 × 4 通道 × 273 格浮点，我们只带 3 档 ⇒ 7.2 KB。
 *
 * ⓘ 这份标定是为 **rev ≥ 3.0** 做的（含 acc.blc 段，而 rev v1.0 的 ISP BLC 不可用）。
 *   官方三对 eco4/eco5 文件的一致交集表明：rev<3.0 的降级动作**只有删掉 acc.blc 一段**，
 *   其余各段与芯片版本无关（依据见 2026-08-19-esp32p4-official-isp-pipeline.md §D.3）。
 *   acc.blc 的数值 16 没有丢，它挪到了传感器自带 BLC 与统计侧减法上，见 cam_tune.h。
 *
 * ⓘ 未提取的段及理由：
 *     acc.blc          rev v1.0 的 ISP BLC 用不了，改由传感器侧处理（cam_tune.h）
 *     agc.anti_flicker 我们不做抗工频闪烁（曝光时间未量化到 10 ms 整数倍）
 *     ian.luma.env.speed_param  16 抽头 FIR 的滑动索引是 [缺口]，我们用一阶低通替代
 *     awb.model / acc.*.model   取值枚举闭源不可知，用不上
 *     af / atc                  SC202CS 定焦、且不用传感器自带 AE
 */
```

- [ ] **Step 8：提交前自查**

```bash
python3 test/isp_cal_extract.py            # 生成
python3 test/isp_cal_extract.py --check    # 必须 OK
sed -i '' 's/2060/2061/' main/cam_isp_cal.h && python3 test/isp_cal_extract.py --check   # 必须 FAIL
python3 test/isp_cal_extract.py            # 复原
ls -l main/cam_isp_cal.h                   # ≈ 7.2 KB 数据 + 注释
```

---

## Task 1：`cam_isp_map.{c,h}` + 宿主机测试（**不上板**，本计划的算法本体）

目标：把 L2/L3 的**全部**算法写成不依赖 ESP-IDF 的纯函数并逐条测到。先例：`cam_tune.c`（281 用例）、`cam_frame_stats.c`（24 用例）。**这一步之后，上板任务里就只剩"把结果喂给 IDF API"的胶水代码。**

**Files:** Create `main/cam_isp_map.h`, `main/cam_isp_map.c`, `test/test_cam_isp_map.c`; Modify `main/CMakeLists.txt`

- [ ] **Step 1：成功判据**

`cc -std=c11 -Wall -Wextra -Werror -I../main test_cam_isp_map.c ../main/cam_isp_map.c -o /tmp/t && /tmp/t` 打印 `OK (N cases)`，N ≥ 90。

- [ ] **Step 2：`cam_isp_map.h` 的接口**

```c
#pragma once
/*
 * 官方标定数据的**运行期消费逻辑**：查表 / 插值 / 折叠 / 钳制 / 统计归约。
 * **纯逻辑，不含任何 ESP-IDF 头**，宿主机 cc 一下就能跑（test/test_cam_isp_map.c）。
 *
 * 与 cam_tune.h 的分工：
 *   cam_tune.h   控制律（AE 的 P 控制器、AWB 的阻尼/限幅/防护）与**全部可调参数**
 *   cam_isp_map  官方标定表的解释器 —— 输入是工作点（gain / CCT / env.luma），
 *                输出是某一级 ISP 的参数。它自己**不含任何可调参数**，
 *                改行为一律去 cam_tune.h 改开关，别改这里的表（表是 cam_isp_cal.h，机械生成的）。
 */
#include <stdint.h>
#include <stdbool.h>

/* ── 按传感器总增益选档 ─────────────────────────────────────────────
 * 语义照官方：表按 gain 升序排，取「gain 不超过当前总增益的最大一档」。
 * ⓘ 官方表在断点之间是否插值是 [缺口]（官方管线文档 §C.9）。我们**不插值** ——
 *   BF 的 matrix[9] 与 SHARP 的 matrix[9] 是整数模板，插值出来的中间值没有物理意义。
 * 返回下标，恒落在 [0, n-1]。gain_milli 小于第 0 档时返回 0。 */
uint32_t cam_map_gain_slot(const uint16_t *gain_breaks, uint32_t n, uint32_t gain_milli);

/* ── 按色温选档（升序表）+ 是否落在两档之间的插值权重 ──────────────
 * 返回下标 i，使 tbl[i] <= cct <= tbl[i+1]；*w_q8 是 cct 在 [i,i+1] 上的位置（0..256）。
 * 越界时钳到端点并令 w=0。 */
uint32_t cam_map_cct_slot(const uint16_t *cct_tbl, uint32_t n, uint32_t cct_k, uint32_t *w_q8);

/* ── rg → CCT（官方 16 点轨迹，线性插值，两端钳位）────────────────
 * rg_q4 = (Σr/Σg) × 10000。返回开尔文，恒落在 [cam_cal_cct_k[15], cam_cal_cct_k[0]]。 */
uint32_t cam_cct_from_rg(uint32_t rg_q4);

/* ── CCM：按 CCT 在官方 19 档间逐元素线性插值 ───────────────────── */
void cam_ccm_at_cct(uint32_t cct_k, int32_t out_milli[9]);

/*
 * ── CCM：把白平衡增益折进矩阵，并把系数钳进 rev v1.0 的 S2.10（±4.0）───
 *
 *   P(t) = ((1−t)·I + t·M) · diag(kr, 1, kb)
 *
 * 取满足 max|P(t)| <= CAM_CCM_ABS_MAX_MILLI 的**最大** t（8 次二分，t 以 1/256 计）。
 * 完整推导见计划 §D.4。三条不变式（宿主机测试逐条守着）：
 *   ① 任意 t，M(t) 的行和恒为 1000 ⇒ 中性面出来仍精确中性、增益精确为 1；
 *   ② t = 0 ⇒ P = diag(kr,1,kb)，正是本改动之前已实机验证的那条路径 ⇒ 钳到底也不会更坏；
 *   ③ kr/kb 被调用方钳在 [1000, 3445] ⇒ t=0 必然可行 ⇒ 二分不会失败。
 * 返回实际采用的 t（0..256）。
 */
uint32_t cam_ccm_fold_wb(const int32_t m_milli[9], uint32_t kr_milli, uint32_t kb_milli,
                         int32_t out_milli[9]);

/* ── AE：25 块 → 加权均值（官方权重表）+ 过暗/过亮块 quorum 剔除 ────
 * n_dark  = 亮度 <  CAM_CAL_AE_LOW_THRESH(14)  的块数
 * n_bright= 亮度 >  CAM_CAL_AE_HIGH_THRESH(239) 的块数
 * 只有当 n_dark >= 5（官方 low_regions）或 n_bright >= 3（high_regions）时才**剔除**
 * 对应的块 —— 官方是"计数达标才进保护分支"，不是每块都挑。
 * 全被剔除（wsum==0）时退回 25 块的**无权算术平均**，保证永远给得出一个数。 */
uint8_t cam_ae_weighted_mean(const uint8_t lum[25], uint8_t *n_dark, uint8_t *n_bright);

/* ── 直方图 16 bin → 场景均值 / 亮块占比 / 暗块占比（百分数）───────
 * bin i 覆盖 [16i, 16i+15]，取中心 16i+8 作代表值。total==0 时全部输出 0。 */
void cam_hist_stats(const uint32_t bins[16], uint8_t *mean, uint8_t *bright_pct, uint8_t *dark_pct);

/* ── env.luma 重建（单位 1/10）：250000 × scene_mean /(target × ev) ──
 * 依据见计划 §E.5（[反推，数值一致性]，非确证）。ev==0 时返回 0。 */
uint32_t cam_env_luma_q1(uint32_t ev, uint8_t scene_mean, uint8_t ae_target);

/* ── gamma 选档（4 档，带官方 luma_min_step=3.0 的迟滞）────────────
 * cur_slot 传当前档，返回新档。只有越过断点且超出迟滞带才换档。 */
uint32_t cam_gamma_slot(uint32_t env_q1, uint32_t cur_slot);
```

- [ ] **Step 3：`cam_ccm_fold_wb()` 的实现（本计划最关键的 30 行）**

```c
/* 硬件 S2.10 的表达上限是 4095/1024 = 3.9990；留一档量化余量 ⇒ 3990。
 * esp_isp_ccm_configure() 的范围检查是闭区间 [-4.0, 4.0]（isp_ccm.c:25-31），
 * 但 hal_utils_float_to_fixed_point_32b() 在 saturation=false 时会对 4.0 报错，
 * 所以**不能贴着 4.0 走**，也不能指望 saturation=true 兜底——那等于让硬件
 * 悄悄改我们的矩阵，而我们的自检行还在打原值。 */
#define CAM_CCM_ABS_MAX_MILLI  3990

static bool ccm_fold_at(const int32_t m[9], uint32_t kr, uint32_t kb,
                        uint32_t t_q8, int32_t out[9])
{
    bool ok = true;
    for (int i = 0; i < 9; i++) {
        const int32_t eye = (i % 4 == 0) ? 1000 : 0;              /* 单位阵在 0/4/8 */
        const int32_t mt  = eye + (int32_t)(((int64_t)(m[i] - eye) * (int64_t)t_q8) / 256);
        const uint32_t k  = (i % 3 == 0) ? kr : ((i % 3 == 2) ? kb : 1000u);
        const int32_t v   = (int32_t)(((int64_t)mt * (int64_t)k) / 1000);
        if (v > CAM_CCM_ABS_MAX_MILLI || v < -CAM_CCM_ABS_MAX_MILLI)
            ok = false;
        if (out)
            out[i] = v;
    }
    return ok;
}

uint32_t cam_ccm_fold_wb(const int32_t m[9], uint32_t kr, uint32_t kb, int32_t out[9])
{
    /* 可行域是 [0, t*]（|线性| 是凸的，max 取上包络仍凸；且 t=0 必然可行，
     * 因为调用方把 kr/kb 钳在 [1000, 3445] ⊂ [0, 3990]）⇒ 二分有效。 */
    uint32_t lo = 0, hi = 256;
    while (lo < hi) {
        const uint32_t mid = (lo + hi + 1) / 2;
        if (ccm_fold_at(m, kr, kb, mid, NULL))
            lo = mid;
        else
            hi = mid - 1;
    }
    ccm_fold_at(m, kr, kb, lo, out);
    return lo;
}
```

- [ ] **Step 4：`test/test_cam_isp_map.c` 的用例分组（N ≥ 90）**

| 组 | 用例 | 判据 |
|---|---|---|
| A. gain 选档（8） | 低于首档 / 恰在断点 / 断点之间 / 高于末档 / n=1 / 空表 | 返回下标恒在 `[0,n-1]`；恰在断点取该档 |
| B. CCT 选档 + 插值权重（8） | 越界两端 / 恰在档上 / 5040↔5090 这对 50 K 间距 | `w_q8 ∈ [0,256]`，端点 `w=0` |
| C. `cam_cct_from_rg`（10） | 16 个 bp 点逐点回代 / 两端外推 / 单调性扫描（rg 从 3000 扫到 9500，步长 1） | 每个 bp 点误差 ≤ 1 K；**全程单调非增**（这条是 §E.4 的整个理由） |
| D. CCM 插值（8） | 1200 K 与 12000 K 取到单位阵 / 5040 与 5090 之间中点 / 每档行和 ≈ 1000±3 | **19 档逐档验行和** ∈ [985, 1015] |
| E. **CCM 折叠 + 钳制（20，本组最重要）** | 见下 | 见下 |
| F. AE 加权 + quorum（12） | 全均匀 / 单块极亮 / 4 块暗（未达 quorum，不剔除） / 5 块暗（达标，剔除） / 3 块亮（达标） / 25 块全暗（退回无权平均） | 剔除前后的均值差符合手算；`n_dark`/`n_bright` 计数正确 |
| G. 直方图归约（8） | 全零 / 单 bin / 均匀 / 全在末 bin | `mean` 在 `[8,248]`；`bright_pct + dark_pct <= 100` |
| H. env.luma + gamma 选档（12） | `ev=833/2775/8306/16556` 恰好落在四个官方断点上 / 迟滞：在断点 ±2.9 内来回不换档、±3.1 换档 / `ev=0` | 断点处档位与官方 `.aen.gamma.table` 顺序一致；迟滞不抖 |
| I. 溢出与除零（6） | `sum_g=0` / `kr=0` / 全零 25 块 / `bins` 全零 | 不崩、不除零、给出文档承诺的兜底值 |

E 组（CCM 折叠）必须覆盖的**六条**：

1. **行和不变式**：对 19 档 × t∈{0,64,128,192,256} × 三组 (kr,kb)，`M(t)` 的行和恒 = 1000（±2 量化）。
2. **中性面不变式**：`P · (1e6/kr, 1000, 1e6/kb)ᵀ / 1000` 三个分量彼此相差 ≤ 1%（即中性还是中性、增益还是 1）。
3. **范围不变式**：任意输入下 `max|out| <= 3990`。
4. **t=0 退化**：`kr=3445, kb=3445` 且 M 取 2292 K 那档 ⇒ 返回 `t=0`，且 `out == diag(3445, 1000, 3445)`（**这就是回退路径，必须逐元素相等**）。
5. **t=256 直通**：`kr=1786, kb=1858` + 5040 K 档 ⇒ 返回 `t=256`（§D.4 表里这一档 `max|MW| = 3.680 < 3.99`）。
6. **单调性**：t 增大时 `max|P(t)|` 非减（用 257 个 t 值扫一遍）—— 这条守着二分的前提。

- [ ] **Step 5：接进构建**

`main/CMakeLists.txt` 的 `aio_srcs` 追加 `"cam_isp_map.c"`。**此时它还没有调用者**，只保证能编译进去（`-Werror` 下未使用的 static 函数会告警 ⇒ 全部非 static 导出，或加 `(void)` 引用）。这一步故意与"接线"分开：编译期问题（头文件顺序、定点溢出、`-Wconversion`）与运行期问题不该混在同一次上板里。

---

## Task 2：L1 —— BF 去噪 + Demosaic 梯度参数（按 gain 分档）

目标：补上官方管线里 RAW 域的两级。**选它们打头阵的理由**：BF 与 demosaic 都不改画面的平均亮度与通道比值 ⇒ **AE 与 AWB 两个闭环的行为完全不变**，是本计划里最安全的一步，用来验证"标定表 → ISP API"这条新通路本身是通的。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行新增一段并且档位跟着环境光走：
   ```
   [自检] 前馈 gain=1.000×(第0档) | BF=ESP_OK 档0 level=2 | DM=ESP_OK 档0 grad=1.500 | 重配=3
   ```
   遮住镜头让 AE 顶到高增益 ⇒ **BF 档号从 0 涨到 3~6、`level` 从 2 涨到 8~10**；开灯回落。
2. 画面：暗处（高增益）**噪点明显变少**，亮处细节无肉眼可见损失。
3. `实测 fps ≥ 9.0`、`拒收=0`、AE 的 `曝光量`/`亮度` 与改动前**同量级**（±10%）——
   这是"没有改变闭环"的判据，不成立就说明 BF/demosaic 影响了亮度，先停下来查。
4. `重配=` 不随时间线性增长（有迟滞，只在档位跳变时重配）。

- [ ] **Step 2：`cam_tune.h` 新增开关与常量**

```c
/*
 * ══ 官方前馈（开环查表）总开关 ══
 *
 * 官方把 ISP 各画质级的参数按**当前工作点**查表下发，不带任何误差反馈
 * （adn/acc/aen 三个模块的表全部以 gain / color_temp / luma 为索引，没有误差项，
 *  见 2026-08-19-esp32p4-official-isp-pipeline.md §B.1）。我们照此办理：
 * 这三个开关各管一组前馈级，任何一组出问题都能单独关掉回到"寄存器复位值"那个
 * 已实机验证过的状态，不必回滚代码。
 */
#define CAM_ADN_ENABLE   1   /* BF(Bayer 域降噪) + Demosaic 梯度参数，按 gain 分档 */
#define CAM_LSC_ENABLE   1   /* 镜头阴影校正（T3） */
#define CAM_AEN_ENABLE   1   /* SHARP 锐化 + Color 对比度/饱和度（T4） */

/*
 * 前馈重配的迟滞：档位算出来变了，也要连续这么多拍都指向新档才真的下发。
 *
 * 为什么必须有：rev < 3.0 **没有影子寄存器**（isp_ll_shadow_update_* 全是空桩，
 * 官方文档 §A.5），参数写下去立刻生效、**没有帧边界原子性** —— 帧中途换 BF 模板
 * 会出现单帧的上下半张不同处理。AE 在档位边界上抖一下就重配一次的话，
 * 那种撕裂会以"偶发横向亮带"的形式出现，而且极难归因。
 * 3 拍 = 300 ms，与 AE 的更新周期同量级，代价是换档慢 0.3 秒，肉眼不可见。
 */
#define CAM_FEEDFWD_HYST_TICKS  3
```

- [ ] **Step 3：`camera_csi.c` —— 一个统一的"档位跟踪器"**

三组前馈（BF/DM 按 gain、SHARP/对比度按 gain、CCM/LSC/饱和度按 CCT）的换档逻辑完全一样，写一次：

```c
#include "cam_isp_map.h"
#include "cam_isp_cal.h"
#include "driver/isp_bf.h"
#include "driver/isp_demosaic.h"

/* 带迟滞的档位跟踪器。cur = 已下发的档，want 连续 CAM_FEEDFWD_HYST_TICKS 拍
 * 都指向同一个新档才认。返回 true 表示需要重配。 */
typedef struct {
    uint32_t cur;        /* 已下发的档 */
    uint32_t pending;    /* 候选档 */
    uint32_t count;      /* 候选档已连续出现几拍 */
    bool     primed;     /* 开机第一次无条件下发 */
} cam_slot_track_t;

static bool slot_changed(cam_slot_track_t *t, uint32_t want)
{
    if (!t->primed) { t->primed = true; t->cur = want; t->count = 0; return true; }
    if (want == t->cur) { t->count = 0; return false; }
    if (want != t->pending) { t->pending = want; t->count = 1; return false; }
    if (++t->count < CAM_FEEDFWD_HYST_TICKS) return false;
    t->cur = want; t->count = 0;
    return true;
}
```

- [ ] **Step 4：BF + Demosaic 的下发**

```c
#if CAM_ADN_ENABLE
static cam_slot_track_t s_bf_slot, s_dm_slot;
static int32_t s_st_bf = STEP_NOT_RUN, s_st_dm = STEP_NOT_RUN;
static uint32_t s_feedfwd_reconf;      /* 累计重配次数，自检行用 */

/* gain 断点表（cam_isp_cal.h 里的 gain_milli 字段抽出来，编译期常量）。 */
static const uint16_t k_bf_gains[] = {1000, 4000, 8000, 16000, 24000, 32000, 64000};
static const uint16_t k_dm_gains[] = {1000, 4000, 8000, 12000};

static void camera_adn_tick(uint32_t gain_milli)
{
    const uint32_t bf = cam_map_gain_slot(k_bf_gains, 7, gain_milli);
    if (slot_changed(&s_bf_slot, bf)) {
        const esp_isp_bf_config_t cfg = {
            /* 官方桥接层一律用 SRND_DATA + tail valid 0/0（官方文档 §C.10）。
             * ⚠️ 绝不能给 esp_isp_bf_configure() 传 NULL：它在 else 分支之后仍然
             *    无条件求值 config->flags.update_once_configured（isp_bf.c），传 NULL 就是空指针解引用。 */
            .padding_mode    = ISP_BF_EDGE_PADDING_MODE_SRND_DATA,
            .padding_data    = 0,
            .denoising_level = cam_cal_bf[bf].level,
            .padding_line_tail_valid_start_pixel = 0,
            .padding_line_tail_valid_end_pixel   = 0,
            .flags = { .update_once_configured = 1 },
        };
        memcpy((void *)cfg.bf_template, cam_cal_bf[bf].matrix, 9);
        s_st_bf = esp_isp_bf_configure(s_isp, &cfg);
        if (s_st_bf == ESP_OK && !s_bf_enabled) {
            s_st_bf = esp_isp_bf_enable(s_isp);      /* enable 有 FSM 门，只能调一次 */
            s_bf_enabled = (s_st_bf == ESP_OK);
        }
        s_feedfwd_reconf++;
    }

    const uint32_t dm = cam_map_gain_slot(k_dm_gains, 4, gain_milli);
    if (slot_changed(&s_dm_slot, dm)) {
        /* grad_ratio 定点：2 整数位 + 4 小数位（soc_caps.h:363-364）⇒ 步长 1/16。
         * 官方四档 1.5/1.25/1.05/1.0 ⇒ 24/20/17/16（1.05 量化到 1.0625，
         * 这个 6% 的偏差比"不配、停在复位值"小得多）。 */
        const uint32_t milli = cam_cal_demosaic[dm].grad_ratio_milli;
        const esp_isp_demosaic_config_t cfg = {
            .grad_ratio = { .integer = milli / 1000,
                            .decimal = ((milli % 1000) * 16 + 500) / 1000 },
            .padding_mode = ISP_DEMOSAIC_EDGE_PADDING_MODE_SRND_DATA,
            .padding_data = 0,
            .padding_line_tail_valid_start_pixel = 0,
            .padding_line_tail_valid_end_pixel   = 0,
        };
        s_st_dm = esp_isp_demosaic_configure(s_isp, &cfg);
        /* ⚠️ demosaic 已经被 output=RGB565 隐式打开了（isp_ll.h:473-478，审计 §A.1 级6），
         *   **不要**再调 esp_isp_demosaic_enable()：它有 FSM 门，会返回 INVALID_STATE，
         *   而那个错误码会让人误以为参数没配上。这里只 configure。 */
        s_feedfwd_reconf++;
    }
}
#endif
```

调用点：`camera_csi_tune_tick()` 里，**排在 `camera_ae_tick()` 之后**（要用本拍刚更新的增益档）。

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `BF=ESP_ERR_INVALID_ARG` | padding tail valid 参数不合法（`end > start` 或都为 0 才合法） | 检查两个字段都是 0 |
| `BF=ESP_ERR_INVALID_STATE` | 重复调了 `esp_isp_bf_enable()` | enable 只能一次，看 `s_bf_enabled` |
| 崩在 `esp_isp_bf_configure` 内部 | 传了 NULL config | 见 Step 4 的 ⚠️ |
| 档位一直是 0 不动 | `gain_milli` 传错（传了下标而不是绝对增益） | 应传 `s_ae_lim.gain_map[s_ae.gain_index]` |
| 画面出现横向亮带 | 帧中途重配（无影子寄存器） | 调大 `CAM_FEEDFWD_HYST_TICKS` |
| 暗处噪点没变少 | BF 在 RAW 域，而我们看的是 JPEG 之后的画面；先确认档位真的变了 | 看自检行的 `level=` 是否跟着涨 |

- [ ] **Step 6：回退路径** —— `CAM_ADN_ENABLE 0`，重编。两个块都不 configure、不 enable，硬件停在复位值 = 今天的状态。

---

## Task 3：L1 —— LSC 镜头阴影校正（固定 5210 K 档）

目标：把官方 273 格 × 4 通道的暗角修正表配进去。**先用固定的中间档（5210 K）**，按色温选档留到 T13 —— 这一步只验证"表的排布对不对、定点转换对不对"。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据（这是本任务唯一能证明它生效的东西）**

1. 自检行 `LSC=ESP_OK 档1(5210K) 格21×13=273`；
2. **对着一面均匀白墙（或白纸铺满画面）**，比较改动前后：
   - 改动前：画面**四角明显比中心暗**（暗角），角/中心亮度比约 **0.3~0.4**；
   - 改动后：四角与中心亮度差 **< 15%**；
   - 量法：临时把 `frame_stats_sample()` 换成对**四角各 160×90 区域**与**中心 160×90 区域**各跑一次
     `cam_frame_stats_rgb565()`（该函数已支持传子区域指针，`frame_stats_sample_bottom()` 就是这么用的），
     把 5 个 `lum_mean` 打进自检行。**这段临时代码在 Step 6 删掉**，判据数字抄进 README。
3. `实测 fps ≥ 9.0`；`重配=` 恒为 1（固定档，只在开机配一次）。
4. AE 的 `亮度` 会**上升约 10~20%**（四角被提亮），AE 随后把曝光压回去 —— 这是预期内的一次性偏移，不是回归。

- [ ] **Step 2：分配 + 填表 + 使能（顺序有硬要求）**

```c
#if CAM_LSC_ENABLE
#include "driver/isp_lsc.h"
static esp_isp_lsc_gain_array_t s_lsc_gain;     /* 四个通道各 273 项，常驻（T13 换档要复用） */
static size_t  s_lsc_n;
static int32_t s_st_lsc = STEP_NOT_RUN;

static esp_err_t camera_lsc_apply(uint32_t slot)
{
    for (size_t i = 0; i < s_lsc_n; i++) {
        s_lsc_gain.gain_r [i].val = cam_cal_lsc[slot][0][i];
        s_lsc_gain.gain_gr[i].val = cam_cal_lsc[slot][1][i];
        s_lsc_gain.gain_gb[i].val = cam_cal_lsc[slot][2][i];
        s_lsc_gain.gain_b [i].val = cam_cal_lsc[slot][3][i];
    }
    const esp_isp_lsc_config_t cfg = { .gain_array = &s_lsc_gain };
    return esp_isp_lsc_configure(s_isp, &cfg);      /* 无 FSM 门，取流中可重配 */
}
#endif
```

在 `camera_csi_init()` 里、`esp_isp_new_processor()` **之后**、任何 `enable` **之前**：

```c
#if CAM_LSC_ENABLE
    /* ⚠️ 顺序：allocate 要求 lsc_fsm == INIT（isp_lsc.c:31），必须在 enable 之前。
     * ⚠️ 数组尺寸由 ISP 的 h_res/v_res 算出：
     *      num_grids_x = (1280-1)/2/32 + 2 = 21，num_grids_y = (720-1)/2/32 + 2 = 13
     *      21 × 13 = 273 —— 与官方标定文件的 lsc_tbl_size 精确相等（img_w/h 也正好是
     *      1280×720，我们与官方标定的分辨率完全一致，不需要重采样）。
     *   若哪天换传感器模式，这个 273 会变，而标定表不会 ⇒ 下面这条断言会立刻拦住。 */
    s_st_lsc = esp_isp_lsc_allocate_gain_array(s_isp, &s_lsc_gain, &s_lsc_n);
    if (s_st_lsc == ESP_OK && s_lsc_n != CAM_CAL_LSC_TBL_SIZE) {
        ESP_LOGE(TAG, "LSC 网格数 %u 与标定表 %u 不符（分辨率变了？）",
                 (unsigned)s_lsc_n, (unsigned)CAM_CAL_LSC_TBL_SIZE);
        s_st_lsc = ESP_ERR_INVALID_SIZE;
    }
    if (s_st_lsc == ESP_OK)
        s_st_lsc = camera_lsc_apply(CAM_LSC_SLOT_DEFAULT);
    if (s_st_lsc == ESP_OK)
        s_st_lsc = esp_isp_lsc_enable(s_isp);
    if (s_st_lsc != ESP_OK)
        ESP_LOGW(TAG, "LSC 没配上(%s)，画面保留暗角，其余一切照常",
                 esp_err_to_name((esp_err_t)s_st_lsc));
#endif
```

`cam_tune.h`：

```c
/* 固定档下标（cam_isp_cal.h 的 LSC 三档是 2410 / 5210 / 8200 K）。
 * 取中间那档：R 通道在 2410 与 8200 之间最大差 0.71，取中点后两侧残差各 ≈0.36，
 * 落在一个 ~3× 的四角提亮上 ≈ 12%，看不出来。按色温选档在 T13。 */
#define CAM_LSC_SLOT_DEFAULT  1
```

- [ ] **Step 3：`ESP_ERR_NOT_SUPPORTED` 的排除（硬约束 1 的现场验证）**

`esp_isp_lsc_configure()` 里有一处版本门：`ESP_CHIP_REV_ABOVE(chip_version, 100)`（`isp_lsc.c:57-60`）。而 `ESP_CHIP_REV_ABOVE(min,rev)` 展开成 `(min) <= (rev)`（`soc/chip_revision.h:31`），本板 rev v1.0 ⇒ `100 <= 100` **为真** ⇒ 可用 `[官§A.7]` `[审§A.3]`。

⚠️ 若实机拿到 `ESP_ERR_NOT_SUPPORTED`，**说明这块板的 efuse 报的不是 v1.0**（比如 v0.x）。这时立刻停下来，`esptool.py chip_id` 读实际版本，并把结论写回 README 的"rev <3.0 已知不可用功能"那张表 —— 这会推翻本计划关于 LSC 的全部前提。

- [ ] **Step 4：内存核对**

`esp_isp_lsc_allocate_gain_array()` 用 `ISP_MEM_ALLOC_CAPS` 分配 4 × 273 × 4 = **4368 B**（内部 RAM）。加上 `cam_isp_cal.h` 的 6552 B flash。上板后读 `esp_get_free_internal_heap_size()` 与改动前对比，差值应 ≈ 4.4 KB。**这个数写进 README。**

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `LSC=ESP_ERR_NOT_SUPPORTED` | 芯片版本不是 v1.0 | 见 Step 3，**停止本任务** |
| `LSC=ESP_ERR_INVALID_SIZE` | 网格数 ≠ 273（分辨率变了） | 重跑提取脚本并改 `LSC_CTS` 对应分辨率，或放弃 LSC |
| 四角**更暗**了 | 表值被当成衰减而不是增益 | 检查 `round(v*256)` 而不是 `round(256/v)` |
| 画面上下亮、左右暗（修正方向转置） | JSON 里 273 个数是 y 快变而非 x 快变 **[缺口，T0 Step 5 已标注]** | 打开提取脚本的转置开关重跑，重编 |
| 四角出现色斑（角上偏红/偏蓝） | 四条通道表填错位（r/gr/gb/b 顺序） | 对照 `esp_isp_lsc_gain_array_t` 的字段顺序 |
| 四角噪点明显 | 正常代价：3.3× 的提亮同时放大噪声 | 若不可接受，T2 的 BF 档位可以按需上调（改 `k_bf_gains` 断点，不改表） |

- [ ] **Step 6：删掉临时的五区亮度统计代码**，把测到的「角/中心比 改动前 X → 改动后 Y」两个数写进 README 草稿（T14 收口）。

---

## Task 4：L1 —— SHARP 锐化 + Color 对比度/饱和度（按 gain 分档）

目标：补上 YUV 域的两级。这两级在 AE/AWB 的采样点**下游**（AE 采 demosaic 后、AWB 采 CCM 前），所以同样不改两个闭环的输入 —— 但**会改我们现在的软件全帧统计**（它采在 ISP 输出）。T4 时 AE 还吃软件统计（T6 才切），所以对比度 132（=1.031×）会让 `lum_mean` 抬约 3%，AE 把曝光压回去，这是**已知且可接受**的一次性偏移；判据里要看到它。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行：`SHARP=ESP_OK 档0 h=16 l=5 m=1.525 | Color=ESP_OK 对比度=132(1.031×) 饱和度=128(1.000×)`；
2. 遮镜头拉高增益 ⇒ **SHARP 档 0→3、`m_coeff` 1.525→1.225**，对比度 132→126；
3. 画面：正常光下**边缘更清晰**（拍一张印刷文字，字缘锐了）；高增益下**不出现噪点被锐化成颗粒**的现象（这正是 `m_coeff` 随增益下降要防的事 `[官§B.7.2]`）；
4. `lum_mean` 相对 T3 抬升 ≈ 3%（对比度 1.031×），AE 在 1~2 个更新周期内压回目标；
5. `实测 fps ≥ 9.0`、`拒收=0`。

- [ ] **Step 2：SHARP 的下发**

```c
#if CAM_AEN_ENABLE
#include "driver/isp_sharpen.h"
#include "driver/isp_color.h"
static const uint16_t k_sh_gains[] = {1000, 8000, 12000, 65000};
static const uint16_t k_ct_gains[] = {1000, 16000, 24000, 65000};   /* 对比度 */

/* 3 整数位 + 5 小数位（soc_caps.h:368-372）⇒ 步长 1/32。
 * 官方 h=1.625 恰好是 52/32（精确）；m=1.525 → 49/32 = 1.53125（差 0.4%）。 */
static inline uint32_t q5_of(uint32_t milli)
{
    return ((milli % 1000) * 32 + 500) / 1000;
}

static void camera_sharpen_apply(uint32_t s)
{
    const esp_isp_sharpen_config_t cfg = {
        .h_freq_coeff = { .integer = cam_cal_sharpen[s].h_coeff_milli / 1000,
                          .decimal = q5_of(cam_cal_sharpen[s].h_coeff_milli) },
        .m_freq_coeff = { .integer = cam_cal_sharpen[s].m_coeff_milli / 1000,
                          .decimal = q5_of(cam_cal_sharpen[s].m_coeff_milli) },
        .h_thresh = cam_cal_sharpen[s].h_thresh,
        .l_thresh = cam_cal_sharpen[s].l_thresh,
        .padding_mode = ISP_SHARPEN_EDGE_PADDING_MODE_SRND_DATA,
        .padding_data = 0,
        .padding_line_tail_valid_start_pixel = 0,
        .padding_line_tail_valid_end_pixel   = 0,
        .flags = { .update_once_configured = 1 },
    };
    memcpy((void *)cfg.sharpen_template, cam_cal_sharpen[s].matrix, 9);
    s_st_sharp = esp_isp_sharpen_configure(s_isp, &cfg);
    if (s_st_sharp == ESP_OK && !s_sharp_enabled) {
        s_st_sharp = esp_isp_sharpen_enable(s_isp);
        s_sharp_enabled = (s_st_sharp == ESP_OK);
    }
}
#endif
```

- [ ] **Step 3：Color 的下发**

```c
/* 对比度/饱和度是 1 整数位 + 7 小数位（isp_types.h:377-402），**128 就是 1.0×**，
 * 标定文件里的 132/130/128/126 与 128/130 就是这个 val 的原值，直接写、不换算。
 * ⓘ 色调（hue）：官方 SC202CS 标定里**根本没有 hue 字段**，写 0 就是对齐；
 *   顺带避开 rev<3.0 只有 8 bit 色调（HAL 内部做 hue*256/360 折算）的精度坑。
 * ⓘ 亮度（brightness）：同样不在标定里，写 0。 */
static void camera_color_apply(uint32_t contrast_val, uint32_t saturation_val)
{
    const esp_isp_color_config_t cfg = {
        .color_contrast   = { .val = contrast_val },
        .color_saturation = { .val = saturation_val },
        .color_hue        = 0,
        .color_brightness = 0,
        .flags = { .update_once_configured = 1 },
    };
    s_st_color = esp_isp_color_configure(s_isp, &cfg);
    if (s_st_color == ESP_OK && !s_color_enabled) {
        s_st_color = esp_isp_color_enable(s_isp);
        s_color_enabled = (s_st_color == ESP_OK);
    }
}
```

⚠️ **`isp_core.c:171-173` 的 `isp_ll_color_enable(true)` workaround（DIG-474）只在 DVP 输入时触发，我们是 CSI 输入 ⇒ 不触发** `[审§A.3]`。所以 color 块此刻确实是关的，`esp_isp_color_enable()` 会正常拿到 FSM 的 INIT 态。若拿到 `ESP_ERR_INVALID_STATE`，说明这条判断错了，回来改这段注释。

- [ ] **Step 4：饱和度先钉在 0 档**

`acc.saturation` 是**按色温**索引的（`{0 → 128, 4500 → 130}`）`[官§B.6.2]`，而 CCT 要到 T10 才有。T4 先钉 `128`（= 1.000×，与"不配 color 块"在饱和度上等价），只让对比度按 gain 动。T13 接上 CCT 之后再让它在 128/130 之间切。**差别只有 1.6%，先钉住不影响任何判据。**

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `Color=ESP_ERR_INVALID_ARG` | val 超 255 / hue 超 359 / brightness 出 [−128,127] | 检查是不是把 1.031 这种浮点乘了 1000 写进去 |
| 画面整体发灰、对比度反而降低 | 把 132 当成"百分数"或做了 `/128` 的换算 | val 是原值，128 = 1.0× |
| 高增益下噪点变成明显颗粒 | SHARP 档没跟着 gain 走 | 看自检行 `m_coeff` 是否随增益下降 |
| 边缘出现白边/黑边（过锐） | `h_coeff` 的定点换算错了（整数位/小数位颠倒） | `1.625 ⇒ integer=1, decimal=20`（0.625×32=20） |

- [ ] **Step 6：回退** —— `CAM_AEN_ENABLE 0`。

---

## Task 5：L2 —— 硬件 AE 5×5 统计**上线但不接管**（纯观测）

目标：把 ISP 的 AE 统计块建起来、跑起来、把 25 块亮度打出来，**控制律仍然吃软件全帧均值**。这一步存在的全部理由是：**换统计源会改变 AE 的工作点**（不同采样点、不同亮度权重、不同空间加权），必须先量出换算比 ρ，下一任务才有据可依。**一个任务一个变量。**

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行新增：
   ```
   [自检] AE统计 帧=NNN 硬件加权=98(暗块0 亮块0) 软件全帧=124 比值ρ=0.79
          块: 88 92 95 93 87 | 94 101 106 100 93 | 96 108 115 107 95 | ... 
   ```
2. `帧=` 与 CSI 的 `帧=` **同步增长**（每帧一次回调）；
3. 遮住镜头 ⇒ 25 块**全部**下降；只遮一半镜头 ⇒ **只有一侧的块**下降（这条证明 5×5 分块的空间性是真的，而不是 25 个相同的数）；
4. 手电照画面中心 ⇒ 中心块冲到 250 以上、`亮块=` 计数涨到 3 以上；
5. **`ρ` 在 AE 收敛后稳定在某个值（记下来，T6 要用）**，反复三次遮挡/复原后回到同一个值 ±0.03；
6. alt 0 下 `帧=` **不涨**（硬约束 6）；
7. `实测 fps ≥ 9.0`。

- [ ] **Step 2：建控制器（`camera_csi_init()` 内，`esp_isp_new_processor()` 之后）**

```c
#include "driver/isp_ae.h"

static isp_ae_ctlr_t s_ae_ctlr;
static int32_t       s_st_aestat = STEP_NOT_RUN;
static portMUX_TYPE  s_ae_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t       s_ae_blocks[25];
static uint32_t      s_ae_stat_frames;

/*
 * ⚠️ 回调跑在 **ISR 上下文**（isp_core.c 的 s_isp_isr_dispatcher）。
 * 这里只做 25 字节的搬运，不打日志、不调任何可能阻塞的东西。
 * 不加 IRAM_ATTR：CONFIG_ISP_ISR_IRAM_SAFE 默认关，ISR 允许访问 flash；
 * 加了反而要求 s_ae_blocks 也进内部 RAM，徒增约束。
 */
static bool cam_on_ae_stat(isp_ae_ctlr_t h, const esp_isp_ae_env_detector_evt_data_t *e, void *ud)
{
    (void)h; (void)ud;
    portENTER_CRITICAL_ISR(&s_ae_lock);
    for (int i = 0; i < 5; i++)
        for (int j = 0; j < 5; j++)
            s_ae_blocks[i * 5 + j] = (uint8_t)e->ae_result.luminance[i][j];
    s_ae_stat_frames++;
    portEXIT_CRITICAL_ISR(&s_ae_lock);
    return false;      /* 没有唤醒任务 */
}
```

```c
    const esp_isp_ae_config_t ae_cfg = {
        /* 官方 esp_video 把这里**硬编码**为 AFTER_DEMOSAIC（esp_video_isp_device.c:879，
         * 官方文档 §C.6）—— 即线性 RGB 亮度，gamma 之前、CCM 之前。
         * 这正是我们要的：T12 加了 gamma 之后 AE 的输入不受影响。 */
        .sample_point = ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC,
        /* ⚠️ 窗口**必须显式写**。isp_hal_ae_window_config() 把窗按 /5 分块，
         *   全零窗口能通过 esp_isp_new_ae_controller() 的参数校验，但 bsize = 0，
         *   25 个块全是 0（官方文档 §C.10 的陷阱）。
         *   写 1280×720 而不是 1279×719：/5 后是 256×144，整除，不丢边缘 5 列。
         *   官方桥接层用的也是整幅传感器分辨率（"Use the full resolution ..."）。 */
        .window = { .top_left = {0, 0}, .btm_right = {CAM_SENSOR_W, CAM_SENSOR_H} },
        /* ⚠️ 三个统计块共用一个 ISP 中断，intr_priority 必须与处理器一致。
         *   我们的 esp_isp_processor_cfg_t 是零初始化 ⇒ intr_priority = 0
         *   ⇒ 这里也必须是 0。不一致时驱动走的是
         *   `ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, ...)`，
         *   **返回值是 1 而不是一个 esp_err_t**，自检行会打出一个看不懂的码。 */
        .intr_priority = 0,
    };
    s_st_aestat = esp_isp_new_ae_controller(s_isp, &ae_cfg, &s_ae_ctlr);
    if (s_st_aestat == ESP_OK) {
        const esp_isp_ae_env_detector_evt_cbs_t cbs = { .on_env_statistics_done = cam_on_ae_stat };
        s_st_aestat = esp_isp_ae_env_detector_register_event_callbacks(s_ae_ctlr, &cbs, NULL);
    }
    if (s_st_aestat == ESP_OK)
        s_st_aestat = esp_isp_ae_controller_enable(s_ae_ctlr);
```

- [ ] **Step 3：只在取流时跑（硬约束 6）**

`camera_csi_start()`：`esp_isp_enable()` 成功之后追加
`esp_isp_ae_controller_start_continuous_statistics(s_ae_ctlr)`。

`camera_csi_stop()`：**在 `esp_isp_disable()` 之前**追加
`esp_isp_ae_controller_stop_continuous_statistics(s_ae_ctlr)`，并 `keep_first_err()` 记账。

> 顺序理由与既有的四步停流一致：先让数据源停，再关块。反过来会在 disable 之后还收到一次中断。
> 幂等由既有的 `s_streaming` 闸保证（start/stop 的 FSM 门只允许 ENABLE↔CONTINUOUS 各一次）。

- [ ] **Step 4：算 ρ 并打出来**

```c
    uint8_t blocks[25];
    portENTER_CRITICAL(&s_ae_lock);
    memcpy(blocks, s_ae_blocks, 25);
    portEXIT_CRITICAL(&s_ae_lock);

    uint8_t nd = 0, nb = 0;
    const uint8_t hw = cam_ae_weighted_mean(blocks, &nd, &nb);
    /* ρ ×1000。软件均值为 0 时打 0，别除零。 */
    const uint32_t rho = s_last_stats.lum_mean ? (uint32_t)hw * 1000u / s_last_stats.lum_mean : 0;
```

- [ ] **Step 5：块序是行主序还是列主序？——不需要知道**

驱动把 `luminance[i][j]` 按 `block_id = i*5 + j` 从 `isp_ll_ae_get_block_mean_lum()` 读出，而**硬件的块编号是横着数还是竖着数，IDF 里查不到 [缺口]**。

这对我们**没有影响**，两条理由：① 官方权重表是一个**中心对称的金字塔**（`1,1,2,1,1 / 1,2,3,2,1 / 1,3,4,3,1 / …`），转置后与自身相同；② 过暗/过亮块只是计数，与位置无关。**所以本计划不去猜它。** 但 Step 1 的判据 3（遮一半镜头只有一侧块下降）会顺带把真实排布测出来，把结论记进代码注释供将来用。

- [ ] **Step 6：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| 25 块**全是 0** | 窗口 bsize=0（窗没写或写了 `{0,0},{0,0}`） | 见 Step 2 的 ⚠️ |
| `esp_isp_new_ae_controller` 返回 `1` | `intr_priority` 与处理器不一致 | 两边都填 0 |
| `帧=` 不涨 | 忘了 `start_continuous_statistics`，或 `enable` 失败 | 看 `s_st_aestat` |
| `帧=` 涨得比 CSI 帧慢一半 | 连续模式的重触发（`isp_ll_ae_manual_update`）被漏 | 这是驱动内部行为，检查是不是误用了 oneshot |
| alt 0 下 `帧=` 还在涨 | stop 路径没停统计 | 见 Step 3 |
| ρ 抖动大（>±0.1） | AE 没收敛就读了 | 只在 `cam_ae_converged()` 为真时记 ρ |

---

## Task 6：L2 —— AE **切到**硬件统计（加权表 + quorum 剔除）

目标：换掉 AE 的反馈量来源。**只换来源与目标值，控制律（四道防振荡闸）一行不改。**

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行 `AE=... 源=硬件5×5 亮度 61→目标 X(±Y)`，**AE 仍然收敛**（`已收敛`），收敛时间与改动前同量级（≤ 2 s）；
2. 遮镜头 / 开灯反复三次，每次都收敛、**不振荡、不过冲**（`下发=` 每次涨 ≤ 8）；
3. **画面观感与 T5 之前一致**（这是本任务的核心判据：只换了测量口径，不该看出亮度变化）；
4. 新增判据 —— **逆光场景**：让画面里出现一扇亮窗（`亮块 ≥ 3`），此时主体应当比改动前更亮（过亮块被剔除，AE 不再被窗户拉低曝光）。这条是官方 quorum 剔除的**唯一**可见收益，必须验到。
5. `实测 fps ≥ 9.0`。

- [ ] **Step 2：`cam_tune.h` 的改动（每个数写理由）**

```c
/*
 * ── AE 的反馈量来源 ────────────────────────────────────────────────
 * 0 = 软件全帧 1/64 采样均值（改动前的行为，采在 ISP 输出 = CCM 之后）
 * 1 = ISP 硬件 5×5 分块统计（采在 **demosaic 之后**，官方 esp_video 硬编码的采样点）
 *
 * 为什么要换：① 官方的 AE 目标、权重表、过曝/欠曝阈值全部是在这个采样点上标定的
 *   —— 换了采样点这些数才有意义；② demosaic 后的抽头在 CCM/gamma **上游**，
 *   AWB 改 CCM、T12 加 gamma 都不会扰动 AE 的输入，两个环真正解耦；
 *   ③ 硬件顺带给出空间分布，过暗/过亮块才有得剔。
 * 回退：设 0 立刻回到已实机验证的软件均值路径（AE 统计块仍然建、仍然打日志）。
 */
#define CAM_AE_SOURCE  1

/*
 * ── AE 目标 ────────────────────────────────────────────────────────
 * ⚠️ 这三个数与 CAM_AE_SOURCE **绑定**，换源必须换数。
 *
 * CAM_AE_SOURCE=0 时的历史值是 120 / 死区 12，测在 CCM 之后。
 * CAM_AE_SOURCE=1 测在 CCM 之前 ⇒ 少了对角阵 diag(1.7,1.0,1.55) 带来的亮度增益
 *   0.30×1.7 + 0.586×1.0 + 0.113×1.55 ≈ 1.27，再叠上中心加权，
 *   T5 实机量到的换算比 ρ = 硬件加权 / 软件全帧 = 0.79。
 *   ⇒ 等价目标 = round(120 × 0.79) = 95，死区 = round(12 × 0.79) = 9。
 * ⓘ 官方的目标是 56/62/64（同一个采样点），比这里低 —— 因为官方管线**下游有 gamma**。
 *   T12 装上 gamma 的同时才把这三个数换成官方值，两件事必须一起改（计划 §E.1）。
 *
 * 【实施时把下面三个数换成 T5 实测 ρ 算出来的值，并把 ρ 写进注释】
 */
#define CAM_AE_TARGET       95
#define CAM_AE_TARGET_LOW   (CAM_AE_TARGET - 9)
#define CAM_AE_TARGET_HIGH  (CAM_AE_TARGET + 9)

/*
 * ── 过暗/过亮块的 quorum（官方 agc.luma_adjust 原值）──────────────
 * 官方语义是"计数达标才进保护分支"，不是逐块挑：
 *   亮度 < 14 的块**数量** >= 5  ⇒ 欠曝保护（把这些块从测光里剔掉）
 *   亮度 > 239 的块**数量** >= 3 ⇒ 过曝保护（同上）
 * 未达 quorum 时一块都不剔 —— 一两个暗角/一盏灯不该改变测光口径。
 * 这四个数**不要动**：它们是官方在这颗传感器上标的，动了就不是对齐了。
 */
#define CAM_AE_DARK_THRESH    14
#define CAM_AE_DARK_QUORUM     5
#define CAM_AE_BRIGHT_THRESH 239
#define CAM_AE_BRIGHT_QUORUM   3
```

⚠️ `cam_ae_step()` 里原来用 `CAM_AE_TARGET ± CAM_AE_DEADBAND` 的对称死区，改成读 `CAM_AE_TARGET_LOW/HIGH` 的**非对称**死区（官方 56/62/64 就是非对称的：−6/+2）。改动只有两行比较，但**必须同步改 `test_cam_tune.c` 里依赖死区的用例**，且 281 个用例一条都不许掉。

- [ ] **Step 3：接线**

```c
static void camera_ae_tick(const cam_frame_stats_t *st)
{
    if (!s_ae_ready)
        return;
#if CAM_AE_SOURCE
    uint8_t blocks[25];
    portENTER_CRITICAL(&s_ae_lock);
    memcpy(blocks, s_ae_blocks, 25);
    const uint32_t frames = s_ae_stat_frames;
    portEXIT_CRITICAL(&s_ae_lock);
    if (frames == 0)
        return;                       /* 还没收到过统计：这一拍不动，别拿全 0 去调曝光 */
    const uint8_t lum = cam_ae_weighted_mean(blocks, &s_ae_dark_n, &s_ae_bright_n);
#else
    const uint8_t lum = st->lum_mean;
#endif
    if (!cam_ae_step(&s_ae, lum, &s_ae_lim))
        return;
    ... 原样不动的 GROUP_EXP_GAIN 下发 ...
}
```

- [ ] **Step 4：AWB 这一拍的影响（必须评估，不能默认无事）**

此刻 AWB 仍吃软件统计（`CAM_AWB_SOURCE` 还没引入），它只通过 `cam_ae_converged()` 与 AE 耦合。换了 AE 的测量口径后收敛判定的**时机**会变，但 AWB 的输入（软件通道均值）与公式都没变 ⇒ 行为等价。判据：`[自检] AWB` 行的 `未更新：` 直方图分布与 T5 时同量级，尤其 `AE未稳=` 不应该暴涨。**若 `AE未稳` 暴涨，说明新死区太窄，AE 报不出收敛** ⇒ 把 `CAM_AE_TARGET_LOW/HIGH` 放宽到 ±12×ρ 再试。

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| 画面整体变亮/变暗一大截 | ρ 用错（方向反了） | ρ = 硬件/软件，新目标 = 旧目标 × ρ |
| AE 振荡 | 换源改变了环路增益 | 先加大 `CAM_AE_INTERVAL_TICKS` 到 4；仍振荡则 `CAM_AE_SOURCE 0` 回退并记录 |
| AE 永不收敛（`AE未稳` 暴涨） | 非对称死区太窄 | 见 Step 4 |
| 逆光下主体仍然很暗 | quorum 没触发 | 看 `亮块=` 是否 ≥3；不足说明窗户占的块不够多，换个更极端的场景验 |
| 全黑场景下 AE 疯狂加曝光 | 25 块全被剔除后退回无权平均（预期行为） | 确认 `cam_ae_weighted_mean` 的兜底分支被走到（宿主机用例 F 已覆盖） |

- [ ] **Step 6：回退** —— `CAM_AE_SOURCE 0` + 目标改回 120/12。

---

## Task 7：黑电平实测 + 传感器自带 BLC —— ⛔ **T10（CCM）的判定点**

目标：把 §D.3 里那个"用不了 `acc.blc`"的硬约束**变成一个实测数字**，并尽可能在传感器侧解决它。**这一步不做，T10 的 CCM 就是在一个未知基座上做大动态的矩阵运算。**

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：先测，再决定要不要写寄存器**

给 `camera_quality_report()` 加三个数（`cam_frame_stats_t` 已经有 `lum_min`，再加三个通道的 min 即可 —— 改 `cam_frame_stats.{c,h}`，**同步加宿主机用例**，24 用例只增不减）：

```
[自检] 黑位 最暗 lum=?? r=?? g=?? b=?? | 传感器BLC=未写/0xc0
```

**测法（必须照做，否则数字没有意义）**：

1. 用不透光的东西**完全盖住镜头**（镜头盖 / 黑胶带 / 手掌紧贴，环境要暗）；
2. 等 10 秒让 AE 顶到上限（`曝光=1244/1244`、增益顶到 16×）；
3. 读 `最暗 r/g/b`。**这三个数就是黑电平基座**（长曝光高增益下的读出噪声会让它比真实基座略高，取三次的最小值）。

**判读**：

| 实测 | 结论 | 动作 |
|---|---|---|
| `r/g/b` 都 ≤ 3 | 传感器自己的 BLC 已经在工作，基座 ≈ 0 | `CAM_SENSOR_BLC_ENABLE 0`，**什么都不做**，§D.3 的问题不存在 |
| `r/g/b` 在 10~20 之间且三者相近 | 基座 ≈ 16，与官方 `acc.blc` 的 16 精确吻合 | 走 Step 2，写 `0x3902 = 0xc0` |
| `r/g/b` 明显不等（差 > 5） | 基座本身有色偏，或者 LSC/CCM 在放大它 | 先把 `CAM_LSC_ENABLE`/`CCM` 临时关掉重测，隔离出真实基座 |
| `r/g/b` > 30 | 不是黑电平，是漏光/没盖严 | 重新盖，别急着写寄存器 |

- [ ] **Step 2：写传感器自带的 BLC（仅当基座 ≈ 16）**

SC202CS 的寄存器表里有一行被**注释掉**的：

```c
// {0x3902, 0x80}, // blc disable. 0xc0 enable
```
（`managed_components/.../sc202cs_mipi_1lane_24Minput_1280x720_raw8_30fps.h` 倒数第 3 行，`[审§A.2 级3]`）

⇒ 这颗传感器**自己有 BLC**，只是既没显式开也没显式关，停在上电默认。这正是 rev v1.0 上 ISP BLC 不可用时**唯一真正的替代执行点**（官方在 esp_video 里对此的处置是"没有任何软件替代，黑电平只能靠传感器自己处理" `[官§D.4b]` —— 我们把这句话落到实处）。

```c
/*
 * ── 传感器自带的黑电平校正 ────────────────────────────────────────
 *
 * 为什么非做不可：rev v1.0 的 ISP BLC 直接返回 ESP_ERR_NOT_SUPPORTED，而官方
 * SC202CS 标定文件里的 acc.blc 说这颗传感器有 16/255 的黑电平基座。基座本身
 * 只是让黑位发灰，真正的问题在 T10：白平衡增益要乘进 CCM，等值基座会被 W 变成
 * **不等值**基座，再被 CCM 的大负非对角项放大成可见的品红色黑位
 * （5040K + kr1.8/kb1.85 + p=16 ⇒ 约 (+23, −8, +21)，推导见计划 §D.3）。
 *
 * 0x3902 = 0xc0 是 esp_cam_sensor 自带寄存器表里被注释掉的那一行给出的
 * （"blc disable. 0xc0 enable"）。**这是厂商表里的注释，不是数据手册**，
 * 所以设成 1 之前必须先按 T7 Step 1 实测基座，设成 1 之后必须再测一次确认降下来了。
 * 任何异常（画面出现横条纹 / 暗部溢出成纯黑 / PID 读不到）都改回 0。
 */
#define CAM_SENSOR_BLC_ENABLE  1
#define CAM_SENSOR_BLC_REG     0x3902
#define CAM_SENSOR_BLC_VAL     0xc0
```

下发点：`camera_csi_init()` 里，`esp_cam_sensor_set_format()` **之后**（set_format 会把整张寄存器表重写一遍，写早了会被覆盖）：

```c
#if CAM_SENSOR_BLC_ENABLE
    s_st_blc = esp_sccb_transmit_reg_a16v8(s_sccb, CAM_SENSOR_BLC_REG, CAM_SENSOR_BLC_VAL);
    if (s_st_blc != ESP_OK)
        ESP_LOGW(TAG, "传感器 BLC 没写进去(%s)，黑位保留基座",
                 esp_err_to_name((esp_err_t)s_st_blc));
#endif
```

⚠️ 需要把 `sccb` 句柄从 `camera_sensor_probe()` 存成文件级静态（现在它是局部变量）。这是本任务唯一的结构性改动。

- [ ] **Step 3：写完再测一次**

同 Step 1 的测法。**判据：`最暗 r/g/b` 全部降到 ≤ 3。**

- [ ] **Step 4：⛔ 判定点**

| 结果 | T10（CCM 官方表）怎么走 |
|---|---|
| 基座本来就 ≈0，或写 `0xc0` 后降到 ≈0 | **放行**，T10 按 §D.4 正常做，`CAM_CCM_STRENGTH_MAX = 256` |
| 写 `0xc0` 无效或有副作用，基座仍 ≈16 | **降级放行**：T10 照做，但 ① T9 Step 5 的统计侧减法必须打开（修正白点估计）；② `CAM_CCM_STRENGTH_MAX` 降到 **192**（=75%），黑位色偏按 t 线性缩到 (+17,−6,+16)；③ README 记下"黑位偏品红"这个已知限制 |
| 基座 > 30 且查不出原因 | **T10 不做**。保持 `CAM_CCM_MODE 0`（对角阵），L3 只做 LSC/饱和度按 CT 选档（T13）。理由：在一个未知的大基座上做 19 档 CCM，画面变化无法归因，投入产出不成立 |

- [ ] **Step 5：失败归因**

| 现象 | 归因 |
|---|---|
| 写 `0x3902` 后 PID 读不到 / 取不到帧 | 寄存器地址理解错了（那行注释可能对应别的模式表） ⇒ 立刻 `CAM_SENSOR_BLC_ENABLE 0` |
| 暗部大片死黑、细节丢失 | BLC 减多了（`0xc0` 可能同时改了减法量） ⇒ 关掉，改走统计侧减法 |
| 基座降了但画面整体变暗 | 正常（减掉了 16/255 = 6%），AE 会补回来 |

---

## Task 8：L2 —— 硬件 AWB 白点统计**上线但不接管**（纯观测，采样点 = CCM 之前）

目标：把 ISP 的 AWB 统计建起来，用**官方标定的白点筛选框**，把 `counted / Σr / Σg / Σb / rg / bg / CCT` 打出来。**控制律仍然吃软件灰世界。**

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行新增：
   ```
   [自检] AWB统计 触发=NN 超时=0 白点=48213/921600(5.2%) Σr/Σg=0.5312 Σb/Σg=0.5701
          → CCT=5480K | 绝对增益 R×1.883 B×1.754（当前 CCM R×1.700 B×1.550）
   ```
2. **拍一张白纸**：`白点=` 占比 > 30%；换成拍一堵红墙：占比掉到 < 5%（**这条证明白点筛选框真的在筛，而不是全收**）；
3. 换光源（白炽灯 ↔ 日光灯 ↔ 窗外自然光），`CCT=` 跟着变，方向正确（白炽灯 < 3500 K，日光 > 5000 K），**且不越出 `[2289, 7466]`**；
4. `触发=` 每秒 +1（oneshot，不是每帧）；`超时=0`；
5. **`实测 fps ≥ 9.0` 且 `拒收=0`** —— 这是本任务最关键的回归项（oneshot 会阻塞帧泵约 35 ms）；
6. alt 0 下 `触发=` 不涨。

- [ ] **Step 2：建控制器（官方标定的筛选框）**

```c
#include "driver/isp_awb.h"

static isp_awb_ctlr_t s_awb_ctlr;
static int32_t s_st_awbstat = STEP_NOT_RUN;

    const esp_isp_awb_config_t awb_cfg = {
        /*
         * ⚠️⚠️ **CCM 之前**。官方 esp_video 也是硬编码这个采样点
         * （esp_video_isp_device.c:639，官方文档 §C.7）。
         * 这一个字段决定了整个控制律的形态：统计**不穿过**被控块（CCM），
         * 于是白点估计是开环前馈而不是闭环反馈 —— 建议增益是**绝对值**，
         * 绝不能再乘当前增益。详见计划 §E.3，以及 cam_awb_step_hw() 的注释。
         */
        .sample_point = ISP_AWB_SAMPLE_POINT_BEFORE_CCM,
        /* 主窗取整幅（官方桥接层默认整幅）。这里是绝对坐标、驱动不做 /5，
         * 所以写 1279/719（含端点）。 */
        .window = { .top_left = {0, 0}, .btm_right = {CAM_SENSOR_W - 1, CAM_SENSOR_H - 1} },
        /* ⚠️ subwindow 在 rev<3.0 上不可用（isp_awb.c:81-89 打 warning 后跳过），
         *   我们**不配**，留零。主窗的四个累加值就是全部可用信息。 */
        .white_patch = {
            /* 官方桥接层不是直接配亮度窗，而是由 green 范围与 rg/bg 范围**推导**出来
             * （官方文档 §C.7 原文）：
             *   lum_max = green_max × (1 + rg_max + bg_max) = 210 × (1+0.879+0.6587) = 532.7
             *   lum_min = green_min × (1 + rg_min + bg_min) =  98 × (1+0.3801+0.2903) = 164.7
             * 驱动这个字段的量纲是 R+G+B（[0, 765]），与上式一致。 */
            .luminance        = { .min = CAM_CAL_LUM_MIN, .max = CAM_CAL_LUM_MAX },   /* 165 / 533 */
            .red_green_ratio  = { .min = 0.3801f, .max = 0.879f  },   /* = awb.range.rg */
            .blue_green_ratio = { .min = 0.2903f, .max = 0.6587f },   /* = awb.range.bg */
        },
        .intr_priority = 0,        /* 与 AE、与处理器一致，见 T5 Step 2 */
    };
    s_st_awbstat = esp_isp_new_awb_controller(s_isp, &awb_cfg, &s_awb_ctlr);
    if (s_st_awbstat == ESP_OK)
        s_st_awbstat = esp_isp_awb_controller_enable(s_awb_ctlr);
```

> ⓘ **这三个框可以直接用，因为它们与我们的采样点同域。** 官方 `awb.range` 的 rg∈[0.38,0.88]
> 明显是**未做白平衡**的 raw 色度值（做过 WB 的话应当围绕 1.0），而 rev v1.0 上我们同样没有
> WBG、采样点同样在 CCM 之前 ⇒ 官方 rev<3.0 的降级路径与我们的管线在这一点上**同构**
> （官方文档 §C.8 的三个结构性后果）。

- [ ] **Step 3：oneshot 触发（**绝不用连续模式**）**

```c
/*
 * ⚠️⚠️ **只用 oneshot，绝不调 esp_isp_awb_controller_start_continuous_statistics()。**
 *
 * 理由是 rev v1.0 上的一处纯浪费：esp_isp_awb_isr() **无条件**读 25 个 subwindow
 * 的 LUT —— 每个子窗 4 次 `set_cmd + get`，共 **100 次寄存器往返**，并往 ISR 栈上
 * 拷 416 字节（16 B 主窗 + 400 B 子窗）。而 rev<3.0 **根本没有 subwindow**
 * （isp_awb.c:81-89 跳过配置），那 400 字节全是垃圾。
 * 连续模式 = 每帧 30 次这样的 ISR；oneshot = 每秒 1 次。
 * （官方文档 §A.4 / §D.4）
 *
 * 超时取 60 ms = 两个传感器帧周期（30 fps ⇒ 33.3 ms）。阻塞发生在帧泵任务里，
 * 而帧泵用的是 vTaskDelayUntil(100 ms) 的固定节拍：只要一拍内的总耗时
 * （取帧 + 统计 + 缩放 4.2 ms + 编码 9.1 ms + 本次阻塞 ≤35 ms）< 100 ms，
 * **帧率一点都不掉**。实测值必须写进 README。
 */
#define CAM_AWB_ONESHOT_MS  60

static esp_err_t camera_awb_fetch(cam_awb_hw_stat_t *out)
{
    isp_awb_stat_result_t res = {0};
    const esp_err_t err =
        esp_isp_awb_controller_get_oneshot_statistics(s_awb_ctlr, CAM_AWB_ONESHOT_MS, &res);
    if (err != ESP_OK)
        return err;
    out->counted = res.white_patch_num;
    out->sum_r = res.sum_r;
    out->sum_g = res.sum_g;
    out->sum_b = res.sum_b;
    return ESP_OK;
}
```

触发节奏：在 `camera_csi_tune_tick()` 里，**每 `CAM_AWB_INTERVAL_TICKS`（10 拍 = 1 秒）触发一次**，且**只在取流中**。T8 阶段拿到结果只打日志。

- [ ] **Step 4：统计侧的软件 BLC（**仅当 T7 判定基座 ≈16**）**

```c
/*
 * rev v1.0 用不了 ISP BLC；若 T7 实测传感器侧也压不掉基座，就在**统计上**减掉它：
 *   Σx' = Σx − p × counted
 * 硬件给的 counted 就是参与累加的像素数，所以这个减法是**精确**的（不是估计）。
 * 它修正的是白点估计（进而是 kr/kb 与 CCT），**修不了画面**——
 * 画面上的基座只能靠传感器 BLC 或降 CCM 强度处理，见计划 §D.3。
 */
#define CAM_STAT_BLC_PEDESTAL  0    /* T7 判定后填 0 或 16 */
```

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `白点=0` 恒定 | 筛选框太窄，或采样点/窗口没配上 | 临时把 rg/bg 放宽到 [0.1, 3.9]、亮度窗放宽到 [1, 764] 重测；若这时有白点，说明官方框与实际数据不同域 ⇒ **回到 §E.4 重新审视**（这会推翻 T9） |
| `白点=` 恒等于全画面像素数 | 筛选没生效（框被写成全域） | 检查浮点字段是不是被 0 初始化了 |
| `超时=` 在涨 | oneshot 的 60 ms 不够，或 ISP 没在取流 | 确认只在 `s_streaming` 时触发；把超时加到 100 ms 再看 |
| `拒收` 开始非零 / fps 掉到 9 以下 | oneshot 阻塞挤掉了帧泵预算 | 把触发挪到 `tud_video_n_frame_xfer()` **之后**（与 USB 传输重叠），或把周期拉到 2 秒 |
| `CCT` 恒定在 2289 或 7466（贴着端点） | rg 算错（分子分母颠倒），或 `sum_g=0` 没防 | 打印原始 Σr/Σg/Σb 核对 |
| `esp_isp_new_awb_controller` 返回 `1` | `intr_priority` 不一致 | 与 AE 一样填 0 |

---

## Task 9：L2 —— AWB **切到**硬件白点统计（⚠️ **本计划风险最高的一步**）

目标：把 AWB 的估计器从"软件灰世界 + 后置统计 + 增量公式"换成"硬件白点筛选 + 前置统计 + **绝对**增益公式"。**这是拓扑改动，不是参数改动。**

**Files:** Modify `main/cam_tune.h`, `main/cam_tune.c`, `main/camera_csi.c`, `test/test_cam_tune.c`

- [ ] **Step 1：成功判据**

1. **白纸测试**：对着白纸、正常室内光，30 秒内收敛；收敛后 `[自检] 画质 通道均值 R G B` **三个数彼此相差 < 5%**（这是白平衡准不准的唯一客观判据，与改动前同一条判据）；
2. **发散判据（最重要）**：连续静置 5 分钟，`R×`/`B×` 稳定不动（`死区内` 计数持续涨、`下发` 不涨）。**若增益缓慢单调爬升/下降，就是 §E.3 那个错误发生了，立刻回退**；
3. **换光源**：白炽灯 ↔ 日光灯来回切三次，每次都在 5~10 秒内重新收敛，且 `R×`/`B×` 回到各自光源下的同一组值（±3%）；
4. **单色场景**：镜头怼红墙 ⇒ `白点=` 掉到 < 5%、`未更新：白点太少=` 涨、增益**一步不动**（这是官方 `min_counted=1200` 门限替代我们旧的"色偏过大"防护）；
5. `实测 fps ≥ 9.0`、`拒收=0`；
6. 宿主机：`test_cam_tune.c` 原有 281 用例全过 + 新增 ≥ 20 条。

- [ ] **Step 2：`cam_tune.h` 的接口（**用类型系统防呆**）**

```c
/*
 * ── AWB 的统计来源 ────────────────────────────────────────────────
 * 0 = 软件灰世界（改动前，统计采在 **CCM 之后**）
 * 1 = ISP 硬件白点筛选统计（统计采在 **CCM 之前**，官方采样点）
 *
 * ⚠️⚠️ 这两条路的**建议值公式不同，而且不能互换**：
 *
 *   源=0：统计在 CCM 之后 ⇒ 改增益会改统计 ⇒ **闭环**
 *         sug = cur × g_mean / chan_mean        ← 必须乘 cur，否则不幂等
 *   源=1：统计在 CCM 之前 ⇒ 改增益**不影响**统计 ⇒ **开环前馈**
 *         sug = Σg / Σchan                      ← 绝不能乘 cur，乘了就单调发散
 *
 * 把源=0 的公式用在源=1 上，每一拍都会把已生效的增益再乘一遍，增益单调跑到限位；
 * 现场表现是"颜色缓慢越来越偏，而所有计数器都显示一切正常"—— 最难归因的那一类。
 * 防呆做法：两条路各自一个函数，源=1 的 cam_awb_step_hw() **签名里根本没有
 * cur_r/cur_b**，写不出乘 cur 的代码。
 */
#define CAM_AWB_SOURCE  1

/* 硬件白点统计的一次采样。counted 是参与累加的像素数（硬件给的，不是估计）。 */
typedef struct {
    uint32_t counted;
    uint32_t sum_r, sum_g, sum_b;
} cam_awb_hw_stat_t;

/*
 * 走一拍（硬件统计版）。**每个 AWB 周期调一次**，不是每帧。
 * 返回 CAM_AWB_APPLIED 表示 st->gain_r/b_milli 变了、必须重配 CCM。
 *
 * 与 cam_awb_step() 的判据差异（全部改成官方标定值）：
 *   ① "色偏过大"防护**取消** —— 它是灰世界时代对"单色场景"的整幅级近似，
 *      而硬件白点筛选是像素级的、且筛选框来自官方标定（rg/bg 的包围盒恰好就是
 *      白点轨迹 bp 的包围盒），比猜的阈值可信。这一路上 SKIP_CAST 恒为 0。
 *   ② 新增"白点太少"：counted < CAM_CAL_MIN_COUNTED(1200，官方 awb.min_counted)
 *      ⇒ 统计不可信，整拍不动。它替代了 ①。
 *   ③ "暗场/过亮"防护**取消** —— 硬件的 white_patch.luminance 窗（165~533，
 *      由官方 green 范围与 rg/bg 范围推导）已经在像素级做了同一件事。这一路上
 *      SKIP_DARK / SKIP_BRIGHT 恒为 0。
 *   ④ 增益上限从 3000 抬到 3445：官方白点轨迹的端点给出 kb 最大 = 1/0.2903 = 3.445
 *      （2289 K 的白炽灯）。旧的 3000 会在暖光下顶住，表现为"白炽灯下永远偏黄"。
 *      3.445 < 4.0 ⇒ CCM 折叠的 t=0 退化路径永远可行（计划 §D.4）。
 *   ⑤ 阻尼与单步限幅**保留、但理由变了**：不再是环路稳定性（已经没有环了），
 *      而是对估计噪声的时域平滑。数值不动，免得同时改两件事。
 *
 * 那三个恒为 0 的计数器**保留不删**：CAM_AWB_SOURCE=0 的回退路径还要用，
 * 而且"它恒为 0"本身就是一条现场信息（说明确实走的是硬件路）。
 */
cam_awb_reason_t cam_awb_step_hw(cam_awb_state_t *st, const cam_awb_hw_stat_t *s,
                                 bool ae_converged);

/* 上限改动（下限 1000 不变：绿通道恒为三者最强，R/B 相对 G 的增益物理上 ≥1）。 */
#undef  CAM_AWB_GAIN_MAX_MILLI
#define CAM_AWB_GAIN_MAX_MILLI 3445
```

`cam_awb_reason_t` 追加一项（放在 `SKIP_AE` 之后，自检行按枚举顺序打）：

```c
    CAM_AWB_SKIP_COUNT,    /* 白点太少（counted < 官方 min_counted）：统计不可信 */
```

- [ ] **Step 3：`cam_awb_step_hw()` 的实现**

```c
cam_awb_reason_t cam_awb_step_hw(cam_awb_state_t *st, const cam_awb_hw_stat_t *s,
                                 bool ae_converged)
{
    if (!st || !s)
        return CAM_AWB_SKIP_PERIOD;

    if (!ae_converged)
        return awb_done(st, CAM_AWB_SKIP_AE);
    if (s->counted < CAM_CAL_MIN_COUNTED || s->sum_g == 0)
        return awb_done(st, CAM_AWB_SKIP_COUNT);

    /* 可选的统计侧黑电平减法（T7 判定后才可能非 0）。
     * counted 是精确的参与像素数 ⇒ 这个减法是精确的。 */
    uint64_t sr = s->sum_r, sg = s->sum_g, sb = s->sum_b;
#if CAM_STAT_BLC_PEDESTAL
    const uint64_t ped = (uint64_t)CAM_STAT_BLC_PEDESTAL * s->counted;
    sr = sr > ped ? sr - ped : 0;
    sg = sg > ped ? sg - ped : 0;
    sb = sb > ped ? sb - ped : 0;
    if (sg == 0)
        return awb_done(st, CAM_AWB_SKIP_COUNT);
#endif

    /* ⚠️ 溢出：Σ 最大 = 921600 × 255 = 2.35e8，乘 1000 会溢出 uint32 ⇒ 全程 uint64。 */
    const uint32_t rg_q4 = (uint32_t)(sr * 10000u / sg);      /* R/G ×10000 */
    const uint32_t bg_q4 = (uint32_t)(sb * 10000u / sg);      /* B/G ×10000 */

    /* 白点必须落在官方轨迹的包围盒里（= awb.range，也就是 bp 的包围盒）。
     * 硬件已经按同一组数逐像素筛过一遍了，这里判的是**累加之后的重心** ——
     * 边界附近的像素能通过逐像素筛选，但重心跑出盒子说明场景不是中性的。 */
    if (rg_q4 < CAM_CAL_RG_MIN || rg_q4 > CAM_CAL_RG_MAX ||
        bg_q4 < CAM_CAL_BG_MIN || bg_q4 > CAM_CAL_BG_MAX)
        return awb_done(st, CAM_AWB_SKIP_RANGE);

    /* ══ 绝对增益。**没有 cur**，看签名就知道乘不进去。══ */
    const uint32_t sug_r = 10000000u / rg_q4;    /* = (1/rg) × 1000，单位 1/1000 */
    const uint32_t sug_b = 10000000u / bg_q4;

    if (st->settle) { st->settle--; return awb_done(st, CAM_AWB_SKIP_PERIOD); }
    st->settle = CAM_AWB_INTERVAL_TICKS > 0 ? CAM_AWB_INTERVAL_TICKS - 1 : 0;

    if (diff_pct(sug_r, st->gain_r_milli) <= CAM_AWB_DEADBAND_PCT &&
        diff_pct(sug_b, st->gain_b_milli) <= CAM_AWB_DEADBAND_PCT) {
        if (st->in_band < CAM_AWB_CONVERGE_TICKS) st->in_band++;
        return awb_done(st, CAM_AWB_SKIP_BAND);
    }

    const uint32_t next_r = awb_next(st->gain_r_milli, sug_r);   /* 阻尼→限幅→范围，原样复用 */
    const uint32_t next_b = awb_next(st->gain_b_milli, sug_b);
    if (next_r == st->gain_r_milli && next_b == st->gain_b_milli)
        return awb_done(st, CAM_AWB_SKIP_QUANT);

    st->gain_r_milli = next_r;
    st->gain_b_milli = next_b;
    st->in_band = 0;
    st->updates++;
    return awb_done(st, CAM_AWB_APPLIED);
}
```

⚠️ 注意 `settle` 的位置：与旧函数一致，**排在场景可信度判据之后**（场景不可信的那段时间不算进更新周期）。

- [ ] **Step 4：宿主机新增用例（≥ 20，其中三条是这一步的命门）**

| 用例 | 判据 |
|---|---|
| **不动点收敛**：固定 `Σr/Σg/Σb`，连喂 200 拍 | 增益收敛到 `1/rg`、`1/bg` 并**停住**（最后 50 拍 `Δ == 0`）。**旧公式若被误用，这条立刻发散到 3445** |
| **幂等**：把增益预置成正确值再喂同一份统计 | 第一拍就返回 `SKIP_BAND`，`updates == 0` |
| `counted = 1199` / `1200` | 前者 `SKIP_COUNT`，后者放行（边界精确） |
| `sum_g = 0` | `SKIP_COUNT`，不除零 |
| `Σ` 取满量程 `921600×255` | 不溢出（用 uint64 验算） |
| rg/bg 各自越界的四种组合 | 全部 `SKIP_RANGE` |
| `ae_converged=false` | `SKIP_AE`，且**不消耗 settle** |
| 统计侧 BLC：`p=16` 打开/关闭 | 打开后 rg 更偏离 1（更接近真实白点），数值手算可核对 |
| 单步限幅：从 1000 跳到 3445 | 需要 ≥ 6 个周期（25%/次），全程单调 |

- [ ] **Step 5：接线**

```c
static void camera_awb_tick(const cam_frame_stats_t *st)
{
    const bool ae_stable = !s_ae_ready || cam_ae_converged(&s_ae);
#if CAM_AWB_SOURCE
    if (--s_awb_phase == 0) {                       /* 每 CAM_AWB_INTERVAL_TICKS 拍触发一次 */
        s_awb_phase = CAM_AWB_INTERVAL_TICKS;
        cam_awb_hw_stat_t hw = {0};
        s_awb_stat_err = camera_awb_fetch(&hw);
        if (s_awb_stat_err != ESP_OK)
            return;                                 /* 超时：这一拍不动 */
        s_awb_hw_last = hw;                         /* 自检行用 */
        if (cam_awb_step_hw(&s_awb, &hw, ae_stable) != CAM_AWB_APPLIED)
            return;
    } else {
        return;
    }
#else
    if (cam_awb_step(&s_awb, st->lum_mean, st->r_mean, st->g_mean, st->b_mean,
                     ae_stable) != CAM_AWB_APPLIED)
        return;
#endif
    s_awb_last_err = camera_ccm_apply(s_awb.gain_r_milli, s_awb.gain_b_milli);
    ... 原样不动的回滚逻辑 ...
}
```

> ⓘ 触发点放在 `camera_csi_tune_tick()` 里意味着 60 ms 的阻塞发生在**取帧之后、缩放之前**。
> 若 Step 1 的判据 5（fps/拒收）不过，按 T8 Step 5 的建议把触发挪到 `uvc_stream.c` 提交之后。
> **那是本计划里唯一允许改 `uvc_stream.c` 的地方，且只能加一个函数调用，不许碰提交逻辑。**

- [ ] **Step 6：⛔ 放弃/回退判定**

**满足任意一条即 `CAM_AWB_SOURCE 0` 回退，并把结论写进 README，L3 的 T10 仍可继续（CCM 用回退路径的增益一样能折叠）**：

- 判据 2（发散）不成立，且穷尽 Step 7 的归因表仍找不到原因；
- 判据 1（白纸三通道差 <5%）在三种光源下都不成立，而 `CAM_AWB_SOURCE=0` 时成立；
- fps 掉到 9 以下且挪触发点也救不回来。

- [ ] **Step 7：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| **增益单调爬到 3445 或掉到 1000** | 公式里乘了 `cur`（§E.3 的经典错） | 检查 `cam_awb_step_hw()` 里有没有出现 `st->gain_*` 参与建议值计算 |
| 增益在两个值之间来回跳 | 死区太窄 / 统计噪声大 | 先看 `白点=` 占比，太低就加大周期；再考虑把 `CAM_AWB_DEADBAND_PCT` 从 5 抬到 8 |
| 白纸下三通道均值差很大但增益不动 | `SKIP_BAND` 在骗人 —— 建议值≈当前值但画面不中性 ⇒ 说明**统计域与观察域不一致**（统计在 CCM 前、观察在 CCM 后） | 这是**预期**的：CCM 是对角阵时两者应当一致；若不一致，说明 CCM 没生效或 LSC/BF 改了通道比 ⇒ 先看 `CCM=` |
| `白点太少` 一直涨（正常场景下） | 亮度窗 165~533 与我们的实际信号电平不匹配（比如 AE 目标改了之后整体偏暗） | 打印 Σg/counted（= 平均 G 值）核对；必要时按实测把 `green` 范围等比缩放，**并在 cam_tune.h 写明偏离官方值的理由** |
| CCT 与肉眼判断相反 | rg/bg 颠倒，或 CCT 表方向反了 | 宿主机用例 C 已覆盖表方向，先查 rg 的分子分母 |

---

## Task 10：L3 —— 官方 19 档 CCM 按 CCT 插值 + WB 折叠 + 强度钳制

> **前置：T7 的判定点必须已放行**（§D.3 / T7 Step 4）。

目标：把今天的对角阵 `diag(kr,1,kb)` 换成官方标定的色彩校正矩阵，并按 §D.4 的强度参数把系数钳进 rev v1.0 的 S2.10。**这是"色彩还原"从无到有的一步**，也是全计划色彩上变化最大的一步。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行：
   ```
   [自检] CCM 模式=官方表 CCT=5480K 档11/12(w=0.42) 强度=100% 
          矩阵 [2.041 -0.775 -0.274 | -0.399 1.613 -0.224 | -0.309 -0.503 1.802] ×W
          → 下发 [3.727 -0.775 -0.481 | -0.729 1.613 -0.393 | -0.564 -0.503 3.161]
   ```
2. **白纸不变色**：对白纸时 `通道均值 R G B` 三个数仍然相差 < 5%（§D.2 的行和不变式的现场验证 —— **换了 CCM 之后白还是白**）；
3. **彩色物体明显更准**：拍一张有饱和红/绿/蓝的东西（色卡最好，没有就用红色可乐罐 + 绿植 + 蓝色文件夹），与 `CAM_CCM_MODE 0` 的截图并排比 —— 饱和度与色相都应更接近肉眼；
4. **强度钳制看得见**：把光源换成白炽灯（CCT 掉到 3000 K 以下），`强度=` 应当从 100% 掉到 40%~65%（§D.4 的表预测 3055 K → 42%、3473 K → 65%）；换回日光 ⇒ 回到 100%；
5. `esp_isp_ccm_configure()` **恒 `ESP_OK`**（`CCM=ESP_OK`）—— 强度钳制的全部意义就是保证这一条；
6. **黑位**：盖住镜头，`最暗 r/g/b` 与 T7 Step 3 测到的一致（±3）。若出现 `r` 和 `b` 明显高于 `g`（品红黑位），就是 §D.3 的问题，按 T7 判定点的降级栏处理；
7. `实测 fps ≥ 9.0`；`重配=` 每秒 ≤ 1。

- [ ] **Step 2：`cam_tune.h`**

```c
/*
 * ── CCM 的形态 ────────────────────────────────────────────────────
 * 0 = 对角阵 diag(kr, 1, kb)（改动前的行为，只做白平衡、不做色彩还原）
 * 1 = 官方 19 档色温标定矩阵按 CCT 插值，再把白平衡增益**右乘**折进去
 *
 * 为什么折叠是对的（不是将就）：官方矩阵的每一行系数之和 ≈ 1.0，前提是白平衡
 * 已由 WBG 在 RAW 域做掉。我们没有 WBG（rev v1.0），于是走官方 rev<3.0 的同一条
 * 降级路：P = M · diag(kr,1,kb)。因为 WBG 与 demosaic 都是逐通道线性算子、可交换，
 * 这个右乘与"先 WBG 再 CCM"**数学等价**；且对中性面 w=(1/kr,1,1/kb) 有
 *   P·w = M·(1,1,1)ᵀ = (行和,行和,行和)ᵀ = (1,1,1)ᵀ
 * ⇒ **行和为 1 这个标定前提被右乘完整保持**，中性面出来仍精确中性、增益仍精确为 1。
 * （完整推导见计划 §D.1/§D.2；官方源码依据见官方文档 §C.8 的 isp_init_ccm_param()。）
 *
 * 真正被破坏的只有**定点范围**：rev v1.0 的 CCM 是 S2.10，系数上限 4.0，而官方
 * 2292 K 那一档本身就含 4.5445 —— 折进 kb=3.44 之后最大系数到 15.6。
 * 解法是下面的强度参数，不是缩放矩阵，理由见 CAM_CCM_STRENGTH_MAX。
 */
#define CAM_CCM_MODE  1

/*
 * ── 色彩还原强度的上限（0..256，256 = 官方矩阵全量）────────────────
 *
 * 实际强度由 cam_ccm_fold_wb() 二分求出：取满足所有 9 个系数 |v| <= 3.990 的**最大** t，
 * 其中 M(t) = (1−t)·I + t·M。为什么是"朝单位阵混合"而不是"整体乘一个 α 缩小"：
 *   · M(t) 的行和恒为 1 ⇒ 白还是白、**整体增益精确为 1**，一点亮度都不损失；
 *     整体缩放则要 AE 补 1/α 的曝光（2292 K 档 α=0.256 ⇒ 多 2 EV 噪声，而低色温场景
 *     多半本来就暗，正是最不该加噪声的地方）。
 *   · t = 0 时 P 退化成 diag(kr,1,kb) —— **正是本改动之前已实机验证过的那条路径**。
 *     也就是说钳到底的"最坏情况"就是"回到已知可用状态"，不引入任何新的失败模式。
 * 实测参考（用官方白点轨迹反推的自洽增益，见计划 §D.4）：
 *   4193~5770 K 原样装得下（t=256）；6000/6554 K 需 t≈241/225；
 *   3800 K t≈212；3473 K t≈166；3055 K t≈107；2517 K t≈26；2292 K t≈10。
 *
 * 这个宏是**总闸**：黑位色偏（计划 §D.3）或高增益噪点被 CCM 放大到不可接受时，
 * 把它调小（192 = 75%）即可全局压低，不必改任何表。
 */
#define CAM_CCM_STRENGTH_MAX  256
```

- [ ] **Step 3：`camera_ccm_apply()` 改写**

```c
static esp_err_t camera_ccm_apply(uint32_t r_milli, uint32_t b_milli)
{
    float m[3][3];
#if CAM_CCM_MODE
    int32_t base[9], folded[9];
    cam_ccm_at_cct(s_cct_k, base);                       /* 19 档按 CCT 逐元素线性插值 */
    s_ccm_t = cam_ccm_fold_wb(base, r_milli, b_milli, folded);
    if (s_ccm_t > CAM_CCM_STRENGTH_MAX) {                /* 总闸 */
        s_ccm_t = CAM_CCM_STRENGTH_MAX;
        cam_ccm_fold_at_public(base, r_milli, b_milli, s_ccm_t, folded);
    }
    for (int i = 0; i < 9; i++)
        m[i / 3][i % 3] = folded[i] / 1000.0f;
#else
    s_ccm_t = 0;
    m[0][0] = r_milli / 1000.0f; m[0][1] = 0.0f; m[0][2] = 0.0f;
    m[1][0] = 0.0f; m[1][1] = CAM_CCM_GAIN_G_MILLI / 1000.0f; m[1][2] = 0.0f;
    m[2][0] = 0.0f; m[2][1] = 0.0f; m[2][2] = b_milli / 1000.0f;
#endif
    const esp_isp_ccm_config_t ccm_cfg = {
        .matrix = { {m[0][0], m[0][1], m[0][2]},
                    {m[1][0], m[1][1], m[1][2]},
                    {m[2][0], m[2][1], m[2][2]} },
        /*
         * ⚠️ saturation 保持 true，但**它不该被用到**：强度钳制已经保证所有系数
         * |v| <= 3.990，落在 S2.10 的表达范围内。saturation=true 只是最后一道
         * "宁可饱和也不要整个配置失败"的网 —— 一旦它真的生效，硬件里的矩阵就与
         * 自检行打出来的不是同一个，那才是最坏的情况（画面错了而日志说没错）。
         * 所以判据 5 要求 CCM 恒 ESP_OK 且强度 < 100% 时必须有对应的低色温。
         */
        .saturation = true,
        .flags = { .update_once_configured = 1 },
    };
    const esp_err_t err = esp_isp_ccm_configure(s_isp, &ccm_cfg);
    if (err == ESP_OK) { s_ccm_r = r_milli; s_ccm_b = b_milli; }
    return err;
}
```

CCT 的来源：`camera_awb_tick()` 里拿到 `rg_q4` 后 `s_cct_k = cam_cct_from_rg(rg_q4)`。
`CAM_AWB_SOURCE = 0` 时没有 rg ⇒ `s_cct_k` 保持默认 **5210 K**（LSC 中间档同一个数），此时 CCM 用一个固定色温的矩阵 —— 仍然比对角阵好，且行为完全确定。

- [ ] **Step 4：重配节奏与迟滞**

CCM 只在下面两种情况下重配：① AWB 判定 `APPLIED`（≤1 Hz）；② CCT 跨过一个档的边界且过了 `CAM_FEEDFWD_HYST_TICKS`。**不要每帧重配** —— 无影子寄存器，帧中途换 9 个系数会撕裂。

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `CCM=ESP_ERR_INVALID_ARG` | 强度钳制没生效或阈值写成了 4000 | 阈值必须是 **3990**；打印 `max\|v\|` 核对 |
| 白纸变成偏色（行和不变式破了） | CCT 插值把矩阵插坏了（比如跨过 1200 K 那个单位阵档） | 检查 `cam_ccm_at_cct` 的越界钳位；宿主机用例 D 已覆盖 19 档行和 |
| 颜色过饱和、发"荧光" | 强度太高 / CCT 估偏（估成日光但实际是暖光） | 先看 `CCT=` 对不对；再把 `CAM_CCM_STRENGTH_MAX` 降到 192 |
| 黑位发品红 | §D.3 的黑电平问题 | 回 T7 判定点的降级栏 |
| 暗处噪点比 `CCM_MODE 0` 明显 | CCM 的大负非对角项放大噪声（**预期代价**） | 提高 BF 档（T2 的断点）或降强度；写进 README 的已知代价 |
| 换光源时颜色"跳" | CCM 与 AWB 同一拍一起变，且没有影子寄存器 | 把 CCT 的迟滞加大到 5 拍 |

- [ ] **Step 6：回退** —— `CAM_CCM_MODE 0`。回到对角阵，即 T9 之前已验证的色彩表现。

---

## Task 11：L2 —— 直方图统计上线 + `env.luma` 重建（纯观测）

目标：建直方图控制器，用它算出**近似均匀加权**的场景均值与亮/暗占比，并按 §E.5 重建 `env.luma`。**这一步不改任何控制行为**，只为 T12 提供索引量并验证 §E.5 的重建是否站得住。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. 自检行：
   ```
   [自检] HIST 触发=NN 超时=0 场景均值=63 亮块=4% 暗块=11% | ev=988 env.luma=253.0 → gamma档3
          bin: 210 1832 4410 ... （16 个）
   ```
2. 16 个 bin 之和 ≈ 参与统计的像素数（整幅 921600 —— **若明显小于它，说明权重或窗口配错了**）；
3. 遮住镜头 ⇒ 直方图整体左移、`暗块=` 冲到 80% 以上；手电照 ⇒ `亮块=` 涨；
4. **`env.luma` 的量程验证（§E.5 的判据）**：从明亮日光走到昏暗室内，`env.luma` 应当**跨过至少两个官方断点**（151 / 301 / 901 / 3001），即 `gamma档` 至少变化两次。**若四档只用得到一档，§E.5 的重建就是错的** ⇒ 走 Step 5 的降级；
5. `触发=` 每秒 +1；`超时=0`；alt 0 下不涨；`实测 fps ≥ 9.0`。

- [ ] **Step 2：配置（三处硬校验，一处都不能错）**

```c
#include "driver/isp_hist.h"

static isp_hist_ctlr_t s_hist_ctlr;
static int32_t s_st_hist = STEP_NOT_RUN;

    const esp_isp_hist_config_t hist_cfg = {
        /* ⚠️ 与 AE 同一个坑：驱动按 /5 分块，全零窗口 ⇒ bsize=0 ⇒ 结果全 0。 */
        .window = { .top_left = {0, 0}, .btm_right = {CAM_SENSOR_W, CAM_SENSOR_H} },
        /* RGB 模式 ⇒ 抽头在 demosaic 之后（官方框图 §A.1 的三选一里的中间那个），
         * 与 AE 同域、且在 gamma 之前 ⇒ T12 加 gamma 不会扰动它。
         * 官方 esp_video 的默认也是 ISP_HIST_SAMPLING_RGB（官方文档 §C.10）。 */
        .hist_mode = ISP_HIST_SAMPLING_RGB,
        /*
         * ⚠️ RGB 系数：驱动要求三个 integer 域为 0（即都 < 1.0），
         *    且文档要求小数部之和 = 256。256/3 除不尽 ⇒ 取 86/85/85。
         *    （这与官方 esp_video 的 85/85/85 只差 1 —— 那个和是 255，
         *     驱动并不检查系数和，只检查权重和，所以两者都能配上；
         *     我们取 86/85/85 让它精确为 256，量纲上更干净。）
         */
        .rgb_coefficient = { .coeff_r = { .integer = 0, .decimal = 86 },
                             .coeff_g = { .integer = 0, .decimal = 85 },
                             .coeff_b = { .integer = 0, .decimal = 85 } },
        /*
         * ⚠️ 25 个权重的小数部之和**必须精确等于 256**
         *    （s_esp_isp_hist_config_hardware() 的 weight_sum == 256，不等就 INVALID_ARG），
         *    而 256/25 除不尽。取 IDF 测试用的那组：中心块 16，其余 24 块各 10
         *    ⇒ 24×10 + 16 = 256。
         *    这里要的是**近似均匀**的场景均值（对应官方 ian.luma.env.weight 全 1），
         *    与 AE 的中心加权金字塔（agc.luma_adjust.weight）是**两张不同的表、两个不同的量**
         *    —— 官方把它们分开正是为了让 gamma 不跟着 AE 的测光抖（官方文档 §B.4.2）。
         */
        .window_weight = { {.integer=0,.decimal=10}, ... 中心那个 16 ... },
        /* ⚠️ 15 个阈值必须**严格落在 (0, 256)**，写 0 会被拒。取 16 的整数倍，
         *    与 IDF/官方一致，于是 16 个 bin 各覆盖 16 个码值。 */
        .segment_threshold = {16,32,48,64,80,96,112,128,144,160,176,192,208,224,240},
        /* ⓘ esp_isp_hist_config_t **没有 intr_priority 字段** —— 直方图的 ISR 直接
         *   复用处理器的优先级，不存在 AE/AWB 那个"三块必须一致"的坑。 */
    };
    s_st_hist = esp_isp_new_hist_controller(s_isp, &hist_cfg, &s_hist_ctlr);
    if (s_st_hist == ESP_OK)
        s_st_hist = esp_isp_hist_controller_enable(s_hist_ctlr);
```

- [ ] **Step 3：触发节奏 —— 与 AWB 错开**

直方图同样用 **oneshot**（`esp_isp_hist_controller_get_oneshot_statistics`，超时 60 ms），每秒一次。**⚠️ 必须与 AWB 的 oneshot 错开半个周期**（AWB 在第 0 拍、直方图在第 5 拍），否则一拍里两次 60 ms 阻塞叠加，帧泵预算 100 ms 会被吃掉 120 ms，`拒收` 立刻非零。

```c
/* AWB 在 phase==0 触发，HIST 在 phase==5 触发（周期 10 拍 = 1 秒）。 */
#define CAM_HIST_PHASE  5
```

- [ ] **Step 4：`env.luma`**

```c
    /* ev 是 AE 状态机里已经维护的量化后实际曝光量 = 曝光行数 × 增益。 */
    s_env_q1 = cam_env_luma_q1(s_ae.ev, s_hist_mean, CAM_AE_TARGET);
    s_gamma_slot_want = cam_gamma_slot(s_env_q1, s_gamma_slot_want);
```
T11 只打印 `s_gamma_slot_want`，**不下发**。

- [ ] **Step 5：§E.5 站不住时的降级（必须先写好，不要临场发挥）**

若判据 4 不成立（四档只用得到一档，或 env 恒在 3001 以上/151 以下）：

```c
/*
 * env.luma 的重建（k=250000 / ev）是 [反推]，不是 [确证]。实测判定它不成立时改用
 * 这条：直接按 ev 的四分位选 gamma 档 —— 断点用**我们自己**测出来的四个 ev 值，
 * 并在下面写清楚它们是怎么测的（哪种光照、AE 收敛后的 ev 是多少）。
 * gamma 的四条曲线仍然是官方的，只是索引换成了我们自己的量。
 */
#define CAM_ENV_MODEL  1   /* 1 = 官方 k/ev 重建；0 = 自测 ev 四分位 */
#define CAM_ENV_EV_BREAKS { 833, 2775, 8306, 16556 }   /* 实测后按需替换 */
```

- [ ] **Step 6：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `esp_isp_new_hist_controller` 返回 `ESP_ERR_INVALID_ARG` | 权重和 ≠ 256 / 某个 integer 域非 0 / 阈值含 0 | 三条逐条核对（Step 2 的三个 ⚠️） |
| 16 个 bin 全 0 | 窗口 bsize=0，或没触发 | 同 AE 的窗口坑 |
| bin 之和远小于 921600 | 权重把大部分块压成 0（我们没有 0 权重）或窗口小了 | 打印窗口实际值 |
| `拒收` 非零 | 两个 oneshot 撞在同一拍 | 见 Step 3 的错相 |
| `env.luma` 恒为 0 | `ev=0`（AE 没就绪） | `s_ae_ready` 为 false 时应打 `env=n/a` 而不是 0 |

---

## Task 12：L1+L2+L3 —— Gamma 上线 + AE 目标官方化 + 按 env 选档 + 背光切目标

> ⚠️ **这四件事必须在同一个任务里做完**，因为它们在数学上是耦合的：加 gamma 会把显示域亮度整体抬高，不同时把 AE 目标从"我们的等价值"换成"官方值"，画面必然过亮（§E.1 给了具体数字）。这是本计划里唯一一处**故意**打破"一个任务一个变量"的地方，理由写在这里。
>
> 同时这也解释了为什么 gamma 排在这么后面：**在 AE（T6）与 AWB（T9）都还吃"ISP 输出"的软件统计时，加 gamma 会污染两个闭环的输入**（gamma 是逐通道非线性映射，通道均值的比值会被压向 1，灰世界当场失效）。只有当三个统计都搬到 gamma 上游的硬件抽头之后，gamma 才真正是一个"纯前向级"。
> **这一条与"先做不改变闭环行为的前向级"这个排序原则相抵触，以证据为准。**

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. `[自检] Gamma=ESP_OK 档2(γ=0.605) env=253.0 切换=3`；
2. **画面观感是本任务的主判据**：与改动前并排比，暗部细节明显增多、整体不再"发闷"（线性域编码在 sRGB 显示器上看就是暗部压死）；**不过亮**（`最亮` 不应大面积贴 255）；
3. AE 仍然收敛，目标显示为官方值：`亮度 60→目标 59(56~64)`；
4. **从明亮走到昏暗**，`档` 从 3 降到 1 或 0，`切换=` 每次只 +1（迟滞生效，不来回跳）；
5. **背光**：让画面出现一扇亮窗（`亮块 ≥ 25%` 且 `场景均值 < 56`）⇒ 自检行 `优先级=暗部` 且目标变成 63；转开镜头 ⇒ 回到 `优先级=高光`、目标 59；
6. `实测 fps ≥ 9.0`；`重配=` 每秒 ≤ 1。

- [ ] **Step 2：`cam_tune.h`**

```c
/*
 * ── Gamma ─────────────────────────────────────────────────────────
 * 0 = 不配 gamma，ISP 输出仍是**线性光**（改动前的行为）
 * 1 = 配官方 4 档 γ 曲线
 *
 * 为什么必须有：我们把线性光的码值直接塞进 JPEG 送给 host，而 host 按 sRGB 显示
 * ⇒ 暗部被压死、整体发闷。今天靠把 AE 目标抬到 120（线性域的一半量程）硬凑观感，
 * 代价是高光容易削顶。官方管线在 RGB2YUV 之前有 gamma，AE 目标才能定在 62。
 *
 * ⚠️ 与 CAM_AE_TARGET **强耦合**：γ=0.605 时 255×(62/255)^0.605 ≈ 110（显示域），
 *   而线性域 120 不加 gamma 时显示域也是 120 —— 两者观感相近。
 *   若只开 gamma 不改目标：255×(120/255)^0.605 ≈ 152，明显过亮。
 *   **这两个宏必须一起改，不许分两次。**
 */
#define CAM_GAMMA_ENABLE    1
#define CAM_GAMMA_ADAPTIVE  1    /* 0 ⇒ 钉在 CAM_GAMMA_SLOT_FIXED 档 */
#define CAM_GAMMA_SLOT_FIXED 2   /* γ=0.605，官方四档里的第 3 档（日常室内） */

/*
 * ── AE 目标：换成官方值 ────────────────────────────────────────────
 * 官方 agc.luma_adjust = {target_low 56, target 62, target_high 64}，
 * 测在与我们相同的采样点（AFTER_DEMOSAIC，线性 RGB 亮度，8 bit）。
 * 死区**不对称**（−6/+2），偏向"宁可略暗"，与 high_light_priority 的取向一致。
 *
 * 高光/暗部优先的目标偏移（官方 agc.{high,low}_light_priority.luma_offset）：
 *   高光优先 −3 ⇒ 目标 59（保高光不过曝，官方 agc.mode 对这颗传感器就是它）
 *   暗部优先 +1 ⇒ 目标 63（保暗部细节）
 * ⓘ 官方那两块里还各有一个 weight_offset（对落在某亮度区间的块加权 +5），
 *   以及 light_threshold_priority[5] 的阶梯表 —— **触发条件与叠加方式是 [缺口]**，
 *   猜错的加权比不加权更坏，所以本工程只取 luma_offset。
 */
#undef  CAM_AE_TARGET
#undef  CAM_AE_TARGET_LOW
#undef  CAM_AE_TARGET_HIGH
#define CAM_AE_TARGET       62
#define CAM_AE_TARGET_LOW   56
#define CAM_AE_TARGET_HIGH  64
#define CAM_AE_HL_OFFSET    (-3)
#define CAM_AE_LL_OFFSET    (+1)

/*
 * ── 背光判据（官方的模式选择器是 [缺口]，这是我们给出的可解释版本）────
 * "画面里有一大片很亮的东西，而整体却偏暗" —— 这正是逆光/背光。
 * 亮块占比用直方图的最高两个 bin（>224），场景均值用直方图的均匀加权均值
 * （= 官方 ian.luma.env 的口径），两者都来自同一次直方图采样。
 * 25% / target_low 这两个数是我们定的，不是官方的，所以放在这里而不是 cam_isp_cal.h。
 */
#define CAM_BACKLIGHT_ENABLE      1
#define CAM_BACKLIGHT_BRIGHT_PCT  25
```

- [ ] **Step 3：gamma 下发**

```c
#if CAM_GAMMA_ENABLE
#include "driver/isp_gamma.h"

/*
 * x 栅格固定为 16,32,…,240,255。
 * ⚠️ 硬件约束：pt[0].x 必须是 2 的幂，相邻差也必须是 2 的幂，末点必须是 255
 *   且末段差按 256−240 算（esp_isp_gamma_configure() 的校验）。
 *   16 的等间距同时满足这三条，也正是 esp_isp_gamma_fill_curve_points() 生成的栅格。
 * y 值由提取脚本按 y=round(255·(x/255)^γ) 算好写在 cam_isp_cal.h 里 ——
 *   ① 官方 use_gamma_param=true，说明曲线由 γ 解析生成而不是用 JSON 里的 y[16]
 *      （本次实施还验证过：那 16 个 y 值在任何 2 的幂栅格上都拟合不出 γ=0.5，
 *       说明它们不是这个栅格上的采样，直接用会画错曲线）；
 *   ② 片上不需要 powf，也就不需要 libm 和浮点开销。
 */
static esp_err_t camera_gamma_apply(uint32_t slot)
{
    isp_gamma_curve_points_t pts;
    for (int i = 0; i < ISP_GAMMA_CURVE_POINTS_NUM; i++) {
        pts.pt[i].x = (i == ISP_GAMMA_CURVE_POINTS_NUM - 1) ? 255 : (uint8_t)(16 * (i + 1));
        pts.pt[i].y = cam_cal_gamma_y[slot][i];
    }
    /* 官方三通道用同一条曲线（JSON 只有一组 y；官方示例也是三通道同曲线）。 */
    esp_err_t err = esp_isp_gamma_configure(s_isp, COLOR_COMPONENT_R, &pts);
    if (err == ESP_OK) err = esp_isp_gamma_configure(s_isp, COLOR_COMPONENT_G, &pts);
    if (err == ESP_OK) err = esp_isp_gamma_configure(s_isp, COLOR_COMPONENT_B, &pts);
    return err;
}
#endif
```

初次 `esp_isp_gamma_enable(s_isp)` 在 `camera_csi_init()` 里配完三条曲线之后调一次（有 FSM 门）。换档时只 `configure`。

- [ ] **Step 4：背光 → AE 目标**

```c
static int camera_ae_target(void)
{
    int t = CAM_AE_TARGET;
#if CAM_BACKLIGHT_ENABLE
    s_backlight = (s_hist_bright_pct >= CAM_BACKLIGHT_BRIGHT_PCT &&
                   s_hist_mean < CAM_AE_TARGET_LOW);
    t += s_backlight ? CAM_AE_LL_OFFSET : CAM_AE_HL_OFFSET;
#else
    t += CAM_AE_HL_OFFSET;
#endif
    return t;
}
```

`cam_ae_step()` 的目标改成由调用方传入（多一个参数），死区仍用 `CAM_AE_TARGET_LOW/HIGH` 相对偏移。**同步改 `test_cam_tune.c`：281 个用例里凡是依赖固定目标的都要传显式目标，用例总数只增不减。**

- [ ] **Step 5：失败归因**

| 现象 | 归因 | 下一步 |
|---|---|---|
| `Gamma=ESP_ERR_INVALID_ARG` | x 栅格不满足 2 的幂约束（比如把末点写成 256） | 末点必须是 **255**，驱动内部按 256 算末段差 |
| 画面过亮、高光大片削顶 | AE 目标没跟着改 | 两个宏必须一起改（Step 2 的 ⚠️） |
| 画面过暗 | γ 档选反了（暗环境选了大 γ） | γ 越小提亮越强；官方是暗→0.5、亮→0.655 |
| 暗部噪点明显 | 正常代价：γ=0.5 把暗部拉起来的同时拉起了噪声 | 这正是官方在暗环境用更强 BF（T2 的 gain 分档）的原因；不可接受就把 `CAM_GAMMA_ADAPTIVE 0` 钉在 0.655 |
| gamma 档来回跳 | 迟滞不够 | `CAM_CAL_GAMMA_MIN_STEP_Q1` 是官方 30（3.0），可加大到 60 并记录理由 |
| 背光判据从不触发 | 25% 太严 | 先看 `亮块=` 实测值，按实测调，并在宏注释里写清楚是实测调的 |

- [ ] **Step 6：回退** —— `CAM_GAMMA_ENABLE 0` + AE 目标改回 T6 的等价值。**两个一起回。**

---

## Task 13：L3 —— 按 CCT 选 LSC 与饱和度

目标：把 T3 固定的 LSC 档与 T4 固定的饱和度接到 CCT 上，完成 L3 的最后两项。

**Files:** Modify `main/cam_tune.h`, `main/camera_csi.c`

- [ ] **Step 1：成功判据**

1. `[自检] LSC 档=0(2410K) 切换=2 | 饱和度=130(1.016×)`；
2. 白炽灯下 ⇒ LSC 档 0、饱和度 128；日光下 ⇒ LSC 档 2、饱和度 130；
3. **切换不撕裂**：换光源时画面不出现单帧的暗角跳变（273×2 条 LUT 写要 ~0.5 ms，落在帧内）；
4. `切换=` 不随时间线性增长（迟滞生效）；
5. `实测 fps ≥ 9.0`。

- [ ] **Step 2：接线**

```c
#if CAM_LSC_BY_CT
    /* 三档中心 2410 / 5210 / 8200 K，取最近邻（不插值：273×4 个值插值要 1092 次乘加，
     * 而三档之间最大差 0.36（R 通道四角），插值换来的精度提升看不出来）。 */
    static const uint16_t k_lsc_cts[] = {2410, 5210, 8200};
    uint32_t w;
    uint32_t slot = cam_map_cct_slot(k_lsc_cts, 3, s_cct_k, &w);
    if (w > 128 && slot + 1 < 3) slot++;                 /* 最近邻 */
    if (slot_changed(&s_lsc_track, slot))
        s_st_lsc = camera_lsc_apply(slot);
#endif
#if CAM_SAT_BY_CT
    /* 官方 acc.saturation 只有两档：{0 → 128, 4500 → 130}，即 ≥4500 K 用 1.016×。 */
    const uint32_t sat = (s_cct_k >= cam_cal_saturation[1].cct_k)
                         ? cam_cal_saturation[1].val : cam_cal_saturation[0].val;
    if (slot_changed(&s_sat_track, sat))
        camera_color_apply(s_contrast_val, sat);
#endif
```

⚠️ **LSC 换档的迟滞要比别处更狠**：它是本计划里最贵的一次重配（273×2 条 LUT 命令），而且在无影子寄存器的硬件上换到一半就是可见的暗角跳变。用 `CAM_FEEDFWD_HYST_TICKS × 2`（6 拍 = 600 ms），并且**只在 AWB 判定 `APPLIED` 或 `SKIP_BAND` 的那一拍**才评估（即只在白点估计可信时才动 LSC）。

- [ ] **Step 3：失败归因**

| 现象 | 归因 |
|---|---|
| 换光源时画面闪一下暗角 | 迟滞不够 / 在帧中途写 LUT ⇒ 加大迟滞；若仍在，接受这个已知代价并写进 README（rev v1.0 无影子寄存器，这是硬件限制） |
| LSC 档一直是 1 | `s_cct_k` 没更新（`CAM_AWB_SOURCE=0` 时它就是固定 5210）⇒ 预期行为 |
| 饱和度在 128/130 之间抖 | CCT 恰好在 4500 附近 ⇒ 给这个比较加 ±150 K 的迟滞 |

- [ ] **Step 4：回退** —— `CAM_LSC_BY_CT 0` / `CAM_SAT_BY_CT 0`，回到固定档。

---

## Task 14：五项能力复合回归 + 文档收口

目标：证明这一整轮改动**没有动到任何一项已实机验证的能力**，并把结论写进 README。

**Files:** Modify `README.md`；不改代码（除非回归发现问题）

- [ ] **Step 1：复合回归清单（全部同时开着做）**

| # | 能力 | 判据 |
|---|---|---|
| 1 | GUD 显示 | host 侧 `/dev/dri/cardN` 存在，`modetest` 出图；**摄像头取流时屏幕无撕裂/花屏**（PSRAM 带宽争用） |
| 2 | HID 键盘 | `evtest` 收到按键，六键同时按无丢 |
| 3 | HID 多点触摸 | `evtest` 收到 5 点绝对坐标 |
| 4 | UAC1 播放 | `aplay` 出声；`alsamixer` 调音量**改的是 ES8388 硬件音量** |
| 5 | UAC1 录音 | `arecord` 有波形 |
| 6 | UVC 出图 | `ffplay` 稳定；`v4l2-ctl --list-formats-ext` 仍报 `MJPG 640x360 10.000 fps` |
| 7 | AE 闭环 | 遮挡/复原三次都收敛 |
| 8 | 端点/FIFO | `python3 test/check_usb_desc.py build/tab5_aio.elf` OK；`git diff HEAD~N --stat` 里没有 `usb_descriptors.*` / `tusb_config.h` |
| 9 | 依赖树 | `ls managed_components \| wc -l` == 12 |
| 10 | 帧率 | 连续 5 分钟 `实测 fps ≥ 9.0`、`拒收=0`、`丢弃=0`、`抢缓冲=0` |
| 11 | alt 0 零占用 | host 关掉摄像头后：`PSRAM 读 停流后` 回到 `空载` 同量级；AE/AWB/HIST 三个 `触发/帧` 计数不涨 |
| 12 | 内存 | `esp_get_free_internal_heap_size()` 相对改动前减少 ≈ 4.4 KB（LSC 数组），PSRAM 无变化 |

- [ ] **Step 2：README 要新增/改写的段落**

1. 「⚠️⚠️ ESP32-P4 rev <3.0 已知**不可用**的硬件功能」那张表：**LSC 一行从"（本工程未使用）"改成"已使用，273 格 ×4 通道"**；BLC 一行补上"改由传感器自带 BLC（0x3902）顶替，实测基座 X → Y"。
2. 新增「摄像头画质：与官方管线的对齐程度」一节，逐级给出：配了什么、参数来自哪、rev v1.0 上的代价（CCM 强度钳制、无影子寄存器的换档撕裂、黑位）。
3. 新增「标定数据从哪来」一节：指向 `test/isp_cal_extract.py` 与 `--check`，写明 JSON 不在仓库里（`managed_components/` 被 gitignore）、复现步骤是先 `idf.py build`。
4. 「宿主机测试」表格加两行：`test/test_cam_isp_map.c`（N 用例）、`test/isp_cal_extract.py --check`。
5. 把实测数字填进去：ρ、黑电平基座、各档 CCM 强度、白点占比、`env.luma` 的实际量程、fps、内存增量。

- [ ] **Step 3：把"没做的"也写下来**

README 里明确列出**本轮对齐之后仍然与官方不同**的地方，以及为什么：

| 项 | 官方 | 我们 | 原因 |
|---|---|---|---|
| BLC | ISP BLC，`acc.blc` 16 | 传感器自带 BLC | rev v1.0 的 ISP BLC 不可用 |
| WBG | 独立 RAW 域增益块 | 折进 CCM 第 0/2 列 | rev v1.0 无 WBG（官方 rev<3.0 也是这么降级的） |
| CCM 强度 | 全量 | 低/高色温端按 t 钳制 | S2.10 上限 4.0；2292 K 档本身含 4.5445 |
| AWB 子窗 | 5×5 分区投票 | 只有主窗 4 个累加值 | rev v1.0 无 subwindow |
| AWB 统计频率 | 每帧（连续） | 每秒（oneshot） | rev v1.0 的 AWB ISR 无条件读 25 个空子窗 |
| LSC 色温档 | 9 档 | 3 档 | 通道间差异只有 R 显著，3 档残差 ≈12%，换 13 KB flash 与换档开销 |
| `adn`/`aen` 表间插值 | [缺口] | 不插值 | 模板是整数矩阵，插值无物理意义 |
| AE 权重加成表 | 有两张 | 不实现 | 触发/叠加方式 [缺口] |
| 抗工频闪烁 | `anti_flicker` | 不做 | 取值枚举 [缺口]，且需要把曝光量化到 10 ms 整数倍，会与 AE 的连续控制冲突 |
| 时域 FIR | `env.speed_param[16]` | 一阶低通 | 滑动索引 [缺口] |

- [ ] **Step 4：把基线文档的偏差补记**（见下面「与基线文档不符/可补充之处」一节，逐条追加到两份研究文档的末尾，标注日期与实测来源）

---

## H. 与基线文档不符 / 可补充之处（本次实施逐条核对源码后的记录）

> 两份基线文档我**没有**默认它们都对。下面是核对 ESP-IDF v6.0 源码与标定 JSON 之后发现的差异，
> 分三类：**纠正**（基线说法与源码不符）、**补充**（基线标 [缺口] 而本次找到了依据）、
> **需注意**（不是错，但会误导实施）。

### H.1 纠正

| # | 基线说法 | 实际 | 影响 |
|---|---|---|---|
| 1 | `[官§C.10]`：esp_video 的直方图默认 5×5 权重是「10/256 为主，内十字 11，中心 12」 | 这组数**加起来是 260**（16×10 + 8×11 + 12），而 `s_esp_isp_hist_config_hardware()` 硬性要求 `weight_sum == 256`，这组权重**配不上去**（`ESP_ERR_INVALID_ARG`）。要么基线对 esp_video 那段的描述不精确，要么 esp_video 用的是另一组数 | T11 不照抄这组，改用 IDF 测试的 `16 + 24×10 = 256`。**照抄会直接失败**，所以这条必须纠正 |
| 2 | `[官§C.10]`：直方图 RGB 系数「各 85/256 ≈ 1/3」 | 三个 85 之和是 255 不是 256。驱动只检查权重和、**不检查系数和**，所以 85/85/85 能配上，但文档说的「和应为 256」与它自己给的默认值对不上 | T11 用 86/85/85，让它精确为 256 |

### H.2 补充（基线标 [缺口]，本次给出数值依据）

| # | 缺口 | 本次结论 | 证据强度 |
|---|---|---|---|
| 3 | `[官§B.2.1]` `ian.luma.env.k = 250000` 的公式与 `env.luma` 的绝对量纲 | `env.luma ≈ 250000 / ev`（`ev = 曝光行数 × 增益`）。把四个 gamma 断点 15.1/30.1/90.1/300.1 代入得 `ev = 16556 / 8306 / 2775 / 833`，**全部落在我们的 ev 值域 [8, 19904] 内且分布合理** | **[反推，数值一致性]**。四个断点同时命中一个两位数量级的窗口，不像巧合，但仍需 T11 判据 4 实测确认 |
| 4 | `[官§B.7.1]` `use_gamma_param` 的确切分支行为 | 本次验证 `y[16]` 与 `γ` **不自洽**：γ=0.5 那档在 `x=16,32,…` 栅格上应给出 `64,90,111,…`，而 JSON 里是 `0,19,35,…`；反解出的 x 也不是任何 2 的幂栅格。⇒ `y[16]` 不是驱动 x 栅格上的采样，`use_gamma_param=true` 时**必须**用 γ 解析生成 | **[反推，排除法]**。加强了基线的原判断 |
| 5 | `[官§B.2.2]` `bp` 的投影方式 | 用 `m_2` 二次拟合把 bg 投影回轨迹后，CCT 与实测 bg 算出的相差 ≤55 K（16 点全验）⇒ CCT 实质上是 **rg 的单变量函数**。但该函数在 `rg > 0.78` 处**不单调**（2955 K → 3631 K 回折） | **[确证，数值]**。⇒ §E.4 决定不在运行期算多项式，改成 16 点查表 + 强制单调 |

### H.3 需注意（不是错，但实施时会踩）

| # | 事项 |
|---|---|
| 6 | `[官§B.4]` 说 `sc202cs_abs_gain_val_map[]` 有 **197** 档（1000~63008），`[审§C.4]` 说 **192** 档。两者都对：`sc202cs.c` 里有**两份**同名表，由 `CONFIG_CAMERA_SC202CS_DIG_GAIN_PRIORITY` 二选一（`:73` 与 `:475`）。我们编进去的是数字增益优先那份 = 192 档。**跨文档引用增益表长度时必须说明是哪一份** |
| 7 | `[官§A.7]` 说 rev<3.0 的 CCM 是「S2.10，范围 ±4.0」。驱动的范围检查是**闭区间** `[-4.0, +4.0]`（`isp_ccm.c:25-31`），但定点格式 2 整数位 + 10 小数位实际能表达的最大值是 `4095/1024 = 3.9990`。**恰好写 4.0 会通过驱动检查、然后在 HAL 里被 saturation 悄悄改掉**（`saturation=true` 时不报错）。⇒ 本计划的钳制阈值取 **3990 milli**，不贴 4.0 |
| 8 | `[官§A.4]` 说统计通过「ISP 中断 + 回调」送出，且回调在 ISR 上下文。补充一条实施细节：`esp_isp_awb_controller_get_oneshot_statistics()` 在 `timeout_ms = 0` 时**没用** —— 它会跳过等待、立刻 `isp_ll_awb_enable(false)`，统计根本来不及完成，回调也不会触发。（AE 的 oneshot 文档说 `timeout_ms=0` 可以在回调里拿结果，AWB 这条路走不通。）⇒ AWB oneshot **必须给正的超时**，本计划取 60 ms |
| 9 | `[审§A.3]` 说 LSC「可用但没用」。补充：`esp_isp_lsc_allocate_gain_array()` 要求 `lsc_fsm == INIT`，**必须在 `esp_isp_lsc_enable()` 之前分配**；而 `esp_isp_lsc_configure()` 没有 FSM 门，取流中可重配（T13 的换档依赖这一点） |
| 10 | `esp_isp_bf_configure(proc, NULL)` 会在 `else` 分支之后**无条件**求值 `config->flags.update_once_configured` ⇒ 传 NULL 是空指针解引用。`sharpen` / `color` 同样的写法。**全程不许传 NULL** |
| 11 | AE/AWB 的 `intr_priority` 与处理器不一致时，驱动走的是 `ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, …)` —— 传给它的是一个**布尔值 1**，于是函数返回 `1` 而不是任何 `esp_err_t`。自检行会打出一个 `esp_err_to_name()` 认不出的码，别往别处查 |
| 12 | 官方 LSC 表的增益值域实测为 **1.000（中心）~ 3.323（R 通道四角）**，而硬件 `isp_lsc_gain_t` 是 2 整数位 + 8 小数位 ⇒ 上限 3.996。**余量只有 20%**。基线两份文档都没提这个数，提取脚本必须带断言（T0 Step 5） |

---

## I. 风险登记与放弃判定点

| 风险 | 影响 | 判定点 | 放弃/回退动作 |
|---|---|---|---|
| **R1（最高）：AWB 拓扑改动写错公式** —— 采样点搬到 CCM 前后仍用乘 `cur` 的增量公式 | 增益单调发散，画面缓慢偏色而所有计数器显示正常，**现场极难归因** | **T9 Step 1 判据 2**（静置 5 分钟增益不动） | `CAM_AWB_SOURCE 0`。三重防呆：新函数签名拿不到 `cur`、旧函数原样保留、宿主机 200 拍不动点用例 |
| R2：官方白点框与我们的实际信号不同域 | `白点=0`，AWB 一步不走 | T8 Step 1 判据 2（白纸 >30%、红墙 <5%） | 若放宽框后有白点，说明 §E.4 的"同域"论断错 ⇒ **T9 不做**，停在 `CAM_AWB_SOURCE 0`，L3 只做 CCM/LSC 的固定档 |
| R3：黑电平基座压不掉 | CCM 折叠后黑位发品红 | **T7 Step 4 的三分支判定点** | 降 `CAM_CCM_STRENGTH_MAX` 到 192，或 `CAM_CCM_MODE 0` |
| R4：两个 oneshot（AWB + HIST）挤掉帧泵预算 | fps < 9 或 `拒收` 非零 | 每个上板任务的通用收尾 | 错相（T11 Step 3）→ 周期拉到 2 秒 → 把触发挪到 USB 提交之后 |
| R5：无影子寄存器导致换档撕裂 | 换光源时单帧暗角/色彩跳变 | T13 Step 1 判据 3 | 加大迟滞；仍在则接受并写进 README（硬件限制，rev v1.0 没有影子寄存器） |
| R6：`env.luma` 重建站不住 | gamma 四档只用得到一档 | **T11 Step 1 判据 4** | `CAM_ENV_MODEL 0`，改用实测 ev 四分位（T11 Step 5 已写好） |
| R7：CCM 放大高增益噪声 | 暗处噪点比对角阵明显 | T10 Step 1 判据 3 的主观比较 | 提高 BF 档断点或降 `CAM_CCM_STRENGTH_MAX`；两者都是一行改动 |
| R8：LSC 表排布转置 | 暗角修正方向横竖颠倒 | T3 Step 5 | 提取脚本的转置开关重跑 |
| R9：芯片其实不是 rev v1.0 | LSC 也用不了，本计划 L1 塌掉一半 | **T3 Step 3** | 停止 T3，读 `esptool.py chip_id`，回来改 README 的版本表 |

**整体放弃判定点**：**T9 结束时判一次**。若 R1 与 R2 都不成立（即 AWB 的硬件路走不通），则本计划的 L2 只交付 AE 那一半，L3 退化成「固定 5210 K 的 CCM + 固定档 LSC/饱和度」——**这仍然比今天（无 CCM 色彩还原、无 LSC、无 gamma）好得多**，且全部改动都在编译开关后面，不阻塞任何已交付能力。

---

## J. 自查（写完这份计划后逐条过的）

- [x] **三层目标每一项都有对应任务** —— §A 的映射表逐行列出，含唯一一个"不做"（Color 色调：官方标定里没有 hue 字段，写 0 即对齐）。
- [x] **七条硬约束都有步骤与判据** —— §B 的表；其中"不破坏已验证能力"与"帧率/拒收"落到 §G 的通用收尾，每个上板任务都要跑一遍。
- [x] **实现级陷阱全部落实** —— §C 的表逐条给出落实位置：`intr_priority` 一致（T5/T8）、AWB 用 oneshot 不用连续（T8）、统计 window 显式配（T5/T11）、直方图权重和精确 256（T11）、gamma x 间隔 2 的幂（T12）、CCM 无 FSM 检查可运行期重配（T10）、无影子寄存器 ⇒ 全部换档带迟滞（T2 起）、AWB 公式必须跟着采样点改（§E.3 + T9 三重防呆）。另补了三条本次新查的（`bf_configure(NULL)` 空指针、CCM 不能贴 4.0、AWB oneshot 不能传 0 超时）。
- [x] **没有占位符** —— 所有代码块都是可用代码；所有数字要么来自标定 JSON、要么来自源码、要么是本次实测算出的（§D.4 的 19 行表、§E.4 的 16 点 CCT、§E.5 的四个 ev 断点、gamma 四档 y 值、LSC 值域与字节数）。唯一两处"实施时填入"是 T6 的 ρ 与 T7 的黑电平基座 —— 它们**按定义**只能上板测，而计划已给出测法、公式与判读表。
- [x] **前后任务的函数名/类型名一致** —— `cam_isp_map.h` 声明的 9 个函数在 T2/T6/T10/T11/T12/T13 里被调用，签名一致；`cam_awb_hw_stat_t` 在 T8 定义、T9 消费；`cam_slot_track_t` / `slot_changed()` 在 T2 定义，T13 复用；`camera_ccm_apply()` / `camera_lsc_apply()` / `camera_color_apply()` 在 T3/T4 定义，T10/T13 复用。
- [x] **CCM 超 4.0 的钳制策略** —— §D.4：朝单位阵混合的强度参数 t，8 次二分求最大可行 t，凸性保证可行域是 `[0,t*]`；`t=0` 恰好退化成今天已验证的对角阵；给了 19 档的实测 t 表。**不用整体缩放**的理由（会多花最多 2 EV 噪声）写在表里对比。
- [x] **"官方 CCM 按 WBG 前提标定而我们要把 WB 乘进 CCM"的矛盾** —— §D.1/§D.2：**这个矛盾不成立**。右乘 `diag(kr,1,kb)` 与"先 WBG 再 CCM"数学等价（两者都是逐通道线性算子，可交换），且中性面 `w=(1/kr,1,1/kb)` 经 `M·W` 后精确得到 `(1,1,1)` —— **行和为 1 的前提被完整保持**。真正破的只有定点范围（§D.4 解决）与黑电平前提（§D.3 解决：传感器自带 BLC → 统计侧减法 → 降强度，三级处置 + T7 判定点）。
- [x] **标定数据的提取方案** —— T0：脚本机械提取、MD5 + 字节数双重指纹守门、`--check` 复现校验（改一个数字就失败）、注明来源与 Apache-2.0、只取 7.2 KB（234 KB 里绝大多数是 LSC 9 档，只带 3 档）、未提取的段逐条写理由、全部在宿主机可验证。
