/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include <stdlib.h>

/********************* Private MACRO Definition ******************************/
//#define GPIO_TEST
//#define GPIO_VIRTUAL_MODEL_TEST
//#define RPMSG_LINUX_TEST
//#define SYSTICK_TEST
//#define TIMER_TEST
//#define TIMER_INTMUX_TEST

/********************* Private Structure Definition **************************/

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ***************************/

/************************************************/
/*                                              */
/*                 HW Borad config              */
/*                                              */
/************************************************/

/************************************************/
/*                                              */
/*                  GPIO_TEST                   */
/*                                              */
/************************************************/
#ifdef GPIO_TEST
static void gpio1_isr(uint32_t irq, void *args)
{
    HAL_GPIO_IRQHandler(GPIO1, GPIO_BANK1);
}

static HAL_Status b7_call_back(eGPIO_bankId bank, uint32_t pin, void *args)
{
    HAL_DBG("GPIO1B7 callback!\n");

    return HAL_OK;
}

static void gpio_test(void)
{
    uint32_t level;

    /* set pinctrl function */
    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_B7,
                         PIN_CONFIG_MUX_FUNC0);
    /* Test pinctrl pull */
    HAL_DBG("test_gpio pull UP\n");
    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_B7,
                         PIN_CONFIG_PUL_UP);
    HAL_DelayMs(3000);
    HAL_DBG("test_gpio pull DOWN\n");
    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_B7,
                         PIN_CONFIG_PUL_DOWN);
    HAL_DelayMs(3000);

    /* Test GPIO output */
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B7, GPIO_OUT);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    HAL_DBG("test_gpio 1b7 level = %d\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO1, GPIO_PIN_B7, GPIO_HIGH);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    HAL_DBG("test_gpio 1b7 output high level = %d\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO1, GPIO_PIN_B7, GPIO_LOW);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    HAL_DBG("test_gpio 1b7 output low level = %d\n", level);
    HAL_DelayMs(3000);

    /* Test GPIO interrupt */
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B7, GPIO_IN);
    HAL_INTMUX_SetIRQHandler(GPIO1_IRQn, gpio1_isr, NULL);
    HAL_IRQ_HANDLER_SetGpioIRQHandler(GPIO_BANK1, GPIO_PIN_B7, b7_call_back, NULL);
    HAL_INTMUX_EnableIRQ(GPIO1_IRQn);
    HAL_GPIO_SetIntType(GPIO1, GPIO_PIN_B7, GPIO_INT_TYPE_EDGE_BOTH);
    HAL_GPIO_EnableIRQ(GPIO1, GPIO_PIN_B7);
    HAL_DBG("test_gpio interrupt ready\n");
}
#endif

/************************************************/
/*                                              */
/*          GPIO_VIRTUAL_MODEL_TEST             */
/*                                              */
/************************************************/
#ifdef GPIO_VIRTUAL_MODEL_TEST
static void gpio0_exp3_isr(uint32_t irq, void *args)
{
    HAL_GPIO_IRQHandler(GPIO0_EXP3, GPIO_BANK0_EXP3);
}

static HAL_Status c3_call_back(eGPIO_bankId bank, uint32_t pin, void *args)
{
    HAL_DBG("GPIO0C3 exp callback!\n");

    return HAL_OK;
}

