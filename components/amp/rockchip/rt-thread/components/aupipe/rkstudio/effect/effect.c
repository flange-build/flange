/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    effect.c
  * @author  Abadon
  * @version V0.1
  * @date    09-06-2023
  * @brief   effect algorithm for rksoc
  *
  ******************************************************************************
  */

#include "aupipe.h"
#include "rkaudio_json.h"

#ifdef RT_USING_AUPIPE_EFFECT

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME                  "EFFECT"

typedef struct param_config_ {
    char* block_name;
    int param_num;
    uint32_t free_map;
    char** property;
    int block_type;
} param_config;

// ------------- Filter -------------
static char** filter_1st_key[6] = {"Enable", "Polarity", "Type", "GainDB", "Fc", "BoostDB"};
static char** filter_2nd_key[7] = {"Enable", "Polarity", "Type", "GainDB", "Fc", "Q", "BoostDB"};
static char** filter_2nd_tone_key[6] = {"Enable", "Polarity", "FcTreble", "BoostDBTreble", "FcBass", "BoostDBBass"};
static char** filter_2nd_iir_key[7] = {"Enable", "Polarity", "B0", "B1", "B2", "A1", "A2"};
static char** filter_2nd_firstorders_key[8] = {"Enable", "Polarity", "Filter1Type", "Filter1Fc", "Filter1BoostDB", "Filter2Type", "Filter2Fc", "Filter2BoostDB"};
static char** filter_2nd_texteq_key[7] = {"Enable", "Polarity", "FilterType", "GainDB", "Fc", "Q", "BoostDB"};
static char** filter_2nd_nonbare_key[6] = {"Enable", "Polarity", "Fc", "Q", "K", "GainDB"};
static char** filter_2nd_fir_key[2] = {"NumCoeffs", "Coeffs"};
static char** filter_2nd_crossover_2way_key[7] = {"LowType", "LowFc", "LowGainDB", "HighType", "HighFc", "HighGainDB", "Polarity"};
static char** filter_2nd_crossover_3way_key[13] = {"LowType", "LowFc", "LowGainDB", "HighType", "HighFc", "HighGainDB", "MedLpType", "MedLpFc", "MedHpType", "MedHpFc", "MedGainDB", "Polarity1", "Polarity2"};
static char** filter_2nd_statevariable_key[2] = {"Fc", "Q"};
static char** filter_2nd_lookup_tone_key[8] = {"Type", "Curves", "BoostDBMax", "BoostDBMin", "GainDB", "Q", "Fc", "SlewRate"};
static char** filter_2nd_lookup_common_key[7] = {"Type", "Curves", "GainDB", "Q", "FcMax", "FcMin", "SlewRate"};
static char** filter_2nd_lookup_butter_key[6] = {"Type", "Curves", "GainDB", "FcMax", "FcMin", "SlewRate"};

#define NUM_FILTER_KEY 18

static param_config filter_config_table[NUM_FILTER_KEY] = {
    {"EN_FILTER_1ST", 6, 0b111111, filter_1st_key, EN_FILTER_1ST},                                              // 0
    {"EN_FILTER_2ND_PARAM_SHELF", 7, 0b1111111, filter_2nd_key, EN_FILTER_2ND_PARAM_SHELF},                     // 1
    {"EN_FILTER_2ND_COMMON", 6, 0b111111, filter_2nd_key, EN_FILTER_2ND_COMMON},                                // 2
    {"EN_FILTER_2ND_BESSEL_BUTTER", 5, 0b11111, filter_2nd_key, EN_FILTER_2ND_BESSEL_BUTTER},                   // 3
    {"EN_FILTER_2ND_TONE", 6, 0b111111, filter_2nd_tone_key, EN_FILTER_2ND_TONE},                               // 4
    {"EN_FILTER_2ND_IIR", 7, 0b1111111, filter_2nd_iir_key, EN_FILTER_2ND_IIR},                                 // 5
    {"EN_FILTER_2ND_FIRSTORDERS", 8, 0b11111111, filter_2nd_firstorders_key, EN_FILTER_2ND_FIRSTORDERS},        // 6
    {"EN_FILTER_2ND_TEXTEQ", 7, 0b1111111, filter_2nd_texteq_key, EN_FILTER_2ND_TEXTEQ},                        // 7
    {"EN_FILTER_NONBARE", 6, 0b111111, filter_2nd_nonbare_key, EN_FILTER_NONBARE},                              // 8
    {"EN_FILTER_FIR", 2, 0b01, filter_2nd_fir_key, EN_FILTER_FIR},                                              // 9
    {"EN_FILTER_CROSSOVER_2WAY", 7, 0b1111111, filter_2nd_crossover_2way_key, EN_FILTER_CROSSOVER_2WAY},        // 10
    {"EN_FILTER_CROSSOVER_3WAY", 13, 0b1111111111111, filter_2nd_crossover_3way_key, EN_FILTER_CROSSOVER_3WAY}, // 11
    {"EN_FILTER_MISCE_DCBLOCKING", 1, 0b1, NULL, EN_FILTER_MISCE_DCBLOCKING},                                   // 12
    {"EN_FILTER_MISCE_STATEVARIABLE", 2, 0b11, filter_2nd_statevariable_key, EN_FILTER_MISCE_STATEVARIABLE},    // 13
    {"EN_FILTER_MISCE_STATEVARIABLEQ", 1, 0b1, filter_2nd_statevariable_key, EN_FILTER_MISCE_STATEVARIABLEQ},   // 14
    {"EN_FILTER_LOOKUP_TONE_PEAK", 8, 0b11111111, filter_2nd_lookup_tone_key, EN_FILTER_LOOKUP_TONE_PEAK},          // 15
    {"EN_FILTER_LOOKUP_COMMON", 7, 0b1111111, filter_2nd_lookup_common_key, EN_FILTER_LOOKUP_COMMON},               // 16
    {"EN_FILTER_LOOKUP_BUTTER_BESSEL", 6, 0b111111, filter_2nd_lookup_butter_key, EN_FILTER_LOOKUP_BUTTER_BESSEL},  // 17
};


