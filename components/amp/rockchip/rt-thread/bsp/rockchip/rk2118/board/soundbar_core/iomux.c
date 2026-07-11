/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-02-07     Cliff Chen   first implementation
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

/** @} */  // IOMUX_Private_Function

/********************* Public Function Definition ****************************/

/** @defgroup IOMUX_Public_Functions Public Functions
 *  @{
 */

#ifdef RT_USING_UART2
/**
 * @brief  Config iomux for uart2
 */
void uart2_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_B4,   // UART2_TX_AUDIO_DEBUG
                        RMIO_UART2_TX_RM1);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_B5,   // UART2_RX_AUDIO_DEBUG
                        RMIO_UART2_RX_RM1);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_B4 |
                         GPIO_PIN_B5,       //PULL-UP
                         PIN_CONFIG_PUL_UP);
}
#endif

#ifdef RT_USING_UART3
/**
 * @brief  Config iomux for uart3
 */
void uart3_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C5,   // UART3_TX
                        RMIO_UART3_TX);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C4,   // UART3_RX
                        RMIO_UART3_RX);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_C4 |
                         GPIO_PIN_C5,   //PULL-UP
                         PIN_CONFIG_PUL_DOWN);

}
#endif

#ifdef RT_USING_SPI2
/**
 * @brief  Config iomux for SPI2
 */
void spi2_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_A1,   // SPI2_MOSI
                        RMIO_SPI2_MOSI);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_B2,   // SPI2_CLK
                        RMIO_SPI2_CLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_B3,   // SPI2_CSN0
                        RMIO_SPI2_CSN0);
}
#endif

#ifdef RT_USING_I2C0
void i2c0_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK0,
                        GPIO_PIN_A7,   // I2C0_SCL
                        RMIO_I2C0_SCL);

    HAL_PINCTRL_SetRMIO(GPIO_BANK0,
                        GPIO_PIN_A6,   // I2C0_SDA
                        RMIO_I2C0_SDA);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A6 |
                         GPIO_PIN_A7,   //HI-Z
                         PIN_CONFIG_PUL_NORMAL);
}
#endif

#ifdef RT_USING_I2C2
/**
 * @brief  Config iomux for I2C2
 */
void i2c2_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C0,   // I2C2_SDA
                        RMIO_I2C2_SDA_RM1);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C1,   // I2C2_SCL
                        RMIO_I2C2_SCL_RM1);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_C0 |
                         GPIO_PIN_C1,   //HI-Z
                         PIN_CONFIG_PUL_UP);
}
#endif

#ifdef RT_USING_I2C3
/**
 * @brief  Config iomux for I2C3
 */
void i2c3_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C2,   // I2C2_SCL
                        RMIO_I2C3_SCL_RM1);

    HAL_PINCTRL_SetRMIO(GPIO_BANK3,
                        GPIO_PIN_C3,   // I2C2_SDA
                        RMIO_I2C3_SDA_RM1);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_C2 |
                         GPIO_PIN_C3,   //HI-Z
                         PIN_CONFIG_PUL_UP);

}
#endif

/**
 * @brief  Config iomux for SPDIF
 */
void spdif_rx_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_B0,   // SPDIF_RX0
                        RMIO_SPDIF_RX0);
}

#ifdef RT_USING_PWM0
/**
 * @brief  Config iomux for pwm0
 */
void pwm0_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK0,
                        GPIO_PIN_A4,   // PWM0_3 IR
                        RMIO_PWM0_CH3);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A4,       //PULL-UP
                         PIN_CONFIG_PUL_UP);

    HAL_PINCTRL_SetRMIO(GPIO_BANK0,
                        GPIO_PIN_A3,   // PWM0_0
                        RMIO_PWM0_CH0);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A3,       //PULL-NORMAL
                         PIN_CONFIG_PUL_NORMAL);

    HAL_PINCTRL_SetRMIO(GPIO_BANK0,
                        GPIO_PIN_A5,   // PWM0_1
                        RMIO_PWM0_CH1);

    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_A5,       //PULL-NORMAL
                         PIN_CONFIG_PUL_NORMAL);
}
#endif

/**
 * @brief  Config iomux for SAI0
 */
void sai0_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A6,   // SAI0_I2S_MCLK
                        RMIO_SAI0_MCLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A0,   // SAI0_I2S_SCLK
                        RMIO_SAI0_SCLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A1,   // SAI0_I2S_LRCK
                        RMIO_SAI0_LRCK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A2,   // SAI0_I2S_SDI0
                        RMIO_SAI0_SDI0);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A3,   // SAI0_I2S_SDI1
                        RMIO_SAI0_SDI1);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A4,   // SAI0_I2S_SDI2
                        RMIO_SAI0_SDI2);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_A5,   // SAI0_I2S_SDI3
                        RMIO_SAI0_SDI3);
}

