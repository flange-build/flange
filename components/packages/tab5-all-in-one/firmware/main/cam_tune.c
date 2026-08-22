/*
 * 摄像头画质调校的纯逻辑部分。设计意图、可调参数与判读方式全在 cam_tune.h。
 * **不含任何 ESP-IDF 依赖** —— 宿主机上 cc 一下就能跑（test/test_cam_tune.c）。
 */
#include "cam_tune.h"

uint32_t cam_ae_ev(uint32_t exposure, uint32_t gain_milli)
{
    return (uint32_t)(((uint64_t)exposure * gain_milli) / 1000u);
}

/* limits 至少要有一张非空的增益表，否则一切无从谈起。 */
static bool limits_ok(const cam_ae_limits_t *lim)
{
    return lim && lim->gain_map && lim->gain_count > 0 && lim->exp_max >= lim->exp_min;
}

void cam_ae_split(uint32_t ev, const cam_ae_limits_t *lim,
                  uint32_t *exposure, uint32_t *gain_index)
{
    if (!exposure || !gain_index)
        return;
    if (!limits_ok(lim)) {
        *exposure = 0;
        *gain_index = 0;
        return;
    }

    /* 曝光时间优先：能用曝光解决的就不动增益。 */
    uint32_t exp = ev;
    if (exp > lim->exp_max)
        exp = lim->exp_max;
    if (exp < lim->exp_min)
        exp = lim->exp_min;

    /* 还差多少倍，交给增益。exp ≥ exp_min ≥ 1，不会除零（exp_min 为 0 时也被下面
     * 的三目挡住 —— 传感器的曝光下限为 0 是不合理的，但代码不该因此崩）。 */
    const uint32_t need = exp ? (uint32_t)(((uint64_t)ev * 1000u) / exp) : lim->gain_map[0];

    /* 取「不超过 need、且不超过增益上限」的最大一档。表是单调升的，线性扫即可
     * （几百项、每 300 ms 才走一次，二分带来的复杂度不值那点时间）。 */
    uint32_t idx = 0;
    for (uint32_t i = 0; i < lim->gain_count; i++) {
        if (lim->gain_map[i] > need || lim->gain_map[i] > CAM_AE_GAIN_MAX_MILLI)
            break;
        idx = i;
    }

    *exposure = exp;
    *gain_index = idx;
}

void cam_ae_init(cam_ae_state_t *st, const cam_ae_limits_t *lim,
                 uint32_t exposure, uint32_t gain_index)
{
    if (!st)
        return;
    const cam_ae_state_t zero = {0};
    *st = zero;
    if (!limits_ok(lim))
        return;

    if (gain_index >= lim->gain_count)
        gain_index = lim->gain_count - 1;   /* 见 cam_tune.h 里那条越界 ⚠️ */
    if (exposure > lim->exp_max)
        exposure = lim->exp_max;
    if (exposure < lim->exp_min)
        exposure = lim->exp_min;

    st->exposure = exposure;
    st->gain_index = gain_index;
    st->ev = cam_ae_ev(exposure, lim->gain_map[gain_index]);
}

bool cam_ae_backlight(uint8_t bright_pct, uint8_t scene_mean)
{
#if CAM_BACKLIGHT_ENABLE
    return bright_pct >= CAM_BACKLIGHT_BRIGHT_PCT && (int)scene_mean < CAM_AE_TARGET_LOW;
#else
    (void)bright_pct;
    (void)scene_mean;
    return false;
#endif
}

int cam_ae_target(bool backlight)
{
    return CAM_AE_TARGET + (backlight ? CAM_AE_LL_OFFSET : CAM_AE_HL_OFFSET);
}

