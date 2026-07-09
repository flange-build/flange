/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include <stdlib.h>

/********************* Private MACRO Definition ******************************/
//#define SOFTIRQ_TEST
//#define GPIO_TEST
//#define GPIO_VIRTUAL_MODEL_TEST
//#define RPMSG_LINUX_TEST
//#define RPMSG_TEST
//#define IRQ_PREEMPT_TEST
//#ifndef PRIMARY_CPU
//#define PRIMARY_CPU
//#endif

#if defined(IRQ_PREEMPT_TEST) && !defined(HAL_GIC_PREEMPT_FEATURE_ENABLED)

#endif

/********************* Private Structure Definition **************************/

static struct GIC_AMP_IRQ_INIT_CFG irqsConfig[] = {
/* TODO: Config the irqs here.
 * GIC version: GICv2
 * The priority higher than 0x80 is non-secure interrupt.
 */
    GIC_AMP_IRQ_CFG_ROUTE(0, 0, 0),   /* sentinel */
};

static struct GIC_IRQ_AMP_CTRL irqConfig = {
    .cpuAff = CPU_GET_AFFINITY(0, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(0, 0),
    .irqsCfg = &irqsConfig[0],
};

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ***************************/

/************************************************/
/*                                              */
/*                 HW Borad config              */
/*                                              */
/************************************************/

/* TODO: Set Module IOMUX Function Here */

/************************************************/
/*                                              */
/*                  GPIO_TEST                   */
/*                                              */
/************************************************/
#ifdef GPIO_TEST
static void gpio_test(void)
{
}
#endif

/************************************************/
/*                                              */
/*          GPIO_VIRTUAL_MODEL_TEST             */
/*                                              */
/************************************************/
#ifdef GPIO_VIRTUAL_MODEL_TEST
static void gpio_virtual_model_test(void)
{
}
#endif

/************************************************/
/*                                              */
/*                SOFTIRQ_TEST                  */
/*                                              */
/************************************************/
#ifdef SOFTIRQ_TEST
#ifdef HAL_GIC_WAIT_LINUX_INIT_ENABLED

#else

#endif
static void softirq_test(void)
{
}
#endif

/************************************************/
/*                                              */
/*              IRQ_PREEMPT_TEST                */
/*                                              */
/************************************************/
#ifdef IRQ_PREEMPT_TEST
static void irq_preempt_test(void)
{
}
#endif

/************************************************/
/*                                              */
/*                 RPMSG_TEST                   */
/*                                              */
/************************************************/
#ifdef RPMSG_TEST
#include "rpmsg_lite.h"

#define MASTER_ID   ((uint32_t)1)
#define REMOTE_ID_0 ((uint32_t)0)
#define REMOTE_ID_2 ((uint32_t)2)
#define REMOTE_ID_3 ((uint32_t)3)

#define RPMSG_CMD_PROB ((uint8_t)0x80)
#define RPMSG_ACK_PROB ((uint8_t)0x81)
#define RPMSG_CMD_TEST ((uint8_t)0x82)
#define RPMSG_ACK_TEST ((uint8_t)0x83)

extern uint32_t __share_rpmsg_start__[];
extern uint32_t __share_rpmsg_end__[];

#define RPMSG_MEM_BASE      ((uint64_t)&__share_rpmsg_start__)
#define RPMSG_MEM_END       ((uint64_t)&__share_rpmsg_end__)
#define RPMSG_TEST_MEM_SIZE (2UL * RL_VRING_OVERHEAD)
#define RPMSG_TEST0_BASE    (RPMSG_MEM_BASE + 0 * RPMSG_TEST_MEM_SIZE)
#define RPMSG_TEST1_BASE    (RPMSG_MEM_BASE + 1 * RPMSG_TEST_MEM_SIZE)
#define RPMSG_TEST2_BASE    (RPMSG_MEM_BASE + 2 * RPMSG_TEST_MEM_SIZE)
#define RPMSG_TEST3_BASE    (RPMSG_MEM_BASE + 3 * RPMSG_TEST_MEM_SIZE)

// define endpoint id for test
#define RPMSG_TEST0_EPT  0x80000000UL
#define RPMSG_TEST1_EPT  0x80000001UL
#define RPMSG_TEST2_EPT  0x80000002UL
#define RPMSG_TEST3_EPT  0x80000003UL
#define EPT_M2R_ADDR(id) (id + VRING_SIZE)  // covert master endpoint number to remote endpoint number
#define EPT_R2M_ADDR(id) (id - VRING_SIZE)  // covert remote endpoint number to master endpoint number

struct rpmsg_block_t {
    uint32_t len;
    uint8_t buffer[32 - 4];
};

struct rpmsg_ept_map_t {
    uint64_t base;          // share memory base addr
    uint32_t size;          // share memory size
    uint32_t m_ept_id;    // master endpoint id
    uint32_t r_ept_id;    // remote endpoint id
};

struct rpmsg_info_t {
    struct rpmsg_lite_instance *instance;
    struct rpmsg_lite_endpoint *ept;
    struct rpmsg_ept_map_t *map;
    uint32_t cb_sta;    // callback status flags
    void * private;
};

static struct rpmsg_ept_map_t rpmsg_ept_map_table[4] = {
    { RPMSG_TEST0_BASE, RPMSG_TEST_MEM_SIZE, RPMSG_TEST0_EPT, EPT_M2R_ADDR(RPMSG_TEST0_EPT) },
    { RPMSG_TEST1_BASE, RPMSG_TEST_MEM_SIZE, RPMSG_TEST1_EPT, EPT_M2R_ADDR(RPMSG_TEST1_EPT) },
    { RPMSG_TEST2_BASE, RPMSG_TEST_MEM_SIZE, RPMSG_TEST2_EPT, EPT_M2R_ADDR(RPMSG_TEST2_EPT) },
    { RPMSG_TEST3_BASE, RPMSG_TEST_MEM_SIZE, RPMSG_TEST3_EPT, EPT_M2R_ADDR(RPMSG_TEST3_EPT) },
};

static void rpmsg_share_mem_check(void)
{
    if ((RPMSG_TEST3_BASE + RPMSG_TEST_MEM_SIZE) > RPMSG_MEM_END) {
        printf("share memory size error: (RPMSG_TEST3_BASE + RPMSG_TEST_MEM_SIZE)(0x%x08x) > RPMSG_MEM_END(0x%x08x)\n",
               RPMSG_TEST3_BASE + RPMSG_TEST_MEM_SIZE, RPMSG_MEM_END);
        while (1) {
            ;
        }
    }
}

static uint32_t remote_id_table[3] = { REMOTE_ID_0, REMOTE_ID_2, REMOTE_ID_3 };
static uint32_t rpmsg_get_remote_index(uint32_t cpu_id)
{
    uint32_t i;

    for (i = 0; i < 3; i++) {
        if (remote_id_table[i] == cpu_id) {
            return i;
        }
    }

    return -1;
}

#ifdef PRIMARY_CPU /*CPU1*/
/*
 payload:       received message data
 payload_len:   received message len
 src:           source ept memory addr
 priv:          private data used in callback
*/
static int32_t master_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    uint32_t i, cpu_id;
    struct rpmsg_info_t *info = (struct rpmsg_info_t *)priv;
    struct rpmsg_block_t *block = (struct rpmsg_block_t *)info->private;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    if (src == info->map->r_ept_id) {     // check source ept addr
        block->len = payload_len;
        memcpy(block->buffer, payload, payload_len);
        info->cb_sta = 1;
    }

