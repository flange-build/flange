/*
 * RK3506 CPU2 上的最小 RT-Thread UART4 + RPMsg 示例。
 *
 * link-id、endpoint 与 mailbox profile 由 flange 根据 FINAL_CONFIG 生成到
 * flange_amp_runtime.h；共享内存地址由同一配置注入链接脚本。RK3506 BSP 已把
 * MAILBOX_BB_2_IRQn 路由到 CPU2，不得套用 RK3568 的 INTID 222 workaround。
 */
#include <rtthread.h>

#include "flange_amp_runtime.h"
#include "hal_base.h"
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"
#include "rpmsg_queue.h"

extern uint32_t __linux_share_rpmsg_start__[];

#define LINUX_RPMSG_MEM ((void *)&__linux_share_rpmsg_start__)

static void rpmsg_ns_cb(uint32_t new_ept, const char *new_ept_name,
                        uint32_t flags, void *user_data)
{
    (void)flags;
    (void)user_data;
    rt_kprintf("rpmsg: ns ept=0x%x name=%s\n", new_ept, new_ept_name);
}

static void rpmsg_echo_entry(void *parameter)
{
    struct rpmsg_lite_instance *instance;
    struct rpmsg_lite_endpoint *endpoint;
    rpmsg_ns_handle ns_handle;
    rpmsg_queue_handle queue;
    uint32_t source;
    uint32_t rx_len;
    char *rx;

    (void)parameter;
    rx = (char *)rt_malloc(RL_BUFFER_PAYLOAD_SIZE);
    if (rx == RT_NULL)
    {
        rt_kprintf("rpmsg: 接收缓冲区分配失败\n");
        return;
    }

    rt_kprintf("rpmsg: remote init link-id=0x%x，等待 Linux link up...\n",
               FLANGE_AMP_LINK_ID);
    instance = rpmsg_lite_remote_init(
        LINUX_RPMSG_MEM, FLANGE_AMP_LINK_ID, RL_NO_FLAGS);
    if (instance == RL_NULL)
    {
        rt_kprintf("rpmsg: remote init 失败\n");
        rt_free(rx);
        return;
    }

    rpmsg_lite_wait_for_link_up(instance, RL_BLOCK);
    rt_kprintf("rpmsg: link up\n");

    ns_handle = rpmsg_ns_bind(instance, rpmsg_ns_cb, RT_NULL);
    if (ns_handle == RL_NULL)
    {
        rt_kprintf("rpmsg: name-service bind 失败\n");
        rt_free(rx);
        return;
    }

    queue = rpmsg_queue_create(instance);
    if (queue == RL_NULL)
    {
        rt_kprintf("rpmsg: queue 创建失败\n");
        rt_free(rx);
        return;
    }
    endpoint = rpmsg_lite_create_ept(
        instance, FLANGE_AMP_EPT_ADDR, rpmsg_queue_rx_cb, queue);
    if (endpoint == RL_NULL)
    {
        rt_kprintf("rpmsg: endpoint 创建失败\n");
        rpmsg_queue_destroy(instance, queue);
        rt_free(rx);
        return;
    }

    rpmsg_ns_announce(
        instance, endpoint, FLANGE_AMP_EPT_NAME, RL_NS_CREATE);
    rt_kprintf("rpmsg: endpoint %s@0x%x announced，echo ready\n",
               FLANGE_AMP_EPT_NAME, FLANGE_AMP_EPT_ADDR);

    while (1)
    {
        rx_len = 0;
        if (rpmsg_queue_recv(instance, queue, &source, rx,
                             RL_BUFFER_PAYLOAD_SIZE, &rx_len,
                             RL_BLOCK) == RL_SUCCESS)
        {
            /* 原样回送实际收到的字节，二进制数据也不会被字符串截断。 */
            rpmsg_lite_send(instance, endpoint, source, rx, rx_len, RL_BLOCK);
        }
    }
}

int main(int argc, char **argv)
{
    rt_thread_t echo_thread;

    (void)argc;
    (void)argv;
    rt_kprintf("atk-rk3506b: CPU%u RT-Thread 启动，UART4 1500000 8N1\n",
               HAL_CPU_TOPOLOGY_GetCurrentCpuId());

    echo_thread = rt_thread_create(
        "rpmsg_echo", rpmsg_echo_entry, RT_NULL, 4096, 20, 10);
    if (echo_thread == RT_NULL)
    {
        rt_kprintf("rpmsg: echo 线程创建失败\n");
        return -RT_ENOMEM;
    }
    rt_thread_startup(echo_thread);

    return RT_EOK;
}