static void gpio_virtual_model_test(void)
{
    uint32_t level;

    /* set pinctrl function */
    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_C3,
                         PIN_CONFIG_MUX_FUNC0);

    /* set pin group configuration */
    HAL_GPIO_EnableVirtualModel(GPIO0);
    HAL_GPIO_SetVirtualModel(GPIO0,
                             GPIO_PIN_A0 | GPIO_PIN_A1 | GPIO_PIN_A2 | GPIO_PIN_A3 |
                             GPIO_PIN_A4 | GPIO_PIN_A5 | GPIO_PIN_A6 | GPIO_PIN_A7 |
                             GPIO_PIN_B0 | GPIO_PIN_B1 | GPIO_PIN_B2 | GPIO_PIN_B3 |
                             GPIO_PIN_B4 | GPIO_PIN_B5 | GPIO_PIN_B6 | GPIO_PIN_B7 |
                             GPIO_PIN_C0 | GPIO_PIN_C1 | GPIO_PIN_C2 |
                             GPIO_PIN_C4 | GPIO_PIN_C5 | GPIO_PIN_C6 | GPIO_PIN_C7 |
                             GPIO_PIN_D0 | GPIO_PIN_D1 | GPIO_PIN_D2 | GPIO_PIN_D3 |
                             GPIO_PIN_D4 | GPIO_PIN_D5 | GPIO_PIN_D6 | GPIO_PIN_D7,
                             GPIO_VIRTUAL_MODEL_OS_A);
    HAL_GPIO_SetVirtualModel(GPIO0,
                             GPIO_PIN_C3,
                             GPIO_VIRTUAL_MODEL_OS_D);

    /* Test GPIO output */
    HAL_GPIO_SetPinDirection(GPIO0_EXP3, GPIO_PIN_C3, GPIO_OUT);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_C3);
    HAL_DBG("test gpio 0c3 level = %d\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO0_EXP3, GPIO_PIN_C3, GPIO_HIGH);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_C3);
    HAL_DBG("test_gpio 0c3 output high level = %d\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO0_EXP3, GPIO_PIN_C3, GPIO_LOW);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_C3);
    HAL_DBG("test_gpio 0c3 output low level = %d\n", level);
    HAL_DelayMs(3000);

    /* Test GPIO interrupt */
    HAL_GPIO_SetPinDirection(GPIO0_EXP3, GPIO_PIN_C3, GPIO_IN);
    HAL_NVIC_SetIRQHandler(GPIO0_3_IRQn, gpio0_exp3_isr);
    HAL_IRQ_HANDLER_SetGpioIRQHandler(GPIO_BANK0_EXP3, GPIO_PIN_C3, c3_call_back, NULL);
    HAL_NVIC_EnableIRQ(GPIO0_3_IRQn);
    HAL_GPIO_SetIntType(GPIO0_EXP3, GPIO_PIN_C3, GPIO_INT_TYPE_EDGE_BOTH);
    HAL_GPIO_EnableIRQ(GPIO0_EXP3, GPIO_PIN_C3);
    HAL_DBG("test gpio exp interrupt ready\n");
}
#endif

/************************************************/
/*                                              */
/*              RPMSG_LINUX_TEST                */
/*                                              */
/************************************************/
#ifdef RPMSG_LINUX_TEST
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"

// CPU0 as master and MCU as remote.
#define MASTER_ID ((uint32_t)0)
#define REMOTE_ID ((uint32_t)3)

// define remote endpoint id for test
#define RPMSG_HAL_REMOTE_TEST_EPT      0x4003U
#define RPMSG_HAL_REMOTE_TEST_EPT_NAME "rpmsg-mcu0-test"

#define RPMSG_HAL_TEST_MSG "Rockchip rpmsg linux test!"

/* TODO: These are defined in the linked script gcc_arm.ld.S */
extern uint32_t __linux_share_rpmsg_start__[];
extern uint32_t __linux_share_rpmsg_end__[];

#define RPMSG_LINUX_MEM_BASE ((uint32_t)&__linux_share_rpmsg_start__)
#define RPMSG_LINUX_MEM_END  ((uint32_t)&__linux_share_rpmsg_end__)
#define RPMSG_LINUX_MEM_SIZE (2UL * RL_VRING_OVERHEAD)

#define RPMSG_PERF_TEST_LOOP       (1024U * 1024U)
#define RPMSG_PERF_TEST_TIMER_RATE PLL_INPUT_OSC_RATE
#define RPMSG_PERF_TEST_PAYLOAD    RL_BUFFER_PAYLOAD_SIZE
struct rpmsg_block_t {
    uint32_t len;
    uint8_t buffer[RL_BUFFER_PAYLOAD_SIZE];
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
        HAL_DBG("share memory size error!\n");
        while (1) {
            ;
        }
    }
}

rpmsg_ns_new_ept_cb rpmsg_ns_cb(uint32_t new_ept, const char *new_ept_name, uint32_t flags, void *user_data)
{
    char ept_name[RL_NS_NAME_SIZE];

    strncpy(ept_name, new_ept_name, RL_NS_NAME_SIZE);
    HAL_DBG("rpmsg remote: new_ept-0x%" PRIx32 " name-%s\n", new_ept, ept_name);
}

