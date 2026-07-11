/*
 * Copyright (c) 2025 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2025-02-24     Tom Song   first implementation
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
}
