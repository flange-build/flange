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
    rt_uint32_t cpu_id;

    cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();
    rt_kprintf("Hello RK3568 RT-Thread! CPU_ID(%d)\n", cpu_id);

    return RT_EOK;
}
