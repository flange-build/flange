/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    gt308l.h
  * @version V0.1
  * @brief   gt308l driver
  *
  * Change Logs:
  * Date           Author          Notes
  * 2023-04-10     Jair Wu         the first version
  *
  ******************************************************************************
  */

#ifndef __GT308L_H__
#define __GT308L_H__

#include <rtthread.h>
#include "drv_touchkey.h"

#define TOUCH_SLAVE_ADDRESS     0x5C

/* GT308L touch HW pin define, these pins must defined in board config */
#ifndef TOUCH_IRQ_PIN
#define TOUCH_IRQ_PIN   0
#endif

#ifndef TOUCH_RST_PIN
#define TOUCH_RST_PIN   0
#endif

#ifndef TOUCH_I2C_DEV
#define TOUCH_I2C_DEV   0
#endif

/* register address  */
#define GT308L_CHIPID_REG02         0x02
#define GT308L_TOUCH_CH_EN_REG03    0x03
#define GT308L_MULTIMODE_REG04      0x04
#define GT308L_PWM_CH_EN_REG05      0x05
#define GT308L_CAL_TIME_REG07       0x07
#define GT308L_TOUCH_PERIOD_REG07   0x07
#define GT308L_TOUCH_OUTPUT_REG2A   0x2A
#define GT308L_OUT_POL_REG3A        0x3A
#define GT308L_INT_MODE_REG3A       0x3A
#define GT308L_SOFT_RST_REG3B       0x3B
#define GT308L_PWM_EN_REG3B         0x3B
#define GT308L_SEN_IDLE_TIME_REG3B  0x3B
#define GT308L_SENSITIVITY1_REG40   0x40
#define GT308L_SENSITIVITY2_REG41   0x41
#define GT308L_SENSITIVITY3_REG42   0x42
#define GT308L_SENSITIVITY4_REG43   0x43
#define GT308L_SENSITIVITY5_REG44   0x44
#define GT308L_SENSITIVITY6_REG45   0x45
#define GT308L_SENSITIVITY7_REG46   0x46
#define GT308L_SENSITIVITY8_REG47   0x47
#define GT308L_PWM_DATA1_REG48      0x48
#define GT308L_PWM_DATA2_REG48      0x48
#define GT308L_PWM_DATA3_REG49      0x49
#define GT308L_PWM_DATA4_REG49      0x49
#define GT308L_PWM_DATA5_REG4A      0x4A
#define GT308L_PWM_DATA6_REG4A      0x4A
#define GT308L_PWM_DATA7_REG4B      0x4B
#define GT308L_PWM_DATA8_REG4B      0x4B
#define GT308L_MON_RST_REG4F        0x4F

