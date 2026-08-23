#!/usr/bin/env python3
"""
从 espressif/esp_cam_sensor 的官方 SC202CS 标定文件机械提取 ISP 参数，生成
main/cam_isp_cal.h。**不手抄任何数字**：每一张表都由本脚本从 JSON 字段路径读出。

用法:
  python3 test/isp_cal_extract.py            # 生成/覆盖 main/cam_isp_cal.h
  python3 test/isp_cal_extract.py --check    # 只校验：重新生成到内存并与磁盘上的比对

⚠️ 工作目录必须是 firmware/（SRC / OUT 都是相对它的路径）。

源文件指纹在下面写死。上游换版本 ⇒ 指纹对不上 ⇒ 脚本拒绝运行，
逼人去看 CHANGELOG 而不是默默生成一份不同的表（tab5_kbd_map.h 那轮的教训）。

⚠️ managed_components/ 在 .gitignore 里 —— **JSON 不在仓库里**。所以生成物
   main/cam_isp_cal.h 必须提交，本脚本只是它的「可复现证明」；跑脚本的前提是
   先 `idf.py build` 把组件拉下来。与 panel_init_data.h（esp-bsp 也没 vendored）
   的处置完全一致。
"""
import difflib
import hashlib
import json
import math
import os
import sys

SRC = ("managed_components/espressif__esp_cam_sensor/sensors/sc202cs/cfg/"
       "sc202cs_default.json")
SRC_MD5 = "0f32b06f7201d8cbee993126fd2ff277"
SRC_SIZE = 234332
OUT = "main/cam_isp_cal.h"

# 选进固件的 LSC 色温档（9 档全带 = 19656 B；这 3 档 = 6552 B）。
# 取舍依据见头文件注释与计划 §T0 Step 5：只有 R 通道随色温有明显差异，
# 取这三档后最大残差 ≈ 0.36（落在一个 ~3× 的提亮上 ≈ 12%，还在四角）。
# **要全带 9 档只改这一行重跑。**
LSC_CTS = (2410, 5210, 8200)

# gamma 曲线的 x 栅格：与 esp_isp_gamma_fill_curve_points() 生成的完全一致
# （x_delta = 256/16 = 16，末点 MIN(256,255) = 255，硬件把它当 256 看，
#  isp_gamma.c 的 `if (i == NUM-1) x_i = 256;`）。硬件要求每段间隔是 2 的幂。
GAMMA_X = tuple(list(range(16, 241, 16)) + [255])

# 硬件定点上限。
LSC_FIXED_MAX = 1 << 10      # isp_lsc_gain_t = 2 整数位 + 8 小数位 ⇒ val < 1024
CCM_ABS_MAX = 4.0            # rev < 3.0 的 CCM 是 S2.10 ⇒ |系数| <= 4.0


def rnd(x):
    """四舍五入、远离零。Python 内建 round() 是银行家舍入，会让 0.5 的边界不可复现。"""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def load():
    raw = open(SRC, "rb").read()
    md5 = hashlib.md5(raw).hexdigest()
    if md5 != SRC_MD5 or len(raw) != SRC_SIZE:
        sys.exit(f"源文件指纹不符：{len(raw)} B / {md5}\n"
                 f"期望：{SRC_SIZE} B / {SRC_MD5}\n"
                 f"上游改过标定文件，先读 esp_cam_sensor 的 CHANGELOG，再改本脚本的指纹。")
    return json.loads(raw)["SC202CS"], md5


# ── 排版小工具 ──────────────────────────────────────────────────────────


def arr(vals, per_line=None, indent="    "):
    """把一串数字排成 C 初始化列表的内容（不含花括号）。"""
    s = [str(v) for v in vals]
    if per_line is None:
        return ", ".join(s)
    out = []
    for i in range(0, len(s), per_line):
        out.append(indent + ", ".join(s[i:i + per_line]) + ",")
    return "\n".join(out)


# ── 各段的提取 ──────────────────────────────────────────────────────────


def emit_bf(s, out):
    bf = s["adn"]["bf"]
    out.append("""
/* ── adn.bf —— Bayer 域降噪，按传感器总增益分 %d 档 ────────────────────
 * JSON: .SC202CS.adn.bf[i].{gain, param.level, param.matrix[9]}
 * level  → esp_isp_bf_config_t.denoising_level
 * matrix → esp_isp_bf_config_t.bf_template[3][3]（行主序，原值搬运）
 * ⓘ 官方表在断点之间是否插值是 [缺口]；matrix[9] 是整数模板，插值无物理意义
 *   ⇒ cam_map_gain_slot() 取「gain 不超过当前总增益的最大一档」，不插值。 */""" % len(bf))
    out.append("#define CAM_CAL_BF_N %d" % len(bf))
    out.append("""typedef struct {
    uint16_t gain_milli;   /* 触发本档的传感器总增益 ×1000 */
    uint8_t  level;        /* denoising_level */
    uint8_t  matrix[9];    /* bf_template，行主序 */
} cam_cal_bf_t;""")
    out.append("static const cam_cal_bf_t cam_cal_bf[CAM_CAL_BF_N] = {")
    for e in bf:
        p = e["param"]
        assert 0 <= p["level"] <= 255 and len(p["matrix"]) == 9
        out.append("    { %5d, %2d, { %s } },"
                   % (rnd(e["gain"] * 1000), p["level"], arr(p["matrix"])))
    out.append("};")
    out.append("/* 断点表，直接喂 cam_map_gain_slot()（与上表的 gain_milli 同源）。 */")
    out.append("static const uint16_t cam_cal_bf_gain[CAM_CAL_BF_N] = { %s };"
               % arr(rnd(e["gain"] * 1000) for e in bf))
    return len(bf) * 12 + len(bf) * 2


