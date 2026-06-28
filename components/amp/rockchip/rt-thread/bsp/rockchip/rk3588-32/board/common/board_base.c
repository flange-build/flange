/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2021-04-12     Steven Liu   first implementation
 * 2022-08-22     Steven Liu   update project structure and related code
 */

#include <rthw.h>
#include <rtthread.h>

#include "board.h"
#include "cp15.h"
#include "mmu.h"
#include "hal_base.h"
#include "hal_bsp.h"
#include "drv_heap.h"

struct mem_desc platform_mem_desc[] =
{
#ifdef RT_USING_UNCACHE_HEAP
    {FIRMWARE_BASE, FIRMWARE_BASE + FIRMWARE_SIZE - 1, FIRMWARE_BASE, NORMAL_MEM},
    {RT_UNCACHE_HEAP_BASE, RT_UNCACHE_HEAP_BASE + RT_UNCACHE_HEAP_SIZE - 1, RT_UNCACHE_HEAP_BASE, UNCACHED_MEM},
#else
    {FIRMWARE_BASE, FIRMWARE_BASE + DRAM_SIZE - 1, FIRMWARE_BASE, NORMAL_MEM},
#endif
    {SHMEM_BASE, SHMEM_BASE + SHMEM_SIZE - 1, SHMEM_BASE, SHARED_MEM},
#ifdef LINUX_RPMSG_BASE
    {LINUX_RPMSG_BASE, LINUX_RPMSG_BASE + LINUX_RPMSG_SIZE - 1, LINUX_RPMSG_BASE, UNCACHED_MEM},
#endif
    {0xF0000000, 0xFF000000 - 1, 0xF0000000, DEVICE_MEM}
};

const rt_uint32_t platform_mem_desc_size = sizeof(platform_mem_desc) / sizeof(platform_mem_desc[0]);

#ifdef RT_USING_PIN
#include "iomux.h"
#endif

#ifdef RT_USING_UART
#include "drv_uart.h"
#endif

#ifdef RT_USING_SYSTICK
#define TICK_IRQn CNTPNS_IRQn
static uint32_t g_tick_load;
#endif

#if defined(RT_USING_UART2)
RT_WEAK const struct uart_board g_uart2_board =
{
    .baud_rate = UART_BR_1500000,
    .dev_flag = ROCKCHIP_UART_SUPPORT_FLAG_DEFAULT,
    .bufer_size = RT_SERIAL_RB_BUFSZ,
    .name = "uart2",
};
#endif /* RT_USING_UART2 */

#if defined(RT_USING_UART4)
RT_WEAK const struct uart_board g_uart4_board =
{
    .baud_rate = UART_BR_1500000,
    .dev_flag = ROCKCHIP_UART_SUPPORT_FLAG_DEFAULT,
    .bufer_size = RT_SERIAL_RB_BUFSZ,
    .name = "uart4",
};
#endif /* RT_USING_UART4 */

#if defined(RT_USING_UART5)
RT_WEAK const struct uart_board g_uart5_board =
{
    .baud_rate = UART_BR_1500000,
    .dev_flag = ROCKCHIP_UART_SUPPORT_FLAG_DEFAULT,
    .bufer_size = RT_SERIAL_RB_BUFSZ,
    .name = "uart5",
};
#endif /* RT_USING_UART4 */

extern void SysTick_Handler(void);
RT_WEAK void tick_isr(int vector, void *param)
{
    /* enter interrupt */
    rt_interrupt_enter();

    HAL_IncTick();
    rt_tick_increase();
#ifdef RT_USING_SYSTICK
    HAL_GIC_ClearPending(TICK_IRQn);
    HAL_GIC_EndOfInterrupt(TICK_IRQn);
    HAL_ARCHTIMER_SetCNTPTVAL(g_tick_load);
#else
    HAL_TIMER_ClrInt(TICK_TIMER);
#endif

    /* leave interrupt */
    rt_interrupt_leave();
}

void idle_wfi(void)
{
    asm volatile("wfi");
}

static struct GIC_AMP_IRQ_INIT_CFG irqsConfig[] =
{
    /* TODO: Config the irqs here. */

