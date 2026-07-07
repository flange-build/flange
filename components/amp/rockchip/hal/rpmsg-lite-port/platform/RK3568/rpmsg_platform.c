/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include <stdint.h>
#include <stdio.h>

#include "hal_base.h"
#include "rpmsg_env.h"
#include "rpmsg_platform.h"

#if defined(RL_USE_ENVIRONMENT_CONTEXT) && (RL_USE_ENVIRONMENT_CONTEXT == 1)
#error "This RPMsg-Lite port requires RL_USE_ENVIRONMENT_CONTEXT set to 0"
#endif

static int32_t isr_counter;
static int32_t disable_counter;
static int32_t first_notify;
static void *platform_lock;
#if defined(RL_USE_STATIC_API) && (RL_USE_STATIC_API == 1)
static LOCK_STATIC_CONTEXT platform_lock_static_ctxt;
#endif

#ifdef RL_PLATFORM_USING_MBOX
/* master core 使用 A2B，remote core 使用 B2A。 */
#define RL_MBOX_B2A 0
#define RL_MBOX_A2B 1

static struct MBOX_REG *rl_pMBox = MBOX0;
static int32_t register_count;

static HAL_Status rpmsg_mbox_isr(uint32_t irq, void *param)
{
    (void)param;

    HAL_MBOX_IrqHandler((int)irq, rl_pMBox);
    HAL_GIC_EndOfInterrupt(irq);

    return HAL_OK;
}

static void rpmsg_master_cb(struct MBOX_CMD_DAT *msg, void *args)
{
    uint32_t link_id;
    struct MBOX_CMD_DAT rx_msg = *msg;

    (void)args;

    if (rx_msg.DATA != RL_RPMSG_MAGIC) {
        printf("rpmsg master: mailbox data error!\n");
    }
    link_id = rx_msg.CMD & 0xFFU;
    env_isr(RL_GET_VQ_ID(link_id, 0));
}

static void rpmsg_remote_cb(struct MBOX_CMD_DAT *msg, void *args)
{
    uint32_t link_id;
    struct MBOX_CMD_DAT rx_msg = *msg;

    (void)args;

    if (rx_msg.DATA != RL_RPMSG_MAGIC) {
        printf("rpmsg remote: mailbox data error!\n");
    }
    link_id = rx_msg.CMD & 0xFFU;

    if (first_notify == 0) {
        env_isr(RL_GET_VQ_ID(link_id, 0));
        first_notify++;
    } else {
        env_isr(RL_GET_VQ_ID(link_id, 1));
    }
}

static inline uint32_t rl_mbox_m_irq(uint32_t cpu_id)
{
    return cpu_id + RL_PLATFORM_B2A_IRQ_BASE;
}

static inline uint32_t rl_mbox_r_irq(uint32_t cpu_id)
{
    return cpu_id + RL_PLATFORM_A2B_IRQ_BASE;
}

static struct MBOX_CLIENT mbox_clm[MBOX_CHAN_CNT] = {
    { "mbox-clm0", RL_PLATFORM_M_IRQ(0), rpmsg_master_cb, (void *)MBOX_CH_0 },
    { "mbox-clm1", RL_PLATFORM_M_IRQ(1), rpmsg_master_cb, (void *)MBOX_CH_1 },
    { "mbox-clm2", RL_PLATFORM_M_IRQ(2), rpmsg_master_cb, (void *)MBOX_CH_2 },
    { "mbox-clm3", RL_PLATFORM_M_IRQ(3), rpmsg_master_cb, (void *)MBOX_CH_3 },
};

static struct MBOX_CLIENT mbox_clr[MBOX_CHAN_CNT] = {
    { "mbox-clr0", RL_PLATFORM_R_IRQ(0), rpmsg_remote_cb, (void *)MBOX_CH_0 },
    { "mbox-clr1", RL_PLATFORM_R_IRQ(1), rpmsg_remote_cb, (void *)MBOX_CH_1 },
    { "mbox-clr2", RL_PLATFORM_R_IRQ(2), rpmsg_remote_cb, (void *)MBOX_CH_2 },
    { "mbox-clr3", RL_PLATFORM_R_IRQ(3), rpmsg_remote_cb, (void *)MBOX_CH_3 },
};
#endif

static void platform_global_isr_disable(void)
{
    __asm volatile("cpsid i");
}

static void platform_global_isr_enable(void)
{
    __asm volatile("cpsie i");
}

