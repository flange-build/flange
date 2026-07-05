/*
 * as5600.c —— AS5600 磁编码器驱动（i2c2，HAL_I2C 直驱轮询）。
 *
 * 读时序照搬 drv_i2c 的 rockchip_i2c_configure 寄存器读配方（REG_CON_MOD_REGISTER_TX：
 * 控制器自动发「设备地址+寄存器地址」再重启读），但用 I2C_POLL + 轮询 HAL_I2C_IRQHandler
 * 推进状态机，不依赖中断。
 */
#include "as5600.h"
#include <rtdevice.h>          /* RT_I2C_RD */
#include "hal_base.h"

static struct I2C_HANDLE s_i2c;
static int s_ready;

/* 最近一次传输诊断（供 foc enc 打印，区分 超时/NACK/错误码）*/
int as5600_last_hal_err;   /* 最后 HAL_Status */
int as5600_last_timeout;   /* 1 = 轮询超时（总线无响应）*/
uint32_t as5600_clk_rate;  /* HAL_I2C_Init 用的输入时钟 */

/* 开 i2c2 时钟门控（用 SDK HAL_CRU_ClkEnable，gate id 见 rk3568.h）：
 *   PCLK_I2C2_GATE / CLK_I2C2_GATE = i2c2 本体；CLK_I2C_GATE = 所有 i2c 共享源时钟。
 *
 * 【为何每次传输前都要调】CRU 是 Linux 主核与 AMP 从核共享的。foc product 的 Linux
 * dtb 里 i2c2 是 disabled，Linux 启动后期的 clk_disable_unused() 会把 i2c2 时钟当
 * “未使用”门控关掉，盖过从核 init 时的使能 → 运行时 SCL 不翻、传输卡在 START 超时。
 * clk_disable_unused 启动后期跑一次、之后不再碰 i2c2，故在传输前（远晚于启动）重新
 * 开门控即稳定生效。门控只停时钟不清寄存器，故 CLKDIV 等配置在 gate/ungate 间保留。*/
static void as5600_ungate_clk(void)
{
    HAL_CRU_ClkEnable(PCLK_I2C2_GATE);
    HAL_CRU_ClkEnable(CLK_I2C2_GATE);
    HAL_CRU_ClkEnable(CLK_I2C_GATE);
}

int as5600_init(void)
{
    uint32_t i2c2_srst[2] = { SRST_P_I2C2, SRST_I2C2 };
    uint32_t rate;

    as5600_ungate_clk();

    /* 解除 I2C2 复位：Linux 未初始化 i2c2（dtb disabled）、控制器留在复位态，复位下
     * 寄存器写入被忽略（HAL_I2C_Init 写的 CLKDIV 恒读回 0）。脉冲复位到干净态（P+IP 同步）。*/
    HAL_CRU_ClkResetSyncAssert(2, i2c2_srst);
    HAL_DelayUs(10);
    HAL_CRU_ClkResetSyncDeassert(2, i2c2_srst);

    rate = HAL_CRU_ClkGetFreq(CLK_I2C);
    as5600_clk_rate = rate;
    if (rate == 0)
    {
        rt_kprintf("as5600: get i2c clk freq failed\n");
        return -RT_ERROR;
    }
    HAL_I2C_Init(&s_i2c, I2C2, rate, I2C_400K);
    s_ready = 1;
    rt_kprintf("as5600: i2c2 init ok, clk=%u Hz\n", rate);
    return RT_EOK;
}

/* 单次寄存器读：写 reg 指针（REGISTER_TX 模式内部完成）后读 len 字节到 buf。
 * 轮询推进，带迭代上限超时（避免编码器缺席时卡死）。*/
static rt_err_t as5600_read_reg(rt_uint8_t reg, rt_uint8_t *buf, rt_uint16_t len)
{
    uint32_t dev  = (AS5600_I2C_ADDR & 0x7f) << 1;
    uint32_t radd = reg | HAL_I2C_REG_MRXADDR_VALID(0);
    HAL_Status err;
    int guard;

    if (!s_ready)
        return -RT_ERROR;

    /* 每次传输前重开门控：抵消 Linux clk_disable_unused 对 i2c2 时钟的门控（见上）*/
    as5600_ungate_clk();

    dev |= HAL_I2C_REG_MRXADDR_VALID(0);
    HAL_I2C_ConfigureMode(&s_i2c, REG_CON_MOD_REGISTER_TX, dev, radd);
    HAL_I2C_SetupMsg(&s_i2c, AS5600_I2C_ADDR, buf, len, RT_I2C_RD);
    HAL_I2C_Transfer(&s_i2c, I2C_POLL, true);

    /* 轮询状态机：HAL_I2C_IRQHandler 返回 HAL_BUSY 表示未完成。上限 ~10ms。*/
    err = HAL_BUSY;
    for (guard = 0; guard < 1000; guard++)
    {
        err = HAL_I2C_IRQHandler(&s_i2c);
        if (err != HAL_BUSY)
            break;
        HAL_DelayUs(10);
    }
    HAL_I2C_Close(&s_i2c);

    as5600_last_hal_err = (int)err;
    as5600_last_timeout = (guard >= 1000) ? 1 : 0;

    if (err == HAL_BUSY)
    {
        HAL_I2C_ForceStop(&s_i2c);
        return -RT_ETIMEOUT;
    }
    return (err == HAL_OK) ? RT_EOK : -RT_EIO;
}

rt_err_t as5600_read_raw(rt_uint16_t *raw)
{
    rt_uint8_t b[2];
    rt_err_t ret = as5600_read_reg(AS5600_REG_RAWANG, b, 2);
    if (ret != RT_EOK)
        return ret;
    *raw = (rt_uint16_t)(((b[0] << 8) | b[1]) & 0x0FFF);
    return RT_EOK;
}

rt_err_t as5600_read_status(rt_uint8_t *status)
{
    return as5600_read_reg(AS5600_REG_STATUS, status, 1);
}
