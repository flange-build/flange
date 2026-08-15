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

bool cam_ae_step(cam_ae_state_t *st, uint8_t lum_mean, const cam_ae_limits_t *lim)
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

    /* ── 闸 1：死区 ── */
    const int diff = (int)lum_mean - CAM_AE_TARGET;
    if (diff >= -CAM_AE_DEADBAND && diff <= CAM_AE_DEADBAND) {
        if (st->in_band < CAM_AE_CONVERGE_TICKS)
            st->in_band++;
        return false;
    }
    st->in_band = 0;

    /* 理论上「一步到位」的曝光量。均值为 0（全黑）时按 1 算 —— 既避免除零，
     * 又让全黑场景走到最大的一步（随后被闸 3 限成 2×），而不是原地不动。 */
    const uint32_t meas = lum_mean ? lum_mean : 1u;
    const uint64_t want = ((uint64_t)st->ev * CAM_AE_TARGET) / meas;

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
