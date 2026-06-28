/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    interrupt.c
  * @author  Jason Zhu
  * @version V0.1
  * @date    25-Oct-2019
  * @brief
  *
  ******************************************************************************
  */

#include <rtthread.h>
#include "drv_uart.h"
#include "interrupt.h"
#include "timer.h"
#include "../cpu/riscv_csr_encoding.h"

#ifdef DEBUG
#define DEBUG_PRINTF(...)   rt_kprintf(__VA_ARGS__)
#else
#define DEBUG_PRINTF(...)
#endif

void write_csr_ipic(unsigned int addr, unsigned int val)
{
    switch (addr)
    {
    case IPIC_CISV :
        write_csr(0xbf0, val);
        break;
    case IPIC_CICSR :
        write_csr(0xbf1, val);
        break;
    case IPIC_IPR :
        write_csr(0xbf2, val);
        break;
    case IPIC_ISVR :
        write_csr(0xbf3, val);
        break;
    case IPIC_EOI :
        write_csr(0xbf4, val);
        break;
    case IPIC_SOI :
        write_csr(0xbf5, val);
        break;
    case IPIC_IDX :
        write_csr(0xbf6, val);
        break;
    case IPIC_ICSR :
        write_csr(0xbf7, val);
        break;
    default:
        break;
    }

    return ;
}

unsigned int read_csr_ipic(unsigned int addr)
{
    unsigned int res;

    switch (addr)
    {
    case IPIC_CISV :
        res = read_csr(0xbf0);
        break;
    case IPIC_CICSR :
        res = read_csr(0xbf1);
        break;
    case IPIC_IPR :
        res = read_csr(0xbf2);
        break;
    case IPIC_ISVR :
        res = read_csr(0xbf3);
        break;
    case IPIC_EOI :
        res = read_csr(0xbf4);
        break;
    case IPIC_SOI :
        res = read_csr(0xbf5);
        break;
    case IPIC_IDX :
        res = read_csr(0xbf6);
        break;
    case IPIC_ICSR :
        res = read_csr(0xbf7);
        break;
    default:
        res = 0;
    }

    return res;
}

void rt_hw_interrupt_init(void)
{
    /* config interrupt vector, direct mode */
    clear_csr(mtvec, 1); //direct mode

    /* Enable global interrupt */
    set_csr(mstatus, MSTATUS_MIE);

    /* enable machine external interrupt */
    set_csr(mie, MIP_MEIP);

    /* enable timer interrupt */
    set_csr(mie, MIP_MTIP);
}

void rt_hw_interrupt_mask(int vector)
{
    write_csr_ipic(IPIC_IDX , vector);
    write_csr_ipic(IPIC_ICSR, 0);
}

void rt_hw_interrupt_umask(int vector)
{
    write_csr_ipic(IPIC_IDX , vector);
    /* enable, rising edge */
    write_csr_ipic(IPIC_ICSR, (IPIC_ICSR_IE | IPIC_ICSR_IM));
}

static void m_timer_hadle(unsigned int i_mcause, unsigned int i_mepc, unsigned int i_sp)
{
    rt_kprintf("m_timer irq enter\n");
}

static void m_ext_hadle(unsigned int i_mcause, unsigned int i_mepc, unsigned int i_sp)
{
    rt_kprintf("m_ext irq enter\n");
    write_csr_ipic(IPIC_SOI , 0); // Just drive IPIC state machine
    rt_kprintf("CISV is 0x%x, IDX is 0x%x\n", read_csr_ipic(IPIC_CISV), read_csr_ipic(IPIC_IDX));
    /* handle the ipic interrupt here */
    write_csr_ipic(IPIC_EOI , 0); // Just drive IPIC state machine
}

static void s_ecfm_hadle(unsigned int i_mcause, unsigned int i_mepc, unsigned int i_sp)
{
    rt_kprintf("Environment call from M-mode\n");
}

void handle_trap(unsigned int i_mcause, unsigned int i_mepc, unsigned int i_sp)
{
    DEBUG_PRINTF("mcasue 0x%x, i_mepc is 0x%x, i_sp is 0x%x\n", i_mcause, i_mepc, i_sp);
    unsigned int mcause = i_mcause & 0x7fffffff;

    if ((i_mcause & 0x80000000) == 0x80000000)
    {
        /* environment interrupt */
        switch (mcause)
        {
        case IRQ_S_SOFT:
            rt_kprintf("s_soft irq enter\n");
            break;
        case IRQ_H_SOFT:
            rt_kprintf("h_soft irq enter\n");
            break;
        case IRQ_M_SOFT:
            rt_kprintf("m_soft irq enter\n");
            break;
        case IRQ_S_TIMER:
            rt_kprintf("s_timer irq enter\n");
            break;
        case IRQ_H_TIMER:
            rt_kprintf("h_timer irq enter\n");
            break;
        case IRQ_M_TIMER:
            m_timer_hadle(i_mcause, i_mepc, i_sp);
            break;
        case IRQ_S_EXT:
            rt_kprintf("s_ext irq enter\n");
            break;
        case IRQ_H_EXT:
            rt_kprintf("h_ext irq enter\n");
            break;
        case IRQ_M_EXT:
            m_ext_hadle(i_mcause, i_mepc, i_sp);
            break;
        case IRQ_COP:
            rt_kprintf("cop irq enter\n");
            break;
        case IRQ_HOST:
            rt_kprintf("host irq enter\n");
            break;
        default:
            rt_kprintf("Environment interrupt not implecation, mcause is 0x%x\n", i_mcause);
        }
    }
    else
    {
        /* system interrupt */
        switch (mcause)
        {
        case EXC_IAM:
            rt_kprintf("Instruction address misaligned\n");
            break;
        case EXC_IAF:
            rt_kprintf("Instruction access fault\n");
            break;
        case EXC_II:
            rt_kprintf("Illegal instruction\n");
            break;
        case EXC_BP:
            write_csr(mepc, i_mepc + 4);
            rt_kprintf("Breakpoint\n");
            break;
        case EXC_LAM:
            rt_kprintf("Load address misaligned\n");
            break;
        case EXC_LAF:
            rt_kprintf("Load access fault\n");
            break;
        case EXC_SAM:
            rt_kprintf("Store/AMO address misaligned\n");
            break;
        case EXC_SAF:
            rt_kprintf("Store/AMO access fault\n");
            break;
        case EXC_ECFU:
            rt_kprintf("Environment call from U-mode\n");
            break;
        case EXC_ECFS:
            rt_kprintf("Environment call from S-mode\n");
            break;
        case EXC_ECFM:
            write_csr(mepc, i_mepc + 4);
            s_ecfm_hadle(i_mcause, i_mepc, i_sp);
            break;
        case EXC_IPF:
            rt_kprintf("Instruction page fault\n");
            break;
        case EXC_LPF:
            rt_kprintf("Load page fault\n");
            break;
        case EXC_SPF:
            rt_kprintf("Store/AMO page fault\n");
            break;
        default:
            rt_kprintf("System interrupt not implecation, mcause is 0x%x\n", i_mcause);
        }
    }
}
