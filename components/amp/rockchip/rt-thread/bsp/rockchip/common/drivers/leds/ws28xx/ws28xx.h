/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef __WS28XX_H__
#define __WS28XX_H__

//#define WS28XX_DEBUG

typedef enum
{
    WS28XX_GET_LED_NUM,
    WS28XX_GET_RGB_DATA_BITS,
} ws28xx_ctrl_t;

struct ws28xx_device
{
    struct rt_device parent;
    struct rt_spi_device *spi;

    rt_uint32_t raw_data_len;
    rt_uint8_t *protocol_data;
    rt_uint32_t leds_num;
    rt_uint32_t rgb_data_bits;
};

#ifndef WS28XX_DEVICE_NAME
#define WS28XX_DEVICE_NAME     "ws28xx"
#endif

#ifndef WS28XX_SPI_DEVICE
#define WS28XX_SPI_DEVICE      "spi2_0"
#endif

#define WS28XX_SPI_MODE        (RT_SPI_MASTER | RT_SPI_LSB | RT_SPI_MODE_3)

//Users need to configure according to the actual hardware
#ifndef WS28XX_RGB_NUM
#define WS28XX_RGB_NUM                  20
#endif

//User needs to configure according to the specific light strip specification
#ifndef WS28XX_DATA_BITS
#define WS28XX_DATA_BITS                24
#endif

//User needs to configure according to the specific light strip specification
#ifndef SINGLE_CODE_DURATION_NS
#define SINGLE_CODE_DURATION_NS         1200
#endif

//User needs to configure according to the specific light strip specification
#ifndef RESET_CODE_DURATION_NS
#define RESET_CODE_DURATION_NS          200*1000
#endif

//Ratio of high and low levels in code 0 and code 1,User needs to configure
//according to the specific light strip specification
#ifndef CODE_LEVEL_RATIO
#define CODE_LEVEL_RATIO                3
#endif

//The ratio of the duration of the low level and high level of code 0
#define T0L_T0H_RATIO  CODE_LEVEL_RATIO
//The ratio of the duration of the high level and low level of code 1
#define T1H_T1L_RATIO  CODE_LEVEL_RATIO

#define CODE0                          (0x01 << (T0L_T0H_RATIO - 1))
#define CODE1                          ((0x01 << (T1H_T1L_RATIO + 1)) - 2)

//How many bits of original data should be used to represent 1-bit protocol data
#define CODE_SIZE                      (CODE_LEVEL_RATIO + 1)
#define CODE_MASK                      ((0x01 << CODE_SIZE) - 1)

#ifndef WS28XX_SPI_MAX_SPEED
#define WS28XX_SPI_MAX_SPEED           (1*1000000000/(SINGLE_CODE_DURATION_NS/CODE_SIZE))
#endif

#define RESET_CODE_SIZE                (RESET_CODE_DURATION_NS*CODE_SIZE/SINGLE_CODE_DURATION_NS/8)

//Pulling the level low for a while before sending valid data can improve compatibility
#define FILL_ZERO_SIZE                 CODE_SIZE

#endif
