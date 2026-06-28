/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    board.c
  * @author  Jason Zhu
  * @version V0.1
  * @date    1-Aug-2019
  * @brief
  *
  ******************************************************************************
  */

#include "board.h"
#include <rthw.h>
#include "interrupt.h"

void *__wrap_memset(void *s, int c, size_t n)
{
    return rt_memset(s, c, n);
}

int rt_hw_board_init(void)
{
    rt_system_heap_init((void *)HEAP_BEGIN, (void *)HEAP_END);
    rt_hw_uart_init();
    rt_hw_interrupt_init();

    return 0;
}