def emit_demosaic(s, out):
    dm = s["adn"]["demosaic"]
    out.append("""
/* ── adn.demosaic —— 去马赛克梯度比，按增益 %d 档 ─────────────────────
 * JSON: .SC202CS.adn.demosaic[i].{gain, gradient_ratio}
 * → esp_isp_demosaic_config_t.grad_ratio（2 整数位 + 4 小数位，步长 1/16）。
 *   定点转换放在下发侧做，本表存 ×1000 的原值。 */""" % len(dm))
    out.append("#define CAM_CAL_DEMOSAIC_N %d" % len(dm))
    out.append("""typedef struct {
    uint16_t gain_milli;
    uint16_t grad_ratio_milli;
} cam_cal_demosaic_t;""")
    out.append("static const cam_cal_demosaic_t cam_cal_demosaic[CAM_CAL_DEMOSAIC_N] = {")
    for e in dm:
        out.append("    { %5d, %4d }," % (rnd(e["gain"] * 1000), rnd(e["gradient_ratio"] * 1000)))
    out.append("};")
    out.append("static const uint16_t cam_cal_demosaic_gain[CAM_CAL_DEMOSAIC_N] = { %s };"
               % arr(rnd(e["gain"] * 1000) for e in dm))
    return len(dm) * 4 + len(dm) * 2


def emit_sharpen(s, out):
    sh = s["aen"]["sharpen"]
    out.append("""
/* ── aen.sharpen —— Y 分量锐化，按增益 %d 档 ──────────────────────────
 * JSON: .SC202CS.aen.sharpen[i].{gain, param.{h_thresh,l_thresh,h_coeff,m_coeff,matrix[9]}}
 * → esp_isp_sharpen_config_t 的同名字段；两个系数是 3 整数位 + 5 小数位，
 *   定点转换放在下发侧做，本表存 ×1000 的原值。
 * m_coeff 随增益单调下降（1.525 → 1.225）：高增益时减弱中频锐化，别放大噪声。 */""" % len(sh))
    out.append("#define CAM_CAL_SHARPEN_N %d" % len(sh))
    out.append("""typedef struct {
    uint16_t gain_milli;
    uint8_t  h_thresh;
    uint8_t  l_thresh;
    uint16_t h_coeff_milli;
    uint16_t m_coeff_milli;
    uint8_t  matrix[9];    /* sharpen_template，行主序 */
} cam_cal_sharpen_t;""")
    out.append("static const cam_cal_sharpen_t cam_cal_sharpen[CAM_CAL_SHARPEN_N] = {")
    for e in sh:
        p = e["param"]
        assert len(p["matrix"]) == 9
        out.append("    { %5d, %2d, %d, %4d, %4d, { %s } },"
                   % (rnd(e["gain"] * 1000), p["h_thresh"], p["l_thresh"],
                      rnd(p["h_coeff"] * 1000), rnd(p["m_coeff"] * 1000), arr(p["matrix"])))
    out.append("};")
    out.append("static const uint16_t cam_cal_sharpen_gain[CAM_CAL_SHARPEN_N] = { %s };"
               % arr(rnd(e["gain"] * 1000) for e in sh))
    return len(sh) * 16 + len(sh) * 2


def emit_contrast(s, out):
    ct = s["aen"]["contrast"]
    out.append("""
/* ── aen.contrast —— 对比度，按增益 %d 档 ─────────────────────────────
 * JSON: .SC202CS.aen.contrast[i].{gain, value}
 * → isp_color_contrast_t（1 整数位 + 7 小数位）⇒ **128 = 1.0×**，原值搬运。 */""" % len(ct))
    out.append("#define CAM_CAL_CONTRAST_N %d" % len(ct))
    out.append("""typedef struct {
    uint16_t gain_milli;
    uint8_t  value;        /* 128 = 1.0× */
} cam_cal_contrast_t;""")
    out.append("static const cam_cal_contrast_t cam_cal_contrast[CAM_CAL_CONTRAST_N] = {")
    for e in ct:
        out.append("    { %5d, %3d }," % (rnd(e["gain"] * 1000), e["value"]))
    out.append("};")
    out.append("static const uint16_t cam_cal_contrast_gain[CAM_CAL_CONTRAST_N] = { %s };"
               % arr(rnd(e["gain"] * 1000) for e in ct))
    return len(ct) * 4 + len(ct) * 2


