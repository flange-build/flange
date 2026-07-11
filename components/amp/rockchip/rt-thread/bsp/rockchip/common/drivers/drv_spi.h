/**
  * Copyright (c) 2024 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_spi.h
  * @version V1.0
  * @brief   spi driver headfile
  *
  * Change Logs:
  * Date           Author          Notes
  * 2024-06-25     Dingqiang Lin   the first version
  *
  ******************************************************************************
  */

#ifdef RT_USING_SPI

#ifndef __DRV_SPI_H__
#define __DRV_SPI_H__

#include <rthw.h>
#include <rtthread.h>
#include <rtdevice.h>

/**
 * SPI configuration structure variable "reserved"
 */
#define RK_SPI_RESERVED_RSD_0     (0)
#define RK_SPI_RESERVED_RSD_1     (1)
#define RK_SPI_RESERVED_RSD_2     (2)
#define RK_SPI_RESERVED_RSD_3     (3)
#define RK_SPI_RESERVED_RSD_MASK  (3)

#define RK_SPI_EXT_FREELOOP_MODE
enum rk_spi_ext_freeloop_type
{
    RK_SPI_FREELOOP_TYPE_UNKNOW,  /**< Type Unknown */
    RK_SPI_FREELOOP_DMA_CYCLIC,   /**< Freeloop implementation by DMA cyclic */
    RK_SPI_FREELOOP_ISR_RECONFIG, /**< Freeloop implementation by IRQ reconfiguration */
};

struct rt_spi_ready_gpio
{
    struct GPIO_REG *gpio;
#ifdef HAL_GPIO_MODULE_ENABLED
    ePINCTRL_GPIO_PINS pin;
#endif
};

struct spi_board
{
    struct rt_spi_ready_gpio ready;
};

rt_err_t rk_spi_ext_freeloop_start(struct rt_spi_device *device,
                                   void *callback, void *param,
                                   char *tx_buf, char *rx_buf, uint32_t length,
                                   enum rk_spi_ext_freeloop_type type);
rt_err_t rk_spi_ext_freeloop_stop(struct rt_spi_device *device);

#endif
#endif
