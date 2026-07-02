/*
 * rk3568_amp_rtt_demo —— RT-Thread AMP 从核 Linux↔AMP rpmsg echo（叠到 BSP 模板的 overlay）。
 *
 * 内存布局（从核链接地址、SHMEM、LINUX_RPMSG）由 flange 的 config.amp.memory 经
 * 环境变量注入，勿在此硬编。
 *
 * 【为何自实现、不直接用厂商 rpmsg_test.c】厂商 Linux-rpmsg 测试用
 * RL_PLATFORM_SET_LINK_ID(MASTER_ID=0, remote_id=cpu3) = 0x03（R=3），与 stock
 * rockchip 内核 rpmsg 驱动不兼容：① link-up 时 Linux 的 kick 消息带 dts link-id
 * （0x10），从核 rpmsg_remote_cb 用消息里的 id 算 env_isr(vq)，而 wait_for_link_up
 * 等的是从核自身 link-id 对应的 vq——0x03 与 0x10 的 vq 对不上，永久死等；② R=3 让
 * 从核新消息发 mailbox ch3，落到 Linux 的 rpmsg-tx 回调(vq[1] consume)被丢，反向
 * echo 不通。故取 link-id = 0x10（M=1、R=0），与 board dts 的 rockchip,link-id
 * <0x10> 一致、与已上板验证的 HAL demo 一致：从核新消息发 ch0，命中 stock 内核
 * rpmsg-rx→vq[0]。222(MBOX0_CH3_A2B)→cpu3 的接收路由由 rpmsg-lite 的
 * platform_init_interrupt 自动完成，gicInit=0 由 BSP board_base 默认满足，均无需
 * COMMON_TEST Kconfig（故本 app 无 .config 覆盖；RT_USING_RPMSG_LITE/LINUX_RPMSG
 * BSP 默认已开）。
 */
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"
#include "hal_gic.h"
#include "rpmsg_lite.h"
#include "rpmsg_queue.h"
#include "rpmsg_ns.h"

/* link-id 必须与 board dts 的 rockchip,link-id 一致（0x10）：M=1（主/从判定，取
 * 非本核 cpu3 即可）、R=0（从核新消息发 mailbox ch0，命中 stock 内核 rpmsg-rx）。*/
#define ECHO_LINK_ID    RL_PLATFORM_SET_LINK_ID(1U, 0U)   /* = 0x10 */

/* 【必须】把 MBOX0_CH3_A2B(222) 加入 AMP GIC 白名单，否则从核收不到 Linux 的 rpmsg
 * kick、永卡 wait_for_link_up。原因：AMP 模式(gicInit=0)下 HAL_GIC_Enable(irq) 被
 * GIC_AmpCheckIrqValid() 门控——只有在 HAL_GIC_Init 时经 irqsCfg 进过 ampValid 白名单
 * 的 IRQ 才能被本核使能。board_base.c 仅在 RT_USING_COMMON_TEST_LINUX_RPMSG_LITE flag
 * 下才把 222 放进 irqsConfig[]；本 app 不开该 flag（避免厂商 rpmsg_test 在错误 link-id
 * 0x03 上抢跑），故 222 缺席 → rpmsg-lite 的 HAL_GIC_Enable(222) 静默返回 HAL_INVAL。
 * 解法：rpmsg init 前再调一次 HAL_GIC_Init——GIC_AMPGetValidConfig 是增量的(不清空
 * board_base 已注册的 UART4 等)，cpuAff 取非本核 → gicInit=0 不重初始化分发器，仅把
 * 222 补进白名单；之后 rpmsg-lite 的 HAL_GIC_Enable(222) 即放行。mailbox 电平触发 +
 * A2B_STATUS latch，从核一 enable 222 就会补触发 Linux 早发的那次 kick，故无时序问题。*/
static struct GIC_AMP_IRQ_INIT_CFG amp_extra_irqs[] = {
    GIC_AMP_IRQ_CFG_ROUTE(MBOX0_CH3_A2B_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(0, 0, CPU_GET_AFFINITY(0, 0)),   /* sentinel: irq=prio=0 终止扫描 */
};
static struct GIC_IRQ_AMP_CTRL amp_extra_gic = {
    .cpuAff = CPU_GET_AFFINITY(0, 0),      /* != cpu3 → gicInit=0，不重初始化分发器 */
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(0, 0),
    .irqsCfg = &amp_extra_irqs[0],
};
#define ECHO_EPT_ID     0x3003U
#define ECHO_EPT_NAME   "rpmsg-ap3-ch0"
#define ECHO_MSG        "Rockchip rpmsg linux test!"

/* Linux 共享 rpmsg 内存基址，由链接脚本 gcc_arm.ld.S 定义（= config.amp.memory
 * 的 rpmsg_base，经 LINUX_RPMSG_BASE 注入）。*/
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
    char *rx = (char *)rt_malloc(RL_BUFFER_PAYLOAD_SIZE);

    if (rx == RT_NULL)
    {
        rt_kprintf("rpmsg echo: rx buffer malloc failed\n");
        return;
    }

    /* 把 222 补进 AMP GIC 白名单（见上），必须在 rpmsg init 之前。*/
    HAL_GIC_Init(&amp_extra_gic);

    inst = rpmsg_lite_remote_init(LINUX_RPMSG_MEM, ECHO_LINK_ID, RL_NO_FLAGS);
    rt_kprintf("rpmsg: remote init (link_id 0x%x), waiting for link up...\n",
               ECHO_LINK_ID);
    rpmsg_lite_wait_for_link_up(inst);
    rt_kprintf("rpmsg: link up! link_id-0x%x\n", inst->link_id);

    rpmsg_ns_bind(inst, rpmsg_ns_cb, &ns_cb_data);
    queue = rpmsg_queue_create(inst);
    ept = rpmsg_lite_create_ept(inst, ECHO_EPT_ID, rpmsg_queue_rx_cb, queue);
    rpmsg_ns_announce(inst, ept, ECHO_EPT_NAME, RL_NS_CREATE);
    rt_kprintf("rpmsg: ept '%s' announced, echo ready\n", ECHO_EPT_NAME);

    while (1)
    {
        if (rpmsg_queue_recv(inst, queue, &src, rx, RL_BUFFER_PAYLOAD_SIZE,
                             RL_NULL, RL_BLOCK) == RL_SUCCESS)
        {
            rpmsg_lite_send(inst, ept, src, ECHO_MSG,
                            (uint32_t)rt_strlen(ECHO_MSG), RL_BLOCK);
        }
    }
}

int main(int argc, char **argv)
{
    rt_thread_t tid;

    rt_kprintf("rk3568_amp_rtt_demo: cpu%d up (RT-Thread AMP)\n",
               HAL_CPU_TOPOLOGY_GetCurrentCpuId());

    tid = rt_thread_create("rpmsg_echo", rpmsg_echo_entry, RT_NULL,
                           4096, 20, 10);
    if (tid != RT_NULL)
    {
        rt_thread_startup(tid);
    }

    return RT_EOK;
}
