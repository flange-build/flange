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
    /* SPK_MUTE is GPIO0_A5 */
    HAL_PINCTRL_SetIOMUX(PA_MUTE_GPIO_BANK,
                         PA_MUTE_PIN,
                         PA_MUTE_PIN_FUNC_GPIO);

    HAL_GPIO_SetPinDirection(PA_MUTE_GPIO, PA_MUTE_PIN, GPIO_OUT);
}

void i2c0_m0_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK1,
                         GPIO_PIN_D0 |  // I2C0_SDA
                         GPIO_PIN_D1,   // I2C0_ SCL
                         PIN_CONFIG_MUX_FUNC2);
}

void i2s0_2ch_m0_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK4,
                         GPIO_PIN_B4 |  // I2S0_2CH_MCLK
                         GPIO_PIN_B5 |  // I2S0_2CH_SCLK
                         GPIO_PIN_B6,   // I2S0_2CH_LRCK_TX
                         PIN_CONFIG_MUX_FUNC1);


    HAL_PINCTRL_SetParam(GPIO_BANK4,
                         GPIO_PIN_B4 |
                         GPIO_PIN_B5 |
                         GPIO_PIN_B6,
                         PIN_CONFIG_DRV_LEVEL3);
}

static void i2s0_8ch_m0_iomux_config_ex(eTRCM_modeType trcm_mode)
{
    switch (trcm_mode)
    {
    case TRCM_TXONLY:
        HAL_PINCTRL_SetIOMUX(GPIO_BANK2,
                             GPIO_PIN_A4 |  // I2S0_MCLK(8CH)
                             GPIO_PIN_A5 |  // I2S0_SCLK_TX(8CH)
                             //GPIO_PIN_A6 |  // I2S0_SCLK_RX(8CH)
                             GPIO_PIN_A7 |  // I2S0_LRCK_TX(8CH)
                             // GPIO_PIN_B0 |  // I2S0_LRCK_RX(8CH)
                             GPIO_PIN_B1 |  // I2S0_SDO0(8CH)
                             GPIO_PIN_B2 |  // I2S0_SDO1(8CH)
                             GPIO_PIN_B5,   // I2S0_SDI0(8CH)
                             PIN_CONFIG_MUX_FUNC1);

        /* select 8 channel I2S0 rx sclk in from sclk relative tx IO input */
        WRITE_REG_MASK_WE(GRF->SOC_CON2,
                          GRF_SOC_CON2_I2S0_8CH_SCLK_IN_RX_SRC_SEL_MASK,
                          1 << GRF_SOC_CON2_I2S0_8CH_SCLK_IN_RX_SRC_SEL_SHIFT);
        return;
    case TRCM_RXONLY:
        HAL_PINCTRL_SetIOMUX(GPIO_BANK2,
                             GPIO_PIN_A4 |  // I2S0_MCLK(8CH)
                             //GPIO_PIN_A5 |  // I2S0_SCLK_TX(8CH)
                             GPIO_PIN_A6 |  // I2S0_SCLK_RX(8CH)
                             //GPIO_PIN_A7 |  // I2S0_LRCK_TX(8CH)
                             GPIO_PIN_B0 |  // I2S0_LRCK_RX(8CH)
                             GPIO_PIN_B1 |  // I2S0_SDO0(8CH)
                             GPIO_PIN_B2 |  // I2S0_SDO1(8CH)
                             GPIO_PIN_B5,   // I2S0_SDI0(8CH)
                             PIN_CONFIG_MUX_FUNC1);
        break;
    default:
        HAL_PINCTRL_SetIOMUX(GPIO_BANK2,
                             GPIO_PIN_A4 |  // I2S0_MCLK(8CH)
                             GPIO_PIN_A5 |  // I2S0_SCLK_TX(8CH)
                             GPIO_PIN_A6 |  // I2S0_SCLK_RX(8CH)
                             GPIO_PIN_A7 |  // I2S0_LRCK_TX(8CH)
                             GPIO_PIN_B0 |  // I2S0_LRCK_RX(8CH)
                             GPIO_PIN_B1 |  // I2S0_SDO0(8CH)
                             GPIO_PIN_B2 |  // I2S0_SDO1(8CH)
                             GPIO_PIN_B5,   // I2S0_SDI0(8CH)
                             PIN_CONFIG_MUX_FUNC1);
        break;
    }
    /* select 8 channel I2S0 rx sclk in from sclk relative rx IO input */
    WRITE_REG_MASK_WE(GRF->SOC_CON2,
                      GRF_SOC_CON2_I2S0_8CH_SCLK_IN_RX_SRC_SEL_MASK,
                      0 << GRF_SOC_CON2_I2S0_8CH_SCLK_IN_RX_SRC_SEL_SHIFT);
}