def emit_saturation(s, out):
    sa = s["acc"]["saturation"]
    out.append("""
/* ── acc.saturation —— 饱和度，按色温 %d 档 ───────────────────────────
 * JSON: .SC202CS.acc.saturation[i].{color_temp, value}
 * → isp_color_saturation_t（1 整数位 + 7 小数位）⇒ **128 = 1.0×**。
 * ⓘ 第 0 档的 color_temp = 0 是「兜底档」，语义上等价于「低于 4500 K 全用 128」。 */""" % len(sa))
    out.append("#define CAM_CAL_SATURATION_N %d" % len(sa))
    out.append("""typedef struct {
    uint16_t cct_k;
    uint8_t  value;        /* 128 = 1.0× */
} cam_cal_saturation_t;""")
    out.append("static const cam_cal_saturation_t cam_cal_saturation[CAM_CAL_SATURATION_N] = {")
    for e in sa:
        out.append("    { %5d, %3d }," % (e["color_temp"], e["value"]))
    out.append("};")
    out.append("static const uint16_t cam_cal_saturation_cct[CAM_CAL_SATURATION_N] = { %s };"
               % arr(e["color_temp"] for e in sa))
    return len(sa) * 4 + len(sa) * 2


def emit_gamma(s, out):
    g = s["aen"]["gamma"]
    tbl = g["table"]
    assert g["use_gamma_param"] is True, "use_gamma_param 变成 false ⇒ 该改用 table[].y 了"
    out.append("""
/* ── aen.gamma —— %d 档 γ 曲线，按环境亮度 env.luma 选档 ──────────────
 * JSON: .SC202CS.aen.gamma.{luma_min_step, table[i].{luma, gamma_param}}
 *
 * ⚠️ **y[16] 不是从 JSON 抄的，是本脚本按 γ 算的** —— JSON 里 use_gamma_param = true，
 *    官方语义是「用 gamma_param 解析生成曲线，table[].y 只在该布尔为 false 时才用」
 *    （2026-08-19-esp32p4-official-isp-pipeline.md §B.7.1）。两者数值并不一致
 *    （例如 γ=0.5 档，JSON 的 y[0]=19，而 255·(16/255)^0.5 = 64）——
 *    我们跟随 use_gamma_param 走解析式那一支。
 *
 *    y = round(255 · (x/255)^γ)，x 取硬件栅格 16,32,…,240,255。
 *    ⓘ 为什么以 255 而不是 256 归一：esp_isp_gamma_fill_curve_points() 要求
 *      y < 256，而 256·(255/256)^0.5 = 255.5 → 256 会被拒；以 255 归一时末点
 *      恒为 255，天然合法。
 *
 * 断点 luma ×10（15.1/30.1/90.1/300.1 ⇒ 151/301/901/3001），量纲不是像素亮度，
 * 是带 ian.luma.env.k 归一化的环境照度量（重建式见计划 §E.5，标 [反推]）。 */""" % len(tbl))
    out.append("#define CAM_CAL_GAMMA_N %d" % len(tbl))
    out.append("#define CAM_CAL_GAMMA_PTS %d" % len(GAMMA_X))
    out.append("/* 选档断点，单位 1/10。 */")
    out.append("static const uint16_t cam_cal_gamma_luma_q1[CAM_CAL_GAMMA_N] = { %s };"
               % arr(rnd(e["luma"] * 10) for e in tbl))
    out.append("/* 各档的 γ ×1000，只为可追溯；运行期用下面算好的 y。 */")
    out.append("static const uint16_t cam_cal_gamma_param_milli[CAM_CAL_GAMMA_N] = { %s };"
               % arr(rnd(e["gamma_param"] * 1000) for e in tbl))
    out.append("/* 硬件 x 栅格（末点 255，硬件按 256 处理）。 */")
    out.append("static const uint8_t cam_cal_gamma_x[CAM_CAL_GAMMA_PTS] = { %s };" % arr(GAMMA_X))
    out.append("static const uint8_t cam_cal_gamma_y[CAM_CAL_GAMMA_N][CAM_CAL_GAMMA_PTS] = {")
    for e in tbl:
        gp = e["gamma_param"]
        ys = [rnd(255.0 * pow(x / 255.0, gp)) for x in GAMMA_X]
        assert all(0 <= y < 256 for y in ys), "gamma y 越界"
        assert all(ys[i] <= ys[i + 1] for i in range(len(ys) - 1)), "gamma y 非单调"
        assert ys[-1] == 255
        out.append("    { %s },   /* γ = %.3f */" % (arr("%3d" % y for y in ys), gp))
    out.append("};")
    out.append("/* 换档迟滞：aen.gamma.luma_min_step ×10。 */")
    out.append("#define CAM_CAL_GAMMA_MIN_STEP_Q1  %d" % rnd(g["luma_min_step"] * 10))
    return len(tbl) * (2 + 2 + len(GAMMA_X)) + len(GAMMA_X)


