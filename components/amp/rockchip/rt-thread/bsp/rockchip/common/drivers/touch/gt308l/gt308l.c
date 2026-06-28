/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    gt308l.c
  * @version V0.1
  * @brief   gt308l driver
  *
  * Change Logs:
  * Date           Author          Notes
  * 2023-04-10     Jair Wu         the first version
  *
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>
#include <stdlib.h>
#include <string.h>

#include "hal_base.h"
#include "board.h"
#include "touch.h"
#include "gt308l.h"

#define GT308L_DEBUG    0

#if GT308L_DEBUG
#define DEBUG(fmt, args...)  rt_kprintf(fmt, ##args)
#else
#define DEBUG(fmt, args...)
#endif

#define THREAD_STACK_SIZE       2048
#define THREAD_PRIORITY         10

struct gt308l_priv;

struct gt308l_workdata
{
    uint32_t mask;
    struct gt308l_priv *gt308l;
};

struct gt308l_priv
{
    struct rt_touch_device touch;
    struct rt_i2c_client *client;
    struct gt308l_hook hook;
    rt_thread_t tid;
    rt_sem_t sem;
};

rt_inline struct gt308l_priv *to_gt308l_priv(struct rt_touch_device *touch)
{
    return rt_container_of(touch, struct gt308l_priv, touch);
}

