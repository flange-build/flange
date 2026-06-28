/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    timer.h
  * @author  Jason Zhu
  * @version V0.1
  * @date    25-Oct-2019
  * @brief
  *
  ******************************************************************************
  */

#ifndef __C_TIMER__H
#define __C_TIMER__H

#define MCAUSE_TMR_IRQ (1 << 31 | 7)
#define SCR1_MTIME_CTRL_EN          0
#define SCR1_MTIME_CTRL_CLKSRC      1
#define SCR1_MTIME_CTRL_WR_MASK     0x3
#define SCR1_MTIME_DIV_WR_MASK      0x3FF

void _reset_mtime();
void _reset_mtimecmp();
void _write_mtime_ctrl(unsigned int t);
void _write_mtime_div(unsigned int t);
void _write_mtimecmp(unsigned int t);
void _write_mtimecmph(unsigned int t);
void _write_mtime(unsigned int t);
void _write_mtimeh(unsigned int t);
unsigned int _read_mtime();
unsigned int _read_mtimeh();
unsigned int _read_mtimecmp();
unsigned int _read_mtimecmph();
unsigned int _read_mtime_ctrl();
unsigned int _read_mtime_div();
void _run_timer();
void _stop_timer();

#endif