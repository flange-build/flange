/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd
 */

/**
 * @file  hal_conf_template.h
 */

#ifndef _HAL_CONF_H_
#define _HAL_CONF_H_

#include "rtconfig.h"

#define HAL_MCU_CORE
#define __RISC_V

#ifdef SMODE_RTOS
#define SMP_CPU_CNT 1
#define RISCV_SMODE
#endif

#ifdef RT_USING_CACHE
#define HAL_DCACHE_MODULE_ENABLED
#define HAL_ICACHE_MODULE_ENABLED
#endif

#ifdef RT_USING_CRU
#define HAL_CRU_MODULE_ENABLED
#endif

#ifdef RT_USING_FLEXBUS
#define HAL_FLEXBUS_MODULE_ENABLED
#endif

#ifdef RT_USING_FLEXBUS_ADC
#define HAL_FLEXBUS_ADC_MODULE_ENABLED
#endif

#ifdef RT_USING_FLEXBUS_DAC
#define HAL_FLEXBUS_DAC_MODULE_ENABLED
#endif

#ifdef RT_USING_SNOR
#define HAL_SNOR_MODULE_ENABLED
#define HAL_SNOR_FSPI_HOST
#define HAL_FSPI_MODULE_ENABLED
#define HAL_FSPI_DMA_ENABLED
#ifdef RT_USING_XIP
#define HAL_FSPI_XIP_ENABLE
#define HAL_SRAM_SECTION_ENABLED
#endif
#endif

#ifdef RT_USING_SPI2APB
#define HAL_SPI2APB_MODULE_ENABLED
#endif

#ifdef RT_USING_UART
#define HAL_UART_MODULE_ENABLED
#endif

#define HAL_DBG_USING_RTT_SERIAL 1   /* redirect the hal log to rtt console */

#endif /* _HAL_CONF_H_ */
