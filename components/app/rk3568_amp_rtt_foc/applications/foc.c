/*
 * foc.c —— rk3568_amp_rtt_foc 电机驱动（里程碑 1：开环 SVPWM，直驱 PWM3 三相）。
 *
 * 数据流（即完整 FOC 的下半截，里程碑 2 只需把 theta_e 换成编码器真值）：
 *   开环匀速 theta_e ──▶ 反 Park(Ud=0,Uq) ──▶ (Ualpha,Ubeta)
 *                    ──▶ SVPWM(min-max 零序注入) ──▶ 三相占空比
 *                    ──▶ HAL_PWM PWM3 ch0/1/2（center-aligned + GlobalLock 原子刷新）
 *
 * 控制节拍：一个专用高优先级线程按 FOC_CTRL_FREQ_HZ 用 HAL_DelayUs 定拍更新占空比
 * （里程碑 1 不引 IRQ/定时器，避开 AMP GIC 白名单问题；cpu3 为从核专用，忙等可接受。
 * 里程碑 2 上电流环时改由 ADC/定时器 ISR 驱动）。PWM 载波由 PWM3 硬件持续产生。
 */
#include "foc.h"
#include "as5600.h"
#include <rtdevice.h>
#include <math.h>
#include <stdlib.h>
#include "hal_base.h"

#ifndef RT_USING_PWM
#warning "rk3568_amp_rtt_foc 需 RT_USING_PWM=y 以使能 hal_conf.h 的 HAL_PWM 门控"
#endif

/* PWM3 三相通道映射：pwm12=ch0, pwm13=ch1, pwm14=ch2 */
#define PH_A_CH   0u
#define PH_B_CH   1u
#define PH_C_CH   2u
#define PWM_CH_MASK  ((1u << PH_A_CH) | (1u << PH_B_CH) | (1u << PH_C_CH))

#define PWM_PERIOD_NS   (1000000000u / FOC_PWM_FREQ_HZ)   /* 20kHz → 50000ns */
#define TWO_PI          6.28318530718f
#define PI              3.14159265359f
#define HALF_PI         1.57079632679f
#define SQRT3_2         0.86602540378f
#define CTRL_DT         (1.0f / (float)FOC_CTRL_FREQ_HZ)   /* 控制周期 s */

struct foc_runtime g_foc = {
    .enabled        = 0,
    .mode           = FOC_MODE_VOLTAGE,
    .dir            = 1,
    .uq_ratio       = 0.0f,
    .calibrated     = 0,
    .enc_dir        = 1,
    .enc_offset_rad = 0.0f,
    .theta_e        = 0.0f,
    .pos_meas       = 0.0f,
    .omega_meas     = 0.0f,
    .target_speed   = 0.0f,
    .target_pos     = 0.0f,
    /* 经验起步值（保守）：目标默认 0/当前位置，故 en 不会乱动。上板从这组往上调：
     * 弱/跟不动→加 kp；有稳态差→加 ki；抖/超调→降 kp 或加滤波。Uq 为 Vdc 归一
     * [0,0.55]，故速度环增益偏小。*/
    .spd_kp = 0.01f, .spd_ki = 0.10f,        /* 速度环 PI */
    .pos_kp = 5.0f,  .pos_ki = 0.0f, .pos_kd = 0.0f,  /* 位置环默认纯 P */
    .vlim      = 20.0f,   /* 位置环限速 20 rad/s */
    .ema_alpha = 0.1f,    /* 速度估计 EMA（非控制增益，使测速可用）*/
};

static struct PWM_HANDLE s_pwm;

/* 控制器内部状态（不经命令暴露）*/
static float s_spd_integ;      /* 速度环积分累加（= Uq 分量）*/
static float s_pos_integ;      /* 位置环积分累加（= ω_set 分量）*/
static float s_pos_prev_mech;  /* 上次机械角（多圈翻圈检测用）*/
static long  s_turns;          /* 累计圈数 */