// ---------------------- Volume Control ----------------------
static char** vc_control_key[2] = {"Volume", "SlewRate"};
static char** vc_ext_control_slew_key[2] = {"VolumeType", "SlewRate"};
static char** vc_gainenvelope_key[4] = {"LoopFlag", "NumPoints", "Times", "GainsDB"};
static char** vc_mute_key[2] = {"Switch", "SlewFlag"};

#define NUM_VC_KEY 7

static param_config vc_config_table[NUM_VC_KEY] = {
    {"EN_VC_SIG_CONTROL", 1, 0b1, vc_control_key, EN_VC_SIG_CONTROL},                               // 0
    {"EN_VC_MULTI_CONTROL", 1, 0b0, vc_control_key, EN_VC_MULTI_CONTROL},                           // 1
    {"EN_VC_SIG_CONTROL_SLEW", 2, 0b11, vc_control_key, EN_VC_SIG_CONTROL_SLEW},                    // 2
    {"EN_VC_MULTI_CONTROL_SLEW", 2, 0b10, vc_control_key, EN_VC_MULTI_CONTROL_SLEW},                // 3
    {"EN_VC_SIG_EXT_CONTROL_SLEW", 2, 0b11, vc_ext_control_slew_key, EN_VC_SIG_EXT_CONTROL_SLEW},   // 4
    {"EN_VC_GAINENVELOPE", 4, 0b0011, vc_gainenvelope_key, EN_VC_GAINENVELOPE},                     // 5
    {"EN_VC_MUTE", 2, 0b11, vc_mute_key, EN_VC_MUTE},                                               // 6
};


// ---------------------- muxes ----------------------
static char** muxes_switch_key[3] = {"Idx", "SlewFlag", "SlewRate"};
static char** muxes_index_key[2] = {"SlewFlag", "SlewRate"};
static char** muxes_crossfade_key[1] = {"SlewRate"};
static char** muxes_statemachine_key[1] = {"Range"};

#define NUM_MUXES_KEY 6

static param_config muxes_config_table[NUM_MUXES_KEY] = {
    {"EN_MUXES_MUXES_SWITCH", 3, 0b111, muxes_switch_key, EN_MUXES_MUXES_SWITCH},           // 0
    {"EN_MUXES_MUXES_INDEX", 2, 0b11, muxes_index_key, EN_MUXES_MUXES_INDEX},               // 1
    {"EN_MUXES_DEMUXES_SWITCH", 3, 0b111, muxes_switch_key, EN_MUXES_DEMUXES_SWITCH},       // 2
    {"EN_MUXES_DEMUXES_INDEX", 2, 0b11, muxes_index_key, EN_MUXES_DEMUXES_INDEX},           // 3
    {"EN_MUXES_CROSSFADE", 1, 0b1, muxes_crossfade_key, EN_MUXES_CROSSFADE},                // 4
    {"EN_MUXES_STATE_MACHINE", 1, 0b0, muxes_statemachine_key, EN_MUXES_STATE_MACHINE},     // 5
};


