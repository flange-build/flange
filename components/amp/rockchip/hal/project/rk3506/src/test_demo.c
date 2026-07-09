/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include <stdlib.h>
#include "simple_console.h"

/********************* Private MACRO Definition ******************************/
//#define GPIO_TEST
//#define GPIO_VIRTUAL_MODEL_TEST
//#define PERF_TEST
//#define PWM_TEST
//#define RPMSG_LINUX_TEST
//#define TIMER_TEST

//#define HAS_CONSOLE

#ifdef HAS_CONSOLE
#define CONSOLE_BUF_MAX  100
#define CONSOLE_LINE_MAX 10

static void command_testall_process(uint8_t *in, int len);
struct console_command command_testall = {
    .name = "testall",
    .help = "Run all auto test demos",
    .process = command_testall_process,
};
#endif

/********************* Private Structure Definition **************************/

static struct GIC_AMP_IRQ_INIT_CFG irqsConfig[] = {
/* TODO: Config the irqs here.
 * GIC version: GICv2
 * The priority higher than 0x80 is non-secure interrupt.
 */
#ifdef GPIO_TEST
    GIC_AMP_IRQ_CFG_ROUTE(GPIO1_IRQn, 0xd0, CPU_GET_AFFINITY(2, 0)),
#endif

#ifdef GPIO_VIRTUAL_MODEL_TEST
    GIC_AMP_IRQ_CFG_ROUTE(GPIO0_3_IRQn, 0xd0, CPU_GET_AFFINITY(2, 0)),
#endif

#ifdef HAS_CONSOLE
    GIC_AMP_IRQ_CFG_ROUTE(UART4_IRQn, 0xd0, CPU_GET_AFFINITY(2, 0)),
#endif

#ifdef TIMER_TEST
    GIC_AMP_IRQ_CFG_ROUTE(TIMER4_IRQn, 0xd0, CPU_GET_AFFINITY(2, 0)),
#endif

#ifdef RPMSG_LINUX_TEST
    GIC_AMP_IRQ_CFG_ROUTE(MAILBOX_BB_2_IRQn, 0xd0, CPU_GET_AFFINITY(2, 0)),
#endif

    GIC_AMP_IRQ_CFG_ROUTE(0, 0, CPU_GET_AFFINITY(1, 0)),   /* sentinel */
};

