/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2021-04-12     Steven Liu   first implementation
 */

#include "rtdef.h"
#include "iomux.h"
#include "hal_base.h"

void rt_hw_iomux_config(void)
{
#ifdef RT_USING_UART
#ifdef RT_USING_UART5
    uart5_m2_iomux_config();
#endif
#ifdef RT_USING_UART7
    uart7_m2_iomux_config();
#endif
#ifdef RT_USING_UART8
    uart8_m1_iomux_config();
#endif
#endif
#ifdef RT_USING_I2C7
    i2c7_m1_iomux_config();
#endif
#ifdef RT_USING_I2C8
    i2c8_m2_iomux_config();
#endif
#ifdef RT_USING_PERI_EN
    peri_s0_iomux_config();
#endif
}