/**
 * @brief  Config iomux for SAI1
 */
void sai1_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_B1,   // SAI1_I2S_MCLK
                        RMIO_SAI1_MCLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_B3,     // SAI1_I2S_SCLK
                        RMIO_SAI1_SCLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_B4,     // SAI1_I2S_LRCK
                        RMIO_SAI1_LRCK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_B5,     // SAI1_I2S_SDI0
                        RMIO_SAI1_SDI0);
}

/**
 * @brief  Config iomux for SAI4
 */
void sai4_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C0,   // SAI4_I2S_SCLK
                        RMIO_SAI4_SCLK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C1,   // SAI4_I2S_LRCK
                        RMIO_SAI4_LRCK);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C2,   // SAI4_I2S_SDO0
                        RMIO_SAI4_SDO0);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C3,   // SAI4_I2S_SDO1
                        RMIO_SAI4_SDO1);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C4,   // SAI4_I2S_SDO2
                        RMIO_SAI4_SDO2);

    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C5,   // SAI4_I2S_SDO3
                        RMIO_SAI4_SDO3);
}

/**
 * @brief  Config iomux for SAI5
 */
void sai5_iomux_config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK4,
                        GPIO_PIN_C6,   // SAI5_I2S_SDO0
                        RMIO_SAI5_SDO0);
}

#ifdef RT_USING_IT6632X
void it6632x_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(IT6632X_RST_GPIO_BANK,
                         IT6632X_RST_GPIO,   // RST
                         IT6632X_RST_PIN_FUNC_GPIO);

    HAL_PINCTRL_SetIOMUX(IT6632X_INT_GPIO_BANK,
                         IT6632X_INT_GPIO,   // INT
                         IT6632X_INT_PIN_FUNC_GPIO);

    HAL_PINCTRL_SetIOMUX(IT6632X_RXMUTE_GPIO_BANK,
                         IT6632X_RXMUTE_GPIO,   // RXMUTE
                         IT6632X_RXMUTE_PIN_FUNC_GPIO);
}
#endif

/**
 * @brief  Config iomux for usb host
 */
void usb_host_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3,
                         GPIO_PIN_A5,
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_A5, // HI-Z
                         PIN_CONFIG_PUL_NORMAL);

    HAL_GPIO_SetPinDirection(GPIO3, GPIO_PIN_A5, GPIO_OUT);
    HAL_GPIO_SetPinLevel(GPIO3, GPIO_PIN_A5, GPIO_LOW);
}

#ifdef RT_USING_AIP1629
/**
 * @brief  Config iomux for led
 */
void led_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3,
                         GPIO_PIN_A2,
                         PIN_CONFIG_MUX_FUNC0);

    HAL_PINCTRL_SetParam(GPIO_BANK3,
                         GPIO_PIN_A2, // HI-Z
                         PIN_CONFIG_PUL_UP);

    HAL_GPIO_SetPinDirection(GPIO3, GPIO_PIN_A2, GPIO_OUT);
    HAL_GPIO_SetPinLevel(GPIO3, GPIO_PIN_A2, GPIO_HIGH);
}
#endif

/**
 * @brief  Config iomux for rk2118 soundbar core board
 */
void rt_hw_iomux_config(void)
{
    sai_mclkout_config_all();
    dsp_jtag_iomux_config();
    fspi0_iomux_config();
#ifdef RT_USING_UART0
    uart0_iomux_config();
#endif
#ifdef RT_USING_UART2
    uart2_iomux_config();
#endif
#ifdef RT_USING_UART3
    uart3_iomux_config();
#endif
    mcu_jtag_m0_iomux_config();
#ifdef RT_USING_SPI2
    spi2_iomux_config();
#endif
#ifdef RT_USING_I2C0
    i2c0_iomux_config();
#endif
#ifdef RT_USING_I2C2
    i2c2_iomux_config();
#endif
#ifdef RT_USING_I2C3
    i2c3_iomux_config();
#endif
#ifdef RT_USING_PWM0
    pwm0_iomux_config();
#endif
    sai0_iomux_config();
    sai1_iomux_config();
    sai4_iomux_config();
    sai5_iomux_config();
#ifdef RT_USING_IT6632X
    it6632x_iomux_config();
    spdif_rx_iomux_config();
#endif
    usb_host_iomux_config();
#ifdef RT_USING_AIP1629
    led_iomux_config();
#endif
}

/** @} */  // IOMUX_Public_Functions

/** @} */  // IOMUX

/** @} */  // RKBSP_Board_Driver
