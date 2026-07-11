/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef __LEDS_AW210XX_H__
#define __LEDS_AW210XX_H__

//#define AWINIC_DEBUG
#ifdef  AWINIC_DEBUG
#define AW_LOG(format, arg...)  rt_kprintf(format, ##arg)
#else
#define AW_LOG(format, arg...)  do {} while (0)
#endif

#define AW210XX_DEVICE_NAME      "aw210xx"
#define AW210XX_I2C_ADDR          (0x30)
#define AW210XX_I2C_DEV          "i2c2"

struct aw_br
{
    rt_uint8_t ch;
    rt_uint8_t br;
};

//using in rgb mode
struct aw_color
{
    rt_uint8_t r;
    rt_uint8_t g;
    rt_uint8_t b;
};

struct aw_rgb_color
{
    struct aw_color rgb;
    rt_uint16_t ch;
};

struct aw_auto_breath
{
    /*
     * ramp rise time
     * T0           Time
     * 0000         0s
     * 0001         0.13s
     * 0010         0.26s
     * 0011         0.38s
     * 0100         0.51s
     * 0101         0.77s
     * 0110         1.04s
     * 0111         1.6S
     * 1000         2.1s
     * 1001         2.6s
     * 1010         3.1s
     * 1011         4.2s
     * 1100         5.2s
     * 1101         6.2s
     * 1110         7.3s
     * 1111         8.3s
     */
    rt_uint8_t t0;
    /*
     * hold on time
     * T0           Time
     * 0000         0.04s
     * 0001         0.13s
     * 0010         0.26s
     * 0011         0.38s
     * 0100         0.51s
     * 0101         0.77s
     * 0110         1.04s
     * 0111         1.6S
     * 1000         2.1s
     * 1001         2.6s
     * 1010         3.1s
     * 1011         4.2s
     * 1100         5.2s
     * 1101         6.2s
     * 1110         7.3s
     * 1111         8.3s
     */
    rt_uint8_t t1;
    /*
     * ramp fall time
     * T0           Time
     * 0000         0s
     * 0001         0.13s
     * 0010         0.26s
     * 0011         0.38s
     * 0100         0.51s
     * 0101         0.77s
     * 0110         1.04s
     * 0111         1.6S
     * 1000         2.1s
     * 1001         2.6s
     * 1010         3.1s
     * 1011         4.2s
     * 1100         5.2s
     * 1101         6.2s
     * 1110         7.3s
     * 1111         8.3s
     */
    rt_uint8_t t2;
    /*
     * hold off time
     * T0           Time
     * 0000         0.04s
     * 0001         0.13s
     * 0010         0.26s
     * 0011         0.38s
     * 0100         0.51s
     * 0101         0.77s
     * 0110         1.04s
     * 0111         1.6S
     * 1000         2.1s
     * 1001         2.6s
     * 1010         3.1s
     * 1011         4.2s
     * 1100         5.2s
     * 1101         6.2s
     * 1110         7.3s
     * 1111         8.3s
     */
    rt_uint8_t t3;

    /*
     * b00:start from RISE state
     * b01:start from ON state
     * b10:start from FALL state
     * b11:start from OFF state
     */
    rt_uint8_t start_state;
    /*
     * b00:stop at OFF state
     * otrer stop at ON state
     */
    rt_uint8_t stop_state;
    //12-bits repeat times
    rt_uint16_t repeat_times;
};

struct aw_manual_breath
{
    rt_uint8_t sw;
    rt_uint8_t rampe;
};

struct aw_breath
{
    rt_uint8_t breath_enable;
    rt_uint8_t br_min;
    rt_uint8_t br_max;
    rt_uint8_t group;

    struct aw_color color;
    struct aw_auto_breath auto_breath;
    struct aw_manual_breath manual_breath;

    rt_uint16_t auto_mode;
};

struct aw210xxx_chipdef
{
    rt_uint8_t  channels;
    rt_uint8_t  br_base_reg;
    rt_uint8_t  col_base_reg;
};

typedef struct
{
    struct rt_device dev;
    struct rt_i2c_client *i2c_client;
    const struct aw210xxx_chipdef *cdef;

    rt_uint8_t  rgb_mode;
    rt_uint8_t  gro_mode;
    rt_uint8_t  chip_en;
    rt_uint8_t  uvlo;
    rt_uint8_t  apse;

} aw210xx_device_t;

typedef enum
{
    RT_AW210XX_BR_SET,
    RT_AW210XX_RGB_BR_SET,
    RT_AW210XX_RGB_MODE_SET,
    RT_AW210XX_PWR_MODE_SET,
    RT_AW210XX_GRO_MODE_EN,
    RT_AW210XX_GRO_MODE_SET,
    RT_AW210XX_GLO_CUR_SET,
    RT_AW210XX_GLO_COL_SET,
    RT_AW210XX_COL_SET,
    RT_AW210XX_RGB_COL_SET,
    RT_AW210XX_BREATH_SET,
} aw210xx_ctrl_t;

