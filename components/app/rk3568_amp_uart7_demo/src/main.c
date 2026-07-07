/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * rk3568_amp_uart7_demo — Orange Pi CM4 AMP 协处理器固件（裸机 HAL，运行在 cpu3）。
 *
 * 基于 rk3568_amp_demo：保留 Linux↔AMP rpmsg echo 行为，仅把从核 console
 * 从 UART4_M1 切到 Orange Pi CM4 40pin 可引出的 UART7_M2：
 *   - UART7_TX_M2 = GPIO4_A2 = 40pin 15
 *   - UART7_RX_M2 = GPIO4_A3 = 40pin 16
 * baud rate 保持 1500000。
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"

#include <stdlib.h>
#include <string.h>

/* Linux = cpu0（master），本核 = cpu3（remote）。link-id 继续使用已验证的
 * 0x10（M=1、R=0），让从核新消息发 mailbox ch0、命中 stock Linux rpmsg-rx。 */
#define LINK_ID_M       1U
#define LINK_ID_R       0U
#define DEMO_EPT_ADDR   0x3003U
#define DEMO_EPT_NAME   "rpmsg-ap3-ch0"
#define DEMO_ECHO_MSG   "Rockchip rpmsg linux test!"

extern uint32_t __linux_share_rpmsg_start__[];
#define LINUX_RPMSG_MEM ((void *)&__linux_share_rpmsg_start__)

/********************* GIC 中断路由（仅本核 cpu3）****************************/
static struct GIC_AMP_IRQ_INIT_CFG irqsConfig[] = {
    GIC_AMP_IRQ_CFG_ROUTE(AMP_CPUOFF_REQ_IRQ(3), 0xd0, CPU_GET_AFFINITY(3, 0)),
#ifdef HAL_GIC_PREEMPT_FEATURE_ENABLED
    GIC_AMP_IRQ_CFG_ROUTE(GIC_TOUCH_REQ_IRQ(3), 0xd0, CPU_GET_AFFINITY(3, 0)),
#endif
    GIC_AMP_IRQ_CFG_ROUTE(MBOX0_CH3_A2B_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(UART7_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(0, 0, 0),
};

static struct GIC_IRQ_AMP_CTRL irqConfig = {
    .cpuAff = CPU_GET_AFFINITY(0, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(0, 0),
    .irqsCfg = &irqsConfig[0],
};

/********************* UART7 console（printf 重定向）************************/
static struct UART_REG *pUart = UART7;

static void HAL_IOMUX_Uart7M2Config(void)
{
    /* UART7 M2 RX-4A3 TX-4A2 */
    HAL_PINCTRL_SetIOMUX(GPIO_BANK4,
                         GPIO_PIN_A3 | GPIO_PIN_A2,
                         PIN_CONFIG_MUX_FUNC4);
    HAL_PINCTRL_IOFuncSelForUART7(IOFUNC_SEL_M2);
}

int _write(int fd, char *ptr, int len)
{
    int i = 0;

    if (fd > 2) {
        return -1;
    }
    while (*ptr && (i < len)) {
        if (*ptr == '\n') {
            HAL_UART_SerialOutChar(pUart, '\r');
        }
        HAL_UART_SerialOutChar(pUart, *ptr);
        i++;
        ptr++;
    }

    return i;
}

/********************* rpmsg 回环 demo ************************************/
struct rpmsg_block_t {
    uint32_t len;
    uint8_t buffer[492];
};

struct rpmsg_info_t {
    struct rpmsg_lite_instance *instance;
    struct rpmsg_lite_endpoint *ept;
    volatile uint32_t cb_sta;
    void *block;
    uint32_t m_ept_id;
};

static void demo_ns_cb(uint32_t new_ept, const char *new_ept_name,
                       uint32_t flags, void *user_data)
{
    (void)flags;
    (void)user_data;
    printf("rpmsg: new ept 0x%lx name '%s'\n", new_ept, new_ept_name);
}

static int32_t demo_ept_cb(void *payload, uint32_t payload_len,
                           uint32_t src, void *priv)
{
    struct rpmsg_info_t *info = (struct rpmsg_info_t *)priv;
    struct rpmsg_block_t *blk = (struct rpmsg_block_t *)info->block;

    info->m_ept_id = src;
    blk->len = payload_len;
    if (payload_len > sizeof(blk->buffer)) {
        payload_len = sizeof(blk->buffer);
    }
    memcpy(blk->buffer, payload, payload_len);
    info->cb_sta = 1;

    return rpmsg_lite_send(info->instance, info->ept, src,
                           DEMO_ECHO_MSG, strlen(DEMO_ECHO_MSG), RL_BLOCK);
}

static void rpmsg_linux_demo(void)
{
    struct rpmsg_info_t *info;
    void *ns_cb_data;

    info = malloc(sizeof(struct rpmsg_info_t));
    info->block = malloc(sizeof(struct rpmsg_block_t));
    info->cb_sta = 0;

    info->instance = rpmsg_lite_remote_init(
        LINUX_RPMSG_MEM,
        RL_PLATFORM_SET_LINK_ID(LINK_ID_M, LINK_ID_R),
        RL_NO_FLAGS);
    rpmsg_lite_wait_for_link_up(info->instance);
    printf("rpmsg: link up (link_id 0x%lx)\n", info->instance->link_id);

    rpmsg_ns_bind(info->instance, demo_ns_cb, &ns_cb_data);
    info->ept = rpmsg_lite_create_ept(info->instance, DEMO_EPT_ADDR,
                                      demo_ept_cb, info);
    rpmsg_ns_announce(info->instance, info->ept, DEMO_EPT_NAME, RL_NS_CREATE);
    printf("rpmsg: ept '%s' announced, waiting for Linux...\n", DEMO_EPT_NAME);

    while (1) {
        __asm volatile("wfi");
    }
}

/********************* main ************************************************/
void main(void)
{
    uint32_t cpu_id, irq;
    struct HAL_UART_CONFIG hal_uart_config = {
        .baudRate = UART_BR_1500000,
        .dataBit = UART_DATA_8B,
        .stopBit = UART_ONE_STOPBIT,
        .parity = UART_PARITY_DISABLE,
    };

    HAL_Init();
    BSP_Init();
    HAL_GIC_Init(&irqConfig);

    HAL_IOMUX_Uart7M2Config();
    HAL_UART_Init(&g_uart7Dev, &hal_uart_config);

#ifdef HAL_SPINLOCK_MODULE_ENABLED
    HAL_SPINLOCK_Init(HAL_CPU_TOPOLOGY_GetCurrentCpuId() << 1 | 1);
#endif

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    irq = AMP_CPUOFF_REQ_IRQ(cpu_id);
    HAL_IRQ_HANDLER_SetIRQHandler(irq, HAL_SMCCC_SIP_AmpCpuOffIrqHandler, NULL);
    HAL_GIC_Enable(irq);

    printf("\n");
    printf("****************************************\n");
    printf("  rk3568_amp_uart7_demo (flange app)    \n");
    printf("  Linux<->AMP rpmsg, CPU(%d)            \n", cpu_id);
    printf("****************************************\n");

    rpmsg_linux_demo();

    while (1) {
        __asm volatile("wfi");
    }
}

void _start(void)
{
    main();
}
