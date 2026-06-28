/**
  * Copyright (c) 2020 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
 */

/** @addtogroup RKBSP_Board_Driver
 *  @{
 */

/** @addtogroup IOMUX
 *  @{
 */

/** @defgroup How_To_Use How To Use
 *  @{
 @verbatim

 ==============================================================================
                    #### How to use ####
 ==============================================================================
 This file provide IOMUX for board, it will be invoked when board initialization.

 @endverbatim
 @} */
#include "rtdef.h"
#include "iomux.h"
#include "hal_base.h"
#include "board.h"

/********************* Private MACRO Definition ******************************/
/** @defgroup IOMUX_Private_Macro Private Macro
 *  @{
 */

/** @} */  // IOMUX_Private_Macro

/********************* Private Structure Definition **************************/
/** @defgroup IOMUX_Private_Structure Private Structure
 *  @{
 */

/** @} */  // IOMUX_Private_Structure

/********************* Private Variable Definition ***************************/
/** @defgroup IOMUX_Private_Variable Private Variable
 *  @{
 */

/** @} */  // IOMUX_Private_Variable

/********************* Private Function Definition ***************************/
/** @defgroup IOMUX_Private_Function Private Function
 *  @{
 */

/**
 * @brief  Config iomux for PDM
 */
void pdm_input_iomux_config(void)
{
    // for pdm input
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_A0 |  // PDM_IN_CLK0
                         GPIO_PIN_A2,   // PDM_IN_SDI0
                         PIN_CONFIG_MUX_FUNC1);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A0 |  // PDM_IN_CLK0
                         GPIO_PIN_A2,   // PDM_IN_SDI0
                         PIN_CONFIG_PUL_NORMAL);

    WRITE_REG_MASK_WE(GRF->SOC_CON2,
                      GRF_SOC_CON2_GRF_CON_AUDIO_BYPASS_CTRL_SEL_MASK,  // Audio bypass controlled by GRF
                      (0x1 << GRF_SOC_CON2_GRF_CON_AUDIO_BYPASS_CTRL_SEL_SHIFT));

    WRITE_REG_MASK_WE(GRF->SOC_CON4,
                      GRF_SOC_CON4_GRF_CON_AUDIO_PRO_APP_PDM_MASK,  // PDM used as audio input
                      (0x1 << GRF_SOC_CON4_GRF_CON_AUDIO_PRO_APP_PDM_SHIFT));
}

/** @} */  // IOMUX_Private_Function

/********************* Public Function Definition ****************************/

/** @defgroup IOMUX_Public_Functions Public Functions
 *  @{
 */

/**
 * @brief  Config iomux for rk2108d_evb_v20 board
 */

static void codec_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK1,
                         GPIO_PIN_B1 |  // AMP_RST
                         GPIO_PIN_B2,   // AMP_INT
                         PIN_CONFIG_MUX_FUNC0);

    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B1, GPIO_OUT);
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B2, GPIO_IN);
}

/**
 * @brief  Config iomux for I2S1
 */
void i2s1_output_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_A6 |  // I2S1_OUT_SCLK_MUX0
                         GPIO_PIN_A7 |  // I2S1_OUT_LRCK_MUX0
                         GPIO_PIN_B0,   // I2S1_OUT_SDO0_MUX0
                         PIN_CONFIG_MUX_FUNC4);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A6 |  // I2S1_OUT_SCLK_MUX0
                         GPIO_PIN_A7 |  // I2S1_OUT_LRCK_MUX0
                         GPIO_PIN_B0,   // I2S1_OUT_SDO0_MUX0
                         PIN_CONFIG_PUL_NORMAL);

    WRITE_REG_MASK_WE(GRF->SOC_CON4,
                      GRF_SOC_CON4_GRF_CON_AUDIO_PRO_APP_I2S1_MASK,  // used I2S1 as audio input
                      (0x1 << GRF_SOC_CON4_GRF_CON_AUDIO_PRO_APP_I2S1_SHIFT));
}

/**
 * @brief  Config iomux for SPK
 */
static void spk_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_A3,
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A3,
                         PIN_CONFIG_PUL_UP);

    HAL_GPIO_SetPinDirection(GPIO0, GPIO_PIN_A3, GPIO_OUT);
    HAL_GPIO_SetPinLevel(GPIO0, GPIO_PIN_A3, GPIO_HIGH);
}

/**
 * @brief  Config iomux for LCDC
 */
void lcdc_iomux_config(void)
{
    /* use gpio interrupt to trigger new frame */
    HAL_PINCTRL_SetIOMUX(RT_HW_LCD_GPIO_TRIGGER_BANK,
                         RT_HW_LCD_GPIO_TRIGGER_GPIO,
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetIOMUX(RT_HW_LCD_POWER_EN_BANK,
                         RT_HW_LCD_POWER_EN_GPIO,   // LCDC_RST
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetIOMUX(GPIO_BANK1,
                         GPIO_PIN_A4,
                         PIN_CONFIG_MUX_FUNC4);
}

/**
 * @brief  Config iomux for SDIO
 */
void sdio_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_C0 |  // SDIO_CLK
                         GPIO_PIN_C1 |  // SDIO_CMD
                         GPIO_PIN_C2 |  // SDIO_D0
                         GPIO_PIN_C3 |  // SDIO_D1
                         GPIO_PIN_C4,   // SDIO_D2
                         PIN_CONFIG_MUX_FUNC4);

    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_C5,   // SDIO_D3
                         PIN_CONFIG_MUX_FUNC3);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_C1 |  // SDIO_CMD
                         GPIO_PIN_C2 |  // SDIO_D0
                         GPIO_PIN_C3 |  // SDIO_D1
                         GPIO_PIN_C4 |  // SDIO_D2
                         GPIO_PIN_C5,   // SDIO_D3
                         PIN_CONFIG_PUL_UP |
                         PIN_CONFIG_DRV_LEVEL1);
}

void usb_vbus_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_A1,
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetParam(GPIO_BANK0, GPIO_PIN_A1, PIN_CONFIG_PUL_NORMAL);
}

void power_key_iomux_config(void)
{
#if defined(POWER_KEY_BANK) && defined(POWER_KEY_PIN)
    HAL_PINCTRL_SetIOMUX(POWER_KEY_BANK,
                         POWER_KEY_PIN,
                         PIN_CONFIG_MUX_FUNC0);
#endif
}

void rt_hw_iomux_config(void)
{
    i2s1_output_iomux_config();

    spk_iomux_config();

    i2c1_m2_iomux_config();

    pdm_input_iomux_config();

    uart1_m1_iomux_config();

    sfc0_iomux_config();

    sfc1_iomux_config();

#ifdef RT_USING_SDIO0
    sdio_iomux_config();
#endif

#ifdef M4_JTAG_ENABLE
    m4_jtag_iomux_config();
#else
    uart0_iomux_config();
#endif

    uart0_cts_rts_iomux_config();

    lcdc_iomux_config();

    i2c0_m1_iomux_config();

#ifdef RT_USING_USB_DEVICE
    usb_vbus_iomux_config();
#endif

    power_key_iomux_config();
}
/** @} */  // IOMUX_Public_Functions

/** @} */  // IOMUX

/** @} */  // RKBSP_Board_Driver
