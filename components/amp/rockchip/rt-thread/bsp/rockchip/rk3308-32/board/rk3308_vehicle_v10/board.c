/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2022-06-09     Cliff Chen   first implementation
 */

#include <rthw.h>
#include <rtthread.h>

#include "board.h"
#include "rk_audio.h"
#include "drv_codecs.h"

#if defined(RT_USING_CODEC_TDA7803) && defined(RT_USING_MULTI_CODECS)
const struct tda7803_private priv_dev0 =
{
    .pGPIO = GPIO0,
    .pin = GPIO_PIN_A6,
    .format = DIGITAL_INPUT_FORMAT_TDM_8CH_DEVICE_1,
};

const struct tda7803_private priv_dev1 =
{
    .pGPIO = GPIO0,
    .pin = GPIO_PIN_A6,
    .format = DIGITAL_INPUT_FORMAT_TDM_8CH_DEVICE_2,
};

const struct codec_desc codec_tda7803[] =
{
    {
        .if_type = IF_TYPE_I2C,
        .name = "tda7803_dev0",
        .i2c_bus = "i2c0",
        .i2c_addr = 0x6C,
        .private = &priv_dev0,
    },
    {
        .if_type = IF_TYPE_I2C,
        .name = "tda7803_dev1",
        .i2c_bus = "i2c0",
        .i2c_addr = 0x6F,
        .private = &priv_dev1,
    },
    { /* sentinel */ }
};

const struct audio_mcodecs_desc rk_mcodecs =
{
    .codecs = { &codec_tda7803[0], &codec_tda7803[1] },
    .playback_mapping = { 8, 8 },
};
#endif

#ifdef RT_USING_AUDIO
const struct audio_card_desc rk_board_audio_cards[] =
{
#ifdef RT_USING_AUDIO_CARD_TDM0
    {
        .name = "tdm0",
        .dai =  I2STDM0,
        .codec = NULL,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_TRUE,
        .format = AUDIO_FMT_TDM_I2S_HALF_FRAME,
        .trcm_mode = TRCM_TXONLY,
        .mclkfs = 256,
        .txMap = 0x3210,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_I2S0
    {
        .name = "i2s0",
        .dai =  I2S0,
        .codec = NULL,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_FALSE,
        .format = AUDIO_FMT_I2S,
        .trcm_mode = TRCM_TXONLY,
        .mclkfs = 256,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_TDM1
    {
        .name = "tdm1",
        .dai =  I2STDM1,
        .codec = (void *) &rk_mcodecs,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_FALSE,
        .format = AUDIO_FMT_TDM_I2S_HALF_FRAME,
        .trcm_mode = TRCM_NONE,
        .mclkfs = 256,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_ACODEC
    {
        .name = "acodec",
        .dai =  I2STDM2,
        .codec = ACODEC,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_TRUE,
        .format = AUDIO_FMT_I2S,
        .mclkfs = 256,
        .rxMap = 0x3210,
    },
#endif

    { /* sentinel */ }
};

#endif