/* ---- 底层：IOMUX / GPIO / PWM3 初始化 ---- */

static void foc_iomux_init(void)
{
    /* 三相 PWM（mux 号取自内核权威 rk3568-pinctrl.dtsi）：
     *   pwm12 gpio3_b7 = func2, pwm13 gpio3_c0 = func2, pwm14 gpio3_c4 = func1 */
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3, GPIO_PIN_B7, PIN_CONFIG_MUX_FUNC2);
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3, GPIO_PIN_C0, PIN_CONFIG_MUX_FUNC2);
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3, GPIO_PIN_C4, PIN_CONFIG_MUX_FUNC1);
    /* EN/FLIP：gpio3_a5 / gpio3_a4 纯 GPIO（mux0）*/
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3, GPIO_PIN_A5, PIN_CONFIG_MUX_FUNC0);
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3, GPIO_PIN_A4, PIN_CONFIG_MUX_FUNC0);
    /* i2c2：gpio0_b5/b6 m0 = mux1（里程碑 2 磁编码器用，此处占位配好）*/
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0, GPIO_PIN_B5, PIN_CONFIG_MUX_FUNC1);
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0, GPIO_PIN_B6, PIN_CONFIG_MUX_FUNC1);
}

static void foc_gpio_init(void)
{
    /* EN(gpio3_a5)=输出（栅驱使能）；FAULT(gpio3_a4)=输入（栅驱故障脚，只读，不驱动）。
     * 旋转方向由 FOC 软件做（转矩矢量符号），无硬件方向脚。*/
    HAL_GPIO_SetPinDirection(GPIO3, GPIO_PIN_A5, GPIO_OUT);
    HAL_GPIO_SetPinDirection(GPIO3, GPIO_PIN_A4, GPIO_IN);
    HAL_GPIO_SetPinLevel(GPIO3, GPIO_PIN_A5,
                         FOC_EN_ACTIVE_HIGH ? GPIO_LOW : GPIO_HIGH);
}

static void foc_en_set(int on)
{
    eGPIO_pinLevel lvl = (FOC_EN_ACTIVE_HIGH == !!on) ? GPIO_HIGH : GPIO_LOW;
    HAL_GPIO_SetPinLevel(GPIO3, GPIO_PIN_A5, lvl);
}

/* 读栅驱故障脚（gpio3_a4）。故障脚多为低有效（nFAULT），返回 1 表示故障有效（低）。*/
static int foc_fault_active(void)
{
    return HAL_GPIO_GetPinLevel(GPIO3, GPIO_PIN_A4) == GPIO_LOW;
}

static void foc_pwm_set_duty(uint8_t ch, float duty)
{
    struct HAL_PWM_CONFIG cfg;
    if (duty < 0.0f) duty = 0.0f;
    if (duty > 1.0f) duty = 1.0f;
    cfg.channel     = ch;
    cfg.periodNS    = PWM_PERIOD_NS;
    cfg.dutyNS      = (uint32_t)(duty * (float)PWM_PERIOD_NS);
    cfg.polarity    = FOC_PWM_POLARITY;
    cfg.alignedMode = HAL_PWM_CENTER_ALIGNED;
    HAL_PWM_SetConfig(&s_pwm, ch, &cfg);
}

static void foc_pwm_init(void)
{
    /* 使能 PWM3 时钟/门控并设定输入时钟（AMP 从核自管，勿依赖 master 预置）*/
    HAL_CRU_ClkEnable(PCLK_PWM3_GATE);
    HAL_CRU_ClkEnable(CLK_PWM3_GATE);
    HAL_CRU_ClkSetFreq(CLK_PWM3, FOC_PWM_CLK_HZ);
    HAL_PWM_Init(&s_pwm, PWM3, FOC_PWM_CLK_HZ);

    /* 三相初始 50% 占空（零差分），center-aligned；先不使能输出 */
    foc_pwm_set_duty(PH_A_CH, 0.5f);
    foc_pwm_set_duty(PH_B_CH, 0.5f);
    foc_pwm_set_duty(PH_C_CH, 0.5f);
    HAL_PWM_Enable(&s_pwm, PH_A_CH, HAL_PWM_CONTINUOUS);
    HAL_PWM_Enable(&s_pwm, PH_B_CH, HAL_PWM_CONTINUOUS);
    HAL_PWM_Enable(&s_pwm, PH_C_CH, HAL_PWM_CONTINUOUS);
}

