#pragma once
/*
 * 官方标定数据的**运行期消费逻辑**：查表 / 插值 / 折叠 / 钳制 / 统计归约。
 * **纯逻辑，不含任何 ESP-IDF 头**，宿主机 cc 一下就能跑（test/test_cam_isp_map.c）。
 *
 * 与 cam_tune.h 的分工：
 *   cam_tune.h   控制律（AE 的 P 控制器、AWB 的阻尼/限幅/防护）与**全部可调参数**
 *   cam_isp_map  官方标定表的解释器 —— 输入是工作点（gain / CCT / env.luma），
 *                输出是某一级 ISP 的参数。它自己**不含任何可调参数**，
 *                改行为一律去 cam_tune.h 改开关，别改这里的表
 *                （表是 cam_isp_cal.h，由 test/isp_cal_extract.py 机械生成）。
 *
 * 定点约定（全文件统一，不要在别处再发明第三种）：
 *   *_milli   ×1000 的定点（增益、CCM 系数、grad_ratio…）
 *   *_q4      ×10000 的定点（色度比 rg/bg —— 官方标定就给到小数点后四位）
 *   *_q8      0..256 的插值权重（256 = 1.0，二分与混合都按 1/256 步进）
 *   *_q1      ×10 的定点（env.luma —— 官方断点本身就带一位小数）
 *
 * 为什么整数：所有这些量最终都要写进 ISP 的定点寄存器，浮点只会在中途引入一层
 * 「宿主机与目标机结果不同」的不可复现性，而本文件的全部价值就在于**能在宿主机上
 * 逐条测到**。CCM 的强度钳制用整数二分 8 次，不用浮点迭代，理由同上。
 */
#include <stdbool.h>
#include <stdint.h>

/* ── 按传感器总增益选档 ─────────────────────────────────────────────
 * 语义照官方：表按 gain 升序排，取「gain 不超过当前总增益的最大一档」。
 * ⓘ 官方表在断点之间是否插值是 [缺口]（官方管线文档 §C.9）。我们**不插值** ——
 *   BF 的 matrix[9] 与 SHARP 的 matrix[9] 是整数模板，插值出来的中间值没有物理意义。
 * 返回下标，恒落在 [0, n-1]。gain_milli 小于第 0 档时返回 0；
 * n == 0 或 gain_breaks == NULL 时返回 0（调用方拿它去索引空表本来就是 bug，
 * 这里只保证不越界读、不崩）。 */
uint32_t cam_map_gain_slot(const uint16_t *gain_breaks, uint32_t n, uint32_t gain_milli);

/* ── 按色温选档（升序表）+ 是否落在两档之间的插值权重 ──────────────
 * 返回下标 i，使 tbl[i] <= cct <= tbl[i+1]；*w_q8 是 cct 在 [i,i+1] 上的位置（0..256）。
 * 越界时钳到端点并令 w=0；恰好落在某一档上时也是 w=0（下标即该档）。
 * w_q8 可传 NULL。 */
uint32_t cam_map_cct_slot(const uint16_t *cct_tbl, uint32_t n, uint32_t cct_k, uint32_t *w_q8);

/* ── ×1000 定点 → 硬件的「整数位.小数位」定点 ───────────────────────
 * ISP 各级的系数寄存器是宽度各不相同的定点位域（都在 soc_caps.h 里）：
 *     demosaic.grad_ratio   2 整数位 + 4 小数位（步长 1/16）
 *     sharpen.h/m_freq_coeff 3 整数位 + 5 小数位（步长 1/32）
 * 而标定表统一存 ×1000 的原值。这里做的三件事一件都不能省：
 *   ① **四舍五入**而不是截断 —— 1.525 在 1/32 栅格上截断是 1.5000（−1.6%），
 *      四舍五入是 1.53125（+0.4%）；
 *   ② **进位** —— 舍入可能把小数部分推到 2^dec_bits（例如 3.99 在 5 位小数上
 *      舍成 32/32），此时必须进到整数位。不进位就会被位域**静默截断成 0**，
 *      3.99 变成 3.00，而现场看到的只是「锐化偏弱」这种说不清的偏差；
 *   ③ **溢出显式返回 false**，由调用方决定是钳住还是放弃这次下发 ——
 *      同样是为了不让位域悄悄吃掉高位。
 * 溢出时输出被钳到该格式能表达的最大值（(2^int−1) + (2^dec−1)/2^dec）。
 * int_bits + dec_bits 必须 <= 31；integer / decimal 不可为 NULL。
 * 官方 SC202CS 标定表里的每一个值都在范围内 ⇒ 正常路径恒返回 true；
 * 这条返回值是给「将来换标定文件」留的守门人。 */
