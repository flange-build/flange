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

/**
 * @brief  Config io domian for board of rk3568 evb1
 */

void rt_hw_iodomain_config(void)
{
    WRITE_REG_MASK_WE(GRF->IO_VSEL0,
                      GRF_IO_VSEL0_POC_VCCIO4_SEL18_MASK |
                      GRF_IO_VSEL0_POC_VCCIO6_SEL18_MASK,
                      (1 << GRF_IO_VSEL0_POC_VCCIO4_SEL18_SHIFT) |
                      (1 << GRF_IO_VSEL0_POC_VCCIO6_SEL18_SHIFT));

    WRITE_REG_MASK_WE(GRF->IO_VSEL1,
                      GRF_IO_VSEL1_POC_VCCIO4_SEL33_MASK |
                      GRF_IO_VSEL1_POC_VCCIO6_SEL33_MASK,
                      (0 << GRF_IO_VSEL1_POC_VCCIO4_SEL33_SHIFT) |
                      (0 << GRF_IO_VSEL1_POC_VCCIO6_SEL33_SHIFT));
}

void touch_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_B5 |  // TOUCH_INT
                         GPIO_PIN_B6 |  // TOUCH_RST
                         GPIO_PIN_C7,   // PANNEL_POWER(LCDC & TOUCH)
                         PIN_CONFIG_MUX_FUNC0);

    /* PANNEL & TOUCH POWER_EN ON */
    HAL_GPIO_SetPinDirection(GPIO0, GPIO_PIN_C7, GPIO_OUT);
    HAL_GPIO_SetPinLevel(GPIO0, GPIO_PIN_C7, GPIO_HIGH);
}

/**
 * @brief  Config iomux for RK3568
 */
void rt_hw_iomux_config(void)
{
    rt_hw_iodomain_config();

#ifdef RT_USING_UART
#ifdef RT_USING_UART2
    uart2_m0_iomux_config();
#endif
#ifdef RT_USING_UART4
    uart4_m1_iomux_config();
#endif
#ifdef RT_USING_UART7
    uart7_m2_iomux_config();
#endif
#endif

#ifdef RT_USING_CAN
    can1_m1_iomux_config();
#endif

#ifdef RT_USING_GMAC
#ifdef RT_USING_GMAC0
    gmac0_iomux_config();
#endif
#ifdef RT_USING_GMAC1
    gmac1_m1_iomux_config();
#endif
#endif

#ifdef RT_USING_I2C
#ifdef RT_USING_I2C0
    i2c0_m0_iomux_config();
#endif

#ifdef RT_USING_I2C1
    i2c1_m0_iomux_config();
#endif
#endif

#ifdef RT_USING_TOUCH
    touch_iomux_config();
#endif

#ifdef RT_USING_SDIO0
    sdmmc0_iomux_config();
#endif
}
