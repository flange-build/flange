/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_touchkey.h
  * @version V0.1
  * @brief   touchkey driver
  *
  * Change Logs:
  * Date           Author          Notes
  * 2023-04-10     Jair Wu         the first version
  *
  ******************************************************************************
  */

#ifndef __DRV_TOUCHKEY_H__
#define __DRV_TOUCHKEY_H__

#include <rtthread.h>

#ifdef RT_USING_TOUCHKEY_DRIVERS

#include "touch.h"

#define RT_TOUCH_CTRL_REGISTER_HOOK     (8)     /* Register interrupt hook */
#define RT_TOUCH_CTRL_UNREGISTER_HOOK   (9)     /* Unregister interrupt hook */
#define RT_TOUCH_CTRL_SWITCH_LED        (10)    /* Switch LEDs */
#define RT_TOUCH_CTRL_DIRECT_LED        (11)    /* LEDs direct output */

int rt_hw_touchkey_register(rt_touch_t touch,
                            const char              *name,
                            rt_uint32_t              flag,
                            void                    *data);

#endif

#endif
