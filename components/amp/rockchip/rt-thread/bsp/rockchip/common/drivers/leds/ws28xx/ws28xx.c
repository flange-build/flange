/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rtthread.h>
#include <rtdevice.h>

#ifdef RT_USING_WS28XX
#include "hal_base.h"
#include "board.h"
#include "ws28xx.h"

static rt_int32_t ws28xx_send_protocol_data(struct rt_spi_device *spi, const void *txbuf, size_t n)
{

    return rt_spi_send(spi, txbuf, n);
}

static rt_int32_t ws28xx_get_protocol_data(rt_uint8_t *inbuf, rt_uint8_t *outbuf, rt_int32_t size)
{
    rt_uint32_t i, j;
    rt_uint8_t char_temp, cur_bit;
    rt_uint32_t index = FILL_ZERO_SIZE;
    rt_uint32_t byte_index = 0;
    rt_uint8_t bit_position = 0;

    rt_uint8_t temp[CODE_SIZE];

    memset(outbuf, 0, FILL_ZERO_SIZE);

    for (i = 0; i < size; i++)
    {
        char_temp  = inbuf[i];
        memset(temp, 0x00, sizeof(temp));
        for (j = 0; j < 8; j++)
        {
            cur_bit = (char_temp & 0x80) >> 7;
            char_temp = char_temp << 1;

            byte_index = (j * CODE_SIZE) / 8;
            bit_position = (j * CODE_SIZE) % 8;

            if (cur_bit == 1)
            {
                temp[byte_index] |= CODE1 << bit_position;
                if (bit_position + CODE_SIZE > 8)
                {
                    temp[byte_index + 1 ] |= CODE1 >> (8 - bit_position);
                }
            }
            else
            {
                temp[byte_index] |= CODE0 << bit_position;
                if (bit_position + CODE_SIZE > 8)
                {
                    temp[byte_index + 1 ] |= CODE0 >> (8 - bit_position);
                }

            }
        }

        for (j = 0; j <  CODE_SIZE; j++)
        {
            outbuf[i * CODE_SIZE + j + FILL_ZERO_SIZE] = temp[j];
            index ++;
        }
    }

    //reset data least 80us
    for (j = 0; j < RESET_CODE_SIZE; j++)
    {
        outbuf[index++] = 0;
    }

    return index;
}

static rt_err_t ws28xx_control(rt_device_t dev, int cmd, void *args)
{
    rt_int32_t ret = RT_EOK;

    struct ws28xx_device *ws28xx = (struct ws28xx_device *)dev->user_data;

    switch (cmd)
    {
    case WS28XX_GET_LED_NUM:
        *(rt_uint32_t *)args = ws28xx->leds_num;
        break;

    case WS28XX_GET_RGB_DATA_BITS:
        *(rt_uint32_t *)args = ws28xx->rgb_data_bits;
        break;

    //TODO:gain config
    default:
        break;
    }
    return ret;
}

static rt_size_t ws28xx_write(rt_device_t dev, rt_off_t pos,
                              const void *buffer, rt_size_t size)
{
    struct ws28xx_device *ws28xx = (struct ws28xx_device *)dev->user_data;
    rt_uint8_t *protocol_data = NULL;
    rt_int32_t cnt;

    if (!ws28xx->spi)
    {
        rt_kprintf("%s: spi data is NULL!\n", __func__);
        return -RT_ERROR;
    }
    protocol_data = ws28xx->protocol_data;
    if (!protocol_data)
    {
        rt_kprintf("%s: protocol_data buf NULL!\n", __func__);
        return -RT_ERROR;
    }
    if (size > ws28xx->raw_data_len)
    {
        rt_kprintf("%s: write data len larger than raw_data_len!\n", __func__);
        return -RT_ERROR;
    }

    cnt = ws28xx_get_protocol_data((rt_uint8_t *)buffer, protocol_data, size);
    //for (i = 0; i < cnt; i++)
    //{
    //    rt_kprintf("[ %d ] = 0x%x\n", i, protocol_data[i]);
    //}

    ws28xx_send_protocol_data(ws28xx->spi, protocol_data, cnt);

    return size;
}

#ifdef RT_USING_DEVICE_OPS
const static struct rt_device_ops spi_simulate_led_ops =
{
    .write = ws28xx_write,
    .control = ws28xx_control,
};
#endif