// ---------------------- dynamics processors ----------------------
static char** dp_env_key[3] = {"HoldTime", "DecayTime", "Rmstc"};
static char** dp_limiter_key[3] = {"Rmstc", "DecayTime", "Threshold"};
static char** dp_compressor_key[8] = {"Rmstc", "HoldTime", "DecayTime", "SoftKnee", "PostGain", "TableLen", "GraphX", "GraphY"};

#define NUM_DP_KEY 8

static param_config dp_config_table[NUM_DP_KEY] = {
    {"EN_DP_ENV", 2, 0b11, dp_env_key, EN_DP_ENV},                                              // 0
    {"EN_DP_ENV_EXT_DECAY", 1, 0b1, dp_env_key, EN_DP_ENV_EXT_DECAY},                           // 1
    {"EN_DP_ENV_RMS", 3, 0b111, dp_env_key, EN_DP_ENV_RMS},                                     // 2
    {"EN_DP_LIMITER", 3, 0b111, dp_limiter_key, EN_DP_LIMITER},                                 // 3
    {"EN_DP_COMPRESSOR_RMS", 8, 0b00111111, dp_compressor_key, EN_DP_COMPRESSOR_RMS},           // 4
    {"EN_DP_COMPRESSOR_PEAK", 8, 0b00111111, dp_compressor_key, EN_DP_COMPRESSOR_PEAK},         // 5
    {"EN_DP_COMPRESSOR_EXT_RMS", 8, 0b00111111, dp_compressor_key, EN_DP_COMPRESSOR_EXT_RMS},   // 6
    {"EN_DP_COMPRESSOR_EXT_PEAK", 8, 0b00111111, dp_compressor_key, EN_DP_COMPRESSOR_EXT_PEAK}, // 7
};


// ---------------------- detectors ----------------------
static char** detectors_key[4] = {"Enable", "Rmstc", "HoldTime", "DecayTime"};
static char** detectors_lookup_key[5] = {"Size", "Table", "Rmstc", "HoldTime", "DecayTime"};
static char** detectors_lookup_2d_key[4] = {"DB", "X", "Y", "Table"};

#define NUM_DETECTORS_KEY 5

static param_config detectors_config_table[NUM_DETECTORS_KEY] = {
    {"EN_DETECTORS_SINGLE_BAND", 4, 0b1111, detectors_key, EN_DETECTORS_SINGLE_BAND},               // 0
    {"EN_DETECTORS_SEVEN_BAND", 4, 0b1111, detectors_key, EN_DETECTORS_SEVEN_BAND},                 // 1
    {"EN_DETECTORS_LOOKUP_INDEX", 2, 0b01, detectors_lookup_key, EN_DETECTORS_LOOKUP_INDEX},  // 2
    {"EN_DETECTORS_LOOKUP_RMS", 5, 0b11101, detectors_lookup_key, EN_DETECTORS_LOOKUP_RMS},     // 3
    {"EN_DETECTORS_LOOKUP_2D", 4, 0b0111, detectors_lookup_2d_key, EN_DETECTORS_LOOKUP_2D},         // 4
};


// ---------------------- loudness ----------------------
static char** loudness_key[7] = {"BassFreq", "TrebleFreq", "BassGain", "TrebleGain", "PostGain", "FilterType", "SlewRate"};

#define NUM_LOUDNESS_KEY 2

static param_config loudness_config_table[NUM_LOUDNESS_KEY] = {
    {"EN_LOUDNESS_LH", 6, 0b111111, loudness_key, EN_LOUDNESS_LH},                   // 0
    {"EN_LOUDNESS_LH_EXT", 7, 0b1111111, loudness_key, EN_LOUDNESS_LH_EXT},          // 1
};

// ---------------------- nlp ----------------------
static char** nlp_key[1] = {"Alpha"};

#define NUM_NLP_KEY 3

static param_config nlp_config_table[NUM_NLP_KEY] = {
    {"EN_NLP_CLIPPERS_HARD", 1, 0b1, nlp_key, EN_NLP_CLIPPERS_HARD},
    {"EN_NLP_CLIPPERS_SOFT", 1, 0b1, nlp_key, EN_NLP_CLIPPERS_SOFT},
    {"EN_NLP_CHANNEL_COPY", 1, 0b1, NULL, EN_NLP_CHANNEL_COPY},
};