/* ---- 调制：反 Park + SVPWM(min-max) ---- */

static void foc_modulate(float theta_e, float uq_ratio,
                         float *da, float *db, float *dc)
{
    /* 反 Park（Ud=0）：单位为 Vdc 比例 */
    float ualpha = -uq_ratio * sinf(theta_e);
    float ubeta  =  uq_ratio * cosf(theta_e);

    /* 反 Clarke → 三相电压（Vdc 比例）*/
    float va = ualpha;
    float vb = -0.5f * ualpha + SQRT3_2 * ubeta;
    float vc = -0.5f * ualpha - SQRT3_2 * ubeta;

    /* 零序注入（min-max）：抬升调制比，等效 SVPWM */
    float vmax = fmaxf(va, fmaxf(vb, vc));
    float vmin = fminf(va, fminf(vb, vc));
    float vcom = 0.5f * (vmax + vmin);

    /* 归一化到占空比：中点 0.5 */
    *da = (va - vcom) + 0.5f;
    *db = (vb - vcom) + 0.5f;
    *dc = (vc - vcom) + 0.5f;
}

/* 施加一个电角度矢量（theta, uq）→ 三相占空比原子刷新（GlobalLock）。
 * 控制线程与标定都经此驱动，确保 PWM 三通道同步生效。*/
static void foc_apply(float theta, float uq)
{
    float da, db, dc;
    foc_modulate(theta, uq, &da, &db, &dc);
    HAL_PWM_GlobalLock(&s_pwm, PWM_CH_MASK);
    foc_pwm_set_duty(PH_A_CH, da);
    foc_pwm_set_duty(PH_B_CH, db);
    foc_pwm_set_duty(PH_C_CH, dc);
    HAL_PWM_GlobalUnlock(&s_pwm, PWM_CH_MASK);
}

/* 机械角(rad) → 电角：normalize(enc_dir·pp·(mech − offset))。*/
static float elec_from_mech(float mech)
{
    float e = (float)g_foc.enc_dir * (float)FOC_POLE_PAIRS
              * (mech - g_foc.enc_offset_rad);
    e = fmodf(e, TWO_PI);
    if (e < 0.0f)
        e += TWO_PI;
    return e;
}

/* 每 tick 读一次编码器，更新：多圈位置 pos_meas、机械角速度 omega_meas（差分+EMA）、
 * 电角 theta_e。读失败则保持上次值。*/
static void foc_pos_update(void)
{
    rt_uint16_t raw;
    float mech, d, pos, w_raw;

    if (as5600_read_raw(&raw) != RT_EOK)
        return;

    mech = (float)raw / (float)AS5600_RES * TWO_PI;

    /* 多圈翻圈检测：相邻机械角跳变 > π 判为越过 0/2π 边界 */
    d = mech - s_pos_prev_mech;
    if (d < -PI)      s_turns++;   /* 2π→0：正向翻一圈 */
    else if (d > PI)  s_turns--;   /* 0→2π：反向翻一圈 */
    s_pos_prev_mech = mech;

    pos = (float)s_turns * TWO_PI + mech;
    w_raw = (pos - g_foc.pos_meas) / CTRL_DT;
    g_foc.omega_meas += g_foc.ema_alpha * (w_raw - g_foc.omega_meas);
    g_foc.pos_meas = pos;

    g_foc.theta_e = elec_from_mech(mech);
}

