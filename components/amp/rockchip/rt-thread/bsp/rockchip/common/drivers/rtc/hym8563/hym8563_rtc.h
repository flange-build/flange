/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#ifndef __HYM8563_H_
#define __HYM8563_H_
#include <rtthread.h>

/* GT1x touch HW pin define, these pins must defined in board config */
#ifndef RTC_IRQ_PIN
#define RTC_IRQ_PIN   0
#endif

#ifndef RTC_I2C_DEV
#define RTC_I2C_DEV     0
#endif

#define HYM8563_ADDR_LENGTH 1
#define HYM8563_ADDRESS     (0x51)

#define HYM8563_CTL1        0x00
#define HYM8563_CTL1_TEST   BIT(7)
#define HYM8563_CTL1_STOP   BIT(5)
#define HYM8563_CTL1_TESTC  BIT(3)

#define HYM8563_CTL2        0x01
#define HYM8563_CTL2_TI_TP  BIT(4)
#define HYM8563_CTL2_AF     BIT(3)
#define HYM8563_CTL2_TF     BIT(2)
#define HYM8563_CTL2_AIE    BIT(1)
#define HYM8563_CTL2_TIE    BIT(0)

#define HYM8563_SEC     0x02
#define HYM8563_SEC_VL      BIT(7)
#define HYM8563_SEC_MASK    0x7f

#define HYM8563_MIN     0x03
#define HYM8563_MIN_MASK    0x7f

#define HYM8563_HOUR        0x04
#define HYM8563_HOUR_MASK   0x3f

#define HYM8563_DAY     0x05
#define HYM8563_DAY_MASK    0x3f

#define HYM8563_WEEKDAY     0x06
#define HYM8563_WEEKDAY_MASK    0x07

#define HYM8563_MONTH       0x07
#define HYM8563_MONTH_CENTURY   BIT(7)
#define HYM8563_MONTH_MASK  0x1f

#define HYM8563_YEAR        0x08

#define HYM8563_ALM_MIN     0x09
#define HYM8563_ALM_HOUR    0x0a
#define HYM8563_ALM_DAY     0x0b
#define HYM8563_ALM_WEEK    0x0c

/* Each alarm check can be disabled by setting this bit in the register */
#define HYM8563_ALM_BIT_DISABLE BIT(7)

#define HYM8563_CLKOUT      0x0d
#define HYM8563_CLKOUT_ENABLE   BIT(7)
#define HYM8563_CLKOUT_32768    0
#define HYM8563_CLKOUT_1024 1
#define HYM8563_CLKOUT_32   2
#define HYM8563_CLKOUT_1    3
#define HYM8563_CLKOUT_MASK 3

#define HYM8563_TMR_CTL     0x0e
#define HYM8563_TMR_CTL_ENABLE  BIT(7)
#define HYM8563_TMR_CTL_4096    0
#define HYM8563_TMR_CTL_64  1
#define HYM8563_TMR_CTL_1   2
#define HYM8563_TMR_CTL_1_60    3
#define HYM8563_TMR_CTL_MASK    3

#define HYM8563_TMR_CNT     0x0f
#define HYM8563_TMR_MAXCNT  0xff
#define HYM8563_TMR_CFG     (HYM8563_TMR_CTL_ENABLE | HYM8563_TMR_CTL_1)

#endif
