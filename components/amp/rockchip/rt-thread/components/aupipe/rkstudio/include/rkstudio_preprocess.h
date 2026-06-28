/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef _RKSTUDIO_PREPROCESS_H_
#define _RKSTUDIO_PREPROCESS_H_

#include <stdio.h>
#include <stdlib.h>
#include "rkaudio_common.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum _RK_TYPE
{
    EN_LOUDNESS = 0x000,
    EN_LOUDNESS_LH,
    EN_LOUDNESS_LH_EXT,

    EN_BASIC_DSP = 0x100,
    EN_BASIC_ARITH_ABS,
    EN_BASIC_ARITH_INV_SQRT,
    EN_BASIC_ARITH_SQRT,
    EN_BASIC_ARITH_DIV,
    EN_BASIC_ARITH_MUL,
    EN_BASIC_ARITH_INVERT,
    EN_BASIC_ARITH_ADD,
    EN_BASIC_ARITH_SUB,
    EN_BASIC_ARITH_RMS,
    EN_BASIC_ARITH_SUMMAT,
    EN_BASIC_ARITH_SQUARE_SUMMAT,

    EN_BASIC_LOGIC_ABSMAX,
    EN_BASIC_LOGIC_MAX,
    EN_BASIC_LOGIC_MIN,
    EN_BASIC_LOGIC_AB,
    EN_BASIC_LOGIC_ABCD,
    EN_BASIC_LOGIC_BUFFER_GATE,
    EN_BASIC_LOGIC_ZERO_COMP,
    EN_BASIC_LOGIC_ONESHOT_FALL,
    EN_BASIC_LOGIC_ONESHOT_FALLRST,
    EN_BASIC_LOGIC_ONESHOT_RISE,
    EN_BASIC_LOGIC_ONESHOT_RISERST,
    EN_BASIC_LOGIC_CALC,

    EN_BASIC_DSP_HOLD_VALUE,
    EN_BASIC_DSP_HOLD_ABSMAX,
    EN_BASIC_DSP_HOLD_MAX,
    EN_BASIC_DSP_HOLD_MIN,

    EN_BASIC_DSP_DELAY,
    EN_BASIC_DSP_VOL_DELAY,
    EN_BASIC_GAIN,
    EN_BASIC_GAIN_SLEW,
    EN_BASIC_POLY,

    EN_DP = 0x200,
    EN_DP_ENV,
    EN_DP_ENV_EXT_DECAY,
    EN_DP_ENV_RMS,
    EN_DP_LIMITER,
    EN_DP_COMPRESSOR_RMS,
    EN_DP_COMPRESSOR_PEAK,
    EN_DP_COMPRESSOR_EXT_RMS,
    EN_DP_COMPRESSOR_EXT_PEAK,

    EN_FILTER = 0x300,
    EN_FILTER_1ST,
    EN_FILTER_2ND_PARAM_SHELF,
    EN_FILTER_2ND_COMMON,
    EN_FILTER_2ND_BESSEL_BUTTER,
    EN_FILTER_2ND_TONE,
    EN_FILTER_2ND_IIR,
    EN_FILTER_2ND_FIRSTORDERS,
    EN_FILTER_2ND_TEXTEQ,
    EN_FILTER_NONBARE,
    EN_FILTER_FIR,
    EN_FILTER_CROSSOVER_2WAY,
    EN_FILTER_CROSSOVER_3WAY,
    EN_FILTER_MISCE_DCBLOCKING,
    EN_FILTER_MISCE_STATEVARIABLE,
    EN_FILTER_MISCE_STATEVARIABLEQ,
    EN_FILTER_LOOKUP_TONE_PEAK,
    EN_FILTER_LOOKUP_COMMON,
    EN_FILTER_LOOKUP_BUTTER_BESSEL,

    EN_DETECTORS = 0x400,
    EN_DETECTORS_SINGLE_BAND,
    EN_DETECTORS_SEVEN_BAND,
    EN_DETECTORS_LOOKUP_INDEX,
    EN_DETECTORS_LOOKUP_RMS,
    EN_DETECTORS_LOOKUP_2D,


    EN_MIXERS = 0x500,
    EN_MIXERS_MERGE,
    EN_MIXERS_SINGLE,
    EN_MIXERS_MULTI,
    EN_MIXERS_STEREO,
    EN_MIXERS_CROSS,
    EN_SPLIT_SINGLE,
    EN_SPLIT_MULTI,
    EN_MIXERS_SINGLE_SLEW,
    EN_MIXERS_MULTI_SLEW,
    EN_MIXERS_STEREO_SLEW,
    EN_MIXERS_CROSS_SLEW,
    EN_SPLIT_SINGLE_SLEW,
    EN_SPLIT_MULTI_SLEW,

    EN_MUXES = 0x600,
    EN_MUXES_MUXES_SWITCH,
    EN_MUXES_MUXES_INDEX,
    EN_MUXES_DEMUXES_SWITCH,
    EN_MUXES_DEMUXES_INDEX,
    EN_MUXES_CROSSFADE,
    EN_MUXES_STATE_MACHINE,


    EN_NLP = 0x700,
    EN_NLP_CLIPPERS_HARD,
    EN_NLP_CLIPPERS_SOFT,
    EN_NLP_CHANNEL_COPY,

    EN_SHARC = 0x800,

    EN_SOURCE = 0X900,
    EN_SOURCE_CLIME,
    EN_SOURCE_DC,
    EN_SOURCE_OSC_BEEQ,
    EN_SOURCE_OSC_SAWTOOTH,
    EN_SOURCE_OSC_SINE,
    EN_SOURCE_OSC_SQUARE,
    EN_SOURCE_OSC_TRIANGLE,
    EN_SOURCE_VCO,
    EN_SOURCE_WHITENOISE,
    EN_SOURCE_SWEEP,

    EN_VC = 0Xa00,
    EN_VC_SIG_CONTROL,
    EN_VC_MULTI_CONTROL,
    EN_VC_SIG_CONTROL_SLEW,
    EN_VC_MULTI_CONTROL_SLEW,
    EN_VC_SIG_EXT_CONTROL_SLEW,
    EN_VC_GAINENVELOPE,
    EN_VC_MUTE

} RK_TYPE;

void RKStuido_version_invoke();

int BlockAlgo_BlockPro_set(int   nSamplingRate, int bitRate, int nBlockSize);

BlockAlgo *BlockAlgo_init(int Input_pin, int Output_pin, int type);

int BlockAlgo_param_reset(BlockAlgo *Algo_struct, void *param);

int BlockAlgo_param_update(BlockAlgo *Algo_struct);

int BlockAlgo_param_invoke(BlockAlgo *Algo_struct);

int BlockAlgo_process(BlockAlgo *Algo_struct, float **data_in, float **data_out);

int BlockAlgo_destroy(BlockAlgo *Algo_struct);

//Quick Interface which didn't need Algo_Struct
int BlockAlgo_Mixers_MulToOne(int in_chan, int size, float **buffer_in, float **buffer_out, float gain);

int HardClip_Controll_Quick(float **buffer_in, float **buffer_out, int input_pin, int nBlocksize, int Out_bitPerSample);

int SoftClip_Controll_Quick(float **buffer_in, float **buffer_out, int input_pin, float alpha, int nBlocksize, int Out_bitPerSample);

#ifdef __cplusplus
}
#endif

#endif    // _RKAUDIO_PREPROCESS_H_