/* 速度环 PI（带积分器钳位抗饱和）：目标转速 → Uq，clamp 到 ±FOC_UQ_MAX。*/
static float foc_speed_pi(float w_target)
{
    float err = w_target - g_foc.omega_meas;
    float u;

    s_spd_integ += g_foc.spd_ki * err * CTRL_DT;
    u = g_foc.spd_kp * err + s_spd_integ;

    if (u > FOC_UQ_MAX)
    {
        u = FOC_UQ_MAX;
        s_spd_integ = FOC_UQ_MAX - g_foc.spd_kp * err;   /* 钳位积分使 u=UQ_MAX */
    }
    else if (u < -FOC_UQ_MAX)
    {
        u = -FOC_UQ_MAX;
        s_spd_integ = -FOC_UQ_MAX - g_foc.spd_kp * err;
    }
    return u;
}

/* 位置环 PID（默认纯 P；D 用 −ω_meas 避免微分踢与噪声）：目标角 → 速度设定，
 * clamp 到 ±vlim（含积分钳位抗饱和）。*/
static float foc_position_pid(float p_target)
{
    float err = p_target - g_foc.pos_meas;
    float w;

    s_pos_integ += g_foc.pos_ki * err * CTRL_DT;
    w = g_foc.pos_kp * err + s_pos_integ + g_foc.pos_kd * (-g_foc.omega_meas);

    if (w > g_foc.vlim)
    {
        w = g_foc.vlim;
        s_pos_integ = g_foc.vlim - g_foc.pos_kp * err - g_foc.pos_kd * (-g_foc.omega_meas);
    }
    else if (w < -g_foc.vlim)
    {
        w = -g_foc.vlim;
        s_pos_integ = -g_foc.vlim - g_foc.pos_kp * err - g_foc.pos_kd * (-g_foc.omega_meas);
    }
    return w;
}

/* 使能瞬间的 bumpless 初始化：清积分、位置目标=当前位置、速度测量归零。*/
static void foc_on_enable(void)
{
    rt_uint16_t raw;
    s_spd_integ = 0.0f;
    s_pos_integ = 0.0f;
    g_foc.omega_meas = 0.0f;
    if (as5600_read_raw(&raw) == RT_EOK)
        s_pos_prev_mech = (float)raw / (float)AS5600_RES * TWO_PI;
    g_foc.target_pos = g_foc.pos_meas;   /* 位置目标=当前，避免跳变冲击 */
}

/* 标定进行中标志：置位时控制线程让出对 PWM/EN 的驱动，避免与标定抢。*/
static volatile int s_calibrating;

/* ---- 控制线程：级联闭环（位置→速度→电压 FOC），全在 1kHz tick ---- */

static void foc_ctrl_entry(void *param)
{
    /* 节拍走 rt_thread_mdelay（阻塞让出调度器），而非 HAL_DelayUs 忙等——忙等会让本
     * 高优先级线程独占 CPU、饿死 finsh/msh。RT tick=1000Hz，period_ms 须 ≥1。*/
    const rt_uint32_t period_ms = (1000u / FOC_CTRL_FREQ_HZ) ? (1000u / FOC_CTRL_FREQ_HZ) : 1u;
    int last_en = -1;

    (void)param;
    while (1)
    {
        int en;

        if (s_calibrating)          /* 标定期间交出驱动权，避免与 foc_calib 抢 PWM/EN */
        {
            last_en = -1;
            rt_thread_mdelay(period_ms);
            continue;
        }

        en = g_foc.enabled;
        if (en != last_en)
        {
            if (en)
                foc_on_enable();    /* 0→1：bumpless 初始化 */
            foc_en_set(en);
            last_en = en;
        }

        if (en && g_foc.calibrated)
        {
            float uq;

            foc_pos_update();       /* 更新 pos_meas / omega_meas / theta_e */

            switch (g_foc.mode)
            {
            case FOC_MODE_SPEED:
                uq = foc_speed_pi(g_foc.target_speed);
                break;
            case FOC_MODE_POSITION:
                uq = foc_speed_pi(foc_position_pid(g_foc.target_pos));
                break;
            case FOC_MODE_VOLTAGE:
            default:
                uq = (float)g_foc.dir * g_foc.uq_ratio;   /* 手动转矩 */
                break;
            }

            foc_apply(g_foc.theta_e, uq);
        }

        rt_thread_mdelay(period_ms);
    }
}