bool cam_ae_step(cam_ae_state_t *st, uint8_t lum_mean, int target, const cam_ae_limits_t *lim)
{
    if (!st || !limits_ok(lim))
        return false;

    st->last_mean = lum_mean;

    /* ── 闸 4：更新频率限制 ── 没到周期就只记录、不计算。 */
    if (st->settle) {
        st->settle--;
        return false;
    }
    st->settle = CAM_AE_INTERVAL_TICKS > 0 ? CAM_AE_INTERVAL_TICKS - 1 : 0;

    /* ── 闸 1：死区 ──
     * 边界是「目标 + 官方偏移」而不是「目标 ± 死区」：官方的死区是**非对称**
     * 的（56/62/64，即 −6/+2），对齐时不对称本身也要一起对齐（理由见 cam_tune.h）。
     * target 由调用方传入（高光优先 59 / 暗部优先 63），死区**跟着它平移** ——
     * 不对称是死区的性质，不是 62 这个数的性质。
     * CAM_AE_SOURCE = 0 时那两个宏退化成对称形式 ⇒ 本行在两种配置下都对。 */
    const int band_lo = target + (CAM_AE_TARGET_LOW - CAM_AE_TARGET);
    const int band_hi = target + (CAM_AE_TARGET_HIGH - CAM_AE_TARGET);
    if ((int)lum_mean >= band_lo && (int)lum_mean <= band_hi) {
        if (st->in_band < CAM_AE_CONVERGE_TICKS)
            st->in_band++;
        return false;
    }
    st->in_band = 0;

    /* 理论上「一步到位」的曝光量。均值为 0（全黑）时按 1 算 —— 既避免除零，
     * 又让全黑场景走到最大的一步（随后被闸 3 限成 2×），而不是原地不动。 */
    const uint32_t meas = lum_mean ? lum_mean : 1u;
    const uint64_t want = ((uint64_t)st->ev * (uint32_t)(target > 0 ? target : 1)) / meas;

    /* ── 闸 2：阻尼 ── 只走到理论值的 NUM/DEN。用有符号数：want 可能小于 ev。 */
    int64_t next = (int64_t)st->ev +
                   ((int64_t)want - (int64_t)st->ev) * CAM_AE_DAMP_NUM / CAM_AE_DAMP_DEN;

    /* ── 闸 3：单步限幅 ── 一拍最多 ×N 或 ÷N。 */
    const int64_t hi = (int64_t)st->ev * CAM_AE_STEP_MAX;
    const int64_t lo = (int64_t)st->ev / CAM_AE_STEP_MAX;
    if (next > hi)
        next = hi;
    if (next < lo)
        next = lo;

    /* 传感器的物理上下限。ev_min 恒用增益表第 0 档：低于 1× 的档位表里没有。 */
    const uint32_t gmax = lim->gain_map[lim->gain_count - 1] > CAM_AE_GAIN_MAX_MILLI
                              ? CAM_AE_GAIN_MAX_MILLI
                              : lim->gain_map[lim->gain_count - 1];
    const int64_t ev_min = (int64_t)cam_ae_ev(lim->exp_min, lim->gain_map[0]);
    const int64_t ev_max = (int64_t)cam_ae_ev(lim->exp_max, gmax);
    if (next < ev_min)
        next = ev_min;
    if (next > ev_max)
        next = ev_max;

    uint32_t exposure = 0, gain_index = 0;
    cam_ae_split((uint32_t)next, lim, &exposure, &gain_index);

    /* 顶到上下限、或者量化后落回同一档：什么都没变，别去打扰 I2C 总线。 */
    if (exposure == st->exposure && gain_index == st->gain_index)
        return false;

    st->exposure = exposure;
    st->gain_index = gain_index;
    /* **存量化后的实际曝光量**，不是请求值 —— 理由见 cam_tune.h 的 cam_ae_step()。 */
    st->ev = cam_ae_ev(exposure, lim->gain_map[gain_index]);
    st->updates++;
    return true;
}

bool cam_ae_converged(const cam_ae_state_t *st)
{
    return st && st->in_band >= CAM_AE_CONVERGE_TICKS;
}

/* CCM 系数的合理区间。上限 4.0 是 rev < 3.0 定点格式的硬上限（cam_tune.h 文件头）。 */
#define CAM_CCM_MIN_MILLI   250u
#define CAM_CCM_MAX_MILLI   4000u

static uint32_t suggest_one(uint8_t chan_mean, uint8_t g_mean, uint32_t cur_milli)
{
    if (chan_mean == 0)
        return cur_milli;      /* 该通道全黑：无从推断，保持原样 */
    uint64_t v = ((uint64_t)cur_milli * g_mean) / chan_mean;
    if (v < CAM_CCM_MIN_MILLI)
        v = CAM_CCM_MIN_MILLI;
    if (v > CAM_CCM_MAX_MILLI)
        v = CAM_CCM_MAX_MILLI;
    return (uint32_t)v;
}

void cam_awb_suggest(uint8_t r_mean, uint8_t g_mean, uint8_t b_mean,
                     uint32_t cur_r_milli, uint32_t cur_b_milli,
                     uint32_t *sug_r_milli, uint32_t *sug_b_milli)
{
    if (sug_r_milli)
        *sug_r_milli = suggest_one(r_mean, g_mean, cur_r_milli);
    if (sug_b_milli)
        *sug_b_milli = suggest_one(b_mean, g_mean, cur_b_milli);
}

