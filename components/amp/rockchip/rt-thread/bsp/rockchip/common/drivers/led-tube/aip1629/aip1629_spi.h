/**
  * Copyright (c) 2024 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef __AIP1629_SPI_H__
#define __AIP1629_SPI_H__

#ifdef RT_USING_AIP1629
#include <rtdevice.h>
#include <rtthread.h>

#ifndef RT_AIP1629_SPI_DEVICE
#define RT_AIP1629_SPI_DEVICE      "spi2_0"
#endif

struct aip1629_device_t
{
    struct rt_spi_device *spi_device;
    uint32_t mode;        //master or slave mode | LSB or MSB | spi mode (0-3)
    uint32_t data_width;  //8 or 16bit
    uint32_t max_speed;   //max speed
    uint32_t segments;    //the segments of a grid, such as a grid has 7 segments or 14 segments
    uint32_t grids;       //grids on the visual front display, such as 5 grids or more
};

//LED Segment Display contains several grids, each grid contains some Segments LED which named A,B,C,...
#define LSD_SEG_A    (1 << 5)
#define LSD_SEG_B    (1 << 6)
#define LSD_SEG_C    (1 << 7)
#define LSD_SEG_D    (1 << 8)
#define LSD_SEG_E    (1 << 9)
#define LSD_SEG_F    (1 << 10)
#define LSD_SEG_G    (1 << 11)
#define LSD_SEG_H    (1 << 12)
#define LSD_SEG_I    (1 << 13)
#define LSD_SEG_J    (1 << 4)
#define LSD_SEG_K    (1 << 3)
#define LSD_SEG_L    (1 << 2)
#define LSD_SEG_M    (1 << 1)
#define LSD_SEG_N    (1 << 0)

/* display 0-9 digit number with segments combination */
#define DIGIT_0     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define DIGIT_1     (LSD_SEG_B | LSD_SEG_C)
#define DIGIT_2     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_D | LSD_SEG_E | LSD_SEG_G | LSD_SEG_H)
#define DIGIT_3     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_G | LSD_SEG_H)
#define DIGIT_4     (LSD_SEG_B | LSD_SEG_C | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H )
#define DIGIT_5     (LSD_SEG_A | LSD_SEG_C | LSD_SEG_D | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define DIGIT_6     (LSD_SEG_A | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define DIGIT_7     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C)
#define DIGIT_8     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define DIGIT_9     (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)

/* display A-Z alphabet with segments combination*/
#define  LETTER_A   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_B   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_H | LSD_SEG_J | LSD_SEG_M)
#define  LETTER_C   (LSD_SEG_A | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_D   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_J | LSD_SEG_M)
#define  LETTER_E   (LSD_SEG_A | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_F   (LSD_SEG_A | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_G   (LSD_SEG_A | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_H   (LSD_SEG_B | LSD_SEG_C | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_I   (LSD_SEG_A | LSD_SEG_D | LSD_SEG_J | LSD_SEG_M)
#define  LETTER_J   (LSD_SEG_A | LSD_SEG_J | LSD_SEG_M)
#define  LETTER_K   (LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_K | LSD_SEG_N)
#define  LETTER_L   (LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_M   (LSD_SEG_B | LSD_SEG_C | LSD_SEG_E | LSD_SEG_F | LSD_SEG_I | LSD_SEG_K)
#define  LETTER_N   (LSD_SEG_B | LSD_SEG_C | LSD_SEG_E | LSD_SEG_F | LSD_SEG_I | LSD_SEG_N)
#define  LETTER_O   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_P   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_Q   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_C | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_R   (LSD_SEG_A | LSD_SEG_B | LSD_SEG_E | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H | LSD_SEG_N)
#define  LETTER_S   (LSD_SEG_A | LSD_SEG_C | LSD_SEG_D | LSD_SEG_F | LSD_SEG_G | LSD_SEG_H)
#define  LETTER_T   (LSD_SEG_A | LSD_SEG_J | LSD_SEG_M)
#define  LETTER_U   (LSD_SEG_B | LSD_SEG_C | LSD_SEG_D | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_V   (LSD_SEG_K | LSD_SEG_L | LSD_SEG_E | LSD_SEG_F)
#define  LETTER_W   (LSD_SEG_B | LSD_SEG_C | LSD_SEG_E | LSD_SEG_F | LSD_SEG_L | LSD_SEG_N)
#define  LETTER_X   (LSD_SEG_I | LSD_SEG_K | LSD_SEG_L | LSD_SEG_N)
#define  LETTER_Y   (LSD_SEG_I | LSD_SEG_K | LSD_SEG_M)
#define  LETTER_Z   (LSD_SEG_A | LSD_SEG_D | LSD_SEG_K | LSD_SEG_L)

#define LETTER_SPACE       (0)
#define LETTER_UNDERLINE   (LSD_SEG_D)
#define LETTER_ADD         (LSD_SEG_G | LSD_SEG_H | LSD_SEG_J | LSD_SEG_M)
#define LETTER_MINUS       (LSD_SEG_G | LSD_SEG_H)

int rt_hw_aip1629_display_init();
int rt_hw_aip1629_display_info(const char *dispinfo);
int rt_hw_aip1629_display_dimmer(const char *diminfo);

#endif
#endif
