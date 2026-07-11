/**
  * Copyright (c) 2024 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rtthread.h>
#include <rtdevice.h>

#ifdef RT_USING_AIP1629
#include "aip1629_spi.h"
#include "board.h"
#include "hal_base.h"
#include "iomux_base.h"

struct aip1629_device_t led_device_ctx;

const static uint16_t digit_number[10] =
{
    DIGIT_0, DIGIT_1, DIGIT_2, DIGIT_3, DIGIT_4, DIGIT_5, DIGIT_6, DIGIT_7, DIGIT_8, DIGIT_9,
};

const static uint16_t alpha_letter[26] =
{
    LETTER_A, LETTER_B, LETTER_C, LETTER_D, LETTER_E, LETTER_F, LETTER_G, LETTER_H,
    LETTER_I, LETTER_J, LETTER_K, LETTER_L, LETTER_M, LETTER_N, LETTER_O, LETTER_P,
    LETTER_Q, LETTER_R, LETTER_S, LETTER_T, LETTER_U, LETTER_V, LETTER_W, LETTER_X,
    LETTER_Y, LETTER_Z,
};

static int rt_hw_aip1692_write_data(uint8_t *dispdata, uint32_t size)
{
    uint8_t cmd_buf;
    uint8_t scankey_buf[4];
    uint8_t cleardata[14] = {0};
    struct rt_spi_device *spi_device = led_device_ctx.spi_device;

    if (spi_device == NULL)
    {
        rt_kprintf("error：not found the spi device\n");
        return -1;
    }

    cmd_buf = 0xc0;   //clear display
    rt_spi_send_then_send(spi_device, &cmd_buf, 1, cleardata, 14);

    cmd_buf = 0x40;   //address auto increase mode
    rt_spi_send(spi_device, &cmd_buf, 1);

    cmd_buf = 0xc0;   //setup the start address
    rt_spi_send_then_send(spi_device, &cmd_buf, 1, dispdata, size);

    cmd_buf = 0x42;   //read scankey, this step should not be ignored
    rt_spi_send_then_recv(spi_device, &cmd_buf, 1, scankey_buf, 4);

    return 0;
}

int rt_hw_aip1629_display_dimmer(const char *diminfo)
{
    uint8_t cmd_buf;
    struct rt_spi_device *spi_device = led_device_ctx.spi_device;

    if (spi_device == NULL)
    {
        rt_kprintf("error：not found the spi device\n");
        return -1;
    }

    if (strstr(diminfo, "DIM 0") != NULL)
    {
        cmd_buf = 0x80;
    }
    else if (strstr(diminfo, "DIM 1") != NULL)
    {
        cmd_buf = 0x88;
    }
    else if (strstr(diminfo, "DIM 2") != NULL)
    {
        cmd_buf = 0x8a;
    }
    else if (strstr(diminfo, "DIM 3") != NULL)
    {
        cmd_buf = 0x8c;
    }
    else
    {
        cmd_buf = 0x8f;
    }
    rt_spi_send(spi_device, &cmd_buf, 1);
    return 0;
}

int rt_hw_aip1629_display_info(const char *dispinfo)
{
    uint16_t seg_bits = 0;
    uint8_t dispdata[16];
    uint32_t i_addr = 0;
    char ch = *dispinfo;

    while (ch != '\0')
    {
        if (ch >= '0' && ch <= '9')
            seg_bits = digit_number[ch - '0'];
        else if (ch >= 'a' && ch <= 'z')
            seg_bits = alpha_letter[ch - 'a'];
        else if (ch >= 'A' && ch <= 'Z')
            seg_bits = alpha_letter[ch - 'A'];
        else if (ch == ' ')
            seg_bits = LETTER_SPACE;
        else if (ch == '_')
            seg_bits = LETTER_UNDERLINE;
        else if (ch == '-')
            seg_bits = LETTER_MINUS;
        else if (ch == '+')
            seg_bits = LETTER_ADD;
        else
            seg_bits = LETTER_SPACE;

        dispdata[i_addr] = seg_bits & 0xff;
        dispdata[i_addr + 1] = (seg_bits >> 8) & 0xff;
        i_addr += 2;
        if (i_addr > led_device_ctx.grids * 2)
        {
            break;
        }
        ch = *(++dispinfo);
    }
    rt_hw_aip1692_write_data(dispdata, i_addr);
    return 0;
}

int rt_hw_aip1629_display_init()
{
    struct rt_spi_configuration cfg;

    led_device_ctx.spi_device = (struct rt_spi_device *)rt_device_find(RT_AIP1629_SPI_DEVICE);
    if (led_device_ctx.spi_device == NULL)
    {
        rt_kprintf("error：not found the spi device\n");
        return -1;
    }

    led_device_ctx.mode = RT_SPI_MASTER | RT_SPI_LSB | RT_SPI_MODE_3;
    led_device_ctx.data_width = 8;
    led_device_ctx.max_speed = 1 * 1000 * 1000;
    led_device_ctx.segments = 14;
    led_device_ctx.grids = 5;

    cfg.data_width = led_device_ctx.data_width;
    cfg.mode = led_device_ctx.mode;
    cfg.max_hz = led_device_ctx.max_speed;
    rt_spi_configure(led_device_ctx.spi_device, &cfg);
    rt_kprintf("configure %s master mode3 LSB\n", RT_AIP1629_SPI_DEVICE);

    rt_hw_aip1629_display_info("HELLO");
    return 0;
}

#endif
