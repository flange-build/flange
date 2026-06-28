/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    interrupt.h
  * @author  Jason Zhu
  * @version V0.1
  * @date    25-Oct-2019
  * @brief
  *
  ******************************************************************************
  */

#ifndef _INTERRUPT_H_
#define _INTERRUPT_H_

void handle_trap(unsigned int i_mcause, unsigned int i_mepc, unsigned int i_sp);
void rt_hw_interrupt_mask(int vector);
void rt_hw_interrupt_umask(int vector);
void rt_hw_interrupt_init(void);

#endif
