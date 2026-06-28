/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    common.c
  * @author  Jiang Di
  * @version V0.1
  * @date    24-04-2023
  * @brief   source algorithm for rksoc
  *
  ******************************************************************************
  */

#include "aupipe.h"
#include "rkaudio_json.h"

#ifdef RT_USING_AUPIPE_SOURCE

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME                  "SOURCE"

#define SOURCE(obj)                   ((ApSource *)(obj))

typedef struct source_object
{
    ApObject base;
    ApPad *src_pad;

    int channels;
    int period_byte;

    int block_type;
    float **out_stream;
    BlockAlgo *block_handle;

    rt_sem_t sem;
    rt_thread_t loop;
    int loop_running;
} ApSource;

static int source_process(ApPad *pad, ApBuffer *buffer);
static int source_param_parse(ApObject *obj, void *arg);

static int source_init(ApObject *obj, void *arg)
{
    ApSource *object = SOURCE(obj);

    int status = RT_EOK;
    Aupipe *aupipe = obj->parent;
    char *parameters = (char *)arg;

    /* get basic parameters of the algorithm */
    status |= aupipe_find_property(parameters, "channels",
                                   VALUE_TYPE_INT, &object->channels);

    if (status != RT_EOK)
    {
        LOG_E("%s plug-in parameter initialization failed", object->base.name);
        return -RT_ERROR;
    }

    object->period_byte = aupipe->period_size * (aupipe->bits >> 3);

    object->src_pad = aupipe_pad_new(obj, object->channels);
    RT_ASSERT(object->src_pad != NULL);

    object->out_stream = (float **)rt_malloc(object->channels  * sizeof(float *));

    for (int i = 0; i < object->channels; i++)
    {
        object->out_stream[i] = (float *)rt_malloc(aupipe->period_size * sizeof(float));
    }

    if (RT_EOK != source_param_parse(obj, arg))
    {
        LOG_E("%s init failed", obj->name);
        return -RT_ERROR;
    }

    object->sem = rt_sem_create("source", 0, RT_IPC_FLAG_FIFO);
    RT_ASSERT(object->sem != NULL);

    return RT_EOK;
}

static int source_deinit(ApObject *obj)
{
    ApSource *object = SOURCE(obj);

    rt_free(object->src_pad);

    for (int i = 0; i < object->channels; i++)
    {
        rt_free(object->out_stream[i]);
    }

    rt_free(object->out_stream);

    rt_sem_delete(object->sem);

    return RT_EOK;
}

//static void do_source(void *arg)
//{
//    ApSource *obj = SOURCE(pad->parent);
//    Aupipe *aupipe = obj->base.parent;
//
//    skv_bytes2floats((SKV_BYTE *)buffer->data, obj->in_stream[pad->id],
//                     aupipe->period_size, aupipe->bits, 0);
//
//    obj->chan_map = obj->chan_map & (~(1 << pad->id));
//    aupipe_buffer_unref(buffer);
//    if (obj->chan_map != 0)
//    {
//        return RT_EOK;
//    }
//    obj->chan_map = (1 << obj->in_channels) - 1;
//
//    BlockAlgo_process(obj->block_handle, obj->in_stream, obj->out_stream);
//
//    for (int i = 0; i < obj->out_channels; i++)
//    {
//        if (obj->src_pad[i].peer == RT_NULL)
//            continue;
//
//        ApBuffer *buffer = (ApBuffer *)aupipe_buffer_new(DATA_TYPE_AUDIO, obj->period_byte);
//        if (!buffer)
//        {
//            LOG_E("%s malloc %d failed", obj->period_byte);
//            break;
//        }
//
//        skv_floats2bytes(obj->out_stream[i], (SKV_BYTE *)buffer->data,
//                         aupipe->period_size, aupipe->bits, 0);
//
//        buffer = aupipe_buffer_ref(buffer);
//        aupipe_pad_push(&obj->src_pad[i], buffer);
//    }
//
//    return RT_EOK;
//}

