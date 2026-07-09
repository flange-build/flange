/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 * Match to XTerm Control Sequences VT102, applied by `mimicom`.
 * Related to https://invisible-island.net/xterm/ctlseqs/ctlseqs.html
 */

#include <stdio.h>
#include <stdbool.h>
#include "hal_base.h"
#include "simple_console.h"
#include "command_io.h"

#define BIT(x) (1U << (x))

#define CONSOLE_FLAG_CMD_LOCK BIT(1)

enum input_mode {
    CONSOLE_INPUT_NORMAL = 0,
    CONSOLE_INPUT_ESCAPE,
    CONSOLE_INPUT_CSI,
};

struct console_buffers {
    uint8_t * *buf;
    uint8_t line;
    uint8_t history;

    int max_input;
    int max_line;
    int index;
    int len;
    uint64_t csi;
};

struct console_dev {
    struct HAL_UART_DEV *uart_dev;
    struct console_buffers bufs;

    enum input_mode mode;
    uint32_t flags;
    const uint8_t *title;
};

static struct console_dev g_console = { 0 };
HAL_LIST_HEAD(command_list);

/*
 * XTerm Control Sequences
 * https://invisible-island.net/xterm/ctlseqs/ctlseqs.html
 *
 * CSI = 0x1b + '['
 *
 * Key              Normal                Note
 * ---------------+---------------------+----------
 * Cursor Up      | CSI A               |
 * Cursor Down    | CSI B               |
 * Cursor Right   | CSI C               |
 * Cursor Left    | CSI D               |
 * Save Cursor    | ESC 7               |
 * Restore Cursor | ESC 8               |
 *
 * Home           | CSI 1 ~             |
 * End            | CSI 4 ~             |
 * Insert         | CSI \x40            |   No support
 * Delete         | CSI ESC \x7F        |   No support
 * PageUp         | CSI V               |   No support
 * PageDown       | CSI 6               |   No support
 */

/* CSI Ps D  Cursor Backward Ps Times (default = 1) (CUB). */
/* CSI Ps K  Erase in Line (EL), VT100 */
/*              Ps = 0  ⇒  Erase to Right (default). */
/*              Ps = 1  ⇒  Erase to Left. */
/*              Ps = 2  ⇒  Erase All. */
/* CSI Ps G  Cursor Character Absolute  [column] (default = [row,1]) (CHA). */

static const uint8_t KEY_CSI[] = { 0x1b, '[' };
static const uint8_t KEY_BACKSPACE[] = { 0x08 };
static const uint8_t KEY_FORWARD[] = { 0x1b, '[', 'D' };
static const uint8_t KEY_BACK[] = { 0x1b, '[', 'C' };
static const uint8_t KEY_CLEANLINE[] = { 0x1b, '[', '2', 'K', 0x1b, '[', 'G' };

static const uint8_t MCU_TITLE[] = "MCU Console: ";

static void console_reset_line(struct console_buffers *bufs)
{
    bufs->index = 0;
    bufs->len = 0;
}

static void console_get_next_history(struct console_buffers *bufs,
                                     int direction)
{
    uint8_t line, i;

    line = bufs->history;

    for (i = 0; i < bufs->max_line; i++) {
        if (direction) {
            line = line ? line - 1 : bufs->max_line - 1;
        } else {
            line = line == (bufs->max_line - 1) ? 0 : line + 1;
        }
        if (bufs->buf[line][0] || line == bufs->line) {
            bufs->history = line;
            break;
        }
    }
}

static void console_get_next_line(struct console_buffers *bufs)
{
    bufs->line = bufs->line < (bufs->max_line - 1) ? bufs->line + 1 : 0;
    bufs->history = bufs->line;
    console_reset_line(bufs);
}

static void console_reset_csi(struct console_buffers *bufs)
{
    bufs->csi = 0;
}

static void console_cursor_move_right(struct console_dev *console, int move)
{
    struct UART_REG *pReg = console->uart_dev->pReg;
    char cnt, num[4] = { 0 };

    HAL_UART_SerialOut(pReg, KEY_CSI, sizeof(KEY_CSI));
    if (move > 0) {
        cnt = snprintf(num, sizeof(num), "%d", move);
        HAL_UART_SerialOut(pReg, (uint8_t *)num, cnt);
        HAL_UART_SerialOutChar(pReg, 'C');
    } else {
        cnt = snprintf(num, sizeof(num), "%d", -move);
        HAL_UART_SerialOut(pReg, (uint8_t *)num, cnt);
        HAL_UART_SerialOutChar(pReg, 'D');
    }
}