int32_t platform_init_interrupt(uint32_t vector_id, void *isr_data)
{
    uint32_t cpu_id;
#ifdef RL_PLATFORM_USING_MBOX
    uint32_t irq;
    int ret;
#endif

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    env_register_isr(vector_id, isr_data);

    env_lock_mutex(platform_lock);

    RL_ASSERT(0 <= isr_counter);
    if (isr_counter < 2 * RL_MAX_INSTANCE_NUM) {
#ifdef RL_PLATFORM_USING_MBOX
        if (cpu_id == RL_GET_M_CPU_ID(vector_id)) {
            irq = rl_mbox_m_irq(RL_GET_R_CPU_ID(vector_id));
        } else {
            irq = rl_mbox_r_irq(cpu_id);
        }
        HAL_GIC_SetIRouter(irq, CPU_GET_AFFINITY(cpu_id, 0));
        HAL_IRQ_HANDLER_SetIRQHandler(irq, rpmsg_mbox_isr, NULL);

        if ((register_count % 2) == 0) {
            if (cpu_id == RL_GET_M_CPU_ID(vector_id)) {
                uint32_t remote_id = RL_GET_R_CPU_ID(vector_id);

                HAL_MBOX_Init(rl_pMBox, RL_MBOX_A2B);
                ret = HAL_MBOX_RegisterClient(rl_pMBox, remote_id,
                                              &mbox_clm[remote_id]);
                if (ret) {
                    printf("mbox master client register failed, ret=%d\n", ret);
                }
            } else {
                HAL_MBOX_Init(rl_pMBox, RL_MBOX_B2A);
                ret = HAL_MBOX_RegisterClient(rl_pMBox, cpu_id,
                                              &mbox_clr[cpu_id]);
                if (ret) {
                    printf("mbox remote client register failed, ret=%d\n", ret);
                }
            }
        }
        register_count++;
#endif
    }
    isr_counter++;

    env_unlock_mutex(platform_lock);

    return 0;
}

int32_t platform_deinit_interrupt(uint32_t vector_id)
{
    env_lock_mutex(platform_lock);

    RL_ASSERT(0 < isr_counter);
    isr_counter--;
    env_unregister_isr(vector_id);

    env_unlock_mutex(platform_lock);

    return 0;
}

void platform_notify(uint32_t vector_id)
{
#ifdef RL_PLATFORM_USING_MBOX
    uint32_t link_id;
    struct MBOX_CMD_DAT tx_msg;

    link_id = RL_GET_LINK_ID(vector_id);
    tx_msg.CMD = link_id & 0xFFU;
    tx_msg.DATA = RL_RPMSG_MAGIC;

    env_lock_mutex(platform_lock);
    HAL_MBOX_SendMsg(rl_pMBox, RL_GET_R_CPU_ID(vector_id), &tx_msg);
    env_unlock_mutex(platform_lock);
#else
    (void)vector_id;
#endif
}

void platform_time_delay(uint32_t num_msec)
{
    HAL_DelayMs(num_msec);
}

int32_t platform_in_isr(void)
{
    return ((__get_mode() != 0x10) ? 1 : 0);
}

int32_t platform_interrupt_enable(uint32_t vector_id)
{
    uint32_t cpu_id;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    RL_ASSERT(0 < disable_counter);

    platform_global_isr_disable();
    disable_counter--;
    if (disable_counter < 2 * RL_MAX_INSTANCE_NUM) {
#ifdef RL_PLATFORM_USING_MBOX
        if (cpu_id == RL_GET_M_CPU_ID(vector_id)) {
            HAL_GIC_Enable(rl_mbox_m_irq(RL_GET_R_CPU_ID(vector_id)));
        } else {
            HAL_GIC_Enable(rl_mbox_r_irq(cpu_id));
        }
#endif
    }
    platform_global_isr_enable();

    return (int32_t)vector_id;
}

int32_t platform_interrupt_disable(uint32_t vector_id)
{
    uint32_t cpu_id;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    RL_ASSERT(0 <= disable_counter);

    platform_global_isr_disable();
    if (disable_counter < 2 * RL_MAX_INSTANCE_NUM) {
#ifdef RL_PLATFORM_USING_MBOX
        if (cpu_id == RL_GET_M_CPU_ID(vector_id)) {
            HAL_GIC_Disable(rl_mbox_m_irq(RL_GET_R_CPU_ID(vector_id)));
        } else {
            HAL_GIC_Disable(rl_mbox_r_irq(cpu_id));
        }
#endif
    }
    disable_counter++;
    platform_global_isr_enable();

    return (int32_t)vector_id;
}

void platform_map_mem_region(uint32_t vrt_addr, uint32_t phy_addr,
                             uint32_t size, uint32_t flags)
{
    (void)vrt_addr;
    (void)phy_addr;
    (void)size;
    (void)flags;
}

void platform_cache_all_flush_invalidate(void)
{
}

void platform_cache_disable(void)
{
}

uint32_t platform_vatopa(void *addr)
{
    return (uint32_t)(uintptr_t)addr;
}

void *platform_patova(uint32_t addr)
{
    return (void *)(uintptr_t)addr;
}

int32_t platform_init(void)
{
#if defined(RL_USE_STATIC_API) && (RL_USE_STATIC_API == 1)
    if (env_create_mutex(&platform_lock, 1, &platform_lock_static_ctxt) != 0)
#else
    if (env_create_mutex(&platform_lock, 1) != 0)
#endif
    {
        return -1;
    }

    return 0;
}

int32_t platform_deinit(void)
{
    env_delete_mutex(platform_lock);
    platform_lock = NULL;

    return 0;
}