void i2s0_8ch_m0_iomux_config(void)
{
    return i2s0_8ch_m0_iomux_config_ex(TRCM_TXONLY);
}

void i2s1_8ch_m0_iomux_config(void)
{
    /* I2S1 8CH M0 */
    HAL_PINCTRL_SetIOMUX(GPIO_BANK1,
                         GPIO_PIN_A2 |  // I2S1_MCLK_M0(8CH)
                         GPIO_PIN_A3 |  // I2S1_SCLK_TX_M0(8CH)
                         GPIO_PIN_A4 |  // I2S1_SCLK_RX_M0(8CH)
                         GPIO_PIN_A5 |  // I2S1_LRCK_TX_M0(8CH)
                         GPIO_PIN_A6 |  // I2S1_LRCK_RX_M0(8CH)
                         GPIO_PIN_A7 |  // I2S1_SDO0_M0(8CH)
                         GPIO_PIN_B0,   // I2S1_SDO1_M0(8CH)
                         PIN_CONFIG_MUX_FUNC2);

    WRITE_REG_MASK_WE(GRF->SOC_CON2, GRF_SOC_CON2_I2S1_8CH_SD_IOE1_MASK |
                      GRF_SOC_CON2_I2S1_8CH_MULTI_IOFUNC_SRC_SEL_MASK,
                      1 << GRF_SOC_CON2_I2S1_8CH_SD_IOE1_SHIFT |
                      0 << GRF_SOC_CON2_I2S1_8CH_MULTI_IOFUNC_SRC_SEL_SHIFT);


    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_A2 |
                         GPIO_PIN_A3 |
                         GPIO_PIN_A4 |
                         GPIO_PIN_A5 |
                         GPIO_PIN_A6 |
                         GPIO_PIN_A7 |
                         GPIO_PIN_B0,
                         PIN_CONFIG_SMT_ENABLE);
}

void spi0_m0_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK2,
                         GPIO_PIN_A0 |          // SPI0_MISO
                         GPIO_PIN_A1 |          // SPI0_MOSI
                         GPIO_PIN_A2 |          // SPI0_CLK
                         GPIO_PIN_A3,           // SPI0_CS0
                         PIN_CONFIG_MUX_FUNC2);

    WRITE_REG_MASK_WE(GRF->SOC_CON13,
                      GRF_SOC_CON13_GPIO2A2_SEL_PLUS_MASK |
                      GRF_SOC_CON13_GPIO2A3_SEL_PLUS_MASK |
                      GRF_SOC_CON13_GPIO2A2_SEL_SRC_CTRL_MASK |
                      GRF_SOC_CON13_GPIO2A3_SEL_SRC_CTRL_MASK,
                      (2 << GRF_SOC_CON13_GPIO2A2_SEL_PLUS_SHIFT) |
                      (2 << GRF_SOC_CON13_GPIO2A3_SEL_PLUS_SHIFT) |
                      (1 << GRF_SOC_CON13_GPIO2A2_SEL_SRC_CTRL_SHIFT) |
                      (1 << GRF_SOC_CON13_GPIO2A3_SEL_SRC_CTRL_SHIFT));
}

/**
 * @brief  Config iomux for RK3308
 */
void rt_hw_iomux_config(void)
{
    rt_hw_iodomain_config();
    uart2_m1_iomux_config();
    uart4_m0_iomux_config();
    i2c0_m0_iomux_config();
    i2c1_m0_iomux_config();
    i2s0_2ch_m0_iomux_config();
    i2s0_8ch_m0_iomux_config();
    i2s1_8ch_m0_iomux_config();
    spkmute_iomux_config();
#ifdef RT_USING_SPI0
    spi0_m0_iomux_config();
#endif
#ifdef RT_USING_SPI1
    spi1_m0_iomux_config();
#endif
#ifdef RT_USING_SPI2
    spi2_m0_iomux_config();
#endif
}