    return RL_RELEASE;
}

static void rpmsg_master_test(void)
{
    uint32_t i, j;
    uint32_t master_id, remote_id;
    struct rpmsg_info_t *info;
    struct rpmsg_info_t *p_rpmsg_info[3];
    struct rpmsg_block_t block, *rblock;

    rpmsg_share_mem_check();
    master_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    /****************** Initial rpmsg ept **************/
    for (i = 0; i < 3; i++) {
        remote_id = remote_id_table[i];

        info = malloc(sizeof(struct rpmsg_info_t));
        if (info == NULL) {
            printf("info malloc error!\n");
            while (1) {
                ;
            }
        }
        info->private = malloc(sizeof(struct rpmsg_block_t));
        if (info->private == NULL) {
            printf("info malloc error!\n");
            while (1) {
                ;
            }
        }

        info->map = &rpmsg_ept_map_table[remote_id];
        info->instance = rpmsg_master_get_instance(master_id, remote_id);
        info->ept = rpmsg_lite_create_ept(info->instance, info->map->m_ept_id, master_ept_cb, info);

        p_rpmsg_info[i] = info;
    }

    /** probe remote ept, wait for remote ept initialized **/
    block.buffer[0] = RPMSG_CMD_PROB;
    block.buffer[1] = (uint8_t)master_id;
    block.len = 2;

    for (i = 0; i < 3; i++) {
        uint32_t timeout;
        info = p_rpmsg_info[i];
        remote_id = remote_id_table[i];
        rblock = (struct rpmsg_block_t *)info->private;

        for (j = 0; j < 20; j++) {
            rpmsg_lite_send(info->instance, info->ept, info->map->r_ept_id, block.buffer, block.len, RL_BLOCK);

            // wait for remote response
            timeout = 10;
            while (timeout) {
                HAL_DelayMs(1);
                if (info->cb_sta == 1) {
                    info->cb_sta = 0;
                    if (rblock->buffer[0] == RPMSG_ACK_PROB) {
                        printf("rpmsg probe remote cpu(%d) sucess!\n", rblock->buffer[1]);
                        break;
                    }
                }
                timeout--;
            }

            if (timeout) {
                break;
            }
        }

        if (j >= 20) {
            printf("rpmsg probe remote cpu(%d) error!\n", remote_id);
        }
    }

    /****************** rpmsg test run **************/
    block.buffer[0] = RPMSG_CMD_TEST;
    block.buffer[1] = (uint8_t)master_id;
    block.buffer[2] = 0x55;
    block.buffer[3] = 0x55;
    block.buffer[4] = 0x55;
    block.len = 5;
    for (i = 0; i < 3; i++) {
        info = p_rpmsg_info[i];
        info->cb_sta = 0;
        remote_id = remote_id_table[i];
        printf("rpmsg_master_send: master[%d]-->remote[%d], remote ept id = 0x%08x\n", master_id, remote_id, info->map->r_ept_id);
        rpmsg_lite_send(info->instance, info->ept, info->map->r_ept_id, block.buffer, block.len, RL_BLOCK);
    }

    while (1) {
        if (p_rpmsg_info[0]->cb_sta == 1) {
            p_rpmsg_info[0]->cb_sta = 0;

            rblock = (struct rpmsg_block_t *)p_rpmsg_info[0]->private;

            // CMD(ACK): RPMSG_ACK_TEST
            if (rblock->buffer[0] == RPMSG_ACK_TEST) {
                remote_id = rblock->buffer[1];
                block.buffer[0 + 2] = rblock->buffer[0 + 2];
                //printf("0: 0x%x\n", rblock->buffer[0 + 2]);
                printf("rpmsg_master_recv: master[%d]<--remote[%d], remote ept id = 0x%08x\n", master_id, remote_id, info->map->r_ept_id);
            }
            // CMD(ACK): ......
            else {
                //......
            }
        }
        if (p_rpmsg_info[1]->cb_sta == 1) {
            p_rpmsg_info[1]->cb_sta = 0;

            rblock = (struct rpmsg_block_t *)p_rpmsg_info[1]->private;

            // CMD(ACK): RPMSG_ACK_TEST
            if (rblock->buffer[0] == RPMSG_ACK_TEST) {
                remote_id = rblock->buffer[1];
                block.buffer[1 + 2] = rblock->buffer[1 + 2];
                //printf("1: 0x%x\n", rblock->buffer[1 + 2]);
                printf("rpmsg_master_recv: master[%d]<--remote[%d], remote ept id = 0x%08x\n", master_id, remote_id, info->map->r_ept_id);
            }
            // CMD(ACK): ......
            else {
                //......
            }
        }
        if (p_rpmsg_info[2]->cb_sta == 1) {
            p_rpmsg_info[2]->cb_sta = 0;

            rblock = (struct rpmsg_block_t *)p_rpmsg_info[2]->private;

            // CMD(ACK): RPMSG_ACK_TEST
            if (rblock->buffer[0] == RPMSG_ACK_TEST) {
                remote_id = rblock->buffer[1];
                block.buffer[2 + 2] = rblock->buffer[2 + 2];
                //printf("2: 0x%x\n", rblock->buffer[2 + 2]);
                printf("rpmsg_master_recv: master[%d]<--remote[%d], remote ept id = 0x%08x\n", master_id, remote_id, info->map->r_ept_id);
            }
            // CMD(ACK): ......
            else {
                //......
            }
        }
        if ((block.buffer[0 + 2] == 0xff) &&
            (block.buffer[1 + 2] == 0xff) &&
            (block.buffer[2 + 2] == 0xff)) {
            printf("rpmsg test OK!\n");
            while (1) {
                ;
            }
            //break;
        }
        HAL_DelayMs(100);
    }

    for (i = 0; i < 3; i++) {
        free(p_rpmsg_info[i]->private);
        free(p_rpmsg_info[i]);
    }
}