rt_err_t ws28xx_register(struct ws28xx_device *device,
                         const char *name, const void *user_data)
{
    rt_err_t result = RT_EOK;

    device->parent.type = RT_Device_Class_Miscellaneous;
    device->parent.rx_indicate = RT_NULL;
    device->parent.tx_complete = RT_NULL;

#ifdef RT_USING_DEVICE_OPS
    device->parent.ops         = &spi_simulate_led_ops;
#else
    device->parent.init        = RT_NULL;
    device->parent.open        = RT_NULL;
    device->parent.close       = RT_NULL;
    device->parent.read        = RT_NULL;
    device->parent.write       = ws28xx_write;
    device->parent.control     = ws28xx_control;
#endif
    device->parent.user_data = (void *)user_data;

    result = rt_device_register(&device->parent, name, RT_DEVICE_FLAG_RDWR);

    return result;

}

static int rt_hw_ws28xx_init(void)
{
    rt_int32_t ret;
    struct rt_spi_configuration cfg;
    rt_int32_t protocol_data_len, raw_data_len, rgb_data_bits;
    static struct ws28xx_device *ws28xx = RT_NULL;

    ws28xx = (struct ws28xx_device *)rt_calloc(1, sizeof(struct ws28xx_device));
    if (!ws28xx)
    {
        ret = -RT_ERROR;
        goto out_1;
    }

    /* before here, IOMUX must be initialized in board_xxxx.c*/
    ws28xx->spi = (struct rt_spi_device *)rt_device_find(WS28XX_SPI_DEVICE);
    if (!ws28xx->spi)
    {
        ret = -RT_ERROR;
        goto out_2;
    }

    cfg.data_width = 8;
    cfg.mode = WS28XX_SPI_MODE;
    cfg.max_hz = WS28XX_SPI_MAX_SPEED;
    ret = rt_spi_configure(ws28xx->spi, &cfg);
    if (ret != RT_EOK)
    {
        rt_kprintf("%s: rt_spi_configure failed\n", __func__);
        goto out_2;
    }

    rgb_data_bits = WS28XX_DATA_BITS;

    if (rgb_data_bits != 16 && rgb_data_bits != 24 && rgb_data_bits != 48)
    {
        rt_kprintf("%s: rgb_data_bits invalid\n", __func__);
        ret = -RT_ERROR;
        goto out_2;
    }

    raw_data_len = WS28XX_RGB_NUM * rgb_data_bits / 8;
    protocol_data_len = raw_data_len * CODE_SIZE + RESET_CODE_SIZE + FILL_ZERO_SIZE;

    ws28xx->protocol_data = rt_calloc(1, protocol_data_len);
    if (!ws28xx->protocol_data)
    {
        rt_kprintf("%s protocol_data buff alloc failed\n", __func__);
        ret = -RT_ERROR;
        goto out_2;
    }

    ws28xx->leds_num = WS28XX_RGB_NUM;
    ws28xx->raw_data_len = raw_data_len;
    ws28xx->rgb_data_bits = rgb_data_bits;

    ret = ws28xx_register(ws28xx, WS28XX_DEVICE_NAME, (void *)ws28xx);

    if (ret)
    {
        goto out_3;
    }
    rt_kprintf("%s spi max speed:%d rgb num:%d, each rgb data cost %d\n",
               __func__, WS28XX_SPI_MAX_SPEED, WS28XX_RGB_NUM, ws28xx->rgb_data_bits);

    return ret;

out_3:
    rt_free(ws28xx->protocol_data);
out_2:
    rt_free(ws28xx);
out_1:
    return ret;
}

INIT_DEVICE_EXPORT(rt_hw_ws28xx_init);

#if defined(RT_USING_FINSH) && defined(WS28XX_DEBUG)
void ws28xx(rt_int32_t argc, char **argv)
{
    rt_err_t ret = RT_EOK;
    static rt_device_t ws28xx = RT_NULL;
    rt_uint8_t test[WS28XX_RGB_NUM * 3];
    rt_uint8_t br;

    ws28xx = rt_device_find(WS28XX_DEVICE_NAME);

    ret = rt_device_open(ws28xx, RT_DEVICE_OFLAG_RDWR | RT_DEVICE_FLAG_INT_RX);
    if (ret != RT_EOK)
    {
        rt_kprintf("Failed to open device: %s\n", WS28XX_DEVICE_NAME);
        return;
    }

    if (argc == 3)
    {
        if (!strcmp(argv[1], "test"))
        {
            br = strtol(argv[2], RT_NULL, 10);
            memset(test, br, sizeof(test));
            if (!rt_device_write(ws28xx, 0, test, sizeof(test)))
            {
                rt_kprintf("%s write err\n", WS28XX_DEVICE_NAME);
            }
        }
        else
        {
            rt_kprintf("Usage: \n");
            rt_kprintf("ws28xx test <val>\n");
        }
    }
    else
    {
        rt_kprintf("Usage: \n");
        rt_kprintf("ws28xx test <val>\n");
    }

    rt_device_close(ws28xx);
}

MSH_CMD_EXPORT(ws28xx, ws28xx test);
#endif
#endif
