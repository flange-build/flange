/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    audiotee.c
  * @author  Jun Zeng
  * @version V0.1
  * @date    10-03-2023
  * @brief   audiotee for rksoc
  *
  ******************************************************************************
  */

#include "aupipe.h"

#ifdef RT_USING_AUPIPE_AUDIOTEE

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME                  "AUDIOTEE"

#define AUDIOTEE(obj)                   ((ApAudioTee *)(obj))

typedef struct audiotee_object
{
    ApObject base;
    ApPad *src_pad;
    ApPad *sink_pad;

    int in_channels;
    int out_channels;
} ApAudioTee;

static int audiotee_process(ApPad *pad, ApBuffer *buffer);

static int audiotee_init(ApObject *obj, void *arg)
{
    ApAudioTee *object = AUDIOTEE(obj);

    int status = RT_EOK;
    char *parameters = (char *)arg;

    status = aupipe_find_property(parameters, "channels",
                                  VALUE_TYPE_INT, &object->in_channels);
    if (status != RT_EOK)
    {
        LOG_E("[%s][%d]:%s plug-in parameter initialization failed",
              __func__, __LINE__, object->base.name);
        return -RT_ERROR;
    }
    object->out_channels = object->in_channels * 2;

    object->src_pad = aupipe_pad_new(obj, object->out_channels);
    if (!object->src_pad)
    {
        LOG_E("[%s][%d]:%s plug-in request new src pad failed",
              __func__, __LINE__, object->base.name);
        return -RT_ERROR;
    }

    object->sink_pad = aupipe_pad_new(obj, object->in_channels);
    if (!object->sink_pad)
    {
        LOG_E("[%s][%d]:%s plug-in request new sink pad failed",
              __func__, __LINE__, object->base.name);
        goto sink_pad;
    }
    for (int i = 0; i < object->in_channels; i++)
    {
        object->sink_pad[i].process = audiotee_process;
    }

    return RT_EOK;

sink_pad:
    rt_free(object->src_pad);

    return -RT_ERROR;
}

static int audiotee_deinit(ApObject *obj)
{
    ApAudioTee *object = AUDIOTEE(obj);

    rt_free(object->src_pad);
    rt_free(object->sink_pad);

    return RT_EOK;
}

static int audiotee_process(ApPad *pad, ApBuffer *buffer)
{
    ApAudioTee *obj = AUDIOTEE(pad->parent);
    Aupipe *aupipe = obj->base.parent;

    if (obj->src_pad[pad->id].peer != RT_NULL)
    {
        if (obj->src_pad[pad->id + obj->in_channels].peer != RT_NULL)
        {
            ApBuffer *new_buffer = aupipe_buffer_new(DATA_TYPE_AUDIO, buffer->len);
            if (!new_buffer)
            {
                LOG_E("%s malloc %d failed", obj->base.name, buffer->len);
                aupipe_buffer_unref(buffer);
                return -RT_ERROR;
            }
            rt_memcpy(new_buffer->data, buffer->data, buffer->len);

            new_buffer = aupipe_buffer_ref(new_buffer);
            aupipe_pad_push(&obj->src_pad[pad->id + obj->in_channels], new_buffer);
        }
        aupipe_pad_push(&obj->src_pad[pad->id], buffer);
    }
    else
    {
        if (obj->src_pad[pad->id + obj->in_channels].peer != RT_NULL)
        {
            aupipe_pad_push(&obj->src_pad[pad->id + obj->in_channels], buffer);
        }
        else
        {
            aupipe_buffer_unref(buffer);
        }
    }

    return RT_EOK;
}

static int audiotee_set_state(ApObject *obj, int state)
{
    ApAudioTee *object = AUDIOTEE(obj);

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

static int audiotee_set_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static int audiotee_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *audiotee_get_pad(ApObject *obj, int type, int id)
{
    ApAudioTee *object = AUDIOTEE(obj);

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

OBJECT_BASE_DEFINE(audiotee, ApAudioTee);

#endif