def emit_ccm(s, out):
    tbl = s["acc"]["ccm"]["table"]
    mx = 0.0
    for e in tbl:
        m = e["matrix"]
        assert len(m) == 9
        for r in range(3):
            rowsum = sum(m[r * 3:r * 3 + 3])
            assert abs(rowsum - 1.0) < 0.02, \
                f"CCM {e['color_temp']}K 第 {r} 行行和 {rowsum} 偏离 1.0 —— 保白前提不成立了"
        mx = max(mx, max(abs(v) for v in m))
    out.append("""
/* ── acc.ccm —— 颜色校正矩阵，按色温 %d 档 ────────────────────────────
 * JSON: .SC202CS.acc.ccm.table[i].{color_temp, matrix[9]}   系数 ×1000，行主序。
 *
 * 两条已核对的性质（cam_isp_map 的两个不变式就靠它们）：
 *   ① **每一行的行和都是 1.000**（本脚本逐档断言 |Σ−1| < 0.02）⇒ 中性面进中性面出，
 *      整体增益精确为 1。把白平衡 diag(kr,1,kb) **右乘**进来后该性质完整保持。
 *   ② 全表最大 |系数| = %.4f（%dK 档），**超过 rev<3.0 的 S2.10 上限 4.0** ⇒
 *      必须靠 cam_ccm_fold_wb() 的强度参数 t 钳制，推导见计划 §D.4。
 *   ③ 两端（%dK / %dK）是单位阵，起钳位守卫作用。 */"""
               % (len(tbl), mx, next(e["color_temp"] for e in tbl
                                     if max(abs(v) for v in e["matrix"]) == mx),
                  tbl[0]["color_temp"], tbl[-1]["color_temp"]))
    out.append("#define CAM_CAL_CCM_N %d" % len(tbl))
    out.append("static const uint16_t cam_cal_ccm_cct[CAM_CAL_CCM_N] = {")
    out.append(arr((e["color_temp"] for e in tbl), per_line=10))
    out.append("};")
    out.append("/* 系数 ×1000。int16_t 装得下最大的 %d。 */" % rnd(mx * 1000))
    out.append("static const int16_t cam_cal_ccm[CAM_CAL_CCM_N][9] = {")
    for e in tbl:
        out.append("    { %s },   /* %5d K */"
                   % (arr("%5d" % rnd(v * 1000) for v in e["matrix"]), e["color_temp"]))
    out.append("};")
    return len(tbl) * 2 + len(tbl) * 18


def emit_cct_locus(s, out):
    """官方白点轨迹 → CCT。全脚本唯一有数学的地方，必须写死在这里而不是手算。"""
    ct = s["ian"]["color_temp"]
    g = ct["g"]                                    # McCamy epicentre 取负 + 三次多项式
    a = g["a2"]
    pts = []
    for bp in ct["bp"]:                            # bp[0] rg 最大(暖) … bp[15] rg 最小(冷)
        rg, bg = bp["a0"], bp["a1"]
        n = (rg + g["a0"]) / (bg + g["a1"])        # n = (rg-0.332)/(bg-0.1858)
        k = ((a[0] * n + a[1]) * n + a[2]) * n + a[3]
        pts.append((rg, k))
    pts.sort(key=lambda p: p[0])                   # 按 rg 升序 ⇒ CCT 降序
    # 强制单调：拟合噪声会在暖端产生一处 15 K 的反转（官方管线文档 §B.2.2 已注明）。
    fixed = []
    forced = []
    for i, (rg, k) in enumerate(pts):
        kk = rnd(k)
        if i and kk >= fixed[-1][1]:
            forced.append((rg, kk, fixed[-1][1] - 1))
            kk = fixed[-1][1] - 1
        fixed.append((rg, kk))
    for rg, was, now in forced:
        print("  [单调化] rg=%.4f 的 CCT 由 %d K 压到 %d K（拟合噪声反转，唯一的人工干预）"
              % (rg, was, now), file=sys.stderr)
    out.append("""
/* ── ian.color_temp —— 白点轨迹 %d 点 → CCT 查表 ─────────────────────
 * JSON: .SC202CS.ian.color_temp.{bp[i].{a0,a1}, g.{a0,a1,a2[4]}}
 *
 * 官方链路是 (rg,bg) → 轨迹投影 → McCamy 式三次多项式 → CCT。本脚本在**提取期**
 * 把这三段数学在 16 个 bp 点上算完，运行期只做「按 rg 线性插值 + 两端钳位」。
 * 两条依据（计划 §E.4）：
 *   ① 用 m_2 的二次拟合把 bg 投影回轨迹后，CCT 与直接用实测 bg 算出的相差 ≤55 K
 *      ⇒ CCT 实际上是 **rg 的单变量函数**；
 *   ② 但该函数在暖端 **不单调**，直接套多项式做选档标量会在暖光下来回跳档。
 *
 * ⚠️ 单调化是本文件**唯一**的人工干预，共 %d 处（脚本运行时会打到 stderr）：%s
 *
 * rg_q4 = (Σr/Σg) × 10000，**升序**；k 是开尔文，**严格降序**。
 * 由 bp 反推的物理自洽增益范围：kr = 1/rg ∈ [%.3f, %.3f]、kb = 1/bg ∈ [%.3f, %.3f]。 */"""
               % (len(fixed), len(forced),
                  ("；".join("rg=%.4f: %d→%d K" % f for f in forced) or "无"),
                  1.0 / max(p["a0"] for p in ct["bp"]), 1.0 / min(p["a0"] for p in ct["bp"]),
                  1.0 / max(p["a1"] for p in ct["bp"]), 1.0 / min(p["a1"] for p in ct["bp"])))
    out.append("#define CAM_CAL_CCT_N %d" % len(fixed))
    out.append("static const uint16_t cam_cal_cct_rg[CAM_CAL_CCT_N] = {")
    out.append(arr((rnd(rg * 10000) for rg, _ in fixed), per_line=8))
    out.append("};")
    out.append("static const uint16_t cam_cal_cct_k[CAM_CAL_CCT_N] = {")
    out.append(arr((k for _, k in fixed), per_line=8))
    out.append("};")
    for i in range(len(fixed) - 1):
        assert fixed[i][0] < fixed[i + 1][0], "rg 未严格升序"
        assert fixed[i][1] > fixed[i + 1][1], "CCT 未严格降序"
    return len(fixed) * 4


