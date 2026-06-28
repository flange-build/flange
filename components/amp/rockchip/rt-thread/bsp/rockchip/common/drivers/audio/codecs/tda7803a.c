/**
  * Copyright (c) 2022 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    tda7803a.c
  * @author  Jun Zeng
  * @version v0.1
  * @date    2022.11.25
  * @brief   The rt-thread codec driver for Rockchip
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>

#ifdef RT_USING_CODEC_TDA7803

#include "hal_bsp.h"
#include "rk_audio.h"
#include "tda7803a.h"
#include "drv_codecs.h"

RT_WEAK struct codec_desc codec_tda7803[] = {0};

static inline struct tda7803_device *to_tda7803_device(struct audio_codec *codec)
{
    return HAL_CONTAINER_OF(codec, struct tda7803_device, codec);
}

static rt_err_t tda_wr_reg(struct rt_i2c_client *i2c_client, rt_uint8_t reg_addr, rt_uint8_t reg_data)
{
    struct rt_i2c_msg msgs[1];
    rt_uint8_t reg_info[2];
    int ret;

    reg_info[0] = reg_addr;
    reg_info[1] = reg_data;

    msgs[0].addr = i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf = &reg_info[0];
    msgs[0].len = 2;

    ret = rt_i2c_transfer(i2c_client->bus, msgs, 1);
    if (ret != 1)
    {
        rt_kprintf("[%s]:write tda7803 codec device register failed\n", __func__);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t tda_rd_reg(struct rt_i2c_client *i2c_client, rt_uint8_t reg_addr, rt_uint8_t *reg_data)
{
    struct rt_i2c_msg msgs[2];
    int ret;

    msgs[0].addr  = i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = &reg_addr;
    msgs[0].len   = 1;

    msgs[1].addr  = i2c_client->client_addr;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = reg_data;
    msgs[1].len   = 1;

    ret = rt_i2c_transfer(i2c_client->bus, msgs, 2);
    if (ret != 2)
    {
        rt_kprintf("[%s]:read tda7803 codec device register failed\n", __func__);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t tda_pa_ctl(bool on, struct GPIO_REG *pGPIO, ePINCTRL_GPIO_PINS pin)
{
    if (on)
    {
        HAL_GPIO_SetPinLevel(pGPIO, pin, GPIO_HIGH);
        rt_thread_mdelay(TDA7803_PA_CTL_DELAY_MS);
    }
    else
    {
        HAL_GPIO_SetPinLevel(pGPIO, pin, GPIO_LOW);
    }

    return RT_EOK;
}

static rt_err_t tda7803_init(struct audio_codec *codec, struct AUDIO_INIT_CONFIG *config)
{
    struct tda7803_private *private;

    private = (struct tda7803_private *)codec->private;
    if (!private)
    {
        rt_kprintf("[%s]:tda7803 codec device no exist\n", __func__);
        goto error;
    }
    tda_pa_ctl(1, private->pGPIO, private->pin);

    return RT_EOK;
error:
    return -RT_ERROR;
}

static rt_err_t tda7803_deinit(struct audio_codec *codec)
{
    struct tda7803_private *private;

    private = (struct tda7803_private *)codec->private;
    if (!private)
    {
        rt_kprintf("[%s]:tda7803 codec device no exist\n", __func__);
        goto error;
    }
    tda_pa_ctl(0, private->pGPIO, private->pin);

    return RT_EOK;
error:
    return -RT_ERROR;
}

static rt_err_t tda7803_config(struct audio_codec *codec, eAUDIO_streamType stream, struct AUDIO_PARAMS *params)
{
    struct tda7803_device *tda7803 = to_tda7803_device(codec);
    struct tda7803_private *private;
    rt_err_t ret = RT_EOK;
    uint32_t sampleRate;

    private = (struct tda7803_private *)codec->private;
    if (!private)
    {
        rt_kprintf("[%s]:tda7803 codec device no exist\n", __func__);
        goto error;
    }

    switch (params->sampleRate)
    {
    case 44100:
        sampleRate = SAMPLE_FREQUENCY_RANGE_44100HZ;
        break;
    case 48000:
        sampleRate = SAMPLE_FREQUENCY_RANGE_48000HZ;
        break;
    case 96000:
        sampleRate = SAMPLE_FREQUENCY_RANGE_96000HZ;
        break;
    case 192000:
        sampleRate = SAMPLE_FREQUENCY_RANGE_192000HZ;
        break;
    default:
        sampleRate = -0;
        ret = -RT_ERROR;
        break;
    }

    if (sampleRate)
    {
        ret |= tda_wr_reg(tda7803->i2c_client, TDA7803A_REGISTER3, sampleRate |
                          private->format);
    }

    if (ret != RT_EOK)
        rt_kprintf("[%s]:tda7803 codec device set samplerate failed\n", __func__);

    ret |= tda_wr_reg(tda7803->i2c_client, TDA7803A_REGISTER2, DISABLE_DIGITAL_MUTE_OFF |
                      CHANNEL_2_AND_4_UMUTE | CHANNEL_1_AND_3_UMUTE | MUTE_TIME_SETTING_1_45MS);
    if (ret != RT_EOK)
        rt_kprintf("[%s]:tda7803 codec device set umute failed\n", __func__);

error:
    return ret;
}

static rt_err_t tda7803_start(struct audio_codec *codec, eAUDIO_streamType stream)
{
    /* ECO Mode ---> Amplifier Mode */
    struct tda7803_device *tda7803 = to_tda7803_device(codec);
    rt_err_t ret = RT_EOK;

    ret = tda_wr_reg(tda7803->i2c_client, TDA7803A_REGISTER7, AMPLIEFIR_SWITCH_ON);
    if (ret != RT_EOK)
        rt_kprintf("[%s]:tda7803 codec device start failed\n", __func__);

    return ret;
}

