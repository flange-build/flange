/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include "hal_conf.h"

#ifdef HAL_AP_CORE

#include "rpmsg_lite.h"
#include "middleware_conf.h"

/* RPMSG shared memory infomation */
extern uint32_t __share_rpmsg_start__[];
extern uint32_t __share_rpmsg_end__[];

#define RPMSG_MEM_BASE ((uint32_t)&__share_rpmsg_start__)
#define RPMSG_MEM_END  ((uint32_t)&__share_rpmsg_end__)

/* RPMSG instance buffer size */
#define RPMSG_POOL_SIZE (2UL * RL_VRING_OVERHEAD)

#if defined(CPU0)
static struct rpmsg_lite_instance *instance = NULL;

void rpmsg_init(void)
{
    uint32_t master_id, remote_id;
    uint32_t rpmsg_base;

    master_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(master_id == MASTER_ID);

    /* only support one remote core now. default CPU3 */
    remote_id = REMOTE_ID_3;

    rpmsg_base = RPMSG_MEM_BASE;
    HAL_ASSERT((rpmsg_base + RPMSG_POOL_SIZE) <= RPMSG_MEM_END);

    instance = rpmsg_lite_master_init((void *)rpmsg_base,
                                      RPMSG_POOL_SIZE,
                                      RL_PLATFORM_SET_LINK_ID(master_id, REMOTE_ID_3),
                                      RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(instance);

    printf("[cpu:%d]: rpmsg master init ok!\n", master_id);
}

struct rpmsg_lite_instance *rpmsg_master_get_instance(uint32_t master_id, uint32_t remote_id)
{
    uint32_t cur_id;

    cur_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(cur_id == MASTER_ID);
    HAL_ASSERT(instance != NULL);

    return instance;
}
#elif defined(CPU3)
static struct rpmsg_lite_instance *instance = NULL;

void rpmsg_init(void)
{
    uint32_t remote_id;
    uint32_t rpmsg_base;

    remote_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(remote_id != MASTER_ID);

    rpmsg_base = RPMSG_MEM_BASE;
    HAL_ASSERT((rpmsg_base + RPMSG_POOL_SIZE) <= RPMSG_MEM_END);

    instance = rpmsg_lite_remote_init((void *)rpmsg_base,
                                      RL_PLATFORM_SET_LINK_ID(MASTER_ID, remote_id), RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(instance);

    printf("[cpu:%d]: rpmsg remote init ok!\n", remote_id);
}

struct rpmsg_lite_instance *rpmsg_remote_get_instance(uint32_t master_id, uint32_t remote_id)
{
    uint32_t cur_id;

    cur_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(cur_id != MASTER_ID);
    HAL_ASSERT(instance != NULL);

    return instance;
}
#endif
#endif /* HAL_AP_CORE */