def emit_awb_box(s, out):
    a = s["awb"]
    r = a["range"]
    # 官方桥接层的推导式（esp_video_isp_device.c，见管线文档 §C.7）：
    #   lum_max = green_max × (1 + rg_max + bg_max)
    #   lum_min = green_min × (1 + rg_min + bg_min)
    lum_max = r["green"]["max"] * (1.0 + r["rg"]["max"] + r["bg"]["max"])
    lum_min = r["green"]["min"] * (1.0 + r["rg"]["min"] + r["bg"]["min"])
    out.append("""
/* ── awb.range —— 硬件 AWB 白点筛选框 ────────────────────────────────
 * JSON: .SC202CS.awb.{range.{rg,bg,green}.{min,max}, min_counted}
 * rg / bg ×10000；亮度窗**不是**独立标定的，而是按官方桥接层的推导式算出来的
 * （管线文档 §C.7 原文）：lum = G × (1 + R/G + B/G) = R+G+B
 *   lum_max = %.0f × (1 + %.4f + %.4f) = %.3f → %d
 *   lum_min = %.0f × (1 + %.4f + %.4f) = %.3f → %d
 * ⚠️ 这三个框是官方在**未做 WB 的 raw 色度空间**里标的（rg 0.38~0.88 明显没白平衡过），
 *   与我们 ISP_AWB_SAMPLE_POINT_BEFORE_CCM 的采样点恰好同域，可以直接用。
 * ⓘ GREEN_MIN/MAX 是**原始的** green 范围，驱动不吃它（驱动的字段是上面那个
 *   R+G+B 的 lum 窗）。留着它是为了现场能验算这条换算：自检行打的
 *   「平均G = Σg/白点数」必须落回 [%d, %d]，否则说明官方 green 范围与我们的
 *   信号电平不同域，亮度窗要按实测重标。 */"""
               % (r["green"]["max"], r["rg"]["max"], r["bg"]["max"], lum_max, rnd(lum_max),
                  r["green"]["min"], r["rg"]["min"], r["bg"]["min"], lum_min, rnd(lum_min),
                  rnd(r["green"]["min"]), rnd(r["green"]["max"])))
    out.append("#define CAM_CAL_RG_MIN        %d" % rnd(r["rg"]["min"] * 10000))
    out.append("#define CAM_CAL_RG_MAX        %d" % rnd(r["rg"]["max"] * 10000))
    out.append("#define CAM_CAL_BG_MIN        %d" % rnd(r["bg"]["min"] * 10000))
    out.append("#define CAM_CAL_BG_MAX        %d" % rnd(r["bg"]["max"] * 10000))
    out.append("#define CAM_CAL_LUM_MIN       %d" % rnd(lum_min))
    out.append("#define CAM_CAL_LUM_MAX       %d" % rnd(lum_max))
    out.append("#define CAM_CAL_GREEN_MIN     %d" % rnd(r["green"]["min"]))
    out.append("#define CAM_CAL_GREEN_MAX     %d" % rnd(r["green"]["max"]))
    out.append("/* 白点数低于它就认为这一拍的估计不可信。 */")
    out.append("#define CAM_CAL_MIN_COUNTED   %d" % a["min_counted"])
    return 0


def emit_ae(s, out):
    la = s["agc"]["luma_adjust"]
    w = la["weight"]
    assert len(w) == 25
    out.append("""
/* ── agc.luma_adjust —— AE 的 5×5 加权表与目标/保护阈值 ───────────────
 * JSON: .SC202CS.agc.luma_adjust.{weight[25], target*, low/high_threshold, low/high_regions}
 * weight 是中心加权金字塔（1..4），块序与 ISP AE 硬件的 5×5 分块一致（行主序）。
 * ⓘ 官方另有一张全 1 的 ian.luma.env.weight —— 那是给 env.luma 用的均匀权重，
 *   与这张中心加权表**分成两张是有意的**（管线文档 §B.4.2）。我们的 env.luma
 *   走直方图的近似均匀权重，所以不需要把那张全 1 表搬进来。
 * ⚠️ 目标亮度 %d 的量纲是 8 bit，测在 ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC
 *   （线性 RGB 亮度），**不能**与我们今天测在 ISP 输出的 CAM_AE_TARGET 直接互换。 */"""
               % la["target"])
    out.append("static const uint8_t cam_cal_ae_weight[25] = {")
    out.append(arr(("%d" % v for v in w), per_line=5))
    out.append("};")
    out.append("#define CAM_CAL_AE_TARGET       %d" % la["target"])
    out.append("#define CAM_CAL_AE_TARGET_LOW   %d" % la["target_low"])
    out.append("#define CAM_CAL_AE_TARGET_HIGH  %d" % la["target_high"])
    out.append("#define CAM_CAL_AE_LOW_THRESH   %d" % la["low_threshold"])
    out.append("#define CAM_CAL_AE_LOW_REGIONS  %d" % la["low_regions"])
    out.append("#define CAM_CAL_AE_HIGH_THRESH  %d" % la["high_threshold"])
    out.append("#define CAM_CAL_AE_HIGH_REGIONS %d" % la["high_regions"])
    out.append("""/* 优先级模式对目标亮度的偏移。**只取 luma_offset**：同一块里的 weight_offset
 * 与两个 threshold 的触发/叠加方式是 [缺口]，猜错比不加权更坏（计划 §E.2）。 */""")
    out.append("#define CAM_CAL_AE_HL_OFFSET    (%d)" % s["agc"]["high_light_priority"]["luma_offset"])
    out.append("#define CAM_CAL_AE_LL_OFFSET    (%d)" % s["agc"]["low_light_priority"]["luma_offset"])
    return 25


def emit_env(s, out):
    out.append("""
/* ── ian.luma.env.k —— 环境照度归一化系数 ────────────────────────────
 * JSON: .SC202CS.ian.luma.env.k
 * ⚠️ 用法标 **[反推，数值一致性]**，不是 [确证]：k/ev 把 gamma 的四个断点
 *   （15.1/30.1/90.1/300.1）映到 ev = 16556/8306/2775/833，**全部落在我们
 *   ev ∈ [8, 19904] 的值域内**且分布合理。推导与证伪判据见计划 §E.5。 */""")
    out.append("#define CAM_CAL_ENV_K   %dUL" % s["ian"]["luma"]["env"]["k"])
    return 0