static rt_err_t gt_wr_reg(struct rt_i2c_client *i2c_client,
                          uint8_t reg8, uint8_t data8)
{
    struct rt_i2c_msg msgs[1];
    uint8_t data_buf[2];
    rt_err_t ret;

    data_buf[0] = reg8;
    data_buf[1] = data8;

    msgs[0].addr = i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf = data_buf;
    msgs[0].len = 2;

    ret = rt_i2c_transfer(i2c_client->bus, msgs, 1);
    if (ret != 1)
    {
        rt_kprintf("ERR: %s: failed: (%d)\n", __func__, ret);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t gt_rd_reg(struct rt_i2c_client *i2c_client,
                          uint8_t reg8, uint8_t *data8)
{
    struct rt_i2c_msg msgs[2];
    rt_err_t ret;

    msgs[0].addr = i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf = &reg8;
    msgs[0].len = 1;

    msgs[1].addr = i2c_client->client_addr;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf = data8;
    msgs[1].len = 1;

    ret = rt_i2c_transfer(i2c_client->bus, msgs, 2);
    if (ret != 2)
    {
        rt_kprintf("ERR: %s: failed: (%d)\n", __func__, ret);
        return ret;
    }

    return RT_EOK;
}

static rt_err_t gt_update_bits(struct rt_i2c_client *i2c_client,
                               uint8_t reg, uint8_t mask, uint8_t val)
{
    uint8_t old, new;
    int ret;

    ret = gt_rd_reg(i2c_client, reg, &old);
    if (ret < 0)
        goto err;

    new = (old & ~mask) | (val & mask);
    ret = gt_wr_reg(i2c_client, reg, new);

err:
    return ret;
}

static rt_err_t irq_handle(rt_touch_t touch)
{
    struct gt308l_priv *gt308l;

    gt308l = to_gt308l_priv(touch);

    rt_sem_release(gt308l->sem);

    return RT_EOK;
}

static void gt308l_thread(void *arg)
{
    struct gt308l_priv *gt308l = (struct gt308l_priv *)arg;
    struct gt308l_hook *p;
    rt_uint8_t last;
    rt_uint8_t new;
    rt_uint8_t change;
    rt_err_t ret;

    ret = gt_rd_reg(gt308l->client, GT308L_TOUCH_OUTPUT_REG2A, &last);
    if (ret != RT_EOK)
        last = 0;

    while (1)
    {
        rt_sem_take(gt308l->sem, RT_WAITING_FOREVER);

        ret = gt_rd_reg(gt308l->client, GT308L_TOUCH_OUTPUT_REG2A, &new);
        if (ret != RT_EOK)
            continue;

        DEBUG("%x => %x\n", last, new);
        change = new ^last;

        rt_list_for_each_entry(p, &gt308l->hook.list, list)
        {
            DEBUG("mask %x %x\n", p->mask, change);
            if (p->mask & change)
            {
                rt_uint8_t oc = p->mask & change;
                DEBUG("oc %x press %x release %x\n", oc, oc & last, oc & new);
                /* Release */
                if (oc & last)
                    p->hook(oc & last, p->arg, RT_FALSE);
                /* Press */
                if (oc & new)
                    p->hook(oc & new, p->arg, RT_TRUE);
            }
        }

        last = new;
    }
}

static rt_err_t gt308l_register_hook(struct gt308l_priv *gt308l, void *data)
{
    struct gt308l_hook *new  = (struct gt308l_hook *)rt_malloc(sizeof(struct gt308l_hook));

    if (!data || !new)
        return -RT_ERROR;

    rt_memcpy(new, data, sizeof(struct gt308l_hook));
    rt_list_insert_after(&gt308l->hook.list, &new->list);

    return RT_EOK;
}

static rt_err_t gt308l_unregister_hook(struct gt308l_priv *gt308l, void *data)
{
    struct gt308l_hook *hook = (struct gt308l_hook *)data;
    struct gt308l_hook *p;

    if (!hook || rt_list_isempty(&gt308l->hook.list))
        return RT_EOK;

    rt_list_for_each_entry(p, &gt308l->hook.list, list)
    {
        if (p->hook == hook->hook)
        {
            rt_list_remove(&p->list);
            break;
        }
    }

    return RT_EOK;
}

struct gt308l_led_reg_info
{
    rt_uint8_t reg;
    rt_uint8_t mask;
    rt_uint8_t shift;
} led_info[] =
{
    {GT308L_PWM_DATA1_REG48, GT308L_PWM_DATA1_MASK, GT308L_PWM_DATA1_SHIFT},
    {GT308L_PWM_DATA2_REG48, GT308L_PWM_DATA2_MASK, GT308L_PWM_DATA2_SHIFT},
    {GT308L_PWM_DATA3_REG49, GT308L_PWM_DATA3_MASK, GT308L_PWM_DATA3_SHIFT},
    {GT308L_PWM_DATA4_REG49, GT308L_PWM_DATA4_MASK, GT308L_PWM_DATA4_SHIFT},
    {GT308L_PWM_DATA5_REG4A, GT308L_PWM_DATA5_MASK, GT308L_PWM_DATA5_SHIFT},
    {GT308L_PWM_DATA6_REG4A, GT308L_PWM_DATA6_MASK, GT308L_PWM_DATA6_SHIFT},
    {GT308L_PWM_DATA7_REG4B, GT308L_PWM_DATA7_MASK, GT308L_PWM_DATA7_SHIFT},
    {GT308L_PWM_DATA8_REG4B, GT308L_PWM_DATA8_MASK, GT308L_PWM_DATA8_SHIFT}
};

static rt_err_t gt308l_switch_led(struct gt308l_priv *gt308l, void *data)
{
    rt_uint8_t *buf = (rt_uint8_t *)data;
    rt_uint8_t mask = buf[0];
    rt_uint8_t val  = buf[1];
    rt_err_t ret;

    ret = gt_update_bits(gt308l->client, GT308L_PWM_CH_EN_REG05, mask, val);
    if (ret != RT_EOK)
        return ret;

    for (int i = 0; i < GT308L_MAX_LED; i++)
    {
        if (mask & (1 << i))
        {
            if (val & (1 << i))
                ret |= gt_update_bits(gt308l->client, led_info[i].reg,
                                      led_info[i].mask, 0xf << led_info[i].shift);
            else
                ret |= gt_update_bits(gt308l->client, led_info[i].reg,
                                      led_info[i].mask, 0x0 << led_info[i].shift);
        }
    }

    if (mask & val)
    {
        ret |= gt_update_bits(gt308l->client, GT308L_PWM_EN_REG3B,
                              GT308L_PWM_EN_MASK, GT308L_PWM_EN_MASK);
    }

    return ret;
}

static rt_err_t gt308l_direct_led(struct gt308l_priv *gt308l, void *data)
{
    rt_uint8_t *buf = (rt_uint8_t *)data;
    rt_uint8_t mask = buf[0];
    rt_uint8_t val  = buf[1];

    return gt_update_bits(gt308l->client, GT308L_PWM_CH_EN_REG05, mask, !val);
}

static rt_err_t gt308l_control(struct rt_touch_device *device, int cmd, void *data)
{
    struct gt308l_priv *gt308l = to_gt308l_priv(device);
    rt_uint8_t buf;
    rt_err_t ret = RT_EOK;

    switch (cmd)
    {
    case RT_TOUCH_CTRL_GET_ID:
        ret = gt_rd_reg(gt308l->client, GT308L_CHIPID_REG02, &buf);
        *(int *)data = buf;
        break;
    case RT_TOUCH_CTRL_REGISTER_HOOK:
        ret = gt308l_register_hook(gt308l, data);
        break;
    case RT_TOUCH_CTRL_UNREGISTER_HOOK:
        ret = gt308l_unregister_hook(gt308l, data);
        break;
    case RT_TOUCH_CTRL_SWITCH_LED:
        ret = gt308l_switch_led(gt308l, data);
        break;
    case RT_TOUCH_CTRL_DIRECT_LED:
        ret = gt308l_direct_led(gt308l, data);
        break;
    default:
        rt_kprintf("Unknown cmd %d", cmd);
        break;
    }

    return ret;
}

static struct rt_touch_ops touch_ops =
{
    .touch_control   = gt308l_control,
};

static int rt_hw_gt308l_init(void)
{
    struct rt_touch_config cfg;
    struct rt_device_pin_mode rst_pin;
    const char *touch_name = TOUCH_DEV_NAME;
    rt_touch_t touch_device;
    struct gt308l_priv *gt308l;
    rt_err_t ret;

    RT_ASSERT(TOUCH_RST_PIN != 0);
    RT_ASSERT(TOUCH_IRQ_PIN != 0);
    RT_ASSERT(TOUCH_I2C_DEV != 0);

    /* touch config init */
    rst_pin.pin = TOUCH_RST_PIN;
    cfg.irq_pin.pin  = TOUCH_IRQ_PIN;
    cfg.irq_pin.mode = PIN_MODE_INPUT_PULLUP;
    cfg.dev_name = TOUCH_I2C_DEV;

    /* gt308l hardware init */
    rt_pin_mode(rst_pin.pin, PIN_MODE_OUTPUT);
    rt_pin_mode(cfg.irq_pin.pin, PIN_MODE_INPUT);
    rt_pin_write(rst_pin.pin, PIN_HIGH);
    rt_thread_mdelay(1);
    rt_pin_write(rst_pin.pin, PIN_LOW);
    rt_pin_mode(cfg.irq_pin.pin, PIN_MODE_INPUT_PULLUP);
    rt_thread_mdelay(20);

    gt308l = (struct gt308l_priv *)rt_calloc(1, sizeof(struct gt308l_priv));
    RT_ASSERT(gt308l != RT_NULL);

    gt308l->sem = rt_sem_create(touch_name, 1, RT_IPC_FLAG_PRIO);
    RT_ASSERT(gt308l->sem != RT_NULL);

    gt308l->tid = rt_thread_create("gt308l", gt308l_thread, gt308l,
                                   THREAD_STACK_SIZE, THREAD_PRIORITY, 10);
    RT_ASSERT(gt308l->tid != RT_NULL);
    rt_thread_startup(gt308l->tid);

    rt_list_init(&gt308l->hook.list);

    /* i2c interface bus */
    gt308l->client = (struct rt_i2c_client *)rt_calloc(1, sizeof(struct rt_i2c_client));
    RT_ASSERT(gt308l->client != RT_NULL);
    gt308l->client->client_addr = TOUCH_SLAVE_ADDRESS;
    gt308l->client->bus = (struct rt_i2c_bus_device *)rt_device_find(cfg.dev_name);
    RT_ASSERT(gt308l->client->bus != RT_NULL);

    ret = rt_device_open((rt_device_t)gt308l->client->bus, RT_DEVICE_FLAG_RDWR);
    RT_ASSERT(ret == RT_EOK);

    /* register touch device */
    touch_device = &gt308l->touch;

    touch_device->irq_handle = irq_handle;
    touch_device->info.type = RT_TOUCH_TYPE_CAPACITANCE;
    touch_device->info.vendor = 0;
    rt_memcpy(&touch_device->config, &cfg, sizeof(struct rt_touch_config));
    touch_device->ops = &touch_ops;
    rt_hw_touchkey_register(touch_device, touch_name, RT_DEVICE_FLAG_INT_RX, RT_NULL);

    return RT_EOK;
}

INIT_DEVICE_EXPORT(rt_hw_gt308l_init);