/* 读当前机械角（rad）到 *out。成功返回 0，失败返回负值。*/
static int foc_read_mech_angle(float *out)
{
    rt_uint16_t raw;
    if (as5600_read_raw(&raw) != RT_EOK)
        return -1;
    *out = (float)raw / (float)AS5600_RES * TWO_PI;
    return 0;
}

/* 极对数已知(=7)下标定电角零点偏置与方向：
 *   1) 把磁场落在电角 0（θ=−π/2），转子 d 轴对齐到电角 0，读机械角 m0 → offset。
 *   2) 磁场移到电角 +delta，读机械角 m1；sign(m1−m0) 定 dir。
 * uq 用 foc uq 设的当前值（须非零）。标定后进 SENSORED、去使能。*/
static int foc_calib(void)
{
    const float delta = 1.0f;            /* 电角步进 ~1rad，小于半电周期避免绕环 */
    float uq = g_foc.uq_ratio;
    rt_uint8_t status = 0;
    float m0 = 0.0f, m1 = 0.0f;
    int i;

    if (uq <= 0.0f)
    {
        rt_kprintf("foc calib: 先 foc uq <值> 给非零电压幅值\n");
        return -1;
    }
    if (as5600_read_status(&status) != RT_EOK)
    {
        rt_kprintf("foc calib: 读 AS5600 失败（检查 i2c2 接线）\n");
        return -1;
    }
    /* MD(bit5)=磁铁检测；ML(bit4)过弱 MH(bit3)过强 */
    if (!(status & 0x20))
        rt_kprintf("foc calib: 警告 AS5600 未检测到磁铁 (status=0x%02x)\n", status);

    s_calibrating = 1;
    foc_en_set(1);

    /* 对齐：让磁场落在电角 0，把转子 d 轴拉到电角 0。注意 foc_apply(θ) 施加的磁场
     * 在电角 θ+90°（反 Park 的 Vq 沿 q 轴），故要磁场在 0 须传 θ=−π/2。settle ~600ms。
     * 此处记录的 m0 才是"转子 d 轴在电角 0 时的机械角"= 正确的 offset。*/
    for (i = 0; i < 600; i++) { foc_apply(-HALF_PI, uq); rt_thread_mdelay(1); }
    if (foc_read_mech_angle(&m0) < 0) goto fail;

    /* 正向步进：磁场移到电角 +delta（θ=−π/2+delta），转子 d 轴跟到 +delta。settle ~400ms。*/
    for (i = 0; i < 400; i++) { foc_apply(-HALF_PI + delta, uq); rt_thread_mdelay(1); }
    if (foc_read_mech_angle(&m1) < 0) goto fail;

    /* 卸力、去使能 */
    foc_apply(0.0f, 0.0f);
    foc_en_set(0);
    s_calibrating = 0;

    g_foc.enc_offset_rad = m0;
    g_foc.enc_dir        = (m1 >= m0) ? 1 : -1;   /* 编码器标定方向（内部），非用户旋转方向 */
    g_foc.calibrated     = 1;
    g_foc.enabled        = 0;
    g_foc.theta_e        = 0.0f;

    rt_kprintf("foc calib: OK  pp=%d offset=%d(mrad) enc_dir=%d (m0=%d m1=%d mrad)\n",
               FOC_POLE_PAIRS, (int)(m0 * 1000), g_foc.enc_dir,
               (int)(m0 * 1000), (int)(m1 * 1000));
    return 0;

fail:
    foc_apply(0.0f, 0.0f);
    foc_en_set(0);
    s_calibrating = 0;
    rt_kprintf("foc calib: 读编码器失败\n");
    return -1;
}