def emit_lsc(s, out):
    lsc = s["acc"]["lsc"]
    n = lsc["lsc_tbl_size"]
    # 驱动按 i = y*num_grids_x + x 写 LUT；ISP_LSC_GET_GRIDS(res) = (res-1)/2/32+2。
    gx = (lsc["img_w"] - 1) // 2 // 32 + 2
    gy = (lsc["img_h"] - 1) // 2 // 32 + 2
    assert gx * gy == n, f"网格 {gx}×{gy} 与 lsc_tbl_size {n} 对不上"
    assert (lsc["img_w"], lsc["img_h"]) == (1280, 720), "标定分辨率变了，网格数要重算"
    by_ct = {e["ct"]: e for e in lsc["table"]}
    for c in LSC_CTS:
        assert c in by_ct, f"LSC 没有 {c} K 这一档，可选：{sorted(by_ct)}"
    chans = ("r", "gr", "gb", "b")

    # 取舍依据：打印各档之间的最大差，以及全表增益值域。
    def tv(c, ch):
        return by_ct[c]["calibrations_%s_tbl" % ch]
    print("  [LSC] 全部 %d 档：%s，选用 %s"
          % (len(by_ct), sorted(by_ct), list(LSC_CTS)), file=sys.stderr)
    for ch in chans:
        d = max(abs(x - y) for x, y in zip(tv(LSC_CTS[0], ch), tv(LSC_CTS[-1], ch)))
        print("  [LSC] %-2s 通道 max|%dK − %dK| = %.3f" % (ch, LSC_CTS[0], LSC_CTS[-1], d),
              file=sys.stderr)
    gmax = max(max(tv(c, ch)) for c in by_ct for ch in chans)
    gmin = min(min(tv(c, ch)) for c in by_ct for ch in chans)
    print("  [LSC] 增益值域 %.3f … %.3f ⇒ 定点 %d（硬件上限 %d，余量 %.0f%%）"
          % (gmin, gmax, rnd(gmax * 256), LSC_FIXED_MAX - 1,
             100.0 * (LSC_FIXED_MAX - 1 - rnd(gmax * 256)) / (LSC_FIXED_MAX - 1)),
          file=sys.stderr)

    out.append("""
/* ── acc.lsc —— 镜头阴影校正，%d 格 × 4 通道 × %d 档 ─────────────────
 * JSON: .SC202CS.acc.lsc.table[ct].calibrations_{r,gr,gb,b}_tbl[%d]
 *
 * 定点：round(v × 256)，对应 isp_lsc_gain_t 的 **2 整数位 + 8 小数位**
 * ⇒ 表达上限 %d/256 = %.3f。全表实测最大增益 **%.3f ⇒ %d**，
 *   **余量只有 %.0f%%** —— 将来换标定文件时脚本里的那条断言是唯一的守门人。
 *
 * 网格：num_grids = (res−1)/2/32 + 2 ⇒ %d×%d = %d，与 lsc_tbl_size 精确相等
 * （isp_lsc.c 按 i = y·num_grids_x + x 写 LUT）。
 * ⚠️ JSON 里 %d 个数的**排布顺序**（x 快变还是 y 快变）是 [缺口]，本脚本按 x 快变
 *   原样搬运。上板若出现「暗角修正方向横竖颠倒」（画面上下亮、左右暗），就是这里。
 *
 * ⓘ 只带 %d 档（官方 9 档全带 = %d B）。取舍：只有 R 通道随色温有明显差异
 *   （max|%dK−%dK| ≈ 0.71，其余三通道 ≤ 0.21），取 %s 后最大残差 ≈ 0.36，
 *   落在一个 ~3× 的提亮上 ≈ 12%%、且在四角、还会被 CCM/AWB 部分吸收。
 *   **要全带 9 档只改 test/isp_cal_extract.py 顶部的 LSC_CTS 再重跑。**
 *
 * 通道次序固定为 **r, gr, gb, b**，与 esp_isp_lsc_gain_array_t 的四个指针同序。 */"""
               % (n, len(LSC_CTS), n,
                  LSC_FIXED_MAX - 1, (LSC_FIXED_MAX - 1) / 256.0, gmax, rnd(gmax * 256),
                  100.0 * (LSC_FIXED_MAX - 1 - rnd(gmax * 256)) / (LSC_FIXED_MAX - 1),
                  gx, gy, n, n,
                  len(LSC_CTS), len(by_ct) * 4 * n * 2, LSC_CTS[0], LSC_CTS[-1],
                  "/".join(str(c) for c in LSC_CTS)))
    out.append("#define CAM_CAL_LSC_N       %d" % len(LSC_CTS))
    out.append("#define CAM_CAL_LSC_GRIDS   %d" % n)
    out.append("#define CAM_CAL_LSC_GRID_X  %d" % gx)
    out.append("#define CAM_CAL_LSC_GRID_Y  %d" % gy)
    out.append("static const uint16_t cam_cal_lsc_cct[CAM_CAL_LSC_N] = { %s };"
               % arr(LSC_CTS))
    out.append("/* [档][通道 r/gr/gb/b][格]，2.8 定点。 */")
    out.append("static const uint16_t cam_cal_lsc[CAM_CAL_LSC_N][4][CAM_CAL_LSC_GRIDS] = {")
    for c in LSC_CTS:
        out.append("    {   /* %d K */" % c)
        for ch in chans:
            v = tv(c, ch)
            assert len(v) == n
            fx = []
            for x in v:
                q = rnd(x * 256)
                assert 0 < q < LSC_FIXED_MAX, \
                    f"LSC {c}K/{ch} 的增益 {x} → {q} 超出 2.8 定点（上限 {LSC_FIXED_MAX - 1}）"
                fx.append(q)
            out.append("        {   /* %-2s */" % ch)
            out.append(arr(("%4d" % q for q in fx), per_line=gx, indent="            "))
            out.append("        },")
        out.append("    },")
    out.append("};")
    return len(LSC_CTS) * 4 * n * 2 + len(LSC_CTS) * 2


# ── 头文件组装 ──────────────────────────────────────────────────────────

