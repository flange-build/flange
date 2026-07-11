/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-09-01     tony.zheng     the first version
 */

#ifndef __NCA9539_H_
#define __NCA9539_H_
#include <rtthread.h>
#include <rtdevice.h>

#ifndef NCA9539_I2C_BUS_NAME
#define NCA9539_I2C_BUS_NAME   0
#endif

#define NCA9539_ADDR                  0x74
#define NCA9539_REG_INPUT_PORT_BASE 0x00
#define NCA9539_REG_INPUT_PORT0 (NCA9539_REG_INPUT_PORT_BASE + 0x0)
#define NCA9539_REG_INPUT_PORT1 (NCA9539_REG_INPUT_PORT_BASE + 0x1)
#define NCA9539_REG_OUTPUT_PORT_BASE 0x02
#define NCA9539_REG_OUTPUT_PORT0 (NCA9539_REG_OUTPUT_PORT_BASE + 0x0)
#define NCA9539_REG_OUTPUT_PORT1 (NCA9539_REG_OUTPUT_PORT_BASE + 0x1)
#define NCA9539_REG_POLARITY_BASE 0x04
#define NCA9539_REG_POLARITY_PORT0 (NCA9539_REG_POLARITY_BASE + 0x0)
#define NCA9539_REG_POLARITY_PORT1 (NCA9539_REG_POLARITY_BASE + 0x1)
#define NCA9539_REG_CONFIG_BASE 0x06
#define NCA9539_REG_CONFIG_PORT0 (NCA9539_REG_CONFIG_BASE + 0x0)
#define NCA9539_REG_CONFIG_PORT1 (NCA9539_REG_CONFIG_BASE + 0x1)


#define NCA9539_BANK_SZ 8
#define NCA9539_MAX_BANK 2

#define NCA9539_CHIP_ADDR 0x74

#ifndef BIT
#define BIT(nr) (1UL << (nr))
#endif

#define IO_DEV_NAME             "nca9539"

#endif
