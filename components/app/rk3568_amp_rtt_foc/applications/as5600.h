/*
 * as5600.h —— AS5600 磁编码器驱动（i2c2，HAL 直驱轮询）。
 *
 * AS5600：12-bit 单圈绝对磁编码器，I2C 从地址 0x36。用 RAW ANGLE(0x0C/0x0D，未经
 * AS5600 内部零点/量程配置）作 FOC 转子位置，避免依赖芯片配置。
 *
 * 走 HAL_I2C 直驱 + 轮询（I2C_POLL），不用 drv_i2c 的中断路径——避开 AMP 从核的
 * GIC 中断路由问题（与本 app 的 HAL 直驱 PWM 一致）。i2c2 IOMUX 由 foc_iomux_init
 * 配（gpio0_b5/b6 mux1）。
 */
#ifndef __AS5600_H__
#define __AS5600_H__

#include <rtthread.h>

#define AS5600_I2C_ADDR   0x36u
#define AS5600_REG_STATUS 0x0Bu   /* bit5=MH 过强 bit4=ML 过弱 bit3=MD 检测到磁铁 */
#define AS5600_REG_RAWANG 0x0Cu   /* RAW ANGLE 高字节；0x0D 低字节，12-bit */
#define AS5600_RES        4096u   /* 12-bit 分辨率 */

/* 初始化 i2c2（时钟门控 + HAL_I2C_Init）。IOMUX 由 foc_iomux_init 先配好。*/
int as5600_init(void);

/* 读 12-bit 原始角（0..4095）。成功返回 RT_EOK，失败返回负值。*/
rt_err_t as5600_read_raw(rt_uint16_t *raw);

/* 读状态寄存器（磁铁检测）。成功返回 RT_EOK。*/
rt_err_t as5600_read_status(rt_uint8_t *status);

/* 诊断（供 foc enc 打印）：最近 HAL_Status、是否轮询超时、init 用的时钟。
 * HAL_Status: 0=OK -16=BUSY -19=NODEV(NACK) -110=TIMEOUT。*/
extern int as5600_last_hal_err;
extern int as5600_last_timeout;
extern rt_uint32_t as5600_clk_rate;

#endif /* __AS5600_H__ */