// ---------------------- basic ----------------------
static char** basic_arith_key[2] = {"Time", "IsDbPs"};
static char** basic_logic_key[1] = {"CompareType"};
static char** basic_bit_key[1] = {"BitValue"};
static char** basic_calc_key[1] = {"LogicType"};
static char** basic_delay_key[3] = {"MaxDelay", "Delay", "Type"};
static char** basic_gain_key[3] = {"Gain", "GainType", "SlewRate"};
static char** basic_poly_key[2] = {"PolyOrder", "PolyTable"};

#define NUM_BASIC_KEY 32

static param_config basic_config_table[NUM_BASIC_KEY] = {
    {"EN_BASIC_ARITH_ABS", 1, 0b1, NULL, EN_BASIC_ARITH_ABS},                                       // 0
    {"EN_BASIC_ARITH_INV_SQRT", 1, 0b1, NULL, EN_BASIC_ARITH_INV_SQRT},                             // 1
    {"EN_BASIC_ARITH_SQRT", 1, 0b1, NULL, EN_BASIC_ARITH_SQRT},                                     // 2
    {"EN_BASIC_ARITH_DIV", 1, 0b1, NULL, EN_BASIC_ARITH_DIV},                                       // 3
    {"EN_BASIC_ARITH_MUL", 1, 0b1, NULL, EN_BASIC_ARITH_MUL},                                       // 4
    {"EN_BASIC_ARITH_INVERT", 1, 0b1, NULL, EN_BASIC_ARITH_INVERT},                                 // 5
    {"EN_BASIC_ARITH_ADD", 1, 0b1, NULL, EN_BASIC_ARITH_ADD},                                       // 6
    {"EN_BASIC_ARITH_SUB", 1, 0b1, NULL, EN_BASIC_ARITH_SUB},                                       // 7
    {"EN_BASIC_ARITH_RMS", 2, 0b11, basic_arith_key, EN_BASIC_ARITH_RMS},                           // 8
    {"EN_BASIC_ARITH_SUMMAT", 1, 0b1, NULL, EN_BASIC_ARITH_SUMMAT},                                 // 9
    {"EN_BASIC_ARITH_SQUARE_SUMMAT", 1, 0b1, NULL, EN_BASIC_ARITH_SQUARE_SUMMAT},                   // 10
    {"EN_BASIC_LOGIC_ABSMAX", 1, 0b1, NULL, EN_BASIC_LOGIC_ABSMAX},                                  // 11
    {"EN_BASIC_LOGIC_MAX", 1, 0b1, NULL, EN_BASIC_LOGIC_MAX},                                       // 12
    {"EN_BASIC_LOGIC_MIN", 1, 0b1, NULL, EN_BASIC_LOGIC_MIN},                                       // 13
    {"EN_BASIC_LOGIC_AB", 1, 0b1, basic_logic_key, EN_BASIC_LOGIC_AB},                              // 14
    {"EN_BASIC_LOGIC_ABCD", 1, 0b1, basic_logic_key, EN_BASIC_LOGIC_ABCD},                          // 15
    {"EN_BASIC_LOGIC_BUFFER_GATE", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_BUFFER_GATE},              // 16
    {"EN_BASIC_LOGIC_ZERO_COMP", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_ZERO_COMP},                  // 17
    {"EN_BASIC_LOGIC_ONESHOT_FALL", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_ONESHOT_FALL},            // 18
    {"EN_BASIC_LOGIC_ONESHOT_FALLRST", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_ONESHOT_FALLRST},      // 19
    {"EN_BASIC_LOGIC_ONESHOT_RISE", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_ONESHOT_RISE},            // 20
    {"EN_BASIC_LOGIC_ONESHOT_RISERST", 1, 0b1, basic_bit_key, EN_BASIC_LOGIC_ONESHOT_RISERST},      // 21
    {"EN_BASIC_LOGIC_CALC", 1, 0b1, basic_calc_key, EN_BASIC_LOGIC_CALC},                           // 22
    {"EN_BASIC_DSP_HOLD_VALUE", 1, 0b1, NULL, EN_BASIC_DSP_HOLD_VALUE},                             // 23
    {"EN_BASIC_DSP_HOLD_ABSMAX", 1, 0b1, NULL, EN_BASIC_DSP_HOLD_ABSMAX},                           // 24
    {"EN_BASIC_DSP_HOLD_MAX", 1, 0b1, NULL, EN_BASIC_DSP_HOLD_MAX},                                 // 25
    {"EN_BASIC_DSP_HOLD_MIN", 1, 0b1, NULL, EN_BASIC_DSP_HOLD_MIN},                                 // 26
    {"EN_BASIC_DSP_DELAY", 3, 0b111, basic_delay_key, EN_BASIC_DSP_DELAY},                          // 27
    {"EN_BASIC_DSP_VOL_DELAY", 1, 0b1, basic_delay_key, EN_BASIC_DSP_VOL_DELAY},                    // 28
    {"EN_BASIC_GAIN", 2, 0b11, basic_gain_key, EN_BASIC_GAIN},                                      // 29
    {"EN_BASIC_GAIN_SLEW", 3, 0b111, basic_gain_key, EN_BASIC_GAIN_SLEW},                           // 30
    {"EN_BASIC_POLY", 2, 0b01, basic_poly_key, EN_BASIC_POLY},                                      // 31
};

