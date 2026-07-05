/*
 * foc.h —— rk3568_amp_rtt_foc 电机驱动公共声明（里程碑 1：开环 SVPWM）。
 *
 * 引脚（与 tspi-rk3566-amp-foc.dtso 从 Linux 摘出的整组一致）：
 *   pwm12 = gpio3_b7 (func2)  三相 A
 *   pwm13 = gpio3_c0 (func2)  三相 B
 *   pwm14 = gpio3_c4 (func1)  三相 C   —— 均属 PWM3 控制器通道 0/1/2
 *   EN    = gpio3_a5 (GPIO out) 栅极驱动使能
 *   FAULT = gpio3_a4 (GPIO in)  栅驱故障脚（只读，低有效）；旋转方向由 FOC 软件做，无硬件方向脚
 *   i2c2  = gpio0_b5/b6(func1) 磁编码器
 *
 * mux 号取自内核权威 rk3568-pinctrl.dtsi：pwm12/13=func2、pwm14=func1、i2c2=func1。
 */
#ifndef __FOC_H__
#define __FOC_H__

#include <rtthread.h>

/* ==== 硬件假设（TODO：对板卡原理图/BOM 核实，见变更 tasks 1.3）====
 * 假设三相栅极驱动为「3 路 PWM 输入 + 全局 EN」型（如 DRV8313/DRV8323 3-PWM 模式）：
 * 每相单路 PWM 进栅驱、由栅驱内部生成互补下管 + 死区；全局 EN 高有效使能三相。
 * 若实测极性相反，翻转下面两个宏即可。*/
#define FOC_EN_ACTIVE_HIGH   1     /* EN 高有效 */
#define FOC_PWM_POLARITY     false /* HAL_PWM_CONFIG.polarity：false=正极性(占空比=高电平占比) */

/* PWM 载波与控制更新率 */
#define FOC_PWM_FREQ_HZ      20000u    /* 三相 PWM 载波频率（硬件产生）*/
#define FOC_PWM_CLK_HZ       24000000u /* PWM3 输入时钟（HAL_CRU_ClkSetFreq 设定）*/
/* 占空比更新率 = RT tick（控制线程走 rt_thread_mdelay 让出调度器，不能忙等：
 * 忙等会饿死 finsh/msh。1kHz 对开环 SVPWM 拖动足够）。须整除 RT_TICK_PER_SECOND。*/
#define FOC_CTRL_FREQ_HZ     1000u

/* 电机极对数（本电机 = 7）：机械角 → 电角 = 机械角 × 极对数。*/
#define FOC_POLE_PAIRS   7

/* Uq 限幅：SVPWM 线性区上限 1/√3≈0.577，留裕度取 0.55。*/
#define FOC_UQ_MAX       0.55f

/* 运行模式（均为有感，须先 calib）：
 *   VOLTAGE  = 手动直给 Uq（转矩，标定/查线序用）
 *   SPEED    = 速度环 PI → Uq
 *   POSITION = 位置环 PID → 速度设定 → 速度环 PI → Uq（级联）*/
enum foc_mode {
    FOC_MODE_VOLTAGE = 0,
    FOC_MODE_SPEED,
    FOC_MODE_POSITION,
};

/* 运行参数（foc 命令读写，控制线程消费）。单写者=命令、单读者=控制线程，
 * 字长量的竞态无害。*/
struct foc_runtime {
    volatile int   enabled;        /* 0/1：EN + 是否输出 */
    volatile int   mode;           /* enum foc_mode */
    volatile int   dir;            /* VOLTAGE 模式转矩矢量符号 +1/−1 */
    volatile float uq_ratio;       /* VOLTAGE 模式电压幅值 [0, FOC_UQ_MAX] */

    /* 标定（里程碑 2）*/
    volatile int   calibrated;     /* 0/1：运行前须先 calib */
    volatile int   enc_dir;        /* 编码器标定方向符号（内部；电角换算用，与用户 dir 无关）*/
    volatile float enc_offset_rad; /* 编码器机械角零点偏置（电角 0 对应的机械角）*/

    /* 反馈（里程碑 3，控制线程每 tick 更新）*/
    volatile float theta_e;        /* 电角度 rad */
    volatile float pos_meas;       /* 多圈机械位置 rad（连续，不回绕）*/
    volatile float omega_meas;     /* 机械角速度 rad/s（差分+EMA）*/

    /* 目标 */
    volatile float target_speed;   /* SPEED 模式目标转速 rad/s */
    volatile float target_pos;     /* POSITION 模式目标角 rad（多圈）*/

    /* 增益（运行时可调，默认 0 → 不产生运动，安全）*/
    volatile float spd_kp, spd_ki; /* 速度环 PI */
    volatile float pos_kp, pos_ki, pos_kd; /* 位置环 PID（默认纯 P）*/
    volatile float vlim;           /* 位置环输出限速 rad/s */
    volatile float ema_alpha;      /* 速度估计 EMA 系数 (0,1] */
};

extern struct foc_runtime g_foc;

/* 启动电机驱动：配 IOMUX、初始化 PWM3/GPIO、拉起控制线程。main() 调用一次。*/
int foc_start(void);

#endif /* __FOC_H__ */