#else
/*
 payload:       received message data
 payload_len:   received message len
 src:           source ept memory addr
 priv:          private data used in callback
*/
static int32_t remote_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    uint32_t i, cpu_id;
    struct rpmsg_info_t *info = (struct rpmsg_info_t *)priv;
    struct rpmsg_block_t *block = (struct rpmsg_block_t *)info->private;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    if (src == info->map->m_ept_id) {      // check source ept addr
        block->len = payload_len;
        memcpy(block->buffer, payload, payload_len);
        info->cb_sta = 1;
    }

    return RL_RELEASE;
}

static void rpmsg_remote_test(void)
{
    uint32_t i, master_id, remote_id;
    struct rpmsg_info_t *info;
    struct rpmsg_block_t *block;

    rpmsg_share_mem_check();
    master_id = MASTER_ID;
    remote_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    info = malloc(sizeof(struct rpmsg_info_t));
    if (info == NULL) {
        printf("info malloc error!\n");
        while (1) {
            ;
        }
    }
    info->private = malloc(sizeof(struct rpmsg_block_t));
    if (info->private == NULL) {
        printf("info malloc error!\n");
        while (1) {
            ;
        }
    }

    info->map = &rpmsg_ept_map_table[remote_id];
    info->cb_sta = 0;
    info->instance = rpmsg_remote_get_instance(master_id, remote_id);
    info->ept = rpmsg_lite_create_ept(info->instance, info->map->r_ept_id, remote_ept_cb, info);
    while (1) {
        if (info->cb_sta == 1) {
            info->cb_sta = 0;

            block = (struct rpmsg_block_t *)info->private;

            // CMD(ACK): RPMSG_CMD_PROB
            if (block->buffer[0] == RPMSG_CMD_PROB) {
                block->buffer[0] = RPMSG_ACK_PROB;
                block->buffer[1] = remote_id;
                block->len = 2;
                rpmsg_lite_send(info->instance, info->ept, info->map->m_ept_id, block->buffer, block->len, RL_BLOCK);
            }
            // CMD(ACK): RPMSG_CMD_TEST
            else if (block->buffer[0] == RPMSG_CMD_TEST) {
                printf("rpmsg_remote_recv: remote[%d]<--master[%d], master ept id = 0x%08x\n", remote_id, block->buffer[1], info->map->m_ept_id);

                block->buffer[0] = RPMSG_ACK_TEST;
                block->buffer[1] = remote_id;

                i = rpmsg_get_remote_index(remote_id);
                block->buffer[i + 2] |= 0xaa;

                printf("rpmsg_remote_send: remote[%d]-->master[%d], master ept id = 0x%08x\n", remote_id, master_id, info->map->m_ept_id);
                rpmsg_lite_send(info->instance, info->ept, info->map->m_ept_id, block->buffer, block->len, RL_BLOCK);
            }
            // CMD(ACK): ......
            else {
                //......
            }
        }
        HAL_DelayMs(100);
    }
}
#endif

