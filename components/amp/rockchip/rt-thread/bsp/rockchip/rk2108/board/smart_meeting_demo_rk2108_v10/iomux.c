/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
 */

#include "rtdef.h"
#include "iomux.h"
#include "hal_base.h"
#include "board.h"
#include "board_wifibt.h"

RT_WEAK RT_UNUSED void sfc0_dual_io_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_B4 |  // SFC_CS
                         GPIO_PIN_B5,   // SFC_CLK
                         PIN_CONFIG_MUX_FUNC3);

    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_B6 |  // SFC_D0
                         GPIO_PIN_B7,   // SFC_D1
                         PIN_CONFIG_MUX_FUNC2);
}

void audio_pa_iomux_config(void)
{
    HAL_PINCTRL_SetIOMUX(PA_PWR_GPIO_BANK,
                         PA_PWR_PIN,    // PA_PWR_PWREN
                         PA_PWR_PIN_FUNC_GPIO);
    HAL_GPIO_SetPinDirection(PA_PWR_GPIO, PA_PWR_PIN, GPIO_OUT);
    HAL_GPIO_SetPinLevel(PA_PWR_GPIO, PA_PWR_PIN, PA_PWR_ON);
    HAL_DelayMs(40);

    HAL_PINCTRL_SetIOMUX(PA_GPIO_BANK,
                         PA_PIN,        // SPK_CTL
                         PA_PIN_FUNC_GPIO);
    HAL_GPIO_SetPinDirection(PA_GPIO, PA_PIN, GPIO_OUT);
    HAL_GPIO_SetPinLevel(PA_GPIO, PA_PIN, PA_UNMUTE);
    HAL_DelayMs(40);
}

void pwr_iomux(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_D1,        // CORE_DVFS
                         PIN_CONFIG_MUX_FUNC4);

    HAL_PINCTRL_SetIOMUX(GPIO_BANK0,
                         GPIO_PIN_C2 |        // PMIC_INT
                         GPIO_PIN_B3,        // LED_BAT_STATUS
                         PIN_CONFIG_MUX_FUNC0);
    HAL_GPIO_SetPinDirection(GPIO0, GPIO_PIN_B3, GPIO_OUT);
    HAL_GPIO_SetPinLevel(GPIO0, GPIO_PIN_B3, GPIO_LOW);
}

uint32_t rk_bt_rst(void)
{
    rt_thread_mdelay(50);
    HAL_GPIO_SetPinLevel(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_LOW);
    rt_thread_mdelay(50);
    HAL_GPIO_SetPinLevel(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_HIGH);
    rt_thread_mdelay(100);
    rt_kprintf("BT POWER On \n");

    return 0;
}

uint32_t rk_bt_power_down(void)
{
    HAL_GPIO_SetPinLevel(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_LOW);
    rt_thread_delay(100);
    HAL_GPIO_SetPinDirection(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_IN);

    return 1;
}

void rk_bt_init_gpio(void)
{
    // setup bt_reg_on
    HAL_PINCTRL_SetIOMUX(BT_GPIO_PORT, BT_POWER_GPIO_PIN, PIN_CONFIG_MUX_FUNC0);
    HAL_GPIO_SetPinDirection(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_OUT);

    // TODO: power on BT
    HAL_GPIO_SetPinLevel(BT_GPIO_PORT_BASE, BT_POWER_GPIO_PIN, GPIO_HIGH);
}

void touchkey_int(void)
{
    HAL_PINCTRL_SetIOMUX(GPIO_BANK1,
                         GPIO_PIN_B6 |      // TOUCH_KEY_RST
                         GPIO_PIN_B7,       // TOUCH_KEY_INT
                         PA_PIN_FUNC_GPIO);

    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B6, GPIO_OUT);
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B7, GPIO_IN);

    HAL_GPIO_SetPinLevel(GPIO1, GPIO_PIN_B6, GPIO_LOW);
}

void rt_hw_iomux_config(void)
{
    pdm_input_iomux_config();

    sfc0_dual_io_iomux_config();

    uart2_iomux_config();

    uart0_iomux_config();

    i2c0_m0_iomux_config();

    i2c2_m0_iomux_config();

#ifdef RT_USING_I2STDM1
    i2s1_output_iomux_config();
#endif

    rk_bt_init_gpio();

    pwr_iomux();

    touchkey_int();

    audio_pa_iomux_config();
}