static void console_spec_del(struct console_dev *console)
{
    struct console_buffers *bufs = &console->bufs;
    uint8_t *buffer = bufs->buf[bufs->line];

    if ((!bufs->index) && (bufs->index == bufs->len)) {
        return;
    }

    HAL_UART_SerialOut(console->uart_dev->pReg,
                       &buffer[bufs->index + 1],
                       bufs->len - bufs->index - 1);
    HAL_UART_SerialOutChar(console->uart_dev->pReg, ' ');
    console_cursor_move_right(console, -(bufs->len - bufs->index));

    memmove(buffer + bufs->index,
            buffer + bufs->index + 1,
            bufs->len - bufs->index - 1);

    bufs->len--;
}

static void console_spec_backspace(struct console_dev *console)
{
    struct console_buffers *bufs = &console->bufs;
    uint8_t *buffer = bufs->buf[bufs->line];

    if (!bufs->index) {
        return;
    }

    HAL_UART_SerialOut(console->uart_dev->pReg, KEY_BACKSPACE,
                       sizeof(KEY_BACKSPACE));

    if (bufs->index != bufs->len) {
        HAL_UART_SerialOut(console->uart_dev->pReg,
                           &buffer[bufs->index],
                           bufs->len - bufs->index);
        HAL_UART_SerialOutChar(console->uart_dev->pReg, ' ');
        console_cursor_move_right(console, -(bufs->len - bufs->index + 1));

        memmove(buffer + bufs->index - 1,
                buffer + bufs->index,
                bufs->len - bufs->index);
    } else {
        HAL_UART_SerialOutChar(console->uart_dev->pReg, ' ');
        HAL_UART_SerialOut(console->uart_dev->pReg, KEY_BACKSPACE,
                           sizeof(KEY_BACKSPACE));
    }

    bufs->index--;
    bufs->len--;
}

static void console_spec_end(struct console_dev *console)
{
    struct console_buffers *bufs = &console->bufs;

    if (bufs->index == bufs->len) {
        return;
    }

    console_cursor_move_right(console, bufs->len - bufs->index);
    bufs->index = bufs->len;
}

static void console_spec_home(struct console_dev *console)
{
    struct console_buffers *bufs = &console->bufs;

    if (!bufs->index) {
        return;
    }

    console_cursor_move_right(console, -bufs->index);
    bufs->index = 0;
}

static void console_history_process(struct console_dev *console, int direction)
{
    struct console_buffers *bufs = &console->bufs;
    struct UART_REG *pReg = console->uart_dev->pReg;

    HAL_UART_SerialOut(pReg, KEY_CLEANLINE, sizeof(KEY_CLEANLINE));
    HAL_UART_SerialOut(pReg, MCU_TITLE, sizeof(MCU_TITLE));
    console_get_next_history(bufs, direction);
    HAL_UART_SerialOut(pReg, bufs->buf[bufs->history],
                       bufs->line == bufs->history ?
                       bufs->len : strlen((char *)bufs->buf[bufs->history]));
}

static void console_history_swap(struct console_dev *console)
{
    struct console_buffers *bufs = &console->bufs;

    if (bufs->line == bufs->history) {
        return;
    }

    strcpy((char *)bufs->buf[bufs->line], (char *)bufs->buf[bufs->history]);
    bufs->index = strlen((char *)bufs->buf[bufs->line]);
    bufs->len = bufs->index;
    bufs->history = bufs->line;
}

static void console_csi_char(struct console_dev *console, uint8_t c)
{
    console->mode = CONSOLE_INPUT_NORMAL;

    switch (c) {
    case 'A':           /* Up */
        console_history_process(console, true);
        break;
    case 'B':           /* Down */
        console_history_process(console, false);
        break;
    case 'D':           /* Left */
        console_history_swap(console);
        if (console->bufs.index) {
            console->bufs.index--;
        }
        HAL_UART_SerialOut(console->uart_dev->pReg, KEY_FORWARD,
                           sizeof(KEY_FORWARD));
        break;
    case 'C':           /* Right */
        console_history_swap(console);
        if (console->bufs.index != console->bufs.len) {
            console->bufs.index++;
        }
        HAL_UART_SerialOut(console->uart_dev->pReg, KEY_BACK,
                           sizeof(KEY_BACK));
        break;
    case '~':
        console_history_swap(console);
        switch (console->bufs.csi) {
        case '1':           /* Home */
            console_spec_home(console);
            break;
        case '4':           /* End */
            console_spec_end(console);
            break;
        case '3':
            console_spec_del(console);
            break;
        default:
            printf("No support now (CSI 0x%2llx ~)\n", console->bufs.csi);
            break;
        }
        console->bufs.csi = 0;
        break;
    default:
        if (c >= '0' && c < '9') {      /* TODO: No support multi chars now */
            console->bufs.csi = c;
            console->mode = CONSOLE_INPUT_CSI;
        } else {
            printf("No support now (CSI 0x%2x)\n", c);
        }
        break;
    }
}

static void console_escap_char(struct console_dev *console, uint8_t c)
{
    if (c != '[') {         /* ignore, TODO */
        console->mode = CONSOLE_INPUT_NORMAL;
        printf("No support now (escap 0x%x)\n", c);

        return;
    }

    console_reset_csi(&console->bufs);
    console->mode = CONSOLE_INPUT_CSI;
}

static void console_insert_char(struct console_dev *console, char c)
{
    struct console_buffers *bufs = &console->bufs;
    uint8_t *buffer = bufs->buf[bufs->line];

    console_history_swap(console);

    if (bufs->len >= (bufs->max_input - 1)) {
        printf("Over max input, reset buf\n");
        console_reset_line(&console->bufs);
        HAL_UART_SerialOut(console->uart_dev->pReg, MCU_TITLE,
                           sizeof(MCU_TITLE));
    }

    if (bufs->len > bufs->index) {
        memmove(buffer + bufs->index + 1,
                buffer + bufs->index,
                bufs->len - bufs->index);
    }

    buffer[bufs->index] = c;

    bufs->index++;
    bufs->len++;
}

static int console_spec_char(struct console_dev *console, uint8_t c)
{
    struct UART_REG *pReg = console->uart_dev->pReg;

    switch (console->mode) {
    case CONSOLE_INPUT_ESCAPE:
        console_escap_char(console, c);

        return -1;
    case CONSOLE_INPUT_CSI:
        console_csi_char(console, c);

        return -1;
    default:
        break;
    }

    switch (c) {
    case '\r':    /* enter */
        console_history_swap(console);
        HAL_UART_SerialOut(pReg, (const uint8_t *)"\n\r", 2);
        console->bufs.buf[console->bufs.line][console->bufs.len] = 0;

        if (console->bufs.buf[console->bufs.line][0] == 0) {
            HAL_UART_SerialOut(pReg, MCU_TITLE, sizeof(MCU_TITLE));

            return -1;
        }

        console->flags |= CONSOLE_FLAG_CMD_LOCK;

        return -1;
    case 0x03:     /* ctrl + c */
        console_history_swap(console);
        HAL_UART_SerialOut(pReg, (const uint8_t *)"[ctrl + c]\n\r",
                           sizeof("[ctrl + c]\n\r"));
        console_reset_line(&console->bufs);
        HAL_UART_SerialOut(pReg, MCU_TITLE, sizeof(MCU_TITLE));

        return -1;
    case 0x08:     /* backspace */
        console_history_swap(console);
        console_spec_backspace(console);

        return -1;
    case 0x1b:    /* Escap */
        console->mode = CONSOLE_INPUT_ESCAPE;

        return -1;
    case '\t':
        /* TODO */
        break;
    }

    if (c < 32) {       /* ignore */
        return -1;
    }

    return 0;
}

static void console_putchar(struct console_dev *console, uint8_t c)
{
    struct console_buffers *bufs = &console->bufs;
    struct UART_REG *pReg = console->uart_dev->pReg;

    HAL_UART_SerialOutChar(pReg, c);
    if (bufs->index < bufs->len) {
        HAL_UART_SerialOut(pReg, bufs->buf[bufs->line] + bufs->index,
                           bufs->len - bufs->index);
        console_cursor_move_right(console, -(bufs->len - bufs->index));
    }
}