/* ══ 闭环 AWB ═══════════════════════════════════════════════════════ */

void cam_awb_init(cam_awb_state_t *st)
{
    if (!st)
        return;
    const cam_awb_state_t zero = {0};
    *st = zero;
    st->gain_r_milli = CAM_CCM_GAIN_R_MILLI;
    st->gain_b_milli = CAM_CCM_GAIN_B_MILLI;
    st->last = CAM_AWB_SKIP_PERIOD;
}

/* 记账 + 返回。每一拍恰好走一次这里，reasons[] 因此是完整的直方图。 */
static cam_awb_reason_t awb_done(cam_awb_state_t *st, cam_awb_reason_t r)
{
    st->last = r;
    st->reasons[r]++;
    return r;
}

/*
 * 一个通道的目标增益：阻尼 → 单步限幅 → 合理范围。
 * 顺序不能换：先阻尼决定「走多远」，再限幅决定「一次最多走多远」，
 * 最后那道范围钳制只是数值安全网（真正的范围判据是调用处的 SKIP_RANGE，
 * 它在**建议值**上判，不可信的建议根本走不到这里）。
 */
static uint32_t awb_next(uint32_t cur, uint32_t sug)
{
    int64_t next = (int64_t)cur +
                   ((int64_t)sug - (int64_t)cur) * CAM_AWB_DAMP_NUM / CAM_AWB_DAMP_DEN;

    const int64_t span = (int64_t)cur * CAM_AWB_STEP_MAX_PCT / 100;
    if (next > (int64_t)cur + span)
        next = (int64_t)cur + span;
    if (next < (int64_t)cur - span)
        next = (int64_t)cur - span;

    if (next < CAM_AWB_GAIN_MIN_MILLI)
        next = CAM_AWB_GAIN_MIN_MILLI;
    if (next > CAM_AWB_GAIN_MAX_MILLI)
        next = CAM_AWB_GAIN_MAX_MILLI;
    return (uint32_t)next;
}

/* |a − b| 占 b 的百分比。b 为 0 时按「差得无穷远」处理（返回 100 以上）。 */
static uint32_t diff_pct(uint32_t a, uint32_t b)
{
    if (b == 0)
        return 1000;
    const uint32_t d = a > b ? a - b : b - a;
    return (uint32_t)(((uint64_t)d * 100u) / b);
}

