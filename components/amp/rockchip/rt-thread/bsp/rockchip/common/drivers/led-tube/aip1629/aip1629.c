/**
  * Copyright (c) 2024 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include "rtthread.h"
#include "rtdevice.h"

#ifdef RT_USING_AIP1629
#include "../drv_led_tube.h"
#include "aip1629.h"
#include "aip1629_spi.h"

struct rt_device *rt_aip1629;

static rt_err_t aip1629_control(rt_device_t dev, int cmd, void *args)
{
    switch (cmd)
    {
    case RT_LED_SET_DISPLAY_INFO:
        rt_hw_aip1629_display_info(args);
        break;
    case RT_LED_SET_DISPLAY_DIMMER:
        rt_hw_aip1629_display_dimmer(args);
        break;
    default:
        break;
    }

    return RT_EOK;
}

#ifdef RT_USING_DEVICE_OPS
const static struct rt_device_ops aip1629_ops =
{
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    aip1629_control,
};
#endif

int rt_hw_aip1629_init(void)
{
    rt_aip1629 = rt_malloc(sizeof(struct rt_device));
    if (!rt_aip1629)
    {
        return -RT_ERROR;
    }

    /* init rt_device structure */
    rt_aip1629->type = RT_Device_Class_Graphic;
#ifdef RT_USING_DEVICE_OPS
    rt_aip1629->ops = &aip1629_ops;
#else
    rt_aip1629->init = NULL;
    rt_aip1629->open = NULL;
    rt_aip1629->close = NULL;
    rt_aip1629->read = NULL;
    rt_aip1629->write = NULL;
    rt_aip1629->control = aip1629_control;
#endif

    /* register rt_aip1629 device to RT-Thread */
    rt_device_register(rt_aip1629, RT_AIP1629_DEVICE, RT_DEVICE_FLAG_RDWR | RT_DEVICE_FLAG_INT_RX);

    rt_hw_aip1629_display_init();
    return 0;
}

INIT_DEVICE_EXPORT(rt_hw_aip1629_init);
#endif
