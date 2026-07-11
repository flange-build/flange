/**
  * Copyright (c) 2018 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: BSD-3-Clause
  ******************************************************************************
  * @file    spi2apb.h
  * @author  David Wu
  * @version V0.1
  * @date    20-Mar-2019
  * @brief   spi2apb driver for pisces
  *
  ******************************************************************************
  */

#ifndef __DRV_SPI2APB_H__
#define __DRV_SPI2APB_H__

#include <stdlib.h>
#include <rtthread.h>
#include "hal_base.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * SPI configuration structure variable "reserved"
 */
#define RK_SPI_RESERVED_LITTLE_ENDIAN     (0)
#define RK_SPI_RESERVED_BIG_ENDIAN        (1)

/* ctrl */
#define RT_DEVICE_CTRL_SPI2APB_CONFIGURATION (1)
#define RT_DEVICE_CTRL_SPI2APB_QUERY_STATUS  (2)
#define RT_DEVICE_CTRL_SPI2APB_REGISTER_CB   (3)
#define RT_DEVICE_CTRL_SPI2APB_READ_REG0     (4)
#define RT_DEVICE_CTRL_SPI2APB_READ_REG1     (5)
#define RT_DEVICE_CTRL_SPI2APB_WRITE_REG2    (6)

/* state */
#define RT_STATE_SPI2APB_BUSY           SPI2APB_BUSY
#define RT_STATE_SPI2APB_TX_FULL        SPI2APB_TX_FULL
#define RT_STATE_SPI2APB_TX_EMPTY       SPI2APB_TX_EMPTY
#define RT_STATE_SPI2APB_RX_FULL        SPI2APB_RX_FULL
#define RT_STATE_SPI2APB_RX_EMPTY       SPI2APB_RX_EMPTY

typedef void (*spi2apb_callback)(rt_uint32_t cparam);

#ifdef __cplusplus
}
#endif

#endif