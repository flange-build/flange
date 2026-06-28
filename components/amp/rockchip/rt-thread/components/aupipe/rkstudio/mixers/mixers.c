/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    mixers.c
  * @author  JD
  * @version V0.1
  * @date    12-05-2023
  * @brief   mixers algorithm for rksoc
  *
  ******************************************************************************
  */

#include "aupipe.h"
#include "rkaudio_json.h"

#ifdef RT_USING_AUPIPE_MIXERS

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME                  "MIXERS"

#define MIXERS(obj)                   ((ApMixers *)(obj))

typedef struct mixers_object
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

    int block_type;
    BlockAlgo *block_handle;
} ApMixers;

static int mixers_process(ApPad *pad, ApBuffer *buffer);
static int mixers_param_parse(ApObject *obj, void *arg);

static int mixers_init(ApObject *obj, void *arg)
{
    ApMixers *object = MIXERS(obj);

    int status = RT_EOK;
    Aupipe *aupipe = obj->parent;
    char *parameters = (char *)arg;

    /* get basic parameters of the algorithm */
    status |= aupipe_find_property(parameters, "in-channels",
                                   VALUE_TYPE_INT, &object->in_channels);
    status |= aupipe_find_property(parameters, "out-channels",
                                   VALUE_TYPE_INT, &object->out_channels);
    if (status != RT_EOK)
    {
        LOG_E("%s plug-in parameter initialization failed", object->base.name);
        return -RT_ERROR;
    }

    object->chan_map = (1 << object->in_channels) - 1;
    object->period_byte = aupipe->period_size * (aupipe->bits >> 3);

    object->src_pad = aupipe_pad_new(obj, object->out_channels);
    RT_ASSERT(object->src_pad != NULL);

    object->sink_pad = aupipe_pad_new(obj, object->in_channels);
    RT_ASSERT(object->sink_pad != NULL);
    for (int i = 0; i < object->in_channels; i++)
    {
        object->sink_pad[i].process = mixers_process;
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

    if (RT_EOK != mixers_param_parse(obj, arg))
    {
        LOG_E("%s init failed", obj->name);
        return -RT_ERROR;
    }

    return RT_EOK;
}

static int mixers_deinit(ApObject *obj)
{
    ApMixers *object = MIXERS(obj);

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

static int mixers_process(ApPad *pad, ApBuffer *buffer)
{
    ApMixers *obj = MIXERS(pad->parent);
    Aupipe *aupipe = obj->base.parent;

    skv_bytes2floats((SKV_BYTE *)buffer->data, obj->in_stream[pad->id],
                     aupipe->period_size, aupipe->bits, 0);

    obj->chan_map = obj->chan_map & (~(1 << pad->id));
    aupipe_buffer_unref(buffer);
    if (obj->chan_map != 0)
    {
        return RT_EOK;
    }
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

static int mixers_param_parse(ApObject *obj, void *arg)
{
    ApMixers *object = MIXERS(obj);
    char *parameters = (char *)arg;
    Aupipe *aupipe = obj->parent;

    int ret = RT_EOK;
    int input_pin, output_pin;

    uint32_t free_map;
    uint32_t param_num;
    float *param = NULL;

    input_pin = object->in_channels;
    output_pin = object->out_channels;

    char *block_type = NULL;
    ret = aupipe_find_property(parameters, "block-type",
                               VALUE_TYPE_STRING, &block_type);


    if ((strstr(block_type, "EN_MIXERS") != NULL) || (strstr(block_type, "EN_SPLIT") != NULL))
    {
        if (0 == strcmp(block_type, "EN_MIXERS_MERGE"))
        {
            param_num = 1;
            free_map = 0b1;

            object->block_type = EN_MIXERS_MERGE;

            param = rt_malloc(sizeof(float) * 1);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            param[0] = 0;

        }
        else if (0 == strcmp(block_type, "EN_MIXERS_SINGLE"))
        {
            param_num = 1;
            free_map = 0b1;

            object->block_type = EN_MIXERS_SINGLE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Gain",
                                        VALUE_TYPE_FLOAT, &param[0]);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_MULTI"))
        {
            param_num = object->in_channels;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_MULTI;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num; iter++)
            {
                param[iter] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_STEREO"))
        {
            param_num = object->in_channels / 2;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_STEREO;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num; iter++)
            {
                param[iter] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_CROSS"))
        {
            param_num = object->in_channels * object->out_channels;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_CROSS;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num; iter++)
            {
                param[iter] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_SPLIT_SINGLE"))
        {
            param_num = 1;
            free_map = 0b1;

            object->block_type = EN_SPLIT_SINGLE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Gain",
                                        VALUE_TYPE_FLOAT, &param[0]);
        }
        else if (0 == strcmp(block_type, "EN_SPLIT_MULTI"))
        {
            param_num = object->out_channels;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_SPLIT_MULTI;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num; iter++)
            {
                param[iter] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_SINGLE_SLEW"))
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_MIXERS_SINGLE_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewRate",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Gain",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_MULTI_SLEW"))
        {
            param_num = object->in_channels + 1;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_MULTI_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewRate",
                                        VALUE_TYPE_FLOAT, &param[0]);

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num - 1; iter++)
            {
                param[iter + 1] = float_array[iter];
            }
            rt_free(float_array);

        }
        else if (0 == strcmp(block_type, "EN_MIXERS_STEREO_SLEW"))
        {
            param_num = object->in_channels / 2 + 1;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_STEREO_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewRate",
                                        VALUE_TYPE_FLOAT, &param[0]);

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num - 1; iter++)
            {
                param[iter + 1] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_MIXERS_CROSS_SLEW"))
        {
            param_num = object->in_channels * object->out_channels + 1;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_MIXERS_CROSS_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewFlag",
                                        VALUE_TYPE_FLOAT, &param[0]);

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num - 1; iter++)
            {
                param[iter + 1] = float_array[iter];
            }
            rt_free(float_array);
        }
        else if (0 == strcmp(block_type, "EN_SPLIT_SINGLE_SLEW"))
        {
            param_num = 1 + 1;
            free_map = 0b11;

            object->block_type = EN_SPLIT_SINGLE_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewRate",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Gain",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (0 == strcmp(block_type, "EN_SPLIT_MULTI_SLEW"))
        {
            param_num = object->out_channels + 1;
            free_map = 0;
            for (int iter = 0; iter < param_num; iter++)
            {
                free_map |= (1 << iter);
            }

            object->block_type = EN_SPLIT_MULTI_SLEW;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "SlewRate",
                                        VALUE_TYPE_FLOAT, &param[0]);

            char *char_array;
            ret |= aupipe_find_property(parameters, "Gains",
                                        VALUE_TYPE_STRING, &char_array);
            float *float_array = (float *)rt_malloc(sizeof(float) * param_num);
            aupipe_parse_array(char_array, float_array);
            rt_free(char_array);
            for (int iter = 0; iter < param_num - 1; iter++)
            {
                param[iter + 1] = float_array[iter];
            }
            rt_free(float_array);
        }
    }
    else
    {
        LOG_E("%s does not support algorithm type", block_type);
        return -RT_ERROR;
    }
    rt_free(block_type);

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

static int mixers_set_state(ApObject *obj, int state)
{
    ApMixers *object = MIXERS(obj);

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

static int mixers_set_property(ApObject *obj, char *name, void *arg)
{
    ApMixers *object = MIXERS(obj);

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

static int mixers_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *mixers_get_pad(ApObject *obj, int type, int id)
{
    ApMixers *object = MIXERS(obj);

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

OBJECT_BASE_DEFINE(mixers, ApMixers);
#endif