static int32_t remote_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    int ret;
    struct rpmsg_info_t *info = (struct rpmsg_info_t *)priv;
    struct rpmsg_block_t *block = (struct rpmsg_block_t *)info->private;

    info->m_ept_id = src;
    block->len = payload_len;
    memcpy(block->buffer, payload, payload_len);
    info->cb_sta = 1;
    //HAL_DBG("rpmsg remote: msg: %s\n", block->buffer);
    ret = rpmsg_lite_send(info->instance, info->ept, info->m_ept_id, RPMSG_HAL_TEST_MSG, strlen(RPMSG_HAL_TEST_MSG), RL_BLOCK);

    if (ret) {
        HAL_DBG("rpmsg_lite_send error!\n");
    }

    return RL_RELEASE;
}

static void rpmsg_linux_test(void)
{
    uint32_t master_id, remote_id;
    struct rpmsg_info_t *info;
    struct rpmsg_block_t *block;
    uint32_t ept_flags;
    void *ns_cb_data;

    rpmsg_share_mem_check();
    master_id = MASTER_ID;
    remote_id = REMOTE_ID;
    HAL_DBG("rpmsg remote: remote core cpu_id-%" PRId32 "\n", remote_id);
//    HAL_DBG("rpmsg remote: shmem_base-0x%" PRIx32 " shmem_end-%" PRIx32 "\n", RPMSG_LINUX_MEM_BASE, RPMSG_LINUX_MEM_END);

    info = malloc(sizeof(struct rpmsg_info_t));
    if (info == NULL) {
        HAL_DBG("info malloc error!\n");
        while (1) {
            ;
        }
    }
    info->private = malloc(sizeof(struct rpmsg_block_t));
    if (info->private == NULL) {
        HAL_DBG("info malloc error!\n");
        while (1) {
            ;
        }
    }

    info->instance = rpmsg_lite_remote_init((void *)RPMSG_LINUX_MEM_BASE, RL_PLATFORM_SET_LINK_ID(master_id, remote_id), RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(info->instance);
    HAL_DBG("rpmsg remote: link up! link_id-0x%" PRIx32 "\n", info->instance->link_id);
    rpmsg_ns_bind(info->instance, rpmsg_ns_cb, &ns_cb_data);
    info->ept = rpmsg_lite_create_ept(info->instance, RPMSG_HAL_REMOTE_TEST_EPT, remote_ept_cb, info);
    ept_flags = RL_NS_CREATE;
    rpmsg_ns_announce(info->instance, info->ept, RPMSG_HAL_REMOTE_TEST_EPT_NAME, ept_flags);
    while (info->cb_sta != 1) {
        HAL_DelayMs(1);
    }
    rpmsg_lite_send(info->instance, info->ept, info->m_ept_id, RPMSG_HAL_TEST_MSG, sizeof(RPMSG_HAL_TEST_MSG), RL_BLOCK);
}
#endif

/************************************************/
/*                                              */
/*                SYSTICK_TEST                  */
/*                                              */
/************************************************/
#ifdef SYSTICK_TEST
static uint64_t last_tick_time = 0;
static void systick_isr(uint32_t irq, void *args)
{
    uint64_t curr;

    curr = HAL_GetSysTimerCount();
    if (last_tick_time != 0) {
        uint32_t interval = (uint32_t)((curr - last_tick_time) * 41.67);
        HAL_DBG("systick_isr: interval=%dns\n", interval);
    }
    HAL_SYSTICK_IRQHandler();
    last_tick_time = curr;
}

static void systick_test(void)
{
    HAL_NVIC_SetIRQHandler(SysTick_IRQn, systick_isr);
    HAL_NVIC_EnableIRQ(SysTick_IRQn);
    HAL_SetTickFreq(1);
    HAL_SYSTICK_Init();
}
#endif

/************************************************/
/*                                              */
/*                  TIMER_TEST                  */
/*                                              */
/************************************************/
#ifdef TIMER_TEST
static int timer_int_count = 0;
static uint32_t latency_sum = 0;
static uint32_t latency_max = 0;
struct TIMER_REG *test_timer = TIMER10;

static void timer_isr(void)
{
    uint32_t count;
    uint32_t latency;

    count = (uint32_t)HAL_TIMER_GetCount(test_timer);
    if (count < 1000000) {
        /* 24M timer: 41.67ns per count */
        latency = count * 41;
        timer_int_count++;
        HAL_DBG("timer_test: latency=%d ns(count=%d)\n", latency, count);
        latency_sum += latency;
        latency_max = latency_max > latency ? latency_max : latency;
    }

    if (timer_int_count == 100) {
        HAL_DBG("timer_test: latency avg=%dns,max=%dns\n", latency_sum / timer_int_count, latency_max);
        timer_int_count = 0;
        latency_sum = 0;
        latency_max = 0;
        HAL_TIMER_ClrInt(test_timer);
        HAL_TIMER_Stop_IT(test_timer);
    }

    HAL_TIMER_ClrInt(test_timer);
}

static void timer_test(void)
{
    uint64_t start, end;
    uint32_t count;

    HAL_DBG("timer_test start\n");
    start = HAL_GetSysTimerCount();
    HAL_DelayUs(1000000);
    end = HAL_GetSysTimerCount();
    count = (uint32_t)(end - start);
    HAL_DBG("sys_timer 1s count: %d(%lld, %lld)\n", count, start, end);

    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 2000000000);
    HAL_TIMER_Start(test_timer);
    start = HAL_TIMER_GetCount(test_timer);
    HAL_DelayUs(1000000);
    end = HAL_TIMER_GetCount(test_timer);
    count = (uint32_t)(end - start);
    HAL_DBG("test_timer 1s count: %d(%lld, %lld)\n", count, start, end);
    HAL_TIMER_Stop(test_timer);

    HAL_NVIC_SetIRQHandler(TIMER10_IRQn, timer_isr);
    HAL_NVIC_EnableIRQ(TIMER10_IRQn);
    HAL_DBG("timer_test: 1s interrupt start\n");
    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 24000000);
    HAL_TIMER_Start_IT(test_timer);
}
#endif

