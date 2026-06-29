/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * rk3568_amp_demo — AMP 协处理器固件（裸机 HAL，运行在 cpu3）。
 *
 * 参考 SDK project/rk3568/src/{main.c, test_demo.c 的 RPMSG_LINUX_TEST} 改写：
 *   - HAL/GIC/UART4 初始化（从核 console = UART4 M1，GPIO3_B1/B2，1500000）；
 *   - Linux↔AMP rpmsg：rpmsg-lite remote 端，建端点 "rpmsg-ap3-ch0"，向 Linux
 *     通告；收到 Linux 消息后回 echo（"Rockchip rpmsg linux test!"）。
 *
 * Linux 侧（CONFIG_RPMSG_CHAR/CTRL 已开）：open /dev/rpmsg_ctrl0 → RPMSG_CREATE_EPT
 * 创建匹配 "rpmsg-ap3-ch0" 的端点 → /dev/rpmsgN，write 发、read 收到 echo。
 */

#include "hal_bsp.h"
#include "hal_base.h"
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"

#include <stdlib.h>
#include <string.h>

/* Linux = cpu0（master），本核 = cpu3（remote）。
 *
 * link-id 编码 (M<<4)|R，这里取 0x10（M=1, R=0）——刻意不直接表征物理核号：
 *   - R（低4位）被 rpmsg-lite platform_notify 当作"从核→主核"的 mailbox 发送
 *     通道号（RL_GET_R_CPU_ID）。stock rockchip_rpmsg_mbox 把"新消息"通道定为
 *     rpmsg-rx=ch0、"consume"通道定为 rpmsg-tx=ch3，故取 R=0 让从核新消息发到
 *     ch0 → 命中驱动 rx 回调 → vq[0]（取 R=3 则发 ch3 落 tx 回调被丢，详见
 *     docs/amp.md；这样可保 Linux 驱动 100% stock，无需 patch tx_callback）。
 *   - M（高4位）仅用于 platform_init_interrupt 的 cpu_id==M_CPU_ID 主/从判定，
 *     取任意 ≠ 本核 cpu3 的值即可，这里 1。
 *   - 接收方向（Linux→从核）仍走 A2B ch3 / INTID 222，由物理 cpu_id=3 决定，
 *     与 link-id 无关。Linux dts 的 rockchip,link-id 必须同步为 0x10（握手 CMD）。
 * 端点名/号需与 Linux 侧约定一致。 */
#define LINK_ID_M       1U   /* link-id 高4位：仅作主/从判定，≠本核 cpu3 */
#define LINK_ID_R       0U   /* link-id 低4位：从核发送 mailbox 通道，0 → 命中驱动 rpmsg-rx(ch0) */
#define DEMO_EPT_ADDR   0x3003U
#define DEMO_EPT_NAME   "rpmsg-ap3-ch0"
#define DEMO_ECHO_MSG   "Rockchip rpmsg linux test!"

/* LINUX_RPMSG 共享内存区起始符号，由链接脚本 gcc_arm.ld.S 定义（落在 LINUX_RPMSG
 * MEMORY 区，地址 = config.amp.memory.rpmsg_base，与内核 rpmsg reserved-memory 对齐）。 */
extern uint32_t __linux_share_rpmsg_start__[];
#define LINUX_RPMSG_MEM ((void *)&__linux_share_rpmsg_start__)

/********************* GIC 中断路由（仅本核 cpu3）****************************/
/* cpu-off（Linux 关从核）、touch（抢占）、rpmsg mailbox（MBOX0_CH3_A2B）都路由到 cpu3。 */
static struct GIC_AMP_IRQ_INIT_CFG irqsConfig[] = {
    GIC_AMP_IRQ_CFG_ROUTE(AMP_CPUOFF_REQ_IRQ(3), 0xd0, CPU_GET_AFFINITY(3, 0)),
#ifdef HAL_GIC_PREEMPT_FEATURE_ENABLED
    GIC_AMP_IRQ_CFG_ROUTE(GIC_TOUCH_REQ_IRQ(3), 0xd0, CPU_GET_AFFINITY(3, 0)),
#endif
    GIC_AMP_IRQ_CFG_ROUTE(MBOX0_CH3_A2B_IRQn, 0xd0, CPU_GET_AFFINITY(3, 0)),
    GIC_AMP_IRQ_CFG_ROUTE(0, 0, 0),   /* sentinel */
};

/* cpuAff/defRouteAff 必须设成"非本核"（Linux master cpu0），使 HAL_GIC_Init 判
 * gicInit=0：从核不抢着重初始化 GIC 分发器（GICD 归 Linux），而是等 Linux 把
 * AMP 路由设好后只使能自己那几条 IRQ。设成本核 cpu3 会让 gicInit=1 → 从核重初始化
 * GICD 与 Linux 抢，导致挂死/停打印。SDK 同理用非本核（见 project/rk3568/src/main.c）。 */
static struct GIC_IRQ_AMP_CTRL irqConfig = {
    .cpuAff = CPU_GET_AFFINITY(0, 0),
    .defPrio = 0xd0,
    .defRouteAff = CPU_GET_AFFINITY(0, 0),
    .irqsCfg = &irqsConfig[0],
};

/********************* UART4 console（printf 重定向）************************/
static struct UART_REG *pUart = UART4;

static void HAL_IOMUX_Uart4M1Config(void)
{
    /* UART4 M1 RX-3B1 TX-3B2 */
    HAL_PINCTRL_SetIOMUX(GPIO_BANK3,
                         GPIO_PIN_B1 | GPIO_PIN_B2,
                         PIN_CONFIG_MUX_FUNC4);
    HAL_PINCTRL_IOFuncSelForUART4(IOFUNC_SEL_M1);
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

/* Linux 端创建端点时的 name-service 通告回调（仅打印）。 */
static void demo_ns_cb(uint32_t new_ept, const char *new_ept_name,
                       uint32_t flags, void *user_data)
{
    (void)flags;
    (void)user_data;
    printf("rpmsg: new ept 0x%lx name '%s'\n", new_ept, new_ept_name);
}

/* 收到 Linux 消息 → 回 echo。 */
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

    /* 回调里处理收发；主循环 wfi 省电。 */
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

    HAL_IOMUX_Uart4M1Config();
    HAL_UART_Init(&g_uart4Dev, &hal_uart_config);

#ifdef HAL_SPINLOCK_MODULE_ENABLED
    HAL_SPINLOCK_Init(HAL_CPU_TOPOLOGY_GetCurrentCpuId() << 1 | 1);
#endif

    /* CPU Off 支持（Linux 经 SIP 关从核）。 */
    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    irq = AMP_CPUOFF_REQ_IRQ(cpu_id);
    HAL_IRQ_HANDLER_SetIRQHandler(irq, HAL_SMCCC_SIP_AmpCpuOffIrqHandler, NULL);
    HAL_GIC_Enable(irq);

    printf("\n");
    printf("****************************************\n");
    printf("  rk3568_amp_demo (flange amp app)      \n");
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
