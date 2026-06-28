/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_touchkey.c
  * @version V0.1
  * @brief   touchkey driver
  *
  * Change Logs:
  * Date           Author          Notes
  * 2023-04-10     Jair Wu         the first version
  *
  ******************************************************************************
  */

#include <rtthread.h>
#include <string.h>

#ifdef RT_USING_TOUCHKEY_DRIVERS

#include "touch.h"
#define DBG_TAG  "touchkey"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

/* ISR for touch interrupt */
static void irq_callback(void *args)
{
    rt_touch_t touch;

    touch = (rt_touch_t)args;

    if (touch->irq_handle != RT_NULL)
        touch->irq_handle(touch);
}

/* touch interrupt initialization function */
static rt_err_t rt_touch_irq_init(rt_touch_t touch)
{
    if (touch->config.irq_pin.pin == RT_PIN_NONE)
    {
        return -RT_EINVAL;
    }

    rt_pin_mode(touch->config.irq_pin.pin, touch->config.irq_pin.mode);

    if (touch->config.irq_pin.mode == PIN_MODE_INPUT_PULLDOWN)
    {
        rt_pin_attach_irq(touch->config.irq_pin.pin, PIN_IRQ_MODE_RISING, irq_callback, (void *)touch);
    }
    else if (touch->config.irq_pin.mode == PIN_MODE_INPUT_PULLUP)
    {
        rt_pin_attach_irq(touch->config.irq_pin.pin, PIN_IRQ_MODE_FALLING, irq_callback, (void *)touch);
    }
    else if (touch->config.irq_pin.mode == PIN_MODE_INPUT)
    {
        rt_pin_attach_irq(touch->config.irq_pin.pin, PIN_IRQ_MODE_RISING_FALLING, irq_callback, (void *)touch);
    }

    rt_pin_irq_enable(touch->config.irq_pin.pin, PIN_IRQ_ENABLE);

    return RT_EOK;
}

/* touch interrupt enable */
static void rt_touch_irq_enable(rt_touch_t touch)
{
    if (touch->config.irq_pin.pin != RT_PIN_NONE)
    {
        rt_pin_irq_enable(touch->config.irq_pin.pin, RT_TRUE);
    }
}

/* touch interrupt disable */
static void rt_touch_irq_disable(rt_touch_t touch)
{
    if (touch->config.irq_pin.pin != RT_PIN_NONE)
    {
        rt_pin_irq_enable(touch->config.irq_pin.pin, RT_FALSE);
    }
}

static rt_err_t rt_touch_open(rt_device_t dev, rt_uint16_t oflag)
{
    rt_touch_t touch;
    RT_ASSERT(dev != RT_NULL);
    touch = (rt_touch_t)dev;

    if (oflag & RT_DEVICE_FLAG_INT_RX && dev->flag & RT_DEVICE_FLAG_INT_RX)
    {
        /* Initialization touch interrupt */
        rt_touch_irq_init(touch);
    }

    return RT_EOK;
}

static rt_err_t rt_touch_close(rt_device_t dev)
{
    rt_touch_t touch;
    RT_ASSERT(dev != RT_NULL);
    touch = (rt_touch_t)dev;

    /* touch disable interrupt */
    rt_touch_irq_disable(touch);

    return RT_EOK;
}

static rt_err_t rt_touch_control(rt_device_t dev, int cmd, void *args)
{
    rt_touch_t touch;
    rt_err_t result = RT_EOK;
    RT_ASSERT(dev != RT_NULL);
    touch = (rt_touch_t)dev;

    switch (cmd)
    {
    case RT_TOUCH_CTRL_DISABLE_INT:
        rt_touch_irq_disable(touch);
        break;
    case RT_TOUCH_CTRL_ENABLE_INT:
        rt_touch_irq_enable(touch);
        break;
    default:
        result = touch->ops->touch_control(touch, cmd, args);
        break;
    }

    return result;
}

#ifdef RT_USING_DEVICE_OPS
const static struct rt_device_ops rt_touch_ops =
{
    RT_NULL,
    rt_touch_open,
    rt_touch_close,
    RT_NULL,
    RT_NULL,
    rt_touch_control
};
#endif

/*
 * touch register
 */
int rt_hw_touchkey_register(rt_touch_t touch,
                            const char              *name,
                            rt_uint32_t              flag,
                            void                    *data)
{
    rt_int8_t result;
    rt_device_t device;
    RT_ASSERT(touch != RT_NULL);

    device = &touch->parent;

#ifdef RT_USING_DEVICE_OPS
    device->ops         = &rt_touch_ops;
#else
    device->init        = RT_NULL;
    device->open        = rt_touch_open;
    device->close       = rt_touch_close;
    device->read        = rt_touch_read;
    device->write       = RT_NULL;
    device->control     = rt_touch_control;
#endif
    device->type        = RT_Device_Class_Touch;
    device->rx_indicate = RT_NULL;
    device->tx_complete = RT_NULL;
    device->user_data   = data;

    result = rt_device_register(device, name, flag | RT_DEVICE_FLAG_STANDALONE);

    if (result != RT_EOK)
    {
        LOG_E("rt_touch register err code: %d", result);
        return result;
    }

    LOG_I("rt_touch init success");

    return RT_EOK;
}
#endif