#define AW210XX_PIN_HIGH                GPIO_HIGH
#define AW210XX_PIN_LOW                 GPIO_LOW

#define AW210XX_CHIPID                  0x18
#define AW210XX_DEFAULT_GOL_CUR         0xff

#define AW210XX_REG_GCR                 0x00
#define AW210XX_REG_BR0                 0x01
#define AW210XX_REG_BR1                 0x02
#define AW210XX_REG_BR2                 0x03
#define AW210XX_REG_BR3                 0x04
#define AW210XX_REG_BR4                 0x05
#define AW210XX_REG_BR5                 0x06
#define AW210XX_REG_BR6                 0x07
#define AW210XX_REG_BR7                 0x08
#define AW210XX_REG_BR8                 0x09
#define AW210XX_REG_BR9                 0x0A
#define AW210XX_REG_BR10                0x0B
#define AW210XX_REG_BR11                0x0C
#define AW210XX_REG_BR12                0x0D
#define AW210XX_REG_BR13                0x0E
#define AW210XX_REG_BR14                0x0F
#define AW210XX_REG_BR15                0x10
#define AW210XX_REG_BR16                0x11
#define AW210XX_REG_BR17                0x12
#define AW210XX_REG_BR18                0x13
#define AW210XX_REG_BR19                0x14
#define AW210XX_REG_BR20                0x15
#define AW210XX_REG_BR21                0x16
#define AW210XX_REG_BR22                0x17
#define AW210XX_REG_BR23                0x18
#define AW210XX_REG_BR24                0x19
#define AW210XX_REG_BR25                0x1A
#define AW210XX_REG_BR26                0x1B
#define AW210XX_REG_BR27                0x1C
#define AW210XX_REG_BR28                0x1D
#define AW210XX_REG_BR29                0x1E
#define AW210XX_REG_BR30                0x1F
#define AW210XX_REG_BR31                0x20
#define AW210XX_REG_BR32                0x21
#define AW210XX_REG_BR33                0x22
#define AW210XX_REG_BR34                0x23
#define AW210XX_REG_BR35                0x24
#define AW210XX_REG_UPDATE              0x49
#define AW210XX_REG_COL0                0x4a
#define AW210XX_REG_COL1                0x4b
#define AW210XX_REG_COL2                0x4c
#define AW210XX_REG_COL3                0x4d
#define AW210XX_REG_COL4                0x4e
#define AW210XX_REG_COL5                0x4f
#define AW210XX_REG_COL6                0x50
#define AW210XX_REG_COL7                0x51
#define AW210XX_REG_COL8                0x52
#define AW210XX_REG_COL9                0x53
#define AW210XX_REG_COL10               0x54
#define AW210XX_REG_COL11               0x55
#define AW210XX_REG_COL12               0x56
#define AW210XX_REG_COL13               0x57
#define AW210XX_REG_COL14               0x58
#define AW210XX_REG_COL15               0x59
#define AW210XX_REG_COL16               0x5a
#define AW210XX_REG_COL17               0x5b
#define AW210XX_REG_COL18               0x5c
#define AW210XX_REG_COL19               0x5d
#define AW210XX_REG_COL20               0x5e
#define AW210XX_REG_COL21               0x5f
#define AW210XX_REG_COL22               0x60
#define AW210XX_REG_COL23               0x61
#define AW210XX_REG_COL24               0x62
#define AW210XX_REG_COL25               0x63
#define AW210XX_REG_COL26               0x64
#define AW210XX_REG_COL27               0x65
#define AW210XX_REG_COL28               0x66
#define AW210XX_REG_COL29               0x67
#define AW210XX_REG_COL30               0x68
#define AW210XX_REG_COL31               0x69
#define AW210XX_REG_COL32               0x6a
#define AW210XX_REG_COL33               0x6b
#define AW210XX_REG_COL34               0x6c
#define AW210XX_REG_COL35               0x6d
#define AW210XX_REG_GCCR                0x6e
#define AW210XX_REG_PHCR                0x70
#define AW210XX_REG_OSDCR               0x71
#define AW210XX_REG_OSST0               0x72
#define AW210XX_REG_OSST1               0x73
#define AW210XX_REG_OSST2               0x74
#define AW210XX_REG_0SST3               0x75
#define AW210XX_REG_OSST4               0x76
#define AW210XX_REG_OTCR                0x77
#define AW210XX_REG_SSCR                0x78
#define AW210XX_REG_UVCR                0x79
#define AW210XX_REG_GCR2                0x7A
#define AW210XX_REG_GCR4                0x7C
#define AW210XX_REG_VER                 0x7E
#define AW210XX_REG_RESET               0x7F
#define AW210XX_REG_WBR                 0x90
#define AW210XX_REG_WBG                 0x91
#define AW210XX_REG_WBB                 0x92
#define AW210XX_REG_PATCFG              0xA0
#define AW210XX_REG_PATGO               0xA1
#define AW210XX_REG_PATCT0              0xA2
#define AW210XX_REG_PATCT1              0xA3
#define AW210XX_REG_PATCT2              0xA4
#define AW210XX_REG_PATCT3              0xA5
#define AW210XX_REG_FADEH               0xA6
#define AW210XX_REG_FADEL               0xA7
#define AW210XX_REG_GCOLR               0xA8
#define AW210XX_REG_GCOLG               0xA9
#define AW210XX_REG_GCOLB               0xAA
#define AW210XX_REG_GCFG0               0xAB
#define AW210XX_REG_GCFG1               0xAC