#define EFFECT(obj)                   ((ApEffect *)(obj))
typedef struct effect_object
{
    ApObject base;
    ApPad *src_pad;
    ApPad *sink_pad;

    int period_byte;
    int in_channels;
    int out_channels;
    uint32_t chan_map;

    float **in_stream;
    float **out_stream;

    int block_type; // 算法种类
    BlockAlgo *block_handle; // 指向算法结构体的指针
} ApEffect;

static int effect_process(ApPad *pad, ApBuffer *buffer);
static int effect_param_parse(ApObject *obj, void *arg);

static int effect_init(ApObject *obj, void *arg)
{
    //ApEffect *object = ((ApEffect *)(obj))
    ApEffect *object = EFFECT(obj);

    int status = RT_EOK;
    Aupipe *aupipe = obj->parent;
    char *parameters = (char *)arg;

    /* get basic parameters of the algorithm */
    // aupipe_find_property从parameters中寻找指定属性以及对应的数值
    status |= aupipe_find_property(parameters, "in-channels",
                                   VALUE_TYPE_INT, &object->in_channels);
    status |= aupipe_find_property(parameters, "out-channels",
                                   VALUE_TYPE_INT, &object->out_channels);
    if (status != RT_EOK)
    {
        LOG_E("%s plug-in parameter initialization failed", object->base.name);
        return -RT_ERROR;
    }

    object->chan_map = (1 << object->in_channels) - 1; // 获得通道数目的掩码
    object->period_byte = aupipe->period_size * (aupipe->bits >> 3); // 一个周期的字节数

    object->src_pad = aupipe_pad_new(obj, object->out_channels);
    RT_ASSERT(object->src_pad != NULL);

    object->sink_pad = aupipe_pad_new(obj, object->in_channels);
    RT_ASSERT(object->sink_pad != NULL);
    for (int i = 0; i < object->in_channels; i++)
    {
        object->sink_pad[i].process = effect_process;
    }

    object->in_stream = (float **)rt_malloc(object->in_channels * sizeof(float *));
    object->out_stream = (float **)rt_malloc(object->out_channels * sizeof(float *));

    for (int i = 0; i < object->in_channels; i++)
    {
        object->in_stream[i] = (float *)rt_malloc(aupipe->period_size * sizeof(float));
    }

    for (int i = 0; i < object->out_channels; i++)
    {
        object->out_stream[i] = (float *)rt_malloc(aupipe->period_size * sizeof(float));
    }

    if (RT_EOK != effect_param_parse(obj, arg))
    {
        LOG_E("%s init failed", obj->name);
        return -RT_ERROR;
    }

    return RT_EOK;
}

static int effect_deinit(ApObject *obj)
{
    ApEffect *object = EFFECT(obj);

    rt_free(object->src_pad);
    rt_free(object->sink_pad);

    for (int i = 0; i < object->in_channels; i++)
    {
        rt_free(object->in_stream[i]);
    }
    for (int i = 0; i < object->out_channels; i++)
    {
        rt_free(object->out_stream[i]);
    }

    rt_free(object->in_stream);
    rt_free(object->out_stream);

    return RT_EOK;
}

static int effect_process(ApPad *pad, ApBuffer *buffer)
{
    ApEffect *obj = EFFECT(pad->parent);
    Aupipe *aupipe = obj->base.parent;

    skv_bytes2floats((SKV_BYTE *)buffer->data, obj->in_stream[pad->id],
                     aupipe->period_size, aupipe->bits, 0);

    obj->chan_map = obj->chan_map & (~(1 << pad->id)); // 完成了一个通道的数据处理，把对应位置为0
    aupipe_buffer_unref(buffer);
    if (obj->chan_map != 0) // 还有通道没有处理完，直接推出
    {
        return RT_EOK;
    }
    // 所有通道都处理完了，开始调用算法处理，并把通道标志复原
    obj->chan_map = (1 << obj->in_channels) - 1;

    BlockAlgo_process(obj->block_handle, obj->in_stream, obj->out_stream);

    for (int i = 0; i < obj->out_channels; i++)
    {
        if (obj->src_pad[i].peer == RT_NULL)
            continue;

        ApBuffer *buffer = (ApBuffer *)aupipe_buffer_new(DATA_TYPE_AUDIO, obj->period_byte);
        if (!buffer)
        {
            LOG_E("%s malloc %d failed", obj->period_byte);
            break;
        }

        skv_floats2bytes(obj->out_stream[i], (SKV_BYTE *)buffer->data,
                         aupipe->period_size, aupipe->bits, 0);

        buffer = aupipe_buffer_ref(buffer);
        aupipe_pad_push(&obj->src_pad[i], buffer);
    }

    return RT_EOK;
}