HEADER = '''#pragma once
/*
 * SC202CS 官方 ISP 标定数据（节选）。
 *
 * ⚠️ **本文件由 test/isp_cal_extract.py 机械生成，不要手改。**
 *    改了就跑 `python3 test/isp_cal_extract.py --check`，它会失败并打出 diff。
 *
 * 来源：espressif/esp_cam_sensor（托管组件 espressif__esp_cam_sensor）
 *       sensors/sc202cs/cfg/sc202cs_default.json
 *       %(size)d 字节，md5 %(md5)s
 * SPDX-FileCopyrightText: Espressif Systems (Shanghai) CO LTD
 * SPDX-License-Identifier: Apache-2.0   （随组件 LICENSE，Apache-2.0）
 *
 * ⓘ 该 JSON 在上游只被 esp_ipa 的构建期代码生成器消费，而本工程**不引 esp_ipa**
 *   （依赖树要保持 12 个目录），所以自带那个提取脚本。**只提取用得到的部分**：
 *   %(size)d 字节里绝大多数是 LSC 的 9 档 × 4 通道 × 273 格浮点，我们只带 3 档。
 *
 * ⓘ managed_components/ 在 .gitignore 里 —— **JSON 不在仓库里**，所以本文件必须
 *   提交，脚本只是它的「可复现证明」。跑脚本前先 `idf.py build` 把组件拉下来。
 *   与 panel_init_data.h（esp-bsp 也没 vendored）的处置完全一致。
 *
 * ⓘ 这份标定是为 **rev >= 3.0** 做的（含 acc.blc 段，而 rev v1.0 的 ISP BLC 不可用）。
 *   官方三对 eco4/eco5 文件的一致交集表明：rev<3.0 的降级动作**只有删掉 acc.blc 一段**，
 *   其余各段与芯片版本无关（依据见 2026-08-19-esp32p4-official-isp-pipeline.md §D.3）。
 *   acc.blc 的数值 16 没有丢，它挪到了传感器自带 BLC 与统计侧减法上。
 *
 * ⓘ **未提取的段及理由**（逐条，别默默漏）：
 *     acc.blc                    rev v1.0 的 ISP BLC 用不了，改由传感器侧 0x3902 处理
 *     acc.ccm.low_luma           暗场把 CCM 旁路成单位阵；我们的强度参数 t 已经是同一
 *                                方向上连续可调的总闸，再叠一个硬跳变只会多一个失败模式
 *     acc.lsc.{model,img_w,img_h,lsc_tbl_size}
 *                                元数据。img_w/h/lsc_tbl_size 已在脚本里做成断言
 *                                （网格数必须等于 21×13）；model 取值枚举闭源
 *     acc.lsc.table 的其余 6 档   见下面 LSC 段的取舍说明
 *     aen.gamma.table[].y        use_gamma_param = true ⇒ 官方走 γ 解析式那一支，
 *                                y[16] 是该布尔为 false 时的备用采样点
 *     aen.gamma.{use_gamma_param,luma_env}
 *                                前者是分支选择（已按 true 处理），后者是具名量的字符串
 *     ian.luma.ae.weight         全 1，是 ian 内部亮度归约的权重；AE 用的是
 *                                agc.luma_adjust.weight 那张中心加权表
 *     ian.luma.env.weight        全 1，我们的 env 走直方图的近似均匀权重，等价
 *     ian.luma.env.speed_param   16 抽头 FIR 的滑动索引是 [缺口]，用一阶低通替代
 *     ian.color_temp.m_2         把 bg 投影回轨迹的二次拟合。提取期已验证「CCT 是 rg
 *                                的单变量函数」（±55 K），运行期不需要它
 *     ian.color_temp.{f_n0,min_step,model}
 *                                f_n0 的确切用途、model 取值枚举闭源不可知
 *     awb.{model,green_luma_*,min_red_gain_step,min_blue_gain_step}
 *                                控制律闭源；死区/阻尼/限幅在 cam_tune.h 里自己定
 *     agc.{exposure,gain}        frame_delay 这类执行侧延迟补偿，我们用
 *                                CAM_AE_INTERVAL_TICKS 表达
 *     agc.anti_flicker           不做抗工频闪烁（曝光时间未量化到 10 ms 整数倍）
 *     agc.{f_n0,f_m0}            用途 [缺口]
 *     agc.mode                   字符串；模式选择器本身闭源，由我们的背光判据代替
 *     agc.{high,low}_light_priority.{low_threshold,high_threshold,weight_offset}
 *     agc.light_threshold_priority[5]
 *                                触发条件与叠加方式 [缺口]，猜错比不加权更坏。
 *                                只取语义明确的 luma_offset（见下面 AE 段）
 *     af / atc                   本文件里没有这两段（SC202CS 定焦、不用传感器自带 AE）
 */

#include <stdint.h>
'''


def build_header(s, md5):
    out = []
    out.append(HEADER % dict(size=SRC_SIZE, md5=md5))
    total = 0
    for fn in (emit_bf, emit_demosaic, emit_sharpen, emit_contrast, emit_saturation,
               emit_gamma, emit_ccm, emit_cct_locus, emit_awb_box, emit_ae, emit_env,
               emit_lsc):
        total += fn(s, out)
    out.append("")
    out.append("/* 表数据合计约 %d 字节（不含注释与对齐填充）。 */" % total)
    return "\n".join(out) + "\n"


def main():
    s, md5 = load()
    text = build_header(s, md5)
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
    print(f"已生成 {OUT}（{len(text.encode())} 字节，源 md5 {md5}）")


if __name__ == "__main__":
    main()
