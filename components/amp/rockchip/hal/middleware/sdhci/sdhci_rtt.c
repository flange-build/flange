/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 * Match to XTerm Control Sequences VT102, applied by `mimicom`.
 * Related to https://invisible-island.net/xterm/ctlseqs/ctlseqs.html
 */
#ifdef RT_THREAD
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"
#include "mmc_api.h"
#define SD_SECTOR_SIZE  512

struct sdhci_device
{
    struct rt_device parent;
};

static struct sdhci_device sdhci_dev;

static rt_err_t sdhci_init(rt_device_t dev)
{
    int ioctlParam[5] = {0, 0, 0, 0, 0};
    int ret;
#if defined (SOC_RK3568)
    sdmmc_init((void *)0xFE310000);
#elif defined (SOC_RK3562)
    sdmmc_init((void *)0xFF870000);
#endif
    ret = sdmmc_ioctrl(SDM_IOCTRL_REGISTER_CARD, ioctlParam);
    if (ret) {
        printf("emmc init error!\n");
        return -1;
    }

    return 0;
}

static rt_err_t sdhci_open(rt_device_t dev, rt_uint16_t oflag)
{
    return RT_EOK;
}

static rt_err_t sdhci_close(rt_device_t dev)
{
    return RT_EOK;
}

static rt_size_t sdhci_read(rt_device_t dev, rt_off_t pos, void *buffer, rt_size_t size)
{
    rt_size_t rt = 0;

    if (!sdmmc_read((uint32_t)pos, (uint32_t)size , buffer))
        rt = size;

    return rt;
}

static rt_size_t sdhci_write(rt_device_t dev, rt_off_t pos, const void *buffer, rt_size_t size)
{
    rt_size_t rt = 0;

    if (!sdmmc_write((uint32_t)pos, (uint32_t)size , buffer))
        rt = size;

    return rt;
}

static rt_err_t sdhci_control(rt_device_t dev, int cmd, void *args)
{
    int ioctlParam[5] = {0, 0, 0, 0, 0};
    rt_err_t result = RT_EOK;

    switch (cmd)
    {
        case RT_DEVICE_CTRL_BLK_GETGEOME:
            {
                struct rt_device_blk_geometry *geometry = (struct rt_device_blk_geometry *)args;
                geometry->bytes_per_sector = SD_SECTOR_SIZE;
                if (sdmmc_ioctrl(SDM_IOCTR_GET_CAPABILITY, ioctlParam)) {
                   printf("emmc get capability error!\n");
                   result = -RT_ERROR;
                } else {
                    geometry->sector_count = ioctlParam[1];
                }
                geometry->block_size = SD_SECTOR_SIZE;
            }
            break;

        default:
            result = -RT_ERROR;
            break;
    }

    return result;
}

#ifdef RT_USING_DEVICE_OPS
const static struct rt_device_ops sdhci_blk_ops =
{
    sdhci_init,
    sdhci_open,
    sdhci_close,
    sdhci_read,
    sdhci_write,
    sdhci_control
};
#endif

int rt_sdhci_driver_init(void)
{
    sdhci_dev.parent.type         = RT_Device_Class_Block;
#ifdef RT_USING_DEVICE_OPS
    sdhci_dev.parent.ops  = &sdhci_blk_ops;
#else
    sdhci_dev.parent.init         = sdhci_init;
    sdhci_dev.parent.open         = sdhci_open;
    sdhci_dev.parent.close        = sdhci_close;
    sdhci_dev.parent.read         = sdhci_read;
    sdhci_dev.parent.write        = sdhci_write;
    sdhci_dev.parent.control      = sdhci_control;
#endif
    sdhci_dev.parent.user_data    = RT_NULL;

    return rt_device_register(&sdhci_dev.parent, "sdhci0", RT_DEVICE_FLAG_RDWR | RT_DEVICE_FLAG_STANDALONE);
}
INIT_DEVICE_EXPORT(rt_sdhci_driver_init);
#endif
