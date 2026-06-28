/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2021-04-12     Steven Liu   the first version
 */
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"

int main(int argc, char **argv)
{
    rt_kprintf("Hello RK3308 RT-Thread!\n");

    if (HAL_CPU_TOPOLOGY_GetCurrentCpuId() == 1)
    {
        rt_kprintf("begin delay 10s\n");
        rt_thread_delay(10 * RT_TICK_PER_SECOND);
        rt_kprintf("end delay 10s\n");
    }

    return RT_EOK;
}