#endif
/************************************************/
/*                                              */
/*              RPMSG_LINUX_TEST                */
/*                                              */
/************************************************/
#ifdef RPMSG_LINUX_TEST
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"

// test is CPU0 as master and CPU3 as remote.
#define MASTER_ID   ((uint32_t)0)
#define REMOTE_ID_3 ((uint32_t)3)

// define remote endpoint id for test
#define RPMSG_HAL_REMOTE_TEST3_EPT      0x3003U
#define RPMSG_HAL_REMOTE_TEST_EPT3_NAME "rpmsg-ap3-ch0"

#define RPMSG_HAL_TEST_MSG "Rockchip rpmsg linux test!"

/* TODO: These are defined in the linked script gcc_arm.ld.S */
extern uint32_t __linux_share_rpmsg_start__[];
extern uint32_t __linux_share_rpmsg_end__[];

#define RPMSG_LINUX_MEM_BASE ((uint32_t)&__linux_share_rpmsg_start__)
#define RPMSG_LINUX_MEM_END  ((uint32_t)&__linux_share_rpmsg_end__)
#define RPMSG_LINUX_MEM_SIZE (2UL * RL_VRING_OVERHEAD)

struct rpmsg_block_t {
    uint32_t len;
    uint8_t buffer[496 - 4];
};

struct rpmsg_info_t {
    struct rpmsg_lite_instance *instance;
    struct rpmsg_lite_endpoint *ept;
    uint32_t cb_sta;    // callback status flags
    void * private;
    uint32_t m_ept_id;
};

