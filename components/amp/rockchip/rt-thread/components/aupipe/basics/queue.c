/**
  * Copyright (c) 2022 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include "aupipe.h"

#ifdef RT_USING_AUPIPE_QUEUE

#include "drv_heap.h"

#undef DBG_SECTION_NAME
#define DBG_SECTION_NAME    "QUEUE"

#define QUEUE(obj)                      ((ApQueue *)(obj))
#define QUEUE_QUIT                      (void *)0xFF00FF00

typedef struct queue_pad
{
    int suspend_pad;
    int list_node_count;

    ApList buffer_list;
    rt_sem_t list_lock;
}QueuePad;

typedef struct queue_object
{
    ApObject base;
    ApPad *src_pad;
    ApPad *sink_pad;
    QueuePad *queue_pad;

    rt_sem_t sem;
    rt_mutex_t mutex;
    rt_thread_t loop;

    int channels;
    int buffer_num;
    int queue_quit;
    int sink_pad_map;
    int loop_running;
} ApQueue;

static int queue_process(ApPad *pad, ApBuffer *buffer);

static int queue_init(ApObject *obj, void *arg)
{
    ApQueue *queue = QUEUE(obj);

    int status = RT_EOK;
    char *parameters = (char *)arg;

    status |= aupipe_find_property(parameters, "channels",
                                   VALUE_TYPE_INT, &queue->channels);
    status |= aupipe_find_property(parameters, "buffer-num",
                                   VALUE_TYPE_INT, &queue->buffer_num);
    if (status != RT_EOK)
    {
        LOG_E("%s plug-in parameter initialization failed",
              queue->base.name);
        return -RT_ERROR;
    }

    queue->queue_quit = RT_FALSE;
    queue->sink_pad_map = (1 << queue->channels) - 1;

    queue->src_pad = aupipe_pad_new(obj, queue->channels);
    if (!queue->src_pad)
    {
        LOG_E("[%s][%d]:%s request src pad failed", __func__, __LINE__,
              queue->base.name);
        return -RT_ERROR;
    }

    queue->sink_pad = aupipe_pad_new(obj, queue->channels);
    if (!queue->sink_pad)
    {
        LOG_E("[%s][%d]:%s request sink pad failed", __func__, __LINE__,
              queue->base.name);
        goto sink_pad;
    }
    queue->queue_pad = rt_malloc(sizeof(QueuePad) * queue->channels);
    if (!queue->queue_pad)
    {
        LOG_E("[%s][%d]:%s plug-in request pad config info failed",
              __func__, __LINE__, queue->base.name);
        goto queue_pad;
    }
    for (int i = 0; i < queue->channels; i++)
    {
        queue->queue_pad[i].suspend_pad = RT_FALSE;
        queue->queue_pad[i].list_node_count = RT_FALSE;
        aupipe_list_init(&queue->queue_pad[i].buffer_list);

        queue->sink_pad[i].process = queue_process;

        queue->queue_pad[i].list_lock = rt_sem_create("lock", 0, RT_IPC_FLAG_FIFO);
        if (queue->queue_pad[i].list_lock == NULL)
        {
            LOG_E("[%s][%d]:%s plug-in list_lock create failed",
                  __func__, __LINE__, queue->base.name);
            goto list_lock;
        }
    }

    queue->sem = rt_sem_create("sem", 0, RT_IPC_FLAG_FIFO);
    if (!queue->sem)
    {
        LOG_E("[%s][%d]:%s plug-in semaphore create failed",
              __func__, __LINE__, queue->base.name);
        goto semaphore;
    }

    queue->mutex = rt_mutex_create("mutex", RT_IPC_FLAG_FIFO);
    if (!queue->mutex)
    {
        LOG_E("[%s][%d]:%s plug-in mutex create failed",
              __func__, __LINE__, queue->base.name);
        goto mutex_lock;
    }

    return RT_EOK;

mutex_lock:
semaphore:
list_lock:
    rt_free(queue->queue_pad);
queue_pad:
    rt_free(queue->sink_pad);
sink_pad:
    return -RT_ERROR;
}

static int queue_deinit(ApObject *obj)
{
    ApQueue *queue = QUEUE(obj);

    rt_free(queue->src_pad);
    rt_free(queue->sink_pad);

    for (int i = 0; i < queue->channels; i++)
    {
        rt_sem_delete(queue->queue_pad[i].list_lock);
    }
    rt_free(queue->queue_pad);

    rt_sem_delete(queue->sem);
    rt_mutex_delete(queue->mutex);

    return RT_EOK;
}

static int queue_process(ApPad *pad, ApBuffer *buffer)
{
    ApQueue *queue = QUEUE(pad->parent);
    ApList *list;

    if (queue->queue_quit == RT_TRUE)
        return RT_EOK;

    rt_mutex_take(queue->mutex, RT_WAITING_FOREVER);
    if (queue->buffer_num <= queue->queue_pad[pad->id].list_node_count)
    {
        queue->queue_pad[pad->id].suspend_pad = RT_TRUE;

        rt_mutex_release(queue->mutex);

        rt_sem_take(queue->queue_pad[pad->id].list_lock, RT_WAITING_FOREVER);
    }
    else
    {
        rt_mutex_release(queue->mutex);
    }

    list = rt_malloc(sizeof(ApList));
    if (!list)
    {
        aupipe_buffer_unref(buffer);
        return -RT_ERROR;
    }
    list->data = buffer;

    rt_mutex_take(queue->mutex, RT_WAITING_FOREVER);
    queue->queue_pad[pad->id].list_node_count++;
    aupipe_list_insert_head(&queue->queue_pad[pad->id].buffer_list, list);
    rt_mutex_release(queue->mutex);

    return RT_EOK;
}

static void do_push(void *arg)
{
    ApQueue *obj = QUEUE(arg);
    uint32_t sink_pad_map;
    ApBuffer *buffer;
    ApList *list;

    sink_pad_map = obj->sink_pad_map;

    while (obj->loop_running)
    {
        rt_mutex_take(obj->mutex, RT_WAITING_FOREVER);
        for (int i = 0; i < obj->channels; i++)
        {
            if (!aupipe_list_is_empty(&obj->queue_pad[i].buffer_list))
            {
                sink_pad_map = sink_pad_map & (~(1 << i));
            }
        }
        rt_mutex_release(obj->mutex);

        if (sink_pad_map != 0)
        {
            sink_pad_map = obj->sink_pad_map;
            rt_thread_mdelay(1);
            continue;
        }
        sink_pad_map = obj->sink_pad_map;

        for (int j = 0; j < obj->channels; j++)
        {
            rt_mutex_take(obj->mutex, RT_WAITING_FOREVER);
            list = aupipe_list_pop_tail(&obj->queue_pad[j].buffer_list);
            obj->queue_pad[j].list_node_count--;

            if (obj->queue_pad[j].list_node_count < obj->buffer_num)
            {
                if (obj->queue_pad[j].suspend_pad == RT_TRUE)
                {
                    obj->queue_pad[j].suspend_pad = RT_FALSE;
                    rt_sem_release(obj->queue_pad[j].list_lock);
                }
            }
            rt_mutex_release(obj->mutex);

            buffer = list->data;
            rt_free(list);
            if (buffer == QUEUE_QUIT)
            {
                break;
            }

            if (obj->src_pad[j].peer == RT_NULL)
            {
                aupipe_buffer_unref(buffer);
                continue;
            }
            aupipe_pad_push(&obj->src_pad[j], buffer);
        }
    }
    rt_sem_release(obj->sem);
}

static void queue_clear_list(ApQueue *obj)
{
    ApList *list;
    ApBuffer *buffer;

    for (int i = 0; i < obj->channels; i++)
    {
        do
        {
            if (aupipe_list_is_empty(&obj->queue_pad[i].buffer_list))
                break;

            list = aupipe_list_pop_tail(&obj->queue_pad[i].buffer_list);
            buffer = (ApBuffer *)list->data;
            rt_free(list);

            if (buffer && buffer != QUEUE_QUIT)
                aupipe_buffer_unref(buffer);
        }
        while(1);
    }
}

static int queue_set_state(ApObject *obj, int state)
{
    ApQueue *queue = QUEUE(obj);

    switch (state)
    {
    case STATE_NULL_TO_READY:
        LOG_I("STATE_NULL_TO_READY");

        queue->loop = rt_thread_create("queue", do_push, queue,
                                       4096, RT_THREAD_PRIORITY_MAX / 2, 10);
        if (!queue->loop)
        {
            LOG_E("[%s][%d]:%s plug-in thread create failed",
                  __func__, __LINE__, queue->base.name);
            return -RT_ERROR;
        }
        break;
    case STATE_PAUSED_TO_PLAYING:
        LOG_I("STATE_PAUSED_TO_PLAYING");

        queue->loop_running = RT_TRUE;
        rt_thread_startup(queue->loop);
        break;
    case STATE_PLAYING_TO_PAUSED:
        LOG_I("STATE_PLAYING_TO_PAUSED");

        if (queue->loop_running == 1)
        {
            /* loop still running */
            ApList *list;
            for (int i = 0; i < queue->channels; i++)
            {
                list = rt_malloc(sizeof(ApList));
                if (list)
                {
                    /* make sure do_push would not block
                     * in aupipe_list_is_empty
                     */
                    list->data = QUEUE_QUIT;
                    aupipe_list_insert_head(&queue->queue_pad[i].buffer_list, list);
                }
            }

            queue->loop_running = 0;
            queue->queue_quit = RT_TRUE;

            if (rt_sem_take(queue->sem, 3000))
            {
                /* Timeout, force delete */
                LOG_W("Timeout");
                rt_thread_delete(queue->loop);
            }
        }
        break;
    case STATE_READY_TO_NULL:
        LOG_I("STATE_READY_TO_NULL");

        queue_clear_list(queue);
        break;
    default:
        break;
    }

    return RT_EOK;
}

static int queue_set_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static int queue_get_property(ApObject *obj, char *name, void *arg)
{
    return RT_EOK;
}

static ApPad *queue_get_pad(ApObject *obj, int type, int id)
{
    ApQueue *queue = QUEUE(obj);

    if (id >= queue->channels)
        return NULL;

    if (type == PAD_TYPE_SINK)
        return &queue->sink_pad[id];

    return &queue->src_pad[id];
}

OBJECT_BASE_DEFINE(queue, ApQueue);

#endif
