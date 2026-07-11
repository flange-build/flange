/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rtthread.h>

#ifdef RT_USING_COMMON_TEST_PCIE_CC_SPEED_TEST_EP

#include "rk_pcie_ep.h"

#define CHECK_SIZE      32
#define THREADS_MAX     2
#define TASK_USER_CMD_INIT_APP      1
#define TASK_USER_CMD_DEINIT_APP    2

struct task_user_cmd_st
{
    unsigned int cmd;
};

struct task_context_st
{
    rt_thread_t thr_recv_rc[THREADS_MAX];
    rt_thread_t thr_send_rc[THREADS_MAX];
    int task_id;
    char enable;
    char recv_rc_exit;
    char send_rc_exit;
    char stream_speed_exit;
    rt_thread_t thr_stream_speed;
    rt_mutex_t mutex_stream_speed;
    unsigned int stream_speed_index;
};

void add_check_info(unsigned char *buff)
{
    int i;
    for (i = 0; i < CHECK_SIZE; i++)
    {
        buff[i] = i;
    }
}

int check_info(unsigned char *buff)
{
    int i;
    for (i = 0; i < CHECK_SIZE; i++)
    {
        if (buff[i] != i)
        {
            return -1;
        }
    }
    return 0;
}

static void stream_speed_thread(void *pArgs)
{
    struct task_context_st *ctx = (struct task_context_st *)pArgs;
    unsigned int stream_index;

    rt_kprintf("%s: start \n", __func__);
    while (!ctx->stream_speed_exit)
    {
        rt_mutex_take(ctx->mutex_stream_speed, RT_WAITING_FOREVER);
        stream_index = ctx->stream_speed_index;
        ctx->stream_speed_index = 0;
        rt_mutex_release(ctx->mutex_stream_speed);
        rt_kprintf("recv rc[%3d]: index=%d each_packet=%ldBytes\n",
                   ctx->task_id, stream_index, rk_pcie_get_buff_max_size(ctx->task_id, E_SEND));
        rt_thread_mdelay(1000);
    }
    rt_kprintf("%s: end \n", __func__);
}

static void recv_rc_stream_thread(void *pArgs)
{
    struct task_context_st *ctx = (struct task_context_st *)pArgs;
    struct pcie_buff_node *node;
    size_t buffer_size = rk_pcie_get_buff_max_size(ctx->task_id, E_SEND);
    char *mptr = rt_malloc(buffer_size);
    if (mptr == RT_NULL)
    {
        rt_kprintf("malloc mptr is null \n");
    }
    rt_memset(mptr, 0, buffer_size);

    rt_kprintf("%s: task id:%d start \n", __func__, ctx->task_id);
    while (!ctx->recv_rc_exit)
    {
        node = rk_pcie_get_buff(ctx->task_id, E_RECV);
        if (node)
        {
            if (check_info(node->vir_addr + node->size - CHECK_SIZE) == 0)
            {
                rt_mutex_take(ctx->mutex_stream_speed, RT_WAITING_FOREVER);
                ctx->stream_speed_index++;
                rt_mutex_release(ctx->mutex_stream_speed);

                rt_memset(node->vir_addr + node->size - CHECK_SIZE, 0, CHECK_SIZE);
            }
            else
            {
                rt_kprintf("check data ==================== error \n");
                for (int i = 0; i < CHECK_SIZE; i++)
                {
                    unsigned char *p = node->vir_addr + node->size - CHECK_SIZE;
                    rt_kprintf("%d ", p[i]);
                }
                rt_kprintf("\ncheck data ===ssss========node->size = %d======== error \n", (int)node->size);
            }

            rk_pcie_release_buff(ctx->task_id, node);
        }
        else
        {
            rt_thread_mdelay(1);
        }
    }
    rt_kprintf("%s: end \n", __func__);
    if (mptr != RT_NULL)
    {
        rt_free(mptr);
    }
}

static void send_rc_stream_thread(void *pArgs)
{
    struct task_context_st *ctx = (struct task_context_st *)pArgs;
    struct pcie_buff_node *node;
    int index = 30;
    size_t buffer_size = rk_pcie_get_buff_max_size(ctx->task_id, E_SEND);
    char *mptr = rt_malloc(buffer_size);
    if (mptr == RT_NULL)
    {
        rt_kprintf("malloc mptr is null \n");
    }
    rt_memset(mptr, 0x55, buffer_size);

    rt_kprintf("%s: start \n", __func__);
    while (!ctx->send_rc_exit)
    {
        node = rk_pcie_get_buff(ctx->task_id, E_SEND);
        if (node)
        {
            node->size = buffer_size;
            add_check_info(node->vir_addr + node->size - CHECK_SIZE);
            rk_pcie_send_buff(ctx->task_id, node);
            index++;
        }
        else
        {
            rt_thread_mdelay(1);
        }
    }
    rt_kprintf("%s: end \n", __func__);
    if (mptr != RT_NULL)
    {
        rt_free(mptr);
    }
}