cam_awb_reason_t cam_awb_step(cam_awb_state_t *st, uint8_t lum_mean,
                              uint8_t r_mean, uint8_t g_mean, uint8_t b_mean,
                              bool ae_converged)
{
    if (!st)
        return CAM_AWB_SKIP_PERIOD;

    st->last_r = r_mean;
    st->last_g = g_mean;
    st->last_b = b_mean;

    /*
     * ── 场景可信度判据（四道防护里的前三道 + AE 闸）──
     *
     * 排在频率限制**之前**，而且都是不带副作用的纯算术：这样 st->last 永远
     * 反映的是「这一帧的场景怎么样」，而不是「还没到点」。它们也**不消耗
     * settle 计数** —— 场景不可信的那段时间不算进更新周期里，等场景恢复了
     * 还要再等满一个周期才动，正好给 AE 留出重新稳定的时间。
     */
    if (!ae_converged)
        return awb_done(st, CAM_AWB_SKIP_AE);
    if (lum_mean < CAM_AWB_LUM_MIN)
        return awb_done(st, CAM_AWB_SKIP_DARK);
    if (lum_mean > CAM_AWB_LUM_MAX)
        return awb_done(st, CAM_AWB_SKIP_BRIGHT);

    /* 防护③：三通道均值的 max/min。任一通道为 0 ⇒ 无穷大色偏 ⇒ 拦下
     * （这同时是 suggest_one() 那个除零守卫在闭环里的第一道保险）。 */
    uint32_t hi = r_mean, lo = r_mean;
    if (g_mean > hi) hi = g_mean;
    if (g_mean < lo) lo = g_mean;
    if (b_mean > hi) hi = b_mean;
    if (b_mean < lo) lo = b_mean;
    if (lo == 0 || (hi * 100u) / lo > CAM_AWB_CAST_MAX_PCT)
        return awb_done(st, CAM_AWB_SKIP_CAST);

    /* ── 频率限制 ── 场景可信，但一秒才允许动一次。 */
    if (st->settle) {
        st->settle--;
        return awb_done(st, CAM_AWB_SKIP_PERIOD);
    }
    st->settle = CAM_AWB_INTERVAL_TICKS > 0 ? CAM_AWB_INTERVAL_TICKS - 1 : 0;

    uint32_t sug_r = st->gain_r_milli, sug_b = st->gain_b_milli;
    cam_awb_suggest(r_mean, g_mean, b_mean, st->gain_r_milli, st->gain_b_milli,
                    &sug_r, &sug_b);

    /*
     * 防护④：建议值必须落在合理范围内，否则**整拍不动**。
     * 注意判的是建议值（场景直接推出来的绝对目标）而不是阻尼后的值：
     * 阻尼后的值必然在范围内（awb_next 自己钳了），拿它来判等于永远不触发。
     */
    if (sug_r < CAM_AWB_GAIN_MIN_MILLI || sug_r > CAM_AWB_GAIN_MAX_MILLI ||
        sug_b < CAM_AWB_GAIN_MIN_MILLI || sug_b > CAM_AWB_GAIN_MAX_MILLI)
        return awb_done(st, CAM_AWB_SKIP_RANGE);

    /* ── 死区 ── 两个通道都差得不多才算「已经平衡」。 */
    if (diff_pct(sug_r, st->gain_r_milli) <= CAM_AWB_DEADBAND_PCT &&
        diff_pct(sug_b, st->gain_b_milli) <= CAM_AWB_DEADBAND_PCT) {
        if (st->in_band < CAM_AWB_CONVERGE_TICKS)
            st->in_band++;
        return awb_done(st, CAM_AWB_SKIP_BAND);
    }

    const uint32_t next_r = awb_next(st->gain_r_milli, sug_r);
    const uint32_t next_b = awb_next(st->gain_b_milli, sug_b);

    /* 整数运算后没有实际变化：别去重配 CCM（9 个寄存器写 + 一次可能的撕裂）。 */
    if (next_r == st->gain_r_milli && next_b == st->gain_b_milli)
        return awb_done(st, CAM_AWB_SKIP_QUANT);

    st->gain_r_milli = next_r;
    st->gain_b_milli = next_b;
    st->in_band = 0;
    st->updates++;
    return awb_done(st, CAM_AWB_APPLIED);
}

bool cam_awb_converged(const cam_awb_state_t *st)
{
    return st && st->in_band >= CAM_AWB_CONVERGE_TICKS;
}

/* ══ 硬件白点统计（采样点 = CCM 之前）══════════════════════════════ */

bool cam_awb_ratios(const cam_awb_hw_stat_t *s, uint32_t *rg_q4, uint32_t *bg_q4)
{
    if (!s || !rg_q4 || !bg_q4 || s->counted == 0)
        return false;

    /* 统计侧黑电平扣除。counted 是硬件数出来的参与像素数 ⇒ 这个减法精确。
     * 常量为 0 时下面三行是恒等变换，编译器会整段折掉（不写 #if 是为了让
     * 「开与不开」走的是同一条代码路径，宿主机用例才能两种都测到）。 */
    const uint64_t ped = (uint64_t)CAM_STAT_BLC_PEDESTAL * s->counted;
    const uint64_t sr = s->sum_r > ped ? (uint64_t)s->sum_r - ped : 0;
    const uint64_t sg = s->sum_g > ped ? (uint64_t)s->sum_g - ped : 0;
    const uint64_t sb = s->sum_b > ped ? (uint64_t)s->sum_b - ped : 0;
    if (sg == 0)
        return false;

    /* ⚠️ 必须 uint64：Σ 满量程 1280×720×255 = 2.35e8，×10000 就溢出 uint32 了。 */
    *rg_q4 = (uint32_t)(sr * 10000u / sg);
    *bg_q4 = (uint32_t)(sb * 10000u / sg);
    return true;
}

/*
 * ⚠️⚠️ 读这个函数之前先读 cam_tune.h 的 CAM_AWB_SOURCE。
 *
 * 一句话：**这里面不许出现 st->gain_r_milli / st->gain_b_milli 参与建议值的
 * 计算。** 它们只允许出现在三个地方 —— 死区比较、awb_next() 的起点、以及最后
 * 的赋值。任何形如 `sug = st->gain_* × ...` 的写法都是 CAM_AWB_SOURCE 那段说的
 * 那个单调发散错误。签名里拿不到外部传进来的 cur 是第一重防呆，这条注释与
 * 宿主机的不动点用例是第二、第三重。
 */
