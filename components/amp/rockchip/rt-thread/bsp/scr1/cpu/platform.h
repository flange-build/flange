/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    platform.h
  * @author  Jason Zhu
  * @version V0.1
  * @date    1-Aug-2019
  * @brief
  *
  ******************************************************************************
  */

#ifndef _PLATFORM_H_
#define _PLATFORM_H_

#define SRAM_BASE   0x00000000
#define PERI_BASE   0x10000000
#define UART_BASE   PERI_BASE
#define TIMER_BASE  (PERI_BASE+0x1000)
#define REGFILE_BASE    (PERI_BASE+0x2000)

#define CTIMER_BASE     0x00490000
#define CTIMER_MTIME_CTRL   0x0000
#define CTIMER_MTIME_DIV    0x0004
#define CTIMER_MTIME        0x0008
#define CTIMER_MTIMEH       0x000C
#define CTIMER_MTIMECMP     0x0010
#define CTIMER_MTIMECMPH    0x0014

#define M0_FAILED       0x1f183f04
#define M0_FAILED_ADD       0x1f183f04
#define M0_SUCESS       0x1f183f08
#define M0_SUCESS_ADD       0x1f183f08
#define M0_DABORT       0x1f183f0c
#define M0_PABORT       0x1f183f00
#define M0_UNDEF        0x1f183f00
#define M0_EXP          0x1f183f00
#define M0_HARD_FAULT_EXP   0x1f183f00
#define M0_MEM_MANAGE_EXP   0x1f183f00
#define M0_BUS_FALUT_EXP    0x1f183f00
#define M0_USAGE_FAULT_EXP  0x1f183f00

#define M0_PASS     *(volatile unsigned long *)(M0_SUCESS_ADD) = 0x1
#define M0_FAIL     *(volatile unsigned long *)(M0_FAILED_ADD) = 0x1

#define RV32_PASS   *(volatile unsigned long *)(M0_SUCESS_ADD) = 0x1
#define RV32_FAIL   *(volatile unsigned long *)(M0_FAILED_ADD) = 0x1

#define word32      *(volatile unsigned int *)
#define word16      *(volatile unsigned short *)
#define word8       *(volatile unsigned char *)

#endif