bool cam_map_to_fixed(uint32_t milli, uint32_t int_bits, uint32_t dec_bits,
                      uint32_t *integer, uint32_t *decimal);

/* ── 带迟滞的档位跟踪器 ─────────────────────────────────────────────
 * 三组前馈（BF/Demosaic 按 gain、SHARP/对比度按 gain、CCM/LSC/饱和度按 CCT）的
 * 换档逻辑完全一样，写一次。
 *
 * 为什么必须有迟滞：本板 rev < 3.0 **没有影子寄存器**（isp_ll_shadow_update_* 在
 * 该分支里是恒真的空桩），参数写下去立刻生效、**没有帧边界原子性** —— 帧中途换
 * BF 模板会出现单帧的上下半张不同处理。AE 在档位断点上抖一下就重配一次的话，
 * 那种撕裂会以「偶发横向亮带」的形式出现，且极难归因。
 *
 * 语义：want 必须**连续** hyst 拍都指向同一个新档才真的换。返回 true 表示
 * 「档变了，调用方去重配硬件」，同时 t->cur 已更新为新档。
 * 开机第一次（primed == false）无条件返回 true —— 那一拍不是「换档」而是
 * 「从没配过到配上」，迟滞在这里没有意义，等 3 拍只会让开机头 300 ms 没有前馈。
 * hyst == 0 按 1 处理（不允许「零拍确认」把迟滞整个短路）。
 * 结构体由调用方零初始化即可。 */
typedef struct {
    uint32_t cur;      /* 已下发的档 */
    uint32_t pending;  /* 候选档 */
    uint32_t count;    /* 候选档已连续出现几拍 */
    bool     primed;   /* 开机第一次下发过了吗 */
} cam_slot_track_t;

bool cam_slot_changed(cam_slot_track_t *t, uint32_t want, uint32_t hyst);

/* ── rg → CCT（官方 16 点轨迹，线性插值，两端钳位）────────────────
 * rg_q4 = (Σr/Σg) × 10000。返回开尔文，恒落在
 * [cam_cal_cct_k[CAM_CAL_CCT_N-1], cam_cal_cct_k[0]] = [2289, 7466]。
 *
 * ⚠️ 为什么是查表而不是在运行期套官方那条三次多项式：该多项式在 rg > 0.78 处
 *   **不单调**（暖端有一处 15 K 的拟合噪声反转），拿它做选档标量会在暖光下来回跳档。
 *   提取脚本已经在 16 个标定点上把三段数学算完并**强制成单调序列**，
 *   于是本函数的输出对 rg 是**单调非增**的 —— 这条性质由宿主机测试全程扫描守着。 */
uint32_t cam_cct_from_rg(uint32_t rg_q4);

/* ── CCM：按 CCT 在官方 19 档间逐元素线性插值 ─────────────────────
 * 输出 9 个 ×1000 的系数，行主序。两端（1200 K / 12000 K）是官方给的单位阵。
 * out_milli 不可为 NULL。 */
void cam_ccm_at_cct(uint32_t cct_k, int32_t out_milli[9]);

/* 硬件 S2.10 的表达上限是 4095/1024 = 3.9990；留一档量化余量 ⇒ 3990。
 * esp_isp_ccm_configure() 的范围检查是闭区间 [-4.0, 4.0]（isp_ccm.c），
 * 但 isp_hal_ccm_set_matrix() 在 saturation=false 时会对越界值直接失败，
 * 而 saturation=true 又等于让硬件**悄悄改我们的矩阵**、自检行还在打原值。
 * 两条都不能指望 ⇒ 自己钳在 3990 以内。 */
#define CAM_CCM_ABS_MAX_MILLI  3990

/*
 * ── CCM：在给定强度 t 上做一次折叠（不搜索）───────────────────────
 *
 *   P(t) = ((1−t)·I + t·M) · diag(kr, 1, kb) ,  t = t_q8 / 256
 *
 * 返回该 t 是否可行（所有系数的 |v| <= CAM_CCM_ABS_MAX_MILLI）。out 可传 NULL
 * （只问可行性、不要结果）。
 *
 * 正常路径请用下面的 cam_ccm_fold_wb()；本函数导出是为了让宿主机测试能**直接**
 * 验证「可行域是以 0 为起点的区间」与「二分给出的 t 是最大可行 t」这两条 ——
 * 若把它藏成 static，测试就只能复制一份实现来验，那验的是复制品不是它本身。
 */
bool cam_ccm_fold_at(const int32_t m_milli[9], uint32_t kr_milli, uint32_t kb_milli,
                     uint32_t t_q8, int32_t out_milli[9]);