cam_awb_reason_t cam_awb_step_hw(cam_awb_state_t *st, const cam_awb_hw_stat_t *s,
                                 bool ae_converged)
{
    if (!st || !s)
        return CAM_AWB_SKIP_PERIOD;

    /* ── 场景可信度 ── 与旧函数同一处置：纯算术、无副作用、不改任何状态。 */
    if (!ae_converged)
        return awb_done(st, CAM_AWB_SKIP_AE);

    /* 白点太少 ⇒ 这一拍的估计不可信。**这一条替代了灰世界那条「色偏过大」**：
     * 镜头怼着红墙时硬件筛不出中性像素，counted 会掉到几百，正是这里挡住。 */
    if (s->counted < CAM_AWB_MIN_COUNTED)
        return awb_done(st, CAM_AWB_SKIP_COUNT);

    uint32_t rg_q4 = 0, bg_q4 = 0;
    /* 算不出来（Σg 被基座扣成 0，或 counted 为 0）也归到「白点太少」：
     * 两者是同一件事 —— 没有足够可信的白点像素。 */
    if (!cam_awb_ratios(s, &rg_q4, &bg_q4))
        return awb_done(st, CAM_AWB_SKIP_COUNT);

    /* 重心必须落在官方白点轨迹的包围盒里，否则整拍不动（不是钳到边界上采纳）。 */
    if (rg_q4 < CAM_AWB_RG_MIN_Q4 || rg_q4 > CAM_AWB_RG_MAX_Q4 ||
        bg_q4 < CAM_AWB_BG_MIN_Q4 || bg_q4 > CAM_AWB_BG_MAX_Q4)
        return awb_done(st, CAM_AWB_SKIP_RANGE);

    /*
     * ══ 绝对增益。**没有 cur**，看签名就知道乘不进去。══
     * sug = (1/rg) × 1000 = 10^7 / rg_q4。rg_q4 已由上面的盒子保证 ≥ 3801，
     * 不会除零、也不会溢出（最大 10^7/2903 = 3445）。
     */
    const uint32_t sug_r = 10000000u / rg_q4;
    const uint32_t sug_b = 10000000u / bg_q4;

    /* ── 死区 ── 两个通道都差得不多才算「已经平衡」。 */
    if (diff_pct(sug_r, st->gain_r_milli) <= CAM_AWB_DEADBAND_PCT &&
        diff_pct(sug_b, st->gain_b_milli) <= CAM_AWB_DEADBAND_PCT) {
        if (st->in_band < CAM_AWB_CONVERGE_TICKS)
            st->in_band++;
        return awb_done(st, CAM_AWB_SKIP_BAND);
    }

    /* 阻尼 → 单步限幅 → 范围钳制，与软件路**共用同一个** awb_next()：
     * 这一段管的是「怎么走过去」，与「目标是多少」正交，换估计器不该动它。 */
    const uint32_t next_r = awb_next(st->gain_r_milli, sug_r);
    const uint32_t next_b = awb_next(st->gain_b_milli, sug_b);
    if (next_r == st->gain_r_milli && next_b == st->gain_b_milli)
        return awb_done(st, CAM_AWB_SKIP_QUANT);

    st->gain_r_milli = next_r;
    st->gain_b_milli = next_b;
    st->in_band = 0;
    st->updates++;
    return awb_done(st, CAM_AWB_APPLIED);
}

const char *cam_awb_reason_str(cam_awb_reason_t r)
{
    switch (r) {
    case CAM_AWB_APPLIED:      return "已更新";
    case CAM_AWB_SKIP_AE:      return "AE未稳";
    case CAM_AWB_SKIP_COUNT:   return "白点太少";
    case CAM_AWB_SKIP_DARK:    return "暗场";
    case CAM_AWB_SKIP_BRIGHT:  return "过亮";
    case CAM_AWB_SKIP_CAST:    return "色偏过大";
    case CAM_AWB_SKIP_PERIOD:  return "未到周期";
    case CAM_AWB_SKIP_BAND:    return "死区内";
    case CAM_AWB_SKIP_RANGE:   return "增益越界";
    case CAM_AWB_SKIP_QUANT:   return "量化无变化";
    default:                   return "未知";
    }
}
