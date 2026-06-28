/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    timer.c
  * @author  Jason Zhu
  * @version V0.1
  * @date    25-Oct-2019
  * @brief
  *
  ******************************************************************************
  */

#include "../cpu/chip_register.h"
#include "timer.h"

void _reset_mtime()
{
    word32(CTIMER_BASE + CTIMER_MTIME) = 0x00;
    word32(CTIMER_BASE + CTIMER_MTIMEH) = 0x00;
}

void _reset_mtimecmp()
{
    word32(CTIMER_BASE + CTIMER_MTIMECMP) = 0x00;
    word32(CTIMER_BASE + CTIMER_MTIMECMPH) = 0x00;
}

void _write_mtime_ctrl(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIME_CTRL) = t;
}

void _write_mtime_div(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIME_DIV) = t;
}

void _write_mtimecmp(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIMECMP) = t;
}

void _write_mtimecmph(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIMECMPH) = t;
}

void _write_mtime(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIME) = t;
}

void _write_mtimeh(unsigned int t)
{
    word32(CTIMER_BASE + CTIMER_MTIMEH) = t;
}

unsigned int _read_mtimecmp()
{
    return word32(CTIMER_BASE + CTIMER_MTIMECMP);
}

unsigned int _read_mtimecmph()
{
    return word32(CTIMER_BASE + CTIMER_MTIMECMPH);
}

unsigned int _read_mtime()
{
    return word32(CTIMER_BASE + CTIMER_MTIME);
}

unsigned int _read_mtimeh()
{
    return word32(CTIMER_BASE + CTIMER_MTIMEH);
}

unsigned int _read_mtime_ctrl()
{
    return word32(CTIMER_BASE + CTIMER_MTIME_CTRL);
}

unsigned int _read_mtime_div()
{
    return word32(CTIMER_BASE + CTIMER_MTIME_DIV);
}

void _run_timer()
{
    unsigned int temp;
    temp = word32(CTIMER_BASE + CTIMER_MTIME_CTRL);
    temp |= (1 << SCR1_MTIME_CTRL_EN);
    word32(CTIMER_BASE + CTIMER_MTIME_CTRL) = temp;
}

void _stop_timer()
{
    unsigned int temp;
    temp = word32(CTIMER_BASE + CTIMER_MTIME_CTRL);
    temp &= (~(1 << SCR1_MTIME_CTRL_EN));
    word32(CTIMER_BASE + CTIMER_MTIME_CTRL) = temp;
}