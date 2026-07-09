/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#ifndef _CONSOLE_H_
#define _CONSOLE_H_

#include "hal_list.h"

struct console_command {
    const char *name;
    const char *help;
    struct HAL_LIST_NODE list;
    void (*process)(uint8_t *args, int len);
};

void console_uart_isr(uint32_t irq, void *args);
int console_run(bool block);
int console_init(struct HAL_UART_DEV *uart,
                 uint8_t * *buf, int max_input, int max_history);
void console_add_command(struct console_command *command);

uint8_t *console_get_paramter(uint8_t *line, int *len, uint8_t * *next);
#endif
