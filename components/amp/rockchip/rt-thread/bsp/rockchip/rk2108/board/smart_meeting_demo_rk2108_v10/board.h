/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
 */

#ifndef __BOARD_H__
#define __BOARD_H__

#include "board_base.h"

#define PA_GPIO_BANK     GPIO_BANK0
#define PA_GPIO          GPIO0
#define PA_PIN           GPIO_PIN_B1
#define PA_PIN_FUNC_GPIO PIN_CONFIG_MUX_FUNC0
#define PA_MUTE          GPIO_LOW
#define PA_UNMUTE        GPIO_HIGH

#define PA_PWR_GPIO_BANK        GPIO_BANK1
#define PA_PWR_GPIO             GPIO1
#define PA_PWR_PIN              GPIO_PIN_A7
#define PA_PWR_PIN_FUNC_GPIO    PIN_CONFIG_MUX_FUNC0
#define PA_PWR_ON               GPIO_HIGH
#define PA_PWR_OFF              GPIO_LOW

#undef USB_VBUS_PIN

#undef PMIC_INT_PIN
#define PMIC_INT_PIN            BANK_PIN(GPIO_BANK0, 18)
#define LED_BAT_STATUS_PIN      BANK_PIN(GPIO_BANK0, 11)

#ifdef RT_USING_TOUCH
#undef TOUCH_IRQ_PIN
#undef TOUCH_RST_PIN
#undef TOUCH_I2C_DEV
#undef TOUCH_DEV_NAME
#define TOUCH_IRQ_PIN           BANK_PIN(GPIO_BANK1, 15)
#define TOUCH_RST_PIN           BANK_PIN(GPIO_BANK1, 14)
#define TOUCH_I2C_DEV           "i2c2"
#define TOUCH_DEV_NAME          "gt308l"
#endif

#endif
