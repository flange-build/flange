/**
  * Copyright (c) 2023 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  */

#include <rtthread.h>
#include <rtdevice.h>

#ifdef RT_USING_DFS_RAMFS
#include <dfs_fs.h>
#include "dfs_ramfs.h"

extern uint32_t __share_ramfs_start__[];
extern uint32_t __share_ramfs_end__[];

#define SHMEM_RAMFS_BEGIN   (&__share_ramfs_start__)
#define SHMEM_RAMFS_END     (&__share_ramfs_end__)
#define SHMEM_RAMFS_SIZE    ((rt_uint32_t)SHMEM_RAMFS_END - (rt_uint32_t)SHMEM_RAMFS_BEGIN)

int share_ramfs_init(void)
{
    struct dfs_ramfs *ramfs;
    int ret = -RT_ERROR;

    ramfs = (struct dfs_ramfs *)dfs_ramfs_create((rt_uint8_t *)SHMEM_RAMFS_BEGIN, SHMEM_RAMFS_SIZE);

    if (opendir("ramfs"))
    {
        ret = dfs_mount(NULL, "/ramfs", "ram", 0, ramfs);
    }
    else
    {
        if (RT_EOK == mkdir("/ramfs", 0x777))
        {
            ret = dfs_mount(NULL, "/ramfs", "ram", 0, ramfs);
        }
    }

    if (ret)
    {
        ret = dfs_mount(NULL, "/", "ram", 0, ramfs);
    }

    if (ret)
    {
        rt_kprintf("mount ramfs failed\n");
    }

    return ret;
}

#ifdef PRIMARY_CPU
INIT_APP_EXPORT(share_ramfs_init);
#endif

#endif
