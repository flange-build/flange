/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef __IS31FL32XX_H__
#define __IS31FL32XX_H__

#define BIT(_x)  (1<<(_x))
#define GENMASK(h, l) \
  (((~0UL) - (1UL << (l)) + 1) & (~0UL >> (32 - 1 - (h))))
#define RT_IS31FL32XX_CMD_DUMMY 0
#define RT_IS31FL32XX_CMD_SET_BRIGHTNESS 1

/* Used to indicate a device has no such register */
#define IS31FL32XX_REG_NONE 0xFF

/* Software Shutdown bit in Shutdown Register */
#define IS31FL32XX_SHUTDOWN_SSD_ENABLE  0
#define IS31FL32XX_SHUTDOWN_SSD_DISABLE BIT(0)

/* IS31FL3216 has a number of unique registers */
#define IS31FL3216_CONFIG_REG 0x00
#define IS31FL3216_LIGHTING_EFFECT_REG 0x03
#define IS31FL3216_CHANNEL_CONFIG_REG 0x04

/* Software Shutdown bit in 3216 Config Register */
#define IS31FL3216_CONFIG_SSD_ENABLE  BIT(7)
#define IS31FL3216_CONFIG_SSD_DISABLE 0

struct is31fl32xx_priv
{
    struct rt_device parent;
    rt_int8_t busName[16];
    struct rt_i2c_client clientDevice;
    const struct is31fl32xx_chipdef *cdef;
};

struct is31fl32x_brightness
{
    rt_uint32_t channel;
    rt_uint32_t brightness;
};

#define IS31FL32XX_DEV_NAME "is32fl32xx"
#define IS31FL32XX_I2C_BUS  "i2c2"
#define IS31FL32XX_I2C_ADR  0x3C

#define IS31FL32XX_PIN_HIGH              GPIO_HIGH
#define IS31FL32XX_PIN_LOW               GPIO_LOW

#define IS31FL3235
//#define IS31FL3236
//#define IS31FL3218
//#define IS31FL3216

//You need to add relevant gpio configuration in
//board.h according to the actual hardware connection
#ifndef IS31FL32XX_SDB_GPIO_BANK
#define IS31FL32XX_SDB_GPIO_BANK         GPIO_BANK0
#endif
#ifndef IS31FL32XX_SDB_GPIO_GRP
#define IS31FL32XX_SDB_GPIO_GRP          GPIO0
#endif
#ifndef IS31FL32XX_SDB_GPIO
#define IS31FL32XX_SDB_GPIO              GPIO_PIN_A4
#endif
#ifndef IS31FL32XX_SDB_PIN
#define IS31FL32XX_SDB_PIN               BANK_PIN(GPIO_BANK0, 4)
#endif

//#define IS31FL32XX_DEBUG

#endif