void console_uart_isr(uint32_t irq, void *args)
{
    struct console_dev *console = &g_console;
    struct UART_REG *pReg = console->uart_dev->pReg;
    uint8_t skip_log = 0, data = 0;
    uint32_t iir = HAL_UART_GetIrqID(pReg);

    if (iir != UART_IIR_RX_TIMEOUT &&
        iir != UART_IIR_RDI) {
        return;
    }

    while (HAL_UART_GetUsr(pReg) & UART_USR_RX_FIFO_NOT_EMPTY) {
        HAL_UART_SerialIn(pReg, &data, 1);

        if (console->flags & CONSOLE_FLAG_CMD_LOCK) {
            if (!skip_log) {
                printf("wait for process command\n");
                skip_log = 1;
            }
            continue;
        }

        if (console_spec_char(console, data))
            continue;

        console_putchar(console, data);
        console_insert_char(console, data);
    }
}

uint8_t *console_get_paramter(uint8_t *line, int *len, uint8_t * *next)
{
    int i, length = *len;
    uint8_t *start;

    for (i = 0; i < length; i++) {
        if (line[i] != ' ') {
            break;
        }
    }

    if (i != length) {
        start = line + i;
    } else {
        return NULL;
    }

    length -= i;
    for (i = 0; i < length; i++) {
        if (start[i] == ' ') {
            break;
        }
    }

    if (i != length) {
        *next = start + i;
        length -= i;
    } else {
        *next = NULL;
        length = 0;
    }

    *len = length;

    return start;
}

int console_run(bool block)
{
    struct console_dev *console = &g_console;
    int len;
    uint8_t *next, *start;
    struct HAL_LIST_NODE *pos;
    struct console_command *command;

    do {
        if (console->flags & CONSOLE_FLAG_CMD_LOCK) {
            len = console->bufs.len;
            start = console_get_paramter(console->bufs.buf[console->bufs.line],
                                         &len, &next);
            HAL_LIST_FOR_EACH(pos, &command_list) {
                command = HAL_CONTAINER_OF(pos, struct console_command, list);
                if ((!memcmp(command->name, start, strlen(command->name)))) {
                    command->process(next, len);
                }
            }

            HAL_UART_SerialOut(console->uart_dev->pReg, MCU_TITLE,
                               sizeof(MCU_TITLE));

            console_get_next_line(&console->bufs);
            console->flags &= ~CONSOLE_FLAG_CMD_LOCK;
        }
    } while (block);

    return 0;
}

static void command_history_process(uint8_t *args, int len)
{
    struct console_buffers *bufs = &g_console.bufs;
    int i, index, max_line = bufs->max_line;

    if (len) {
        return;
    }

    index = bufs->line;
    for (i = 0; i < (max_line - 1); i++) {
        index = index ? index - 1 : max_line - 1;

        if (bufs->buf[index][0]) {
            printf("%2d => %s\n", i, bufs->buf[index]);
        } else {
            break;
        }
    }
}

static void command_help_process(uint8_t *args, int len)
{
    struct HAL_LIST_NODE *pos;
    struct console_command *command;
    int length;

    if (len) {
        return;
    }

    printf("Command \t\t\tHelp\n");
    HAL_LIST_FOR_EACH(pos, &command_list) {
        command = HAL_CONTAINER_OF(pos, struct console_command, list);
        length = strlen(command->name);
        if (length > 24) {
            printf("%s\t%s\n", command->name, command->help);
        } else if (length > 16) {
            printf("%s\t\t%s\n", command->name, command->help);
        } else if (length > 8) {
            printf("%s\t\t\t%s\n", command->name, command->help);
        } else {
            printf("%s\t\t\t\t%s\n", command->name, command->help);
        }
    }
}

void console_add_command(struct console_command *command)
{
    HAL_LIST_InsertAfter(&command_list, &command->list);
}

static struct console_command command_help = {
    .name = "help",
    .help = "Show this message",
    .process = command_help_process,
};

static struct console_command command_history = {
    .name = "history",
    .help = "Show all history commands",
    .process = command_history_process,
};

int console_init(struct HAL_UART_DEV *uart,
                 uint8_t * *buf, int max_input, int max_line)
{
    struct console_dev *console = &g_console;

    console->uart_dev = uart;

    console->bufs.buf = buf;
    console->bufs.line = 0;
    console->bufs.history = 0;
    console->bufs.max_input = max_input;
    console->bufs.max_line = max_line;

    HAL_UART_SerialOut(uart->pReg, MCU_TITLE, sizeof(MCU_TITLE));

    console_add_command(&command_help);
    console_add_command(&command_history);
    console_add_command(&command_io);

    return 0;
}
