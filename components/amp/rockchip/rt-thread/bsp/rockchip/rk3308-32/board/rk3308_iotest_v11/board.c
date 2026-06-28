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

#ifdef RT_USING_AUDIO
const struct audio_card_desc rk_board_audio_cards[] =
{
#ifdef RT_USING_AUDIO_CARD_I2S0
    {
        .name = "i2s0",
        .dai =  I2S0,
        .codec = NULL,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_TRUE,
        .format = AUDIO_FMT_I2S,
        .trcm_mode = TRCM_TXONLY,
        .mclkfs = 256,
    },
    {
        .name = "tdm0",
        .dai =  I2STDM0,
        .codec = NULL,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_TRUE,
        .format = AUDIO_FMT_TDM_PCM,
        .trcm_mode = TRCM_TXONLY,
        .mclkfs = 256,
        .txMap = 0x3210,
        .rxMap = 0x3210,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_I2S1
    {
        .name = "tdm1",
        .dai =  I2STDM1,
        .codec = NULL,
        .codec_master = HAL_FALSE,
        .clk_invert = HAL_FALSE,
        .playback = HAL_TRUE,
        .capture = HAL_TRUE,
        .format = AUDIO_FMT_TDM_PCM,
        .trcm_mode = TRCM_TXONLY,
        .mclkfs = 256,
        .txMap = 0x3210,
        .rxMap = 0x3210,
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
        .rxMap = 0x0321,
    },
#endif

    { /* sentinel */ }
};

#endif