int foc_start(void)
{
    rt_thread_t tid;

    foc_iomux_init();
    foc_gpio_init();
    foc_pwm_init();
    if (as5600_init() != RT_EOK)
        rt_kprintf("foc: AS5600 init failed（i2c2）——sensored 模式不可用\n");

    tid = rt_thread_create("foc_ctrl", foc_ctrl_entry, RT_NULL,
                           2048, 5, 10);   /* 高优先级，dedicated 从核 */
    if (tid == RT_NULL)
    {
        rt_kprintf("foc: create ctrl thread failed\n");
        return -RT_ERROR;
    }
    rt_thread_startup(tid);
    rt_kprintf("foc: started (SVPWM, PWM3 %uHz, ctrl %uHz, pp=%d)\n",
               FOC_PWM_FREQ_HZ, FOC_CTRL_FREQ_HZ, FOC_POLE_PAIRS);
    return RT_EOK;
}

/* ---- finsh 命令 ---- */

static const char *foc_mode_name(int m)
{
    switch (m)
    {
    case FOC_MODE_SPEED:    return "speed";
    case FOC_MODE_POSITION: return "position";
    default:                return "voltage";
    }
}

static void foc_usage(void)
{
    rt_kprintf("用法: foc <sub> [arg]（单位：机械 rad / rad·s⁻¹）\n");
    rt_kprintf("  en / dis                使能 / 去使能（dis 复位积分+目标）\n");
    rt_kprintf("  mode voltage|speed|position   运行模式\n");
    rt_kprintf("  uq <0..0.55>            voltage 模式电压幅值\n");
    rt_kprintf("  dir <1|-1>              voltage 模式转矩方向\n");
    rt_kprintf("  spd <rad/s>             speed 模式目标转速\n");
    rt_kprintf("  pos <rad>               position 模式目标角（多圈）\n");
    rt_kprintf("  gain spd.kp|spd.ki|pos.kp|pos.ki|pos.kd|vlim|slew <值>\n");
    rt_kprintf("  calib                   标定编码器（先 foc uq 给非零）\n");
    rt_kprintf("  enc / i2cdiag / status  调试\n");
}

static void foc_status(void)
{
    rt_kprintf("foc: mode=%s en=%d calib=%d fault=%d enc_dir=%d off=%d(mrad)\n",
               foc_mode_name(g_foc.mode), g_foc.enabled, g_foc.calibrated,
               foc_fault_active(), g_foc.enc_dir, (int)(g_foc.enc_offset_rad * 1000));
    rt_kprintf("     pos=%d tgt_pos=%d (mrad)  omega=%d tgt_spd=%d (mrad/s)\n",
               (int)(g_foc.pos_meas * 1000), (int)(g_foc.target_pos * 1000),
               (int)(g_foc.omega_meas * 1000), (int)(g_foc.target_speed * 1000));
    rt_kprintf("     gains spd(kp=%d.%03d ki=%d.%03d) pos(kp=%d.%03d ki=%d.%03d kd=%d.%03d) "
               "vlim=%d slew=%d.%03d\n",
               (int)g_foc.spd_kp, (int)(g_foc.spd_kp * 1000) % 1000,
               (int)g_foc.spd_ki, (int)(g_foc.spd_ki * 1000) % 1000,
               (int)g_foc.pos_kp, (int)(g_foc.pos_kp * 1000) % 1000,
               (int)g_foc.pos_ki, (int)(g_foc.pos_ki * 1000) % 1000,
               (int)g_foc.pos_kd, (int)(g_foc.pos_kd * 1000) % 1000,
               (int)g_foc.vlim, (int)g_foc.ema_alpha, (int)(g_foc.ema_alpha * 1000) % 1000);
}