static rt_err_t tda7803_stop(struct audio_codec *codec, eAUDIO_streamType stream)
{
    /* ECO Mode ---> Amplifier Mode */
    struct tda7803_device *tda7803 = to_tda7803_device(codec);
    rt_err_t ret = RT_EOK;

    ret = tda_wr_reg(tda7803->i2c_client, TDA7803A_REGISTER7, AMPLIEFIR_SWITCH_OFF);
    if (ret != RT_EOK)
        rt_kprintf("[%s]:tda7803 codec device stop failed\n", __func__);

    return ret;
}

static const struct audio_codec_ops tda7803_ops =
{
    .init = tda7803_init,
    .deinit = tda7803_deinit,
    .config = tda7803_config,
    .start = tda7803_start,
    .stop = tda7803_stop,
};

static HAL_Status spk_mute_prepare(struct GPIO_REG *pGPIO, ePINCTRL_GPIO_PINS pin)
{
    eGPIO_bankId bank;
    HAL_Status ret = HAL_OK;

    if (pGPIO == GPIO0)
        bank = GPIO_BANK0;
    else if (pGPIO == GPIO1)
        bank = GPIO_BANK2;
    else if (pGPIO == GPIO2)
        bank = GPIO_BANK2;
    else if (pGPIO == GPIO3)
        bank = GPIO_BANK3;
    else if (pGPIO == GPIO4)
        bank = GPIO_BANK4;
    else
        bank = -1;

    ret = HAL_PINCTRL_SetIOMUX(bank, (uint32_t)pin, PIN_CONFIG_MUX_FUNC0);
    if (ret != HAL_OK)
    {
        rt_kprintf("[%s]:pin ctrl set iomux failed\n", __func__);
        goto error;
    }

    ret = HAL_GPIO_SetPinDirection(pGPIO, pin, GPIO_OUT);
    if (ret != HAL_OK)
    {
        rt_kprintf("[%s]:gpio set pin direction failed\n", __func__);
        goto error;
    }

    ret = HAL_GPIO_SetPinLevel(pGPIO, pin, GPIO_LOW);
    if (ret != HAL_OK)
    {
        rt_kprintf("[%s]:gpio set pin level failed\n", __func__);
        goto error;
    }

    return HAL_OK;
error:
    return ret;
}

int rt_hw_codec_tda7803_init(void)
{
    struct tda7803_private *private;
    struct tda7803_device *tda7803;
    struct codec_desc *codec_dev;
    rt_err_t ret = RT_EOK;

    for (codec_dev = codec_tda7803; codec_dev->private != NULL; codec_dev++)
    {
        private = (struct tda7803_private *)codec_dev->private;

        ret = spk_mute_prepare(private->pGPIO, private->pin);

        tda7803 = rt_calloc(1, sizeof(struct tda7803_device));
        if (!tda7803)
        {
            rt_kprintf("[%s]:tda7803 device calloc failed\n", __func__);
            return -RT_ERROR;
        }
        tda7803->i2c_client = rt_calloc(1, sizeof(struct rt_i2c_client));
        if (!tda7803->i2c_client)
        {
            rt_kprintf("[%s]:tda7803 i2c client calloc failed\n", __func__);
            goto i2c_client_calloc_failed;
        }
        tda7803->i2c_client->bus = rt_i2c_bus_device_find(codec_dev->i2c_bus);
        if (!tda7803->i2c_client->bus)
        {
            rt_kprintf("[%s]:tda7803 i2c client bus find failed\n", __func__);
            goto i2c_client_bus_no_find;
        }

        tda7803->codec.ops = &tda7803_ops;
        tda7803->codec.private = private;
        tda7803->codec.id = (uint32_t)codec_dev;
        tda7803->i2c_client->client_addr = codec_dev->i2c_addr;

        ret = rk_audio_register_codec(&tda7803->codec);
        if (ret != RT_EOK)
        {
            rt_kprintf("[%s]:tda7803 codec device register failed\n", __func__);
            goto codec_register_failed;
        }
        rt_kprintf("[%s]:tda7803 codec device %d register failed\n", __func__, tda7803->codec.id);
        continue;

codec_register_failed:
i2c_client_bus_no_find:
        rt_free(tda7803->i2c_client);
i2c_client_calloc_failed:
        rt_free(tda7803);
        ret = -RT_ERROR;
    }

    return ret;
}

INIT_DEVICE_EXPORT(rt_hw_codec_tda7803_init);
#endif
