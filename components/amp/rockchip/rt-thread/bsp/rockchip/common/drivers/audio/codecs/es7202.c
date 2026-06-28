/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    es7202.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.27
  * @brief   The rt-thread codec driver for Rockchip
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>

#ifdef RT_USING_CODEC_ES7202

#include "rk_audio.h"
#include "drv_codecs.h"
#include "hal_bsp.h"
#include "es7202_reg.h"

/* 1: VDD 3.3V, 0: VDD 1.8V */
#define ES7202_VDD_VOLTAGE_3V3      1
#define ES7202_DEVICE_NUM_MAX       2
#define ES7202_CHANNELS_MAX         (ES7202_DEVICE_NUM_MAX * 2)

/* codec private data */
struct es7202_priv
{
    struct audio_codec codec;
    struct rt_i2c_client *i2c_client[ES7202_DEVICE_NUM_MAX];

    uint32_t device_num;
};

static inline struct es7202_priv *to_es7202_priv(struct audio_codec *codec)
{
    return HAL_CONTAINER_OF(codec, struct es7202_priv, codec);
}

static rt_err_t es7202_wr_reg(struct rt_i2c_client *i2c_client,
                              rt_uint8_t reg_addr, rt_uint8_t reg_data)
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
        rt_kprintf("ERR: %s: %x failed: (%d)\n", __func__, i2c_client->client_addr, ret);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t es7202_rd_reg(struct rt_i2c_client *i2c_client,
                              rt_uint8_t reg_addr, rt_uint8_t *reg_data)
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
        rt_kprintf("ERR: %s: %x failed: (%d)\n", __func__, i2c_client->client_addr, ret);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t es7202_update_bits(struct rt_i2c_client *client, rt_uint8_t reg,
                                   rt_uint8_t mask, rt_uint8_t value)
{
    rt_uint8_t val_old = 0, val_new = 0;
    rt_err_t ret;

    ret = es7202_rd_reg(client, reg, &val_old);
    if (ret != RT_EOK)
        goto err;

    val_new = (val_old & ~mask) | (value & mask);
    if (val_new != val_old)
        ret = es7202_wr_reg(client, reg, val_new);

err:
    return ret;
}

static rt_err_t es7202_init(struct audio_codec *codec, struct AUDIO_INIT_CONFIG *config)
{
    return RT_EOK;
}

static rt_err_t es7202_deinit(struct audio_codec *codec)
{
    return RT_EOK;
}

static rt_err_t es7202_config(struct audio_codec *codec, eAUDIO_streamType stream,
                              struct AUDIO_PARAMS *params)
{
    struct es7202_priv *es7202 = to_es7202_priv(codec);
    int ch = (params->channels > ES7202_CHANNELS_MAX) ?
             ES7202_CHANNELS_MAX : params->channels;

    es7202->device_num = RT_ALIGN(ch, 2) / 2;

    for (int i = 0; i < es7202->device_num; i++)
    {
        es7202_wr_reg(es7202->i2c_client[i], ES7202_SOFT_MODE_REG01, 0x01);
#if ES7202_VDD_VOLTAGE_3V3
        /* VDD 3.3V */
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_MISC1_REG1B, 0x50);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_PGA1_REG1D, 0x17);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_PGA2_REG1E, 0x17);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x7F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_BIAS_VMID_REG11, 0x2F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x0F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x00);
#else
        /* VDD 1.8V */
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_MISC1_REG1B, 0x40);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_PGA1_REG1D, 0x17);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_PGA2_REG1E, 0x17);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x7F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_BIAS_VMID_REG11, 0x2F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x3F);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_ANALOG_EN_REG10, 0x00);
#endif
        es7202_wr_reg(es7202->i2c_client[i], ES7202_MOD1_BIAS_REG14, 0x58);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_CLK_DIV_REG02, 0x01);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_T2_VMID_REG05, 0x01);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_MISC_CTL_REG08, 0x02);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_RESET_REG00, 0x01);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_CLK_EN_REG03, 0x03);
        es7202_wr_reg(es7202->i2c_client[i], ES7202_BIAS_VMID_REG11, 0x2E);
    }

    return RT_EOK;
}

static rt_err_t es7202_start(struct audio_codec *codec, eAUDIO_streamType stream)
{
    struct es7202_priv *es7202 = to_es7202_priv(codec);
    rt_err_t ret = RT_EOK;

    for (int i = 0; i < es7202->device_num; i++)
        ret |= es7202_update_bits(es7202->i2c_client[i],
                                  ES7202_PDM_INF_CTL_REG07, 0x03, 0x00);

    return ret;
}

static rt_err_t es7202_stop(struct audio_codec *codec, eAUDIO_streamType stream)
{
    struct es7202_priv *es7202 = to_es7202_priv(codec);
    rt_err_t ret = RT_EOK;

    for (int i = 0; i < es7202->device_num; i++)
        ret |= es7202_update_bits(es7202->i2c_client[i],
                                  ES7202_PDM_INF_CTL_REG07, 0x03, 0x03);

    return ret;
}

static const struct audio_codec_ops es7202_ops =
{
    .init = es7202_init,
    .deinit = es7202_deinit,
    .config = es7202_config,
    .start = es7202_start,
    .stop = es7202_stop,
};

int rt_hw_codec_es7202_init(void)
{
    struct codec_desc *codec_dev = (struct codec_desc *)&codec_es7202;
    struct es7202_priv *es7202;
    rt_err_t ret = RT_EOK;

    es7202 = rt_calloc(1, sizeof(struct es7202_priv));
    RT_ASSERT(es7202);

    for (int i = 0; i < ES7202_DEVICE_NUM_MAX; i++)
    {
        es7202->i2c_client[i] = rt_calloc(1, sizeof(struct rt_i2c_client));
        RT_ASSERT(es7202->i2c_client[i]);
        es7202->i2c_client[i]->bus = rt_i2c_bus_device_find(codec_dev->i2c_bus);
        RT_ASSERT(es7202->i2c_client[i]->bus);
        es7202->i2c_client[i]->client_addr = codec_dev->i2c_addr + i;
    }

    es7202->codec.ops = &es7202_ops;
    es7202->codec.id = (uint32_t)codec_dev;
    es7202->device_num = ES7202_DEVICE_NUM_MAX;

    ret |= rk_audio_register_codec(&es7202->codec);
    if (ret != RT_EOK)
    {
        rt_kprintf("ERR: %s, something wrong: %d\n", __func__, ret);
        goto err;
    }

    rt_kprintf("TAG: register codec es7202 success\n");
    return RT_EOK;

err:
    rt_kprintf("ERR: %s, register codec es7202 failed: %d\n", __func__, ret);
    for (int i = 0; i < ES7202_DEVICE_NUM_MAX; i++)
    {
        if (es7202->i2c_client[i])
            rt_free(es7202->i2c_client[i]);
    }
    if (es7202)
        rt_free(es7202);
    return ret;
}

INIT_DEVICE_EXPORT(rt_hw_codec_es7202_init);

#endif
