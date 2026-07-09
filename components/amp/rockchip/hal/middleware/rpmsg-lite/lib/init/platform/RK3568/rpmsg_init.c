/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"

#include "rpmsg_lite.h"
#include "middleware_conf.h"

/* RPMSG shared memory infomation */
extern uint32_t __share_rpmsg_start__[];
extern uint32_t __share_rpmsg_end__[];

#define RPMSG_MEM_BASE ((uint32_t)&__share_rpmsg_start__)
#define RPMSG_MEM_END  ((uint32_t)&__share_rpmsg_end__)

/* RPMSG instance buffer size */
#define RPMSG_POOL_SIZE (2UL * RL_VRING_OVERHEAD)

static uint32_t remote_table[3] =
{
    REMOTE_ID_2,
    REMOTE_ID_3,
    REMOTE_ID_0
};

#ifdef PRIMARY_CPU

static struct rpmsg_lite_instance *instance[3] ={ 0, 0, 0 };

void rpmsg_init(void)
{
    uint32_t i;
    uint32_t master_id;
    uint32_t rpmsg_base;

    master_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(master_id == MASTER_ID);

    for (i = 0; i < 3; i++) {
        rpmsg_base = RPMSG_MEM_BASE + i * RPMSG_POOL_SIZE;
        HAL_ASSERT((rpmsg_base + RPMSG_POOL_SIZE) <= RPMSG_MEM_END);

        instance[i] = rpmsg_lite_master_init((void *)rpmsg_base,
                                             RPMSG_POOL_SIZE,
                                             RL_PLATFORM_SET_LINK_ID(master_id, remote_table[i]),
                                             RL_NO_FLAGS);
        rpmsg_lite_wait_for_link_up(instance[i]);
    }

    rk_printf("[cpu:%d]: rpmsg master init ok!\n", master_id);
}

struct rpmsg_lite_instance *rpmsg_master_get_instance(uint32_t master_id, uint32_t remote_id)
{
    uint32_t i;
    uint32_t cur_id;

    //master_id reserved for future

    cur_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(cur_id == MASTER_ID);

    for (i = 0; i < 3; i++) {
        if (remote_id == remote_table[i]) {
            break;
        }
    }
    HAL_ASSERT(i < 3);
    HAL_ASSERT(instance[i] != NULL);

    return instance[i];
}

#else

static struct rpmsg_lite_instance *instance = NULL;

void rpmsg_init(void)
{
    uint32_t i;
    uint32_t remote_id;
    uint32_t rpmsg_base;

    remote_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(remote_id != MASTER_ID);

    for (i = 0; i < 3; i++) {
        if (remote_id == remote_table[i]) {
            break;
        }
    }
    HAL_ASSERT(i < 3);

    rpmsg_base = RPMSG_MEM_BASE + i * RPMSG_POOL_SIZE;
    HAL_ASSERT((rpmsg_base + RPMSG_POOL_SIZE) <= RPMSG_MEM_END);

    instance = rpmsg_lite_remote_init((void *)rpmsg_base,
                                      RL_PLATFORM_SET_LINK_ID(MASTER_ID, remote_id), RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(instance);

    rk_printf("[cpu:%d]: rpmsg remote init ok!\n", remote_id);
}

struct rpmsg_lite_instance *rpmsg_remote_get_instance(uint32_t master_id, uint32_t remote_id)
{
    uint32_t cur_id;

    //master_id & remote_id reserved for future

    cur_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    HAL_ASSERT(cur_id != MASTER_ID);

    HAL_ASSERT(instance != NULL);

    return instance;
}

#endif