static int effect_param_parse(ApObject *obj, void *arg)
{
    ApEffect *object = EFFECT(obj);
    char *parameters = (char *)arg;
    Aupipe *aupipe = obj->parent;

    int ret = RT_EOK;
    int input_pin, output_pin;
    int i_key;

    uint32_t free_map;
    uint32_t param_num;
    float *param = NULL;

    input_pin = object->in_channels;
    output_pin = object->out_channels;

    char *block_name = NULL;
    ret = aupipe_find_property(parameters, "block-type",
                               VALUE_TYPE_STRING, &block_name);

    if (strstr(block_name, "EN_FILTER") != NULL) {
        for (i_key = 0; i_key < NUM_FILTER_KEY; i_key++) {
            if (0 == strcmp(block_name, filter_config_table[i_key].block_name)) {
                param_num = filter_config_table[i_key].param_num;
                free_map = filter_config_table[i_key].free_map;

                object->block_type = filter_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (9 == i_key) { // fir
                    ret |= aupipe_find_property(parameters, "NumCoeffs",
                                                VALUE_TYPE_FLOAT, &param[0]);
                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Coeffs",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * (int)param[0]);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 1) = (uint32_t)float_array;
                }
                else if (12 == i_key) { // dcblocking
                    param[0] = 0;
                }
                else {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, filter_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }
                break; // find the key
            }
        }
    }
    else if  (strstr(block_name, "EN_VC") != NULL) {
        for (i_key = 0; i_key < NUM_VC_KEY; i_key++) {
            if (0 == strcmp(block_name, vc_config_table[i_key].block_name)) {
                param_num = vc_config_table[i_key].param_num;
                free_map = vc_config_table[i_key].free_map;

                object->block_type = vc_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (1 == i_key) { // EN_VC_MULTI_CONTROL
                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Volume",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * object->in_channels);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 0) = (uint32_t)float_array;
                }
                else if (3 == i_key) { // EN_VC_MULTI_CONTROL_SLEW
                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Volume",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * object->in_channels);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);
                    *(uint32_t *)(param + 0) = (uint32_t)float_array;

                    ret |= aupipe_find_property(parameters, "SlewRate",
                                                VALUE_TYPE_FLOAT, &param[1]);
                }
                else if (5 == i_key) { // GAINENVELOPE
                    ret |= aupipe_find_property(parameters, "LoopFlag",
                                                VALUE_TYPE_FLOAT, &param[0]);
                    ret |= aupipe_find_property(parameters, "NumPoints",
                                                VALUE_TYPE_FLOAT, &param[1]);

                    char *char_array1;
                    ret |= aupipe_find_property(parameters, "Times",
                                                VALUE_TYPE_STRING, &char_array1);
                    float *float_array1 = (float *)rt_malloc(sizeof(float) * param[1]);
                    aupipe_parse_array(char_array1, float_array1);
                    rt_free(char_array1);
                    *(uint32_t *)(param + 2) = (uint32_t)float_array1;

                    char *char_array2;
                    ret |= aupipe_find_property(parameters, "GainsDB",
                                                VALUE_TYPE_STRING, &char_array2);
                    float *float_array2 = (float *)rt_malloc(sizeof(float) * param[1]);
                    aupipe_parse_array(char_array2, float_array2);
                    rt_free(char_array2);
                    *(uint32_t *)(param + 3) = (uint32_t)float_array2;
                }
                else {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, vc_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }
                break; // find the key
            }
        }
    }
    else if (strstr(block_name, "EN_MUXES") != NULL) {
         for (i_key = 0; i_key < NUM_MUXES_KEY; i_key++) {
            if (0 == strcmp(block_name, muxes_config_table[i_key].block_name)) {
                param_num = muxes_config_table[i_key].param_num;
                free_map = muxes_config_table[i_key].free_map;

                object->block_type = muxes_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (5 == i_key) {
                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Range",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * object->in_channels);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 0) = (uint32_t)float_array;
                }
                else {
                   for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, muxes_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }

                break; // find the key
            }
         }
    }
    else if (strstr(block_name, "EN_DP") != NULL) {
        for (i_key = 0; i_key < NUM_DP_KEY; i_key++) {
            if (0 == strcmp(block_name, dp_config_table[i_key].block_name)) {
                param_num = dp_config_table[i_key].param_num;
                free_map = dp_config_table[i_key].free_map;

                object->block_type = dp_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (i_key >= 4) {
                    for (int i = 0; i < 6; i++) {
                        ret |= aupipe_find_property(parameters, dp_config_table[i_key].property[i],
                                                VALUE_TYPE_FLOAT, &param[i]);
                    }
                    char *char_array1;
                    ret |= aupipe_find_property(parameters, "GraphX",
                                                VALUE_TYPE_STRING, &char_array1);
                    float *float_array1 = (float *)rt_malloc(sizeof(float) * param[5]);
                    aupipe_parse_array(char_array1, float_array1);
                    rt_free(char_array1);
                    *(uint32_t *)(param + 6) = (uint32_t)float_array1;

                    char *char_array2;
                    ret |= aupipe_find_property(parameters, "GraphY",
                                                VALUE_TYPE_STRING, &char_array2);
                    float *float_array2 = (float *)rt_malloc(sizeof(float) * param[5]);
                    aupipe_parse_array(char_array2, float_array2);
                    rt_free(char_array2);
                    *(uint32_t *)(param + 7) = (uint32_t)float_array2;
                }
                else {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, dp_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }

                break; // find the key
            }
        }
    }
    else if (strstr(block_name, "EN_DETECTORS") != NULL) {
        for (i_key = 0; i_key < NUM_DETECTORS_KEY; i_key++) {
            if (0 == strcmp(block_name, detectors_config_table[i_key].block_name)) {
                param_num = detectors_config_table[i_key].param_num;
                free_map = detectors_config_table[i_key].free_map;

                object->block_type = detectors_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (i_key <= 1) {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, detectors_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }
                else if (2 == i_key) {
                    ret |= aupipe_find_property(parameters, "Size",
                                                VALUE_TYPE_FLOAT, &param[0]);

                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Table",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * (int)param[0]);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 1) = (uint32_t)float_array;
                }
                else if (3 == i_key) {
                    ret |= aupipe_find_property(parameters, "Size",
                                                VALUE_TYPE_FLOAT, &param[0]);

                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Table",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * (int)param[0]);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 1) = (uint32_t)float_array;

                    ret |= aupipe_find_property(parameters, "Rmstc",
                                                VALUE_TYPE_FLOAT, &param[2]);
                    ret |= aupipe_find_property(parameters, "HoldTime",
                                                VALUE_TYPE_FLOAT, &param[3]);
                    ret |= aupipe_find_property(parameters, "DecayTime",
                                                VALUE_TYPE_FLOAT, &param[4]);
                }
                else if (4 == i_key) {
                    ret |= aupipe_find_property(parameters, "DB",
                                                VALUE_TYPE_FLOAT, &param[0]);
                    ret |= aupipe_find_property(parameters, "X",
                                                VALUE_TYPE_FLOAT, &param[1]);
                    ret |= aupipe_find_property(parameters, "Y",
                                                VALUE_TYPE_FLOAT, &param[2]);

                    char *char_array;
                    ret |= aupipe_find_property(parameters, "Table",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * (int)param[1] * (int)param[2]);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 3) = (uint32_t)float_array;
                }

                break; // find the key
            }
        }
    }
    else if (strstr(block_name, "EN_LOUDNESS") != NULL) {
        for (i_key = 0; i_key < NUM_LOUDNESS_KEY; i_key++) {
            if (0 == strcmp(block_name, loudness_config_table[i_key].block_name)) {
                param_num = loudness_config_table[i_key].param_num;
                free_map = loudness_config_table[i_key].free_map;

                object->block_type = loudness_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                for (int i = 0; i < param_num; i++) {
                    ret |= aupipe_find_property(parameters, loudness_config_table[i_key].property[i],
                                                VALUE_TYPE_FLOAT, &param[i]);
                }
            }

            break; // find the key
        }
    }
    else if (strstr(block_name, "EN_NLP") != NULL) {
        for (i_key = 0; i_key < NUM_NLP_KEY; i_key++) {
            if (0 == strcmp(block_name, nlp_config_table[i_key].block_name)) {
                param_num = nlp_config_table[i_key].param_num;
                free_map = nlp_config_table[i_key].free_map;

                object->block_type = nlp_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (2 == i_key) {
                    param[0] = 0;
                }
                else {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, nlp_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }

                break; // find the key
            }
        }
    }
    else if (strstr(block_name, "EN_BASIC") != NULL) {
        for (i_key = 0; i_key < NUM_BASIC_KEY; i_key++) {
            if (0 == strcmp(block_name, basic_config_table[i_key].block_name)) {
                param_num = basic_config_table[i_key].param_num;
                free_map = basic_config_table[i_key].free_map;

                object->block_type = basic_config_table[i_key].block_type;

                param = rt_malloc(sizeof(float) * param_num);
                if (param == NULL) {
                    LOG_E("%s rt_malloc failed", block_name);
                    return -RT_ERROR;
                }

                if (i_key <= 7 || (i_key>=9 && i_key <=13) || (i_key>=23 && i_key <=26)) {
                    param[0] = 0;
                }
                else if (31 == i_key) {
                    ret |= aupipe_find_property(parameters, "PolyOrder",
                                                VALUE_TYPE_FLOAT, &param[0]);

                    char *char_array;
                    ret |= aupipe_find_property(parameters, "PolyTable",
                                                VALUE_TYPE_STRING, &char_array);
                    float *float_array = (float *)rt_malloc(sizeof(float) * (int)param[0]);
                    aupipe_parse_array(char_array, float_array);
                    rt_free(char_array);

                    *(uint32_t *)(param + 1) = (uint32_t)float_array;
                }
                else {
                    for (int i = 0; i < param_num; i++) {
                        ret |= aupipe_find_property(parameters, basic_config_table[i_key].property[i],
                                                    VALUE_TYPE_FLOAT, &param[i]);
                    }
                }

                break;
            }
        }
    }
    else
    {
        LOG_E("%s does not support algorithm type", block_name);
        return -RT_ERROR;
    }
    rt_free(block_name);
    if (ret != RT_EOK)
    {
        LOG_E("plug-in parameter initialization failed");
        return -RT_ERROR;
    }

    BlockAlgo_BlockPro_set(aupipe->rate, aupipe->bits, aupipe->period_size);
    object->block_handle = BlockAlgo_init(input_pin, output_pin, object->block_type);
    if (object->block_handle == NULL)
    {
        LOG_E("BlockAlgo_init failed");
        return -RT_ERROR;
    }

    ret = BlockAlgo_param_reset(object->block_handle, (void *)param);
    if (ret != RT_EOK)
    {
        LOG_E("BlockAlgo_param_reset failed");
        return -RT_ERROR;
    }

    for (int i = 0; i < param_num; i++)
    {
        if (((free_map >> i) & 0x1) == 0)
            rt_free((uint32_t)param[i]);
    }
    rt_free(param);

    return RT_EOK;
}

