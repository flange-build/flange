/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2022-06-09     Cliff chen   first implementation
 */

#include "rtdef.h"
#include "iomux.h"
#include "board.h"
#include "hal_base.h"

/**
 * @brief  Config io domian for board of rk3308_ddr2p116sd4_v10
 */

void rt_hw_iodomain_config(void)
{
    /* VCC IO 2 voltage select 1v8 */
    GRF->SOC_CON0 = (1 << GRF_SOC_CON0_IO_VSEL2_SHIFT) |
                    (GRF_SOC_CON0_IO_VSEL2_MASK << 16);
}

void spkmute_iomux_config(void)
{
    /* PA_MUTE is GPIO0_A5 */
    HAL_PINCTRL_SetIOMUX(PA_MUTE_GPIO_BANK,
                         PA_MUTE_PIN,
                         PA_MUTE_PIN_FUNC_GPIO);

    HAL_GPIO_SetPinDirection(PA_MUTE_GPIO, PA_MUTE_PIN, GPIO_OUT);
}

/**
 * @brief  Config iomux for RK3308
 */
void rt_hw_iomux_config(void)
{
    rt_hw_iodomain_config();

#ifdef RT_USING_UART1
    uart1_m0_iomux_config();
#endif

#ifdef RT_USING_UART2
    uart2_m1_iomux_config();
#endif

#ifdef RT_USING_UART3
    uart3_m1_iomux_config();
#endif

#ifdef RT_USING_UART4
    uart4_m0_iomux_config();
#endif

    i2c1_m0_iomux_config();
    i2s0_8ch_m0_iomux_config();
    spkmute_iomux_config();

#ifdef RT_USING_SPI1
    spi1_m0_iomux_config();
#endif

#ifdef RT_USING_SPI2
    spi2_m0_iomux_config();
#endif

#ifdef RT_USING_SDIO0
    sdio_iomux_config();
#endif

#ifdef RT_USING_GMAC
#ifdef RT_USING_GMAC0
    gmac0_m1_iomux_config();
#endif
#endif

}