/* register shift/mask */
#define GT308L_CHIPID_SW_SHIFT      (1U)
#define GT308L_CHIPID_SW_MASK       (0x01U << GT308L_CHIPID_SW_SHIFT)
#define GT308L_CHIPID_HW_SHIFT      (2U)
#define GT308L_CHIPID_HW_MASK       (0x03U << GT308L_CHIPID_HW_SHIFT)
#define GT308L_TOUCH_CH_EN_SHIFT    (0U)
#define GT308L_TOUCH_CH_EN_MASK     (0xFFU << GT308L_TOUCH_CH_EN_SHIFT)
#define GT308L_MULTIMODE_SHIFT      (2U)
#define GT308L_MULTIMODE_MASK       (0x01U << GT308L_MULTIMODE_SHIFT)
#define GT308L_PWM_CH_EN_SHIFT      (0U)
#define GT308L_PWM_CH_EN_MASK       (0xFFU << GT308L_PWM_CH_EN_SHIFT)
#define GT308L_CAL_TIME_SHIFT       (0U)
#define GT308L_CAL_TIME_MASK        (0x0FU << GT308L_CAL_TIME_SHIFT)
#define GT308L_TOUCH_PERIOD_SHIFT   (4U)
#define GT308L_TOUCH_PERIOD_MASK    (0x07U << GT308L_TOUCH_PERIOD_SHIFT)
#define GT308L_TOUCH_OUTPUT_SHIFT   (0U)
#define GT308L_TOUCH_OUTPUT_MASK    (0xFFU << GT308L_TOUCH_OUTPUT_SHIFT)
#define GT308L_OUT_POL_SHIFT        (1U)
#define GT308L_OUT_POL_MASK         (0x01U << GT308L_OUT_POL_SHIFT)
#define GT308L_INT_MODE_SHIFT       (4U)
#define GT308L_INT_MODE_MASK        (0x01U << GT308L_INT_MODE_SHIFT)
#define GT308L_SOFT_RST_SHIFT       (0U)
#define GT308L_SOFT_RST_MASK        (0x01U << GT308L_SOFT_RST_SHIFT)
#define GT308L_PWM_EN_SHIFT         (4U)
#define GT308L_PWM_EN_MASK          (0x01U << GT308L_PWM_EN_SHIFT)
#define GT308L_SEN_IDLE_TIME_SHIFT  (5U)
#define GT308L_SEN_IDLE_TIME_MASK   (0x03U << GT308L_SEN_IDLE_TIME_SHIFT)
#define GT308L_SENSITIVITY1_SHIFT   (0U)
#define GT308L_SENSITIVITY1_MASK    (0x3FU << GT308L_SENSITIVITY1_SHIFT)
#define GT308L_SENSITIVITY2_SHIFT   (0U)
#define GT308L_SENSITIVITY2_MASK    (0x3FU << GT308L_SENSITIVITY2_SHIFT)
#define GT308L_SENSITIVITY3_SHIFT   (0U)
#define GT308L_SENSITIVITY3_MASK    (0x3FU << GT308L_SENSITIVITY3_SHIFT)
#define GT308L_SENSITIVITY4_SHIFT   (0U)
#define GT308L_SENSITIVITY4_MASK    (0x3FU << GT308L_SENSITIVITY4_SHIFT)
#define GT308L_SENSITIVITY5_SHIFT   (0U)
#define GT308L_SENSITIVITY5_MASK    (0x3FU << GT308L_SENSITIVITY5_SHIFT)
#define GT308L_SENSITIVITY6_SHIFT   (0U)
#define GT308L_SENSITIVITY6_MASK    (0x3FU << GT308L_SENSITIVITY6_SHIFT)
#define GT308L_SENSITIVITY7_SHIFT   (0U)
#define GT308L_SENSITIVITY7_MASK    (0x3FU << GT308L_SENSITIVITY7_SHIFT)
#define GT308L_SENSITIVITY8_SHIFT   (0U)
#define GT308L_SENSITIVITY8_MASK    (0x3FU << GT308L_SENSITIVITY8_SHIFT)
#define GT308L_PWM_DATA1_SHIFT      (0U)
#define GT308L_PWM_DATA1_MASK       (0x0FU << GT308L_PWM_DATA1_SHIFT)
#define GT308L_PWM_DATA2_SHIFT      (4U)
#define GT308L_PWM_DATA2_MASK       (0x0FU << GT308L_PWM_DATA2_SHIFT)
#define GT308L_PWM_DATA3_SHIFT      (0U)
#define GT308L_PWM_DATA3_MASK       (0x0FU << GT308L_PWM_DATA3_SHIFT)
#define GT308L_PWM_DATA4_SHIFT      (4U)
#define GT308L_PWM_DATA4_MASK       (0x0FU << GT308L_PWM_DATA4_SHIFT)
#define GT308L_PWM_DATA5_SHIFT      (0U)
#define GT308L_PWM_DATA5_MASK       (0x0FU << GT308L_PWM_DATA5_SHIFT)
#define GT308L_PWM_DATA6_SHIFT      (4U)
#define GT308L_PWM_DATA6_MASK       (0x0FU << GT308L_PWM_DATA6_SHIFT)
#define GT308L_PWM_DATA7_SHIFT      (0U)
#define GT308L_PWM_DATA7_MASK       (0x0FU << GT308L_PWM_DATA7_SHIFT)
#define GT308L_PWM_DATA8_SHIFT      (4U)
#define GT308L_PWM_DATA8_MASK       (0x0FU << GT308L_PWM_DATA8_SHIFT)
#define GT308L_MON_RST_SHIFT        (5U)
#define GT308L_MON_RST_MASK         (0x01U << GT308L_MON_RST_SHIFT)

#ifdef RT_TOUCH_KEY_NUMBER
#define GT308L_MAX_KEY              RT_TOUCH_KEY_NUMBER
#else
#define GT308L_MAX_KEY              8
#endif

#define GT308L_MAX_LED              GT308L_MAX_KEY

struct gt308l_hook
{
    rt_list_t list;
    void (*hook)(rt_uint32_t mask, void *arg, rt_bool_t pressed);
    void *arg;
    rt_uint32_t mask;
};

#endif
