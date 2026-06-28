/**
  * Copyright (c) 2018 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    interrupt.c
  * @version V0.1
  * @brief   interrupt interface for rt-thread
  *
  * Change Logs:
  * Date           Author          Notes
  * 2019-05-08     Cliff.Chen      first implementation
  *
  ******************************************************************************
  */

#include <rthw.h>
#include "hal_base.h"

#ifdef HAS_CUSTOME_INTC

struct irq_register_info
{
    int irq_no;
    int index;
    int mask;
    rt_isr_handler_t irq_func;
};

struct rk_intc
{
    struct INTMUX_REG *intc_base;
    rt_isr_handler_t irq_dispatch;
    struct irq_register_info irq_info[INTMUX_NUM_INT_PER_OUT];
};

static void intc_irq_dispatch(uint32_t ID, uint32_t GROUP);

#define DEFINE_RK_INTC_IRQ(ID, GROUP)                                 \
static void rk_intc##ID##_group##GROUP##_irq_dispatch(int irq, void *param);  \
static struct rk_intc rk_intc##ID##_group##GROUP =                            \
{                                                              \
    .intc_base = INTMUX##ID,                                     \
    .irq_dispatch = rk_intc##ID##_group##GROUP##_irq_dispatch,                 \
};                                                             \
static void rk_intc##ID##_group##GROUP##_irq_dispatch(int irq, void *param)   \
{                                                              \
    intc_irq_dispatch(ID, GROUP);                               \
}

#ifdef INTMUX0
DEFINE_RK_INTC_IRQ(0, 0);
DEFINE_RK_INTC_IRQ(0, 1);
DEFINE_RK_INTC_IRQ(0, 2);
DEFINE_RK_INTC_IRQ(0, 3);
#endif
#ifdef INTMUX1
DEFINE_RK_INTC_IRQ(1, 0);
DEFINE_RK_INTC_IRQ(1, 1);
DEFINE_RK_INTC_IRQ(1, 2);
DEFINE_RK_INTC_IRQ(1, 3);
#endif

static struct rk_intc *rk_intc_table[] =
{
#ifdef INTMUX0
    &rk_intc0_group0,
    &rk_intc0_group1,
    &rk_intc0_group2,
    &rk_intc0_group3,
#endif
#ifdef INTMUX0
    &rk_intc1_group0,
    &rk_intc1_group1,
    &rk_intc1_group2,
    &rk_intc1_group3,
#endif
};

static void intc_irq_dispatch(uint32_t ID, uint32_t GROUP)
{
    uint32_t i, irq_no, index, mask;
    struct rk_intc *intc = rk_intc_table[ID * 4 + GROUP];

    for (i = 0; i < INTMUX_NUM_INT_PER_OUT; i++)
    {
        if (intc->irq_info[i].irq_func == NULL)
            break;

        index = intc->irq_info[i].index;
        mask = intc->irq_info[i].mask;
        if (intc->intc_base->INT_FLAG_GROUP[index] & mask)
            intc->irq_info[i].irq_func(intc->irq_info[i].irq_no, NULL);
    }
}

static void rk_intc_init(void)
{
    uint32_t i;

    for (i = 0; i < HAL_ARRAY_SIZE(rk_intc_table); i++)
    {
        HAL_NVIC_SetIRQHandler(INTMUX_OUT0_IRQn + i, (NVIC_IRQHandler)rk_intc_table[i]->irq_dispatch);
        HAL_NVIC_EnableIRQ(INTMUX_OUT0_IRQn + i);
        memset(rk_intc_table[i]->irq_info, 0, sizeof(rk_intc_table[i]->irq_info));
    }
}

static void rk_intc_mask(uint32_t vector)
{
    uint32_t intc, irq, group, offset;

    if (vector >= TOTAL_INTERRUPTS || (vector >= INTMUX_OUT0_IRQn && vector <= INTMUX_OUT7_IRQn))
        return;

    if (vector < NUM_INTERRUPTS)
        HAL_NVIC_DisableIRQ(vector);
    else
    {
        intc = (vector - NUM_INTERRUPTS) / INTMUX_NUM_INT_PER_OUT;
        irq = (vector - NUM_INTERRUPTS) % INTMUX_NUM_INT_PER_CON;
        group = irq >> 3;
        offset = irq % 8;
        if (intc >= HAL_ARRAY_SIZE(rk_intc_table))
            return;

        rk_intc_table[intc]->intc_base->INT_ENABLE_GROUP[group] &= ~(0x1 << offset);
    }
}

static void rk_intc_unmask(uint32_t vector)
{
    uint32_t intc, irq, group, offset;

    if (vector >= TOTAL_INTERRUPTS || (vector >= INTMUX_OUT0_IRQn && vector <= INTMUX_OUT7_IRQn))
        return;

    if (vector < NUM_INTERRUPTS)
        HAL_NVIC_EnableIRQ(vector);
    else
    {
        intc = (vector - NUM_INTERRUPTS) / INTMUX_NUM_INT_PER_OUT;
        irq = (vector - NUM_INTERRUPTS) % INTMUX_NUM_INT_PER_CON;
        group = irq >> 3;
        offset = irq % 8;
        if (intc >= HAL_ARRAY_SIZE(rk_intc_table))
            return;

        rk_intc_table[intc]->intc_base->INT_ENABLE_GROUP[group] |= 0x1 << offset;
    }
}


void rt_hw_interrupt_init(void)
{
    uint32_t i;

    for (i = 0; i < NUM_INTERRUPTS; i++)
    {
        HAL_NVIC_SetPriority(i, NVIC_PERIPH_PRIO_DEFAULT, NVIC_PERIPH_SUB_PRIO_DEFAULT);
    }

    rk_intc_init();
}

void rt_hw_interrupt_mask(int vector)
{
    rk_intc_mask(vector);
}

void rt_hw_interrupt_umask(int vector)
{
    rk_intc_unmask(vector);
}

rt_isr_handler_t rt_hw_interrupt_install(int              vector,
        rt_isr_handler_t handler,
        void            *param,
        const char      *name)
{
    int group, index, mask, irq, offset, i;
    struct rk_intc *intc;

    if (vector >= TOTAL_INTERRUPTS || (vector >= INTMUX_OUT0_IRQn && vector <= INTMUX_OUT7_IRQn))
        return NULL;

    if (vector < NUM_INTERRUPTS)
        HAL_NVIC_SetIRQHandler(vector, (NVIC_IRQHandler)handler);
    else
    {
        group = (vector - NUM_INTERRUPTS) / INTMUX_NUM_INT_PER_OUT;
        if (group >= HAL_ARRAY_SIZE(rk_intc_table))
            return NULL;
        intc = rk_intc_table[group];

        irq = (vector - NUM_INTERRUPTS) % INTMUX_NUM_INT_PER_CON;
        index = irq >> 3;
        offset = irq % 8;
        mask = 0x1 << offset;
        for (i = 0; i < INTMUX_NUM_INT_PER_CON; i++)
        {
            if (intc->irq_info[i].irq_func == NULL)
            {
                intc->irq_info[i].irq_no = vector;
                intc->irq_info[i].index = index;
                intc->irq_info[i].mask = mask;
                intc->irq_info[i].irq_func = handler;
                break;
            }
        }

        if (i == INTMUX_NUM_INT_PER_CON)
            return NULL;
    }

    return handler;
}
#endif  /* HAS_CUSTOME_INTC */
