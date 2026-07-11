/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2021-04-12     Steven Liu   first implementation
 */

#ifndef __BOARD_H__
#define __BOARD_H__

#include "board_base.h"
#include "hal_base.h"

#define USB_HOST_VBUS_PIN       BANK_PIN(GPIO_BANK0, 6)

#define TOUCH_IRQ_PIN           BANK_PIN(GPIO_BANK0, 13)    //GPIO0_B5
#define TOUCH_RST_PIN           BANK_PIN(GPIO_BANK0, 14)    //GPIO0_B6
#define TOUCH_IRQ_PIN_MODE      PIN_MODE_INPUT_PULLUP
#define TOUCH_I2C_DEV           "i2c1"
#define TOUCH_DEV_NAME          "gt1x"

#endif