static struct GIC_IRQ_AMP_CTRL irqConfig = {
    .cpuAff = CPU_GET_AFFINITY(1, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(1, 0),
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
static void gpio1_isr(uint32_t irq, void *args)
{
    HAL_GPIO_IRQHandler(GPIO1, GPIO_BANK1);
}

static HAL_Status b7_call_back(eGPIO_bankId bank, uint32_t pin, void *args)
{
    printf("GPIO1B7 callback!\n");

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
    printf("test_gpio pull UP\n");
    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_B7,
                         PIN_CONFIG_PUL_UP);
    HAL_DelayMs(3000);
    printf("test_gpio pull DOWN\n");
    HAL_PINCTRL_SetParam(GPIO_BANK1,
                         GPIO_PIN_B7,
                         PIN_CONFIG_PUL_DOWN);
    HAL_DelayMs(3000);

    /* Test GPIO output */
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B7, GPIO_OUT);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    printf("test_gpio 1b7 level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO1, GPIO_PIN_B7, GPIO_HIGH);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    printf("test_gpio 1b7 output high level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO1, GPIO_PIN_B7, GPIO_LOW);
    level = HAL_GPIO_GetPinLevel(GPIO1, GPIO_PIN_B7);
    printf("test_gpio 1b7 output low level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);

    /* Test GPIO interrupt */
    HAL_GPIO_SetPinDirection(GPIO1, GPIO_PIN_B7, GPIO_IN);
    HAL_IRQ_HANDLER_SetIRQHandler(GPIO1_IRQn, gpio1_isr, NULL);
    HAL_IRQ_HANDLER_SetGpioIRQHandler(GPIO_BANK1, GPIO_PIN_B7, b7_call_back, NULL);
    HAL_GIC_Enable(GPIO1_IRQn);
    HAL_GPIO_SetIntType(GPIO1, GPIO_PIN_B7, GPIO_INT_TYPE_EDGE_RISING);
    HAL_GPIO_EnableIRQ(GPIO1, GPIO_PIN_B7);
    printf("test_gpio interrupt ready\n");
}
#endif

/************************************************/
/*                                              */
/*          GPIO_VIRTUAL_MODEL_TEST             */
/*                                              */
/************************************************/
#ifdef GPIO_VIRTUAL_MODEL_TEST
static void gpio0_exp_isr(uint32_t irq, void *args)
{
    HAL_GPIO_IRQHandler(GPIO0_EXP3, GPIO_BANK0_EXP3);
}

static HAL_Status b7_call_back(eGPIO_bankId bank, uint32_t pin, void *args)
{
    printf("GPIO0B7 exp callback!\n");

    return HAL_OK;
}

static void gpio_virtual_model_test(void)
{
    uint32_t level;

    /* set pinctrl function */
    HAL_PINCTRL_SetParam(GPIO_BANK0,
                         GPIO_PIN_B7,
                         PIN_CONFIG_MUX_FUNC0);

    /* set pin group configuration */
    HAL_GPIO_EnableVirtualModel(GPIO0);
    HAL_GPIO_SetVirtualModel(GPIO0,
                             GPIO_PIN_A0 | GPIO_PIN_A1 | GPIO_PIN_A2 | GPIO_PIN_A3 |
                             GPIO_PIN_A4 | GPIO_PIN_A5 | GPIO_PIN_A6 | GPIO_PIN_A7 |
                             GPIO_PIN_B0 | GPIO_PIN_B1 | GPIO_PIN_B2 | GPIO_PIN_B3 |
                             GPIO_PIN_B4 | GPIO_PIN_B5 | GPIO_PIN_B6 |
                             GPIO_PIN_C0 | GPIO_PIN_C1 | GPIO_PIN_C2 | GPIO_PIN_C3 |
                             GPIO_PIN_C4 | GPIO_PIN_C5 | GPIO_PIN_C6 | GPIO_PIN_C7 |
                             GPIO_PIN_D0 | GPIO_PIN_D1 | GPIO_PIN_D2 | GPIO_PIN_D3 |
                             GPIO_PIN_D4 | GPIO_PIN_D5 | GPIO_PIN_D6 | GPIO_PIN_D7,
                             GPIO_VIRTUAL_MODEL_OS_A);
    HAL_GPIO_SetVirtualModel(GPIO0,
                             GPIO_PIN_B7,
                             GPIO_VIRTUAL_MODEL_OS_D);

    /* Test GPIO output */
    HAL_GPIO_SetPinDirection(GPIO0_EXP3, GPIO_PIN_B7, GPIO_OUT);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_B7);
    printf("test gpio 0b7 level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO0_EXP3, GPIO_PIN_B7, GPIO_HIGH);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_B7);
    printf("test_gpio 0b7 output high level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);
    HAL_GPIO_SetPinLevel(GPIO0_EXP3, GPIO_PIN_B7, GPIO_LOW);
    level = HAL_GPIO_GetPinLevel(GPIO0_EXP3, GPIO_PIN_B7);
    printf("test_gpio 0b7 output low level = %" PRId32 "\n", level);
    HAL_DelayMs(3000);

    /* Test GPIO interrupt */
    HAL_GPIO_SetPinDirection(GPIO0_EXP3, GPIO_PIN_B7, GPIO_IN);
    HAL_IRQ_HANDLER_SetIRQHandler(GPIO0_3_IRQn, gpio0_exp_isr, NULL);
    HAL_IRQ_HANDLER_SetGpioIRQHandler(GPIO_BANK0_EXP3, GPIO_PIN_B7, b7_call_back, NULL);
    HAL_GIC_Enable(GPIO0_3_IRQn);
    HAL_GPIO_SetIntType(GPIO0_EXP3, GPIO_PIN_B7, GPIO_INT_TYPE_EDGE_RISING);
    HAL_GPIO_EnableIRQ(GPIO0_EXP3, GPIO_PIN_B7);
    printf("test gpio exp interrupt ready\n");
}
#endif

/************************************************/
/*                                              */
/*                  PERF_TEST                   */
/*                                              */
/************************************************/
#ifdef PERF_TEST
#include "benchmark.h"

uint32_t g_sum = 0;

static void perf_test(void)
{
    uint32_t loop = 1000, size = 64 * 1024;
    uint32_t *ptr;
    uint32_t time_start, time_end, time_ms;

    printf("Perftest Start:\n");
    benchmark_main();

    printf("memset test start:\n");
    ptr = (uint32_t *)malloc(size);
    if (ptr) {
        time_start = HAL_GetTick();
        for (int i = 0; i < loop; i++) {
            memset(ptr, i, size);
        }
        time_end = HAL_GetTick();
        time_ms = time_end - time_start;
        printf("memset bw=%" PRId32 "KB/s, time_ms=%d\n",
               1000 * (size * loop / 1024) / time_ms, time_ms);

        /* prevent optimization */
        for (int i = 0; i < size / sizeof(uint32_t); i++) {
            g_sum += ptr[i];
        }
        printf("sum=%d\n", g_sum);
        free(ptr);
    }
    printf("memset test end\n");

    printf("Perftest End:\n");
}
#endif

/************************************************/
/*                                              */
/*                  PWM_TEST                    */
/*                                              */
/************************************************/
#ifdef PWM_TEST
static struct PWM_HANDLE hal_pwm1_handle;
struct HAL_PWM_CONFIG hal_channel0_config = {
    .channel = 0,
    .periodNS = 100000,
    .dutyNS = 40000,
    .polarity = true,
};

struct HAL_PWM_CONFIG hal_channel1_config = {
    .channel = 1,
    .periodNS = 100000,
    .dutyNS = 20000,
    .polarity = false,
};

struct HAL_PWM_CONFIG hal_channel2_config = {
    .channel = 2,
    .periodNS = 100000,
    .dutyNS = 50000,
    .polarity = false,
};

static void HAL_IOMUX_PWM0_Config(void)
{
    HAL_PINCTRL_SetRMIO(GPIO_BANK0, GPIO_PIN_B0, RMIO_PWM1_CH0);
    HAL_PINCTRL_SetRMIO(GPIO_BANK0, GPIO_PIN_B1, RMIO_PWM1_CH1);
    HAL_PINCTRL_SetRMIO(GPIO_BANK0, GPIO_PIN_B2, RMIO_PWM1_CH2);
}

static void pwm_isr(uint32_t irq, void *args)
{
    struct PWM_HANDLE *pPWM = (struct PWM_HANDLE *)args;
    uint32_t i;

    for (i = 0; i < pPWM->channelNum; i++) {
        HAL_PWM_ChannelIRQHandler(pPWM, i);
        if (pPWM->pChHandle[i].mode == HAL_PWM_CAPTURE) {
            printf("chanel%d pos cycles = %ld and neg cycles = %ld\n", i,
                   pPWM->pChHandle[i].result.posCycles, pPWM->pChHandle[i].result.negCycles);
        }
    }
}

static void pwm_test(void)
{
    uint64_t result;
    uint8_t channel_mask;

    printf("pwm_test: test start:\n");

    uint32_t hal_pwm0_clk = HAL_CRU_ClkGetFreq(g_pwm1Dev.clkID);

    HAL_PWM_Init(&hal_pwm1_handle, g_pwm1Dev.pReg, hal_pwm0_clk);

    HAL_IOMUX_PWM0_Config();

    HAL_PWM_SetConfig(&hal_pwm1_handle, hal_channel0_config.channel, &hal_channel0_config);
    HAL_PWM_SetConfig(&hal_pwm1_handle, hal_channel1_config.channel, &hal_channel1_config);
    HAL_PWM_SetConfig(&hal_pwm1_handle, hal_channel2_config.channel, &hal_channel2_config);

    HAL_PWM_SetOutputOffset(&hal_pwm1_handle, hal_channel0_config.channel, 20000);
    HAL_PWM_SetOutputOffset(&hal_pwm1_handle, hal_channel1_config.channel, 30000);
    HAL_PWM_SetOutputOffset(&hal_pwm1_handle, hal_channel2_config.channel, 40000);

    HAL_PWM_Enable(&hal_pwm1_handle, hal_channel0_config.channel, HAL_PWM_CONTINUOUS);
    HAL_PWM_Enable(&hal_pwm1_handle, hal_channel1_config.channel, HAL_PWM_CONTINUOUS);
    HAL_PWM_Enable(&hal_pwm1_handle, hal_channel2_config.channel, HAL_PWM_CAPTURE);

    printf("pwm_test: 1s counter\n", __func__);
    HAL_PWM_EnableCounter(&hal_pwm1_handle, hal_channel2_config.channel);

    HAL_DelayMs(1000);

    HAL_PWM_GetCounterRes(&hal_pwm1_handle, hal_channel2_config.channel, &result);
    printf("pwm test: pwm counter res = 0x%08" PRIx32 "\n", result);

    HAL_PWM_DisableCounter(&hal_pwm1_handle, hal_channel2_config.channel);
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
#define REMOTE_ID ((uint32_t)2)

// define remote endpoint id for test
#define RPMSG_HAL_REMOTE_TEST_EPT      0x4002U
#define RPMSG_HAL_REMOTE_TEST_EPT_NAME "rpmsg-ap3-ch0"

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
        printf("share memory size error!\n");
        while (1) {
            ;
        }
    }
}

rpmsg_ns_new_ept_cb rpmsg_ns_cb(uint32_t new_ept, const char *new_ept_name, uint32_t flags, void *user_data)
{
    char ept_name[RL_NS_NAME_SIZE];

    strncpy(ept_name, new_ept_name, RL_NS_NAME_SIZE);
    printf("rpmsg remote: new_ept-0x%" PRIx32 " name-%s\n", new_ept, ept_name);
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
    //printf("rpmsg remote: msg: %s\n", block->buffer);
    ret = rpmsg_lite_send(info->instance, info->ept, info->m_ept_id, RPMSG_HAL_TEST_MSG, strlen(RPMSG_HAL_TEST_MSG), RL_BLOCK);

    if (ret) {
        printf("rpmsg_lite_send error!\n");
    }

    return ret;
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
    printf("rpmsg remote: remote core cpu_id-%" PRId32 "\n", remote_id);
//    printf("rpmsg remote: shmem_base-0x%" PRIx32 " shmem_end-%" PRIx32 "\n", RPMSG_LINUX_MEM_BASE, RPMSG_LINUX_MEM_END);

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
    info->ept = rpmsg_lite_create_ept(info->instance, RPMSG_HAL_REMOTE_TEST_EPT, remote_ept_cb, info);
    ept_flags = RL_NS_CREATE;
    rpmsg_ns_announce(info->instance, info->ept, RPMSG_HAL_REMOTE_TEST_EPT_NAME, ept_flags);
    while (info->cb_sta != 1) {
    }
    rpmsg_lite_send(info->instance, info->ept, info->m_ept_id, RPMSG_HAL_TEST_MSG, sizeof(RPMSG_HAL_TEST_MSG), RL_BLOCK);
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
struct TIMER_REG *test_timer = TIMER4;
static bool desc_timer = true;

static void timer_isr(uint32_t irq, void *args)
{
    uint32_t count;
    uint32_t latency;

    count = (uint32_t)HAL_TIMER_GetCount(test_timer);
    if (desc_timer) {
        count = 24000000 - count;
    }
    /* 24M timer: 41.67ns per count */
    latency = count * 41;
    printf("timer_test: latency=%" PRId32 "ns(count=%" PRId32 ")\n", latency, count);
    timer_int_count++;
    latency_sum += latency;
    latency_max = latency_max > latency ? latency_max : latency;
    if (timer_int_count == 100) {
        printf("timer_test: latency avg=%dns,max=%dns\n", latency_sum / timer_int_count, latency_max);
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

    printf("timer_test start\n");
    start = HAL_GetSysTimerCount();
    HAL_DelayUs(1000000);
    end = HAL_GetSysTimerCount();
    /* sys_timer: TIMER5 is a increment count TIMER */
    count = (uint32_t)(end - start);
    printf("sys_timer 1s count: %" PRId32 "(%lld, %lld)\n", count, start, end);

    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 2000000000);
    HAL_TIMER_Start(test_timer);
    start = HAL_TIMER_GetCount(test_timer);
    HAL_DelayUs(1000000);
    end = HAL_TIMER_GetCount(test_timer);
    /* Pay attention to the timer type */
    /* test_timer: TIMER4 is a decrement count TIMER */
    desc_timer = true;
    count = (uint32_t)(start - end);
    printf("test_timer 1s count: %" PRId32 "(%lld, %lld)\n", count, start, end);
    HAL_TIMER_Stop(test_timer);

    HAL_IRQ_HANDLER_SetIRQHandler(TIMER4_IRQn, timer_isr, NULL);
    HAL_GIC_Enable(TIMER4_IRQn);
    printf("timer_test: 1s interrupt start\n");
    HAL_TIMER_Init(test_timer, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(test_timer, 24000000);
    HAL_TIMER_Start_IT(test_timer);
}
#endif

/********************* Public Function Definition ****************************/

void TEST_DEMO_GIC_Init(void)
{
    HAL_GIC_Init(&irqConfig);
}

#ifndef HAS_CONSOLE
void test_demo(void)
#else
static void command_testall_process(uint8_t *in, int len)
#endif
{
#ifdef GPIO_TEST
    gpio_test();
#endif

#ifdef GPIO_VIRTUAL_MODEL_TEST
    gpio_virtual_model_test();
#endif

#ifdef PERF_TEST
    perf_test();
#endif

#ifdef PWM_TEST
    pwm_test();
#endif

#if defined(RPMSG_LINUX_TEST)
    rpmsg_linux_test();
#endif

#ifdef TIMER_TEST
    timer_test();
#endif
}

#ifdef HAS_CONSOLE
void test_demo(void)
{
    int i;
    uint8_t *lines[CONSOLE_LINE_MAX];

    for (i = 0; i < CONSOLE_LINE_MAX; i++) {
        lines[i] = malloc(CONSOLE_BUF_MAX);
        memset(lines[i], 0, CONSOLE_BUF_MAX);
    }

    console_init(&g_uart4Dev, lines, CONSOLE_BUF_MAX, CONSOLE_LINE_MAX);
    console_add_command(&command_testall);

    HAL_IRQ_HANDLER_SetIRQHandler(g_uart4Dev.irqNum, console_uart_isr, NULL);
    HAL_GIC_Enable(g_uart4Dev.irqNum);
    HAL_UART_EnableIrq(g_uart4Dev.pReg, 1);
    console_run(true);

    command_testall_process(NULL, 0);
}
#endif
