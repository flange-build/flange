/*
 * rk3568_amp_uart7_rtt_demo —— Orange Pi CM4 RT-Thread AMP 从核
 * Linux↔AMP rpmsg echo（叠到 BSP 模板的 overlay）。
 *
 * 与 rk3568_amp_rtt_demo 保持同一 rpmsg 协议，app 自带 .config 片段把
 * 从核 console 切到 UART7_M2（40pin: GPIO4_A2/TX, GPIO4_A3/RX），baud rate
 * 仍由 BSP g_uart7_board 保持 115200。
 *
 * 内存布局（从核链接地址、SHMEM、LINUX_RPMSG）由 flange 的 config.amp.memory
 * 经环境变量注入，勿在此硬编。
 */
#include <stdint.h>
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"
#include "hal_gic.h"
#include "rpmsg_lite.h"
#include "rpmsg_queue.h"
#include "rpmsg_ns.h"
#include "swift_bridge.h"

/* link-id 必须与 board dts 的 rockchip,link-id 一致（0x10）：M=1（主/从判定，取
 * 非本核 cpu3 即可）、R=0（从核新消息发 mailbox ch0，命中 stock 内核 rpmsg-rx）。*/
#define ECHO_LINK_ID    RL_PLATFORM_SET_LINK_ID(1U, 0U)   /* = 0x10 */

/* 把 MBOX0_CH3_A2B(222) 加入 AMP GIC 白名单，否则从核收不到 Linux 的 rpmsg
 * kick、永卡 wait_for_link_up。解法同 rk3568_amp_rtt_demo：rpmsg init 前再调
 * 一次 HAL_GIC_Init，gicInit 保持 0，只补白名单。*/
static struct GIC_AMP_IRQ_INIT_CFG amp_extra_irqs[] = {
    GIC_AMP_IRQ_CFG_ROUTE(MBOX0_CH3_A2B_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(0, 0, CPU_GET_AFFINITY(0, 0)),
};
static struct GIC_IRQ_AMP_CTRL amp_extra_gic = {
    .cpuAff = CPU_GET_AFFINITY(0, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(0, 0),
    .irqsCfg = &amp_extra_irqs[0],
};

#define ECHO_EPT_ID     0x3003U
#define ECHO_EPT_NAME   "rpmsg-ap3-ch0"

extern uint32_t __linux_share_rpmsg_start__[];
#define LINUX_RPMSG_MEM ((void *)&__linux_share_rpmsg_start__)

static void rpmsg_ns_cb(uint32_t new_ept, const char *new_ept_name,
                        uint32_t flags, void *user_data)
{
    rt_kprintf("rpmsg: ns callback new_ept-0x%x name-%s\n",
               new_ept, new_ept_name);
}

static void rpmsg_echo_entry(void *param)
{
    struct rpmsg_lite_instance *inst;
    struct rpmsg_lite_endpoint *ept;
    rpmsg_queue_handle queue;
    void *ns_cb_data;
    uint32_t src;
    uint32_t rx_len;
    uint32_t reply_len;
    char *rx = (char *)rt_malloc(RL_BUFFER_PAYLOAD_SIZE);
    char *tx = (char *)rt_malloc(RL_BUFFER_PAYLOAD_SIZE);

    if (rx == RT_NULL || tx == RT_NULL)
    {
        rt_kprintf("rpmsg echo: buffer malloc failed\n");
        if (rx != RT_NULL)
        {
            rt_free(rx);
        }
        if (tx != RT_NULL)
        {
            rt_free(tx);
        }
        return;
    }

    HAL_GIC_Init(&amp_extra_gic);

    inst = rpmsg_lite_remote_init(LINUX_RPMSG_MEM, ECHO_LINK_ID, RL_NO_FLAGS);
    rt_kprintf("rpmsg: remote init (link_id 0x%x), waiting for link up...\n",
               ECHO_LINK_ID);
    rpmsg_lite_wait_for_link_up(inst, RL_BLOCK);
    rt_kprintf("rpmsg: link up! link_id-0x%x\n", inst->link_id);

    rpmsg_ns_bind(inst, rpmsg_ns_cb, &ns_cb_data);
    queue = rpmsg_queue_create(inst);
    ept = rpmsg_lite_create_ept(inst, ECHO_EPT_ID, rpmsg_queue_rx_cb, queue);
    rpmsg_ns_announce(inst, ept, ECHO_EPT_NAME, RL_NS_CREATE);
    rt_kprintf("rpmsg: ept '%s' announced, echo ready\n", ECHO_EPT_NAME);

    while (1)
    {
        if (rpmsg_queue_recv(inst, queue, &src, rx, RL_BUFFER_PAYLOAD_SIZE,
                             &rx_len, RL_BLOCK) == RL_SUCCESS)
        {
            reply_len = swift_handle_message((const uint8_t *)rx, rx_len,
                                             (uint8_t *)tx,
                                             RL_BUFFER_PAYLOAD_SIZE);
            if (reply_len > 0U)
            {
                rpmsg_lite_send(inst, ept, src, tx, reply_len, RL_BLOCK);
            }
        }
    }
}

int main(int argc, char **argv)
{
    rt_thread_t tid;

    rt_kprintf("rk3568_amp_uart7_rtt_demo: cpu%d up (RT-Thread AMP)\n",
               HAL_CPU_TOPOLOGY_GetCurrentCpuId());

    tid = rt_thread_create("rpmsg_echo", rpmsg_echo_entry, RT_NULL,
                           4096, 20, 10);
    if (tid != RT_NULL)
    {
        rt_thread_startup(tid);
    }

    return RT_EOK;
}