/* 读一次编码器并打印（调试）：原始计数、机械角(度)、磁铁状态。*/
static void foc_enc_dump(void)
{
    rt_uint16_t raw = 0;
    rt_uint8_t status = 0;
    if (as5600_read_raw(&raw) != RT_EOK)
    {
        rt_kprintf("foc enc: 读失败 hal_err=%d %s clk=%u Hz\n",
                   as5600_last_hal_err,
                   as5600_last_timeout ? "(轮询超时→总线无响应:iomux/接线/上拉/供电)"
                                       : "(hal_err=-19 NODEV→NACK:地址/器件；其它→协议)",
                   as5600_clk_rate);
        return;
    }
    as5600_read_status(&status);
    rt_kprintf("foc enc: raw=%d/4096  mech=%d(deg)  status=0x%02x [%s%s%s]\n",
               raw, raw * 360 / (int)AS5600_RES, status,
               (status & 0x20) ? "MD " : "",
               (status & 0x10) ? "ML(弱) " : "",
               (status & 0x08) ? "MH(强)" : "");
}

/* I2C 底层诊断：读回 CRU 门控真实状态 + 尝试传输后 dump CON/IPD（看 START 是否执行）。*/
static void foc_i2cdiag(void)
{
    rt_uint32_t g30, g32, con, ipd;
    rt_uint16_t raw = 0;

    /* CRU 门控真实状态：bit=0 使能、bit=1 门控关。
     *   GATE_CON30 bit2=PCLK_I2C2 bit3=CLK_I2C2；GATE_CON32 bit10=CLK_I2C(共享源)*/
    g30 = READ_REG(CRU->CRU_CLKGATE_CON[30]);
    g32 = READ_REG(CRU->CRU_CLKGATE_CON[32]);
    rt_kprintf("i2cdiag: [前] GATE30=0x%08x PCLK_I2C2=%s CLK_I2C2=%s | CLK_I2C(共享)=%s\n",
               g30, (g30 & (1 << 2)) ? "关" : "开", (g30 & (1 << 3)) ? "关" : "开",
               (g32 & (1 << 10)) ? "关" : "开");

    /* 立即写-读回测试：判定 cpu3 能否写 CRU 门控 vs Linux 事后重新门控 */
    CRU->CRU_CLKGATE_CON[30] = (0x3U << (2 + 16));   /* clr bit2,3 */
    CRU->CRU_CLKGATE_CON[32] = (0x1U << (10 + 16));  /* clr bit10 */
    g30 = READ_REG(CRU->CRU_CLKGATE_CON[30]);
    g32 = READ_REG(CRU->CRU_CLKGATE_CON[32]);
    rt_kprintf("i2cdiag: [写后立即读] GATE30=0x%08x CLK_I2C2=%s | CLK_I2C(共享)=%s  %s\n",
               g30, (g30 & (1 << 3)) ? "关" : "开", (g32 & (1 << 10)) ? "关" : "开",
               (g30 & (1 << 3)) ? "(写不进→cpu3 无法改 CRU)" : "(写进了→若稍后又关=Linux 重门控)");

    /* 尝试一次读，再 dump I2C2 CON/IPD：START 若执行过，IPD 应有位、CON 的 START 应自清 */
    as5600_read_raw(&raw);
    con = READ_REG(I2C2->CON);
    ipd = READ_REG(I2C2->IPD);
    rt_kprintf("i2cdiag: after xfer CON=0x%08x IPD=0x%08x CLKDIV=0x%08x hal_err=%d %s\n",
               con, ipd, READ_REG(I2C2->CLKDIV), as5600_last_hal_err,
               (ipd == 0) ? "(IPD=0→START 没执行:功能时钟没跑)" : "(IPD 有位→总线在动)");
    rt_kprintf("i2cdiag: IOMUX_H=0x%08x clk=%u Hz\n",
               READ_REG(GRF->GPIO0B_IOMUX_H), as5600_clk_rate);
}

