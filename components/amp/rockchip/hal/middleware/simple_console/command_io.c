/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#include <stdbool.h>
#include <stdio.h>
#include "hal_base.h"
#include "simple_console.h"
#include "command_io.h"

#define SHOW_MASK(x) (~(0xffffffff << (x)))

struct command_io_info {
    uint32_t addr;
    bool write;
    int len;
    uint32_t val;
    int unit;
};

static void print_data_by_unit(uint32_t data, int unit)
{
    switch (unit) {
    case 1:
        printf("%02lx ", data);
        break;
    case 2:
        printf("%04lx ", data);
        break;
    case 4:
        printf("%08lx ", data);
        break;
    default:
        break;
    }
}

static void dump_one_reg(uint32_t data, int unit, int *len)
{
    int i;

    for (i = 0; i < (4 / unit) && (*len > 0); i++) {
        print_data_by_unit((data >> ((unit << 3) * i)) & (SHOW_MASK(unit << 3)),
                           unit);
        *len -= unit;
    }
}

static void dump_reg(uint32_t addr, int num, int unit)
{
    uint32_t data;
    int i;

    while (num > 0) {
        printf("0x%08lx:  ", addr);
        for (i = 0; i < 4 && num > 0; i++) {
            data = *(volatile uint32_t *)(addr + (i << 2));
            dump_one_reg(data, unit, &num);
        }
        addr += 16;
        printf("\n");
    }
}

static void command_io_help(void)
{
    printf("Raw memory i/o utility\n");
    printf("\nio -v -1|2|4 -r|w [-l <len>] <addr> [<value>]\n");
    printf("\n    -v          Verbose, asks for confirmation\n");
    printf("    -1|2|4      Sets memory access size in bytes (default byte)\n");
    printf("    -l <len>    Length in bytes of area to access (defaults to one access)\n");
    printf("    -r|w        Read from or Write to memory (default read)\n");
    printf("    <addr>      The memory address to access\n");
    printf("    <var>       The value to write (implies -w)\n");
    printf("\nExamples:\n");
    printf("    io 0x1000           Reads one bytes from 0x1000\n");
    printf("    io 0x1000 0x12      Writes 0x12 to location 0x1000\n");
    printf("    io -2 -l 8 0x1000   Reads 8 words from 0x1000\n");
}

static int command_io_parse(uint8_t *input, int len,
                            struct command_io_info *command)
{
    uint8_t *next;
    uint32_t *val;

    command->len = 1;
    command->write = false;
    command->unit = 1;
    command->val = 0;
    command->addr = 0;

    next = input;
    while (len) {
        input = console_get_paramter(next, &len, &next);
        if (!input) {
            return -1;
        }

        if (input[0] != '-') {
            if (!command->addr) {
                val = &command->addr;
            } else {
                command->write = true;
                val = &command->val;
            }

            *val = strtoul((char *)input, NULL, 0);
            if (input == next) {
                return -1;
            }

            continue;
        }

        switch (input[1]) {
        case 'v':
            printf("Version 1.0\n");

            return -1;
        case 'l':
            input = console_get_paramter(next, &len, &next);
            if (!input) {
                return -1;
            }

            command->len = strtoul((char *)input, NULL, 0);
            if (input == next) {
                return -1;
            }
            break;
        case '1':
            command->unit = 1;
            break;
        case '4':
            command->unit = 4;
            break;
        case '8':
            command->unit = 8;
            break;
        case 'r':
            command->write = false;
            break;
        case 'h':
            command_io_help();
            break;
        default:
            return -1;
        }
    }

    if (command->len > 1 && command->write) {
        return -1;
    }

    return command->addr ? 0 : -1;
}

static void command_io_process(uint8_t *in, int len)
{
    struct command_io_info command;

    if (command_io_parse(in, len, &command)) {
        return;
    }

    if (command.write) {
        *(volatile uint32_t *)(command.addr) = command.val;
    } else {
        dump_reg(command.addr, command.len, command.unit);
    }
}

struct console_command command_io = {
    .name = "io",
    .help = "Show or set value of register",
    .process = command_io_process,
};