static int effect_set_state(ApObject *obj, int state)
{
    ApEffect *object = EFFECT(obj);

    switch (state)
    {
    case STATE_NULL_TO_READY:
        LOG_I("STATE_NULL_TO_READY");
        break;
    case STATE_READY_TO_NULL:
        LOG_I("STATE_READY_TO_NULL");
        break;
    default:
        break;
    }

    return RT_EOK;
}

// 修改参数
static int effect_set_property(ApObject *obj, char *name, void *arg)
{
    ApEffect *object = EFFECT(obj);

    float *value;
    float attribute_config[3];

    aupipe_parse_array(name, &attribute_config);

    int param_id = (int)attribute_config[0];

    if (0 == attribute_config[1])
    {
        value = (float *)rt_malloc(sizeof(float) * (int)attribute_config[2]);

        aupipe_parse_array((char *)arg, value);

        for (int i = 0; i < attribute_config[2]; i++)
        {
            object->block_handle->pState[i] = value[i];
        }
        rt_free(value);
    }
    else
    {
        object->block_handle->pParam[param_id] = atof((char *)arg);
    }

    BlockAlgo_param_update(object->block_handle);

    return RT_EOK;
}

static int effect_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *effect_get_pad(ApObject *obj, int type, int id)
{
    ApEffect *object = EFFECT(obj);

    if (type == PAD_TYPE_SINK)
    {
        if (id >= object->in_channels)
            return NULL;

        return &object->sink_pad[id];
    }

    if (id >= object->out_channels)
        return NULL;

    return &object->src_pad[id];
}

OBJECT_BASE_DEFINE(effect, ApEffect);

#endif