/************************************************/
/*                                              */
/*              TIMER_INTMUX_TEST               */
/*                                              */
/************************************************/
#ifdef TIMER_INTMUX_TEST
static int timer_int_count = 0;
static uint32_t latency_sum = 0;
static uint32_t latency_max = 0;
struct TIMER_REG *test_timer = TIMER8;

static void timer_isr(uint32_t irq, void *args)
{
    uint32_t count;
    uint32_t latency;

    count = (uint32_t)HAL_TIMER_GetCount(test_timer);
    /* 24M timer: 41.67ns per count */
    latency = count * 41;
    HAL_DBG("timer_test: latency=%d ns(count=%d)\n", latency, count);
    timer_int_count++;
    latency_sum += latency;
    latency_max = latency_max > latency ? latency_max : latency;
    if (timer_int_count == 100) {
        HAL_DBG("timer_test: latency avg=%dns,max=%dns\n", latency_sum / timer_int_count, latency_max);
        timer_int_count = 0;
        latency_sum = 0;
        latency_max = 0;
        HAL_TIMER_ClrInt(test_timer);
        HAL_TIMER_Stop_IT(test_timer);
    }

    HAL_TIMER_ClrInt(test_timer);
}

static void timer_test(void)
{
    uint64_t start, end;
    uint32_t count;

    HAL_DBG("timer_test start\n");
    start = HAL_GetSysTimerCount();
    HAL_DelayUs(1000000);
    end = HAL_GetSysTimerCount();
    count = (uint32_t)(end - start);
    HAL_DBG("sys_timer 1s count: %d(%lld, %lld)\n", count, start, end);

    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 2000000000);
    HAL_TIMER_Start(test_timer);
    start = HAL_TIMER_GetCount(test_timer);
    HAL_DelayUs(1000000);
    end = HAL_TIMER_GetCount(test_timer);
    count = (uint32_t)(end - start);
    HAL_DBG("test_timer 1s count: %d(%lld, %lld)\n", count, start, end);
    HAL_TIMER_Stop(test_timer);

    HAL_INTMUX_SetIRQHandler(TIMER8_IRQn, timer_isr, NULL);
    HAL_INTMUX_EnableIRQ(TIMER8_IRQn);
    HAL_DBG("timer_test: 1s interrupt start\n");
    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 24000000);
    HAL_TIMER_Start_IT(test_timer);
}
#endif

void test_demo(void)
{
#if defined(GPIO_TEST)
    gpio_test();
#endif

#ifdef GPIO_VIRTUAL_MODEL_TEST
    gpio_virtual_model_test();
#endif

#ifdef RPMSG_LINUX_TEST
    rpmsg_linux_test();
#endif

#ifdef SYSTICK_TEST
    systick_test();
#endif

#ifdef TIMER_TEST
    timer_test();
#endif

#ifdef TIMER_INTMUX_TEST
    timer_test();
#endif
}