/*
 * ── CCM：把白平衡增益折进矩阵，并把系数钳进 rev v1.0 的 S2.10（±4.0）───
 *
 * 取满足 max|P(t)| <= CAM_CCM_ABS_MAX_MILLI 的**最大** t（8 次二分，t 以 1/256 计）。
 * 完整推导见计划 §D.4。三条不变式（宿主机测试逐条守着）：
 *   ① 任意 t，M(t) 的行和恒为 1000（整数截断误差 <= 2）⇒ 中性面出来仍精确中性、
 *      整体增益精确为 1，**一点亮度都不损失**（这正是「朝单位阵混合」优于
 *      「整体乘一个 α 缩小」的地方：后者要 AE 多加 1/α 的曝光或增益）；
 *   ② t = 0 ⇒ P = diag(kr, 1, kb)，正是本改动之前已实机验证过的那条对角阵路径
 *      ⇒ 钳到底也只是回到已验证状态，不存在新的失败模式；
 *   ③ 调用方把 kr/kb 钳在 [1000, 3445]（由官方白点轨迹反推的物理自洽范围）
 *      ⇒ t=0 必然可行（max(kr,1,kb) <= 3445 < 3990）⇒ 二分不会失败。
 * 返回实际采用的 t（0..256）。out_milli 不可为 NULL。
 */
uint32_t cam_ccm_fold_wb(const int32_t m_milli[9], uint32_t kr_milli, uint32_t kb_milli,
                         int32_t out_milli[9]);

/* ── AE：25 块 → 加权均值（官方权重表）+ 过暗/过亮块 quorum 剔除 ────
 * n_dark  = 亮度 <  CAM_CAL_AE_LOW_THRESH(14)  的块数
 * n_bright= 亮度 >  CAM_CAL_AE_HIGH_THRESH(239) 的块数
 * 只有当 n_dark >= CAM_CAL_AE_LOW_REGIONS(5) 或 n_bright >= CAM_CAL_AE_HIGH_REGIONS(3)
 * 时才**剔除**对应的块 —— 官方是「计数达标才进保护分支」，不是每块都挑。
 * 两个 quorum 各自独立生效。
 * 全被剔除（权重和为 0）时退回 25 块的**无权算术平均**，保证永远给得出一个数。
 * n_dark / n_bright 可传 NULL；lum 为 NULL 时返回 0 并把两个计数清 0。 */
uint8_t cam_ae_weighted_mean(const uint8_t lum[25], uint8_t *n_dark, uint8_t *n_bright);

/* ── 直方图 16 bin → 场景均值 / 亮块占比 / 暗块占比（百分数）───────
 * bin i 覆盖 [16i, 16i+15]，取中心 16i+8 作代表值 ⇒ mean 恒落在 [8, 248]。
 * dark_pct  = bin 0  的占比（覆盖 0..15，官方 low_threshold 14 落在其中）
 * bright_pct= bin 15 的占比（覆盖 240..255，恰好就是官方 high_threshold 239 之上）
 * ⓘ 两端 bin 与官方两个阈值只是**近似**对齐（bin 0 多含了 14、15 两级），
 *   16 bin 的分辨率就到这里；它只用于背光判据这类定性判断，不进 AE 的执行量。
 * 三个输出指针都可传 NULL；total == 0（或 bins == NULL）时全部输出 0。 */
void cam_hist_stats(const uint32_t bins[16], uint8_t *mean, uint8_t *bright_pct,
                    uint8_t *dark_pct);

/* ── env.luma 重建（单位 1/10）：CAM_CAL_ENV_K × 10 × scene_mean /(target × ev) ──
 * 依据见计划 §E.5（[反推，数值一致性]，**非确证**）。AE 收敛时 scene_mean ≈ target
 * ⇒ 退化成 250000/ev，官方四个 gamma 断点恰好对应 ev = 16556/8306/2775/833。
 * ev == 0 或 ae_target == 0 时返回 0。 */
uint32_t cam_env_luma_q1(uint32_t ev, uint8_t scene_mean, uint8_t ae_target);

/* ── gamma 选档（4 档，带官方 luma_min_step = 3.0 的迟滞）────────────
 * 档 i 的语义：env_q1 <= cam_cal_gamma_luma_q1[i] 的最小 i；都超过就取末档。
 * （env 小 = 环境暗 = 曝光量大 ⇒ 取 γ 最小那档，提亮最强。）
 * cur_slot 传当前档，返回新档。只有越过断点**且**超出 CAM_CAL_GAMMA_MIN_STEP_Q1
 * 的迟滞带才换档；cur_slot 越界时按无迟滞处理（开机第一拍）。 */
uint32_t cam_gamma_slot(uint32_t env_q1, uint32_t cur_slot);