static void do_source(void *arg)
{
    ApSource *obj = SOURCE(arg);
    Aupipe *aupipe = obj->base.parent;

    int total_period_byte;
    int bit_width, period_byte;

    bit_width = aupipe->bits >> 3;
    period_byte = aupipe->period_size * bit_width;
    total_period_byte = period_byte * obj->channels;

    char *read_buffer = (char *)rt_malloc(total_period_byte);

    while (obj->loop_running)
    {
        BlockAlgo_process(obj->block_handle, NULL, obj->out_stream);

        for (int i = 0; i < obj->channels; i++)
        {
            if (obj->src_pad[i].peer == RT_NULL)
                continue;

            ApBuffer *buffer = (ApBuffer *)aupipe_buffer_new(DATA_TYPE_AUDIO, period_byte);
            if (!buffer)
            {
                LOG_E("%s malloc %d failed", period_byte);
                break;
            }

            skv_floats2bytes(obj->out_stream[i], (SKV_BYTE *)buffer->data,
                             aupipe->period_size, aupipe->bits, 0);

            buffer = aupipe_buffer_ref(buffer);
            aupipe_pad_push(&obj->src_pad[i], buffer);
        }
    }

    rt_sem_release(obj->sem);
    obj->loop_running = 0;
}

static int source_param_parse(ApObject *obj, void *arg)
{
    ApSource *object = SOURCE(obj);
    char *parameters = (char *)arg;
    Aupipe *aupipe = obj->parent;

    int output_pin;
    int ret = RT_EOK;

    uint32_t free_map;
    uint32_t param_num;
    float *param = NULL;

    output_pin = object->channels;

    char *block_type = NULL;
    ret = aupipe_find_property(parameters, "block-type",
                               VALUE_TYPE_STRING, &block_type);

    if (strstr(block_type, "EN_SOURCE") != NULL)
    {
        if (strstr(block_type, "CLIME") != NULL)
        {
            param_num = 6;
            free_map = 0b100011;

            object->block_type = EN_SOURCE_CLIME;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }


            ret |= aupipe_find_property(parameters, "ArrayLength",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "MaxTime",
                                        VALUE_TYPE_FLOAT, &param[1]);

            char *char_array1;
            ret |= aupipe_find_property(parameters, "TimeArray",
                                        VALUE_TYPE_STRING, &char_array1);
            float *float_array1 = (float *)rt_malloc(sizeof(float) * (int)param[0]);
            aupipe_parse_array(char_array1, float_array1);
            rt_free(char_array1);
            *(uint32_t *)(param + 2) = (uint32_t)float_array1;

            char *char_array2;
            ret |= aupipe_find_property(parameters, "FrequencyArray",
                                        VALUE_TYPE_STRING, &char_array2);
            float *float_array2 = (float *)rt_malloc(sizeof(float) * (int)param[0]);
            aupipe_parse_array(char_array2, float_array2);
            rt_free(char_array2);
            *(uint32_t *)(param + 3) = (uint32_t)float_array2;

            char *char_array3;
            ret |= aupipe_find_property(parameters, "GainArray",
                                        VALUE_TYPE_STRING, &char_array3);
            float *float_array3 = (float *)rt_malloc(sizeof(float) * (int)param[0]);
            aupipe_parse_array(char_array3, float_array3);
            rt_free(char_array3);
            *(uint32_t *)(param + 4) = (uint32_t)float_array3;

            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[5]);
        }
        else if (strstr(block_type, "DC") != NULL)
        {
            param_num = 1;
            free_map = 0b1;

            object->block_type = EN_SOURCE_DC;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "InputDecimal",
                                        VALUE_TYPE_FLOAT, &param[0]);
        }
        else if (strstr(block_type, "OSC_BEEQ") != NULL)
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_SOURCE_OSC_BEEQ;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Frequency",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (strstr(block_type, "OSC_SAWTOOTH") != NULL)
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_SOURCE_OSC_SAWTOOTH;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Frequency",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (strstr(block_type, "OSC_SINE") != NULL)
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_SOURCE_OSC_SINE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }
            ret |= aupipe_find_property(parameters, "Frequency",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (strstr(block_type, "OSC_SQUARE") != NULL)
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_SOURCE_OSC_SQUARE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Frequency",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (strstr(block_type, "OSC_TRIANGLE") != NULL)
        {
            param_num = 2;
            free_map = 0b11;

            object->block_type = EN_SOURCE_OSC_TRIANGLE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "Frequency",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[1]);
        }
        else if (strstr(block_type, "VCO") != NULL)
        {
            param_num = 1;
            free_map = 0b1;
            object->block_type = EN_SOURCE_VCO;

            param = rt_malloc(sizeof(float) * 1);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }
            param[0] = 0;
        }
        else if (strstr(block_type, "WHITENOISE") != NULL)
        {
            param_num = 3;
            free_map = 0b111;

            object->block_type = EN_SOURCE_WHITENOISE;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "MeanNeed",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "SigmaNeed",
                                        VALUE_TYPE_FLOAT, &param[1]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[2]);
        }
        else if (strstr(block_type, "SWEEP") != NULL)
        {
            param_num = 8;
            free_map = 0b11111111;

            object->block_type = EN_SOURCE_SWEEP;

            param = rt_malloc(sizeof(float) * param_num);
            if (param == NULL)
            {
                LOG_E("%s rt_malloc failed", block_type);
                return -RT_ERROR;
            }

            ret |= aupipe_find_property(parameters, "StartFreq",
                                        VALUE_TYPE_FLOAT, &param[0]);
            ret |= aupipe_find_property(parameters, "EndFreq",
                                        VALUE_TYPE_FLOAT, &param[1]);
            ret |= aupipe_find_property(parameters, "RepeatCounter",
                                        VALUE_TYPE_FLOAT, &param[2]);
            ret |= aupipe_find_property(parameters, "SweepTime",
                                        VALUE_TYPE_FLOAT, &param[3]);
            ret |= aupipe_find_property(parameters, "PhaseInc",
                                        VALUE_TYPE_FLOAT, &param[4]);
            ret |= aupipe_find_property(parameters, "RepeatTime",
                                        VALUE_TYPE_FLOAT, &param[5]);
            ret |= aupipe_find_property(parameters, "Peak",
                                        VALUE_TYPE_FLOAT, &param[6]);
            ret |= aupipe_find_property(parameters, "Switch",
                                        VALUE_TYPE_FLOAT, &param[7]);
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
    object->block_handle = BlockAlgo_init(0, output_pin, object->block_type);
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

static int source_set_state(ApObject *obj, int state)
{
    ApSource *object = SOURCE(obj);

    switch (state)
    {
    case STATE_NULL_TO_READY:
        LOG_I("STATE_NULL_TO_READY");
        object->loop = rt_thread_create("filesrc", do_source, object,
                                        4096, RT_THREAD_PRIORITY_MAX / 2, 10);
        if (!object->loop)
        {
            LOG_E("do_playfile thread create failed");
            return -RT_ERROR;
        }
        break;
    case STATE_PAUSED_TO_PLAYING:
        LOG_I("STATE_PAUSED_TO_PLAYING");
        object->loop_running = 1;
        rt_thread_startup(object->loop);
        break;
    case STATE_PLAYING_TO_PAUSED:
        LOG_I("STATE_PLAYING_TO_PAUSED");
        if (object->loop_running == 1)
        {
            /* loop still running */
            object->loop_running = 0;
            if (rt_sem_take(object->sem, 3000))
            {
                /* Timeout, force delete */
                LOG_W("Timeout");
                rt_thread_delete(object->loop);
            }
        }
        break;
    case STATE_READY_TO_NULL:
        LOG_I("STATE_READY_TO_NULL");
        break;
    default:
        break;
    }

    return RT_EOK;
}

static int source_set_property(ApObject *obj, char *name, void *arg)
{
    ApSource *object = SOURCE(obj);

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

static int source_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *source_get_pad(ApObject *obj, int type, int id)
{
    ApSource *object = SOURCE(obj);

    if (type == PAD_TYPE_SINK)
    {
        LOG_E("%s plug-in has no sink pad", obj->name);
        return NULL;
    }

    if (id >= object->channels)
        return NULL;

    return &object->src_pad[id];
}

OBJECT_BASE_DEFINE(source, ApSource);
#endif
