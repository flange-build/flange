/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rthw.h>
#include <rtthread.h>

#ifndef _DRV_PCIE_EP_H__
#define _DRV_PCIE_EP_H__

struct rt_hw_pcie_ep_board
{
    uintptr_t bar0_cpu_addr;
    uintptr_t bar1_cpu_addr;
    uintptr_t bar2_cpu_addr;
    uintptr_t bar3_cpu_addr;
    uintptr_t bar4_cpu_addr;
    uintptr_t bar5_cpu_addr;
};

uintptr_t rk_pcie_ep_mmap(rt_device_t dev, uint32_t cur_mmap_res);

#endif