int task_create(struct task_context_st *ctx, int id)
{
    int ret;
    ret = rk_pcie_task_create(id);
    if (ret != 0)
    {
        rt_kprintf("[%s] task: %d create fail\n", __func__, id);
        return -1;
    }

    return 0;
}

int task_destory(struct task_context_st *ctx, int id)
{
    rk_pcie_task_destroy(id);
    return 0;
}

int app_create(struct task_context_st *ctx, int id)
{
    ctx->task_id = id;

    ctx->recv_rc_exit = 0;
    ctx->send_rc_exit = 0;
    ctx->stream_speed_exit = 0;

    ctx->mutex_stream_speed = rt_mutex_create("stream_speed_mutex", RT_IPC_FLAG_PRIO);
    ctx->thr_stream_speed = rt_thread_create("stream_speed", stream_speed_thread, ctx, 2048, 10, 20);
    rt_thread_startup(ctx->thr_stream_speed);

    for (int i = 0; i < THREADS_MAX; i++)
    {
        char name[16];
        rt_snprintf(name, sizeof(name), "recv_rc_%d", i);
        ctx->thr_recv_rc[i] = rt_thread_create(name, recv_rc_stream_thread, ctx, 2048, 10, 20);
        rt_thread_startup(ctx->thr_recv_rc[i]);

        rt_snprintf(name, sizeof(name), "send_rc_%d", i);
        ctx->thr_send_rc[i] = rt_thread_create(name, send_rc_stream_thread, ctx, 2048, 10, 20);
        rt_thread_startup(ctx->thr_send_rc[i]);
    }

    ctx->enable = 1;

    return 0;
}

int app_destory(struct task_context_st *ctx, int id)
{
    ctx->recv_rc_exit = 1;
    ctx->send_rc_exit = 1;

    for (int i = 0; i < THREADS_MAX; i++)
    {
        rt_thread_delete(ctx->thr_recv_rc[i]);
        rt_thread_delete(ctx->thr_send_rc[i]);
    }

    ctx->stream_speed_exit = 1;
    rt_thread_delete(ctx->thr_stream_speed);
    rt_mutex_delete(ctx->mutex_stream_speed);

    ctx->enable = 0;

    return 0;
}

int pcie_speed_test_ep(int argc, char **argv)
{
    int ret = 0;
    struct task_context_st task_ctx[PCIE_DMA_TASK_MAX] = {0};
    struct pcie_task_msg_st msg;
    struct task_user_cmd_st *user_cmd;
    int mem_type;

    mem_type = 3;
    rt_kprintf("mem type is %d \n", mem_type);

    ret = rk_pcie_device_init(mem_type);
    if (ret != 0)
    {
        rt_kprintf("pcie init device error....\n");
        return -1;
    }

    while (1)
    {
        ret = rk_pcie_get_msg_for_bus(&msg, 100);
        if (ret == 0)
        {
            rt_kprintf("task_id:%d type:%d size:%d \n", msg.task_id, msg.type, msg.size);
            switch (msg.type)
            {
            case E_TASK_MSG_CREATE:
                task_create(&task_ctx[msg.task_id], msg.task_id);
                break;
            case E_TASK_MSG_DESTROY:
                task_destory(&task_ctx[msg.task_id], msg.task_id);
                break;
            case E_TASK_MSG_USER:
            {
                user_cmd = (struct task_user_cmd_st *)msg.data;
                switch (user_cmd->cmd)
                {
                case TASK_USER_CMD_INIT_APP:
                    app_create(&task_ctx[msg.task_id], msg.task_id);
                    break;
                case TASK_USER_CMD_DEINIT_APP:
                    app_destory(&task_ctx[msg.task_id], msg.task_id);
                    break;
                }
            }
            break;
            default:
                rt_kprintf("error msg type!!! \n");
                break;
            }
        }
    }

    rk_pcie_device_deinit();

    return 0;
}

MSH_CMD_EXPORT(pcie_speed_test_ep, pcie chips connect speed test ep cmd);

#endif