#define AW210XX_BIT_APSE_MASK               (~(1 << 7))
#define AW210XX_BIT_APSE_ENABLE             (1 << 7)
#define AW210XX_BIT_APSE_DISENA             (0 << 7)
#define AW210XX_BIT_CHIPEN_MASK             (~(1 << 0))
#define AW210XX_BIT_CHIPEN_ENABLE           (1 << 0)
#define AW210XX_BIT_CHIPEN_DISENA           (0 << 0)
#define AW210XX_BIT_UVPD_MASK               (~(1 << 1))
#define AW210XX_BIT_UVPD_ENABLE             (0 << 1)
#define AW210XX_BIT_UVPD_DISENA             (1 << 1)
#define AW210XX_BIT_UVDIS_MASK              (~(1 << 0))
#define AW210XX_BIT_UVDIS_ENABLE            (0 << 0)
#define AW210XX_BIT_UVDIS_DISENA            (1 << 0)
#define AW210XX_BIT_ABME_MASK               (~(1 << 0))
#define AW210XX_BIT_ABME_ENABLE             (1 << 0)
#define AW210XX_BIT_ABME_DISENA             (0 << 0)
#define AW210XX_BIT_GSLDIS_MASK             (~(1 << 6))
#define AW210XX_BIT_GSLDIS_ENABLE           (0 << 6)
#define AW210XX_BIT_GSLDIS_DISENA           (1 << 6)
#define AW210XX_BIT_RGBMD_MASK              (~(1 << 0))
#define AW210XX_BIT_RGBMD_ENABLE            (1 << 0)
#define AW210XX_BIT_RGBMD_DISENA            (0 << 0)
#define AW210XX_BIT_CLKFRQ_MASK             (~(7 << 4))
#define AW210XX_BIT_CLKFRQ_16MHz            (0 << 4)
#define AW210XX_BIT_CLKFRQ_8MHz             (1 << 4)
#define AW210XX_BIT_CLKFRQ_1MHz             (2 << 4)
#define AW210XX_BIT_CLKFRQ_512kHz           (3 << 4)
#define AW210XX_BIT_CLKFRQ_256kHz           (4 << 4)
#define AW210XX_BIT_CLKFRQ_125kHz           (5 << 4)
#define AW210XX_BIT_CLKFRQ_62_5kHz          (6 << 4)
#define AW210XX_BIT_CLKFRQ_31_25kHz         (7 << 4)

#define AW210XX_BIT_GROP_MASK               (~(1 << 4))
#define AW210XX_BIT_GROP_ENABLE             (0 << 4)
#define AW210XX_BIT_GROP_DISENA             (1 << 4)

#define AW210XX_BIT_PWMRES_MASK             (~(3 << 1))
#define AW210XX_BIT_PWMRES_8BIT             (0 << 1)
#define AW210XX_BIT_PWMRES_9BIT             (1 << 1)
#define AW210XX_BIT_PWMRES_12BIT            (2 << 1)
#define AW210XX_BIT_PWMRES_9_AND_3_BIT          (3 << 1)

#define AW210XX_DCPWM_SET               (7 << 5)
#define AW210XX_DCPWM_CLEAN             (0x00)
#define AW210XX_DCPWM_SET_MASK              ~(7 << 5)
#define AW210XX_OPEN_THRESHOLD_SET          (1 << 3)
#define AW210XX_OPEN_THRESHOLD_SET_MASK         ~(1 << 3)
#define AW210XX_SHORT_THRESHOLD_SET         (1 << 2)
#define AW210XX_SHORT_THRESHOLD_SET_MASK        ~(1 << 2)

//You need to add relevant gpio configuration in
//board.h according to the actual hardware connection
#ifndef AW210XX_EN_GPIO_BANK
#define AW210XX_EN_GPIO_BANK         GPIO_BANK3
#endif
#ifndef AW210XX_EN_GPIO_GRP
#define AW210XX_EN_GPIO_GRP          GPIO3
#endif
#ifndef AW210XX_EN_GPIO
#define AW210XX_EN_GPIO              GPIO_PIN_A2
#endif
#ifndef AW210XX_EN_PIN
#define AW210XX_EN_PIN               BANK_PIN(GPIO_BANK3, 2)
#endif

#endif