/* foc gain <name> <值>：运行时调增益。返回 0 成功、-1 名字未知。*/
static int foc_set_gain(const char *name, float v)
{
    if (rt_strcmp(name, "spd.kp") == 0)      g_foc.spd_kp = v;
    else if (rt_strcmp(name, "spd.ki") == 0) g_foc.spd_ki = v;
    else if (rt_strcmp(name, "pos.kp") == 0) g_foc.pos_kp = v;
    else if (rt_strcmp(name, "pos.ki") == 0) g_foc.pos_ki = v;
    else if (rt_strcmp(name, "pos.kd") == 0) g_foc.pos_kd = v;
    else if (rt_strcmp(name, "vlim") == 0)   g_foc.vlim = v;
    else if (rt_strcmp(name, "slew") == 0)   g_foc.ema_alpha = v;
    else return -1;
    return 0;
}

static void foc(int argc, char **argv)
{
    if (argc < 2)
    {
        foc_usage();
        foc_status();
        return;
    }
    if (rt_strcmp(argv[1], "en") == 0)
    {
        g_foc.enabled = 1;
    }
    else if (rt_strcmp(argv[1], "dis") == 0)
    {
        g_foc.enabled = 0;
        s_spd_integ = 0.0f;             /* 复位积分，目标=当前位置（bumpless）*/
        s_pos_integ = 0.0f;
        g_foc.target_pos = g_foc.pos_meas;
    }
    else if (rt_strcmp(argv[1], "mode") == 0 && argc >= 3)
    {
        if (rt_strcmp(argv[2], "speed") == 0)         g_foc.mode = FOC_MODE_SPEED;
        else if (rt_strcmp(argv[2], "position") == 0) g_foc.mode = FOC_MODE_POSITION;
        else                                          g_foc.mode = FOC_MODE_VOLTAGE;
        if (!g_foc.calibrated)
            rt_kprintf("foc: 未标定，运行前先 foc calib\n");
    }
    else if (rt_strcmp(argv[1], "uq") == 0 && argc >= 3)
    {
        float v = (float)atof(argv[2]);
        if (v < 0.0f) v = 0.0f;
        if (v > FOC_UQ_MAX) v = FOC_UQ_MAX;
        g_foc.uq_ratio = v;
    }
    else if (rt_strcmp(argv[1], "dir") == 0 && argc >= 3)
    {
        g_foc.dir = (atoi(argv[2]) < 0) ? -1 : 1;
    }
    else if (rt_strcmp(argv[1], "spd") == 0 && argc >= 3)
    {
        g_foc.target_speed = (float)atof(argv[2]);
    }
    else if (rt_strcmp(argv[1], "pos") == 0 && argc >= 3)
    {
        g_foc.target_pos = (float)atof(argv[2]);
    }
    else if (rt_strcmp(argv[1], "gain") == 0 && argc >= 4)
    {
        if (foc_set_gain(argv[2], (float)atof(argv[3])) < 0)
        {
            rt_kprintf("foc gain: 未知 %s（spd.kp/ki pos.kp/ki/kd vlim slew）\n", argv[2]);
            return;
        }
    }
    else if (rt_strcmp(argv[1], "calib") == 0)
    {
        foc_calib();
        return;
    }
    else if (rt_strcmp(argv[1], "enc") == 0)
    {
        foc_enc_dump();
        return;
    }
    else if (rt_strcmp(argv[1], "i2cdiag") == 0)
    {
        foc_i2cdiag();
        return;
    }
    else if (rt_strcmp(argv[1], "status") == 0)
    {
        /* fallthrough to status print */
    }
    else
    {
        foc_usage();
        return;
    }
    foc_status();
}

#ifdef RT_USING_FINSH
#include <finsh.h>
MSH_CMD_EXPORT(foc, foc motor: en/dis/mode/uq/dir/spd/pos/gain/calib/enc/status);
#endif
