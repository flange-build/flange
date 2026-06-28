/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include "aupipe.h"

#ifdef RT_USING_AUPIPE_AUDIOROUTE

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME                  "AUDIOROUTE"

#define AUDIOROUTE(obj)                   ((ApAudioRoute *)(obj))

typedef struct audioroute_object
{
    ApObject base;
    ApPad *src_pad;
    ApPad *sink_pad;

    int in_channels;
    int out_channels;
    uint32_t sink_map;

    char *route_param;
    float *free_mapping;
    float *route_mapping;

    ApBuffer **aud_buffer;
} ApAudioRoute;

static int audioroute_process(ApPad *pad, ApBuffer *buffer);

static int audioroute_init(ApObject *obj, void *arg)
{
    ApAudioRoute *object = AUDIOROUTE(obj);

    int status = RT_EOK;
    char *parameters = (char *)arg;

    status |= aupipe_find_property(parameters, "in-channels",
                                   VALUE_TYPE_INT, &object->in_channels);
    status |= aupipe_find_property(parameters, "out-channels",
                                   VALUE_TYPE_INT, &object->out_channels);
    status |= aupipe_find_property(parameters, "route-param",
                                   VALUE_TYPE_STRING, &object->route_param);
    if (status != RT_EOK)
    {
        LOG_E("%s plug-in parameter initialization failed", object->base.name);
        return -RT_ERROR;
    }

    object->route_mapping = (float *)rt_malloc(sizeof(float) * object->out_channels);
    if (object->route_mapping == RT_NULL)
    {
        LOG_E("route_mapping malloc failed");
        goto null_route_mapping;
    }

    if (RT_EOK != parse_string_parameter(object->route_param, object->route_mapping, ","))
    {
        LOG_E("parse_string_parameter failed");
        goto null_parse;
    }
    object->aud_buffer = (ApBuffer **)rt_malloc(sizeof(ApBuffer *) * object->in_channels);
    if (object->aud_buffer == RT_NULL)
    {
        LOG_E("aud_buffer malloc failed");
        goto null_aud_buffer;
    }

    object->free_mapping = (float *)rt_malloc(sizeof(float) * object->in_channels);
    if (object->free_mapping == RT_NULL)
    {
        LOG_E("free_mapping malloc failed");
        goto null_free_mapping;
    }

    for (int i = 0; i < object->in_channels; i++)
    {
        object->free_mapping[i] = RT_FALSE;
    }
    for (int j = 0; j < object->out_channels; j++)
    {
        if (-RT_ERROR < object->route_mapping[j])
            object->free_mapping[(int)object->route_mapping[j]] = RT_TRUE;
    }

    object->sink_map = (1 << object->in_channels) - 1;
    object->src_pad = aupipe_pad_new(obj, object->out_channels);
    RT_ASSERT(object->src_pad != NULL);

    object->sink_pad = aupipe_pad_new(obj, object->in_channels);
    RT_ASSERT(object->sink_pad != NULL);
    for (int i = 0; i < object->in_channels; i++)
    {
        object->sink_pad[i].process = audioroute_process;
    }

    return RT_EOK;

null_free_mapping:
    rt_free(object->aud_buffer);
null_aud_buffer:
    rt_free(object->route_param);
null_parse:
    rt_free(object->route_mapping);
null_route_mapping:

    return -RT_ERROR;
}

static int audioroute_deinit(ApObject *obj)
{
    ApAudioRoute *object = AUDIOROUTE(obj);

    rt_free(object->src_pad);
    rt_free(object->sink_pad);
    rt_free(object->route_param);
    rt_free(object->free_mapping);
    rt_free(object->route_mapping);

    rt_free(object->aud_buffer);

    return RT_EOK;
}

static int audioroute_process(ApPad *pad, ApBuffer *buffer)
{
    ApAudioRoute *obj = AUDIOROUTE(pad->parent);
    Aupipe *aupipe = obj->base.parent;
    int length = buffer->len;

    obj->aud_buffer[pad->id] = buffer;

    obj->sink_map = obj->sink_map & (~(1 << pad->id));
    if (obj->sink_map != 0)
    {
        return RT_EOK;
    }
    obj->sink_map = (1 << obj->in_channels) - 1;

    for (int i = 0; i < obj->out_channels; i++)
    {
        if (obj->src_pad[i].peer == RT_NULL)
        {
            if (-RT_ERROR < (int)obj->route_mapping[i])
            {
                aupipe_buffer_unref(obj->aud_buffer[(int)obj->route_mapping[i]]);
            }
            continue;
        }
        else
        {
            if (-RT_ERROR < (int)obj->route_mapping[i])
            {
                aupipe_pad_push(&obj->src_pad[i], obj->aud_buffer[(int)obj->route_mapping[i]]);
            }
            else
            {
                ApBuffer *fill_buffer = (ApBuffer *)aupipe_buffer_new(DATA_TYPE_AUDIO, length);
                if (!fill_buffer)
                {
                    LOG_E("%s malloc %d failed", obj->base.name, fill_buffer->len);
                    return -RT_ERROR;;
                }

                rt_memset(fill_buffer->data, 0, fill_buffer->len);

                fill_buffer = aupipe_buffer_ref(fill_buffer);
                aupipe_pad_push(&obj->src_pad[i], fill_buffer);
            }
        }
    }

    for (int i = 0; i < obj->in_channels; i++)
    {
        if (RT_FALSE == obj->free_mapping[i])
            aupipe_buffer_unref(obj->aud_buffer[i]);
    }

    return RT_EOK;
}

static int audioroute_set_state(ApObject *obj, int state)
{
    ApAudioRoute *object = AUDIOROUTE(obj);

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

static int audioroute_set_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static int audioroute_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *audioroute_get_pad(ApObject *obj, int type, int id)
{
    ApAudioRoute *object = AUDIOROUTE(obj);

    if (type == PAD_TYPE_SINK) {
        if (id >= object->in_channels)
            return NULL;

        return &object->sink_pad[id];
    }

    if (id >= object->out_channels)
        return NULL;

    return &object->src_pad[id];
}

OBJECT_BASE_DEFINE(audioroute, ApAudioRoute);

#endif