static void rpmsg_share_mem_check(void)
{
    if ((RPMSG_LINUX_MEM_BASE + RPMSG_LINUX_MEM_SIZE) > RPMSG_LINUX_MEM_END) {
        printf("shared memory size error!\n");
        while (1) {
            ;
        }
    }
}

rpmsg_ns_new_ept_cb rpmsg_ns_cb(uint32_t new_ept, const char *new_ept_name, uint32_t flags, void *user_data)
{
    uint32_t cpu_id;
    char ept_name[RL_NS_NAME_SIZE];

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    strncpy(ept_name, new_ept_name, RL_NS_NAME_SIZE);
    printf("rpmsg remote: new_ept-0x%" PRIx32 " name-%s\n", new_ept, ept_name);
}

static int32_t remote_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    int ret;
    uint32_t cpu_id;
    struct rpmsg_info_t *info = (struct rpmsg_info_t *)priv;
    struct rpmsg_block_t *block = (struct rpmsg_block_t *)info->private;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    info->m_ept_id = src;
    block->len = payload_len;
    memcpy(block->buffer, payload, payload_len);
    info->cb_sta = 1;
    printf("rpmsg remote: msg: %s\n", block->buffer);

    return RL_RELEASE;
}

static void rpmsg_linux_test(void)
{
    uint32_t master_id, remote_id, i;
    struct rpmsg_info_t *info;
    struct rpmsg_block_t *block;
    uint32_t ept_flags;
    void *ns_cb_data;

    rpmsg_share_mem_check();
    master_id = MASTER_ID;
    remote_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    printf("rpmsg remote: remote core cpu_id-%" PRId32 "\n", remote_id);
    printf("rpmsg remote: shmem_base-0x%" PRIx32 " shmem_end-%" PRIx32 "\n", RPMSG_LINUX_MEM_BASE, RPMSG_LINUX_MEM_END);

    info = malloc(sizeof(struct rpmsg_info_t));
    if (info == NULL) {
        printf("info malloc error!\n");
        while (1) {
            ;
        }
    }
    info->private = malloc(sizeof(struct rpmsg_block_t));
    if (info->private == NULL) {
        printf("info malloc error!\n");
        while (1) {
            ;
        }
    }

    info->instance = rpmsg_lite_remote_init((void *)RPMSG_LINUX_MEM_BASE, RL_PLATFORM_SET_LINK_ID(master_id, remote_id), RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(info->instance);
    printf("rpmsg remote: link up! link_id-0x%" PRIx32 "\n", info->instance->link_id);
    rpmsg_ns_bind(info->instance, rpmsg_ns_cb, &ns_cb_data);
    info->cb_sta = 0;
    info->ept = rpmsg_lite_create_ept(info->instance, RPMSG_HAL_REMOTE_TEST3_EPT, remote_ept_cb, info);
    ept_flags = RL_NS_CREATE;
    rpmsg_ns_announce(info->instance, info->ept, RPMSG_HAL_REMOTE_TEST_EPT3_NAME, ept_flags);
    for (i = 0; i < 10; i++) {
        while (1) {
            if (info->cb_sta == 1) {
                info->cb_sta = 0;
                rpmsg_lite_send(info->instance, info->ept, info->m_ept_id, RPMSG_HAL_TEST_MSG, sizeof(RPMSG_HAL_TEST_MSG), RL_BLOCK);
                break;
            }
            __NOP();
        }
    }
}
#endif

/********************* Public Function Definition ****************************/

void TEST_DEMO_GIC_Init(void)
{
    HAL_GIC_Init(&irqConfig);
}

void test_demo(void)
{
#if defined(GPIO_TEST) && defined(CPU0)
    gpio_test();
#endif

#if defined(GPIO_VIRTUAL_MODEL_TEST) && defined(CPU0)
    gpio_virtual_model_test();
#endif

#if defined(SOFTIRQ_TEST) && defined(CPU3)
    softirq_test();
#endif

#ifdef RPMSG_TEST
#ifdef PRIMARY_CPU /*CPU1*/
    printf("PRIMARY_CPU:%d\n", PRIMARY_CPU);
    rpmsg_master_test();
#else
    rpmsg_remote_test();
#endif
#endif

#if defined(RPMSG_LINUX_TEST) && defined(CPU3)
    rpmsg_linux_test();
#endif

#if defined(IRQ_PREEMPT_TEST) && defined(CPU3)
    irq_preempt_test();
#endif
}