    /* TODO: By default, UART2 is used for master core CPU0, and UART5 is used for remote core CPU3 */
    GIC_AMP_IRQ_CFG_ROUTE(UART2_IRQn, 0xd0, CPU_GET_AFFINITY(0, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(UART5_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    /* DMAC0 for I2S0/I2S1 and DMAC1 for I2S2/I2S3 */
    GIC_AMP_IRQ_CFG_ROUTE(DMAC0_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(DMAC1_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),

    GIC_AMP_IRQ_CFG_ROUTE(0, 0, CPU_GET_AFFINITY(0, 0)),   /* sentinel */
};

static struct GIC_IRQ_AMP_CTRL irqConfig =
{
    .cpuAff = CPU_GET_AFFINITY(0, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(3, 0),
    .irqsCfg = &irqsConfig[0],
};

#ifdef RT_USING_SYSTICK

static void generic_timer_config(void)
{
    uint32_t freq;

    freq = HAL_ARCHTIMER_GetCNTFRQ();

    // Calculate load value
    g_tick_load = (freq / RT_TICK_PER_SECOND) - 1U;

    HAL_ARCHTIMER_SetCNTPCTL(0U);
    HAL_ARCHTIMER_SetCNTPTVAL(g_tick_load);
    HAL_GIC_ClearPending(TICK_IRQn);
    rt_hw_interrupt_install(TICK_IRQn, tick_isr, RT_NULL, "tick");
    rt_hw_interrupt_umask(TICK_IRQn);
    HAL_ARCHTIMER_SetCNTPCTL(1U);
}
#endif

/**
 *  Initialize the Hardware related stuffs. Called from rtthread_startup()
 *  after interrupt disabled.
 */
void rt_hw_board_init(void)
{
    /* HAL_Init */
    HAL_Init();

    /* hal bsp init */
    BSP_Init();

    /* initialize hardware interrupt */
    HAL_GIC_Init(&irqConfig);
    rt_hw_interrupt_init();

    /* tick init */
    HAL_SetTickFreq(1000 / RT_TICK_PER_SECOND);

#ifdef RT_USING_SYSTICK
    generic_timer_config();
#else
    rt_hw_interrupt_install(TICK_IRQn, tick_isr, RT_NULL, "tick");
    rt_hw_interrupt_umask(TICK_IRQn);
    HAL_TIMER_Init(TICK_TIMER, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(TICK_TIMER, (PLL_INPUT_OSC_RATE / RT_TICK_PER_SECOND) - 1);
    HAL_TIMER_Start_IT(TICK_TIMER);
#endif

#ifdef RT_USING_PIN
    rt_hw_iomux_config();
#endif

    /* initialize uart */
#ifdef RT_USING_UART
    rt_hw_usart_init();
#endif

#ifdef RT_USING_CONSOLE
    rt_console_set_device(RT_CONSOLE_DEVICE_NAME);
#endif

#ifdef RT_USING_HEAP
    /* initialize memory system */
    rt_system_heap_init(RT_HW_HEAP_BEGIN, RT_HW_HEAP_END);
#endif

#ifdef RT_USING_UNCACHE_HEAP
#if ((RT_UNCACHE_HEAP_BASE & 0x000fffff) || (RT_UNCACHE_HEAP_SIZE & 0x000fffff) || (DRAM_SIZE <= RT_UNCACHE_HEAP_SIZE))
#error "Uncache heap base and size should be at least 1M align, Uncache heap size must less than dram size!";
#endif
    rt_kprintf("base_mem: BASE = 0x%08x, SIZE = 0x%08x\n", FIRMWARE_BASE, FIRMWARE_SIZE);
    rt_kprintf("uncached_heap: BASE = 0x%08x, SIZE = 0x%08x\n", RT_UNCACHE_HEAP_BASE, RT_UNCACHE_HEAP_SIZE);
    rt_uncache_heap_init((void *)RT_UNCACHE_HEAP_BASE, (void *)(RT_UNCACHE_HEAP_BASE + RT_UNCACHE_HEAP_SIZE));
#else
    rt_kprintf("base_mem: BASE = 0x%08x, SIZE = 0x%08x\n", FIRMWARE_BASE, DRAM_SIZE);
#endif
    rt_kprintf("share_mem: BASE = 0x%08x, SIZE = 0x%08x\n", SHMEM_BASE, SHMEM_SIZE);

    rt_thread_idle_sethook(idle_wfi);

#ifdef RT_USING_COMPONENTS_INIT
    rt_components_board_init();
#endif
}

