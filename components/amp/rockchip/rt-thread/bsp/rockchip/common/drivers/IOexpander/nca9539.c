/*
 * Copyright (c) 2006-2025, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2025-02-06     tom.song     the first version
 */

#include <rtthread.h>
#include <rtdevice.h>
#include <string.h>
#include <stdlib.h>
#include "hal_base.h"
#include "board.h"
#include "nca9539.h"

static struct rt_i2c_client *nca9539_client;
typedef struct rt_device_pin *rt_expin_t;
static rt_expin_t pin_device = RT_NULL;

static rt_err_t write_reg(struct rt_i2c_bus_device *bus, rt_uint8_t reg, rt_uint8_t *data)
{
    rt_uint8_t buf[2];
    struct rt_i2c_msg msgs;
    rt_uint32_t buf_size = 1;

    buf[0] = reg; //cmd
    if (data != RT_NULL)
    {
        buf[1] = data[0];
        //buf[2] = data[1];
        buf_size = 2;
    }

    msgs.addr = NCA9539_ADDR;
    msgs.flags = RT_I2C_WR;
    msgs.buf = buf;
    msgs.len = buf_size;

    if (rt_i2c_transfer(bus, &msgs, 1) == 1)
    {
        return RT_EOK;
    }
    else
    {
        return -RT_ERROR;
    }
}

static rt_err_t read_regs(struct rt_i2c_bus_device *bus, rt_uint8_t len, rt_uint8_t *buf)
{
    struct rt_i2c_msg msgs;

    msgs.addr = NCA9539_ADDR;
    msgs.flags = RT_I2C_RD;
    msgs.buf = buf;
    msgs.len = len;

    if (rt_i2c_transfer(bus, &msgs, 1) == 1)
    {
        return RT_EOK;
    }
    else
    {
        return -RT_ERROR;
    }
}

static rt_err_t read_nca9539(rt_uint16_t  addr, rt_uint32_t  count, rt_uint8_t *buf)
{
    rt_uint8_t temp[8] = {0};
    rt_err_t ret;
    write_reg(nca9539_client->bus, addr, RT_NULL);
    ret = read_regs(nca9539_client->bus, count, temp);
    for (int i = 0; i < count; i++)
    {
        buf[i] = temp[i];
    }
    return  ret;
}

static int nca9539_gpio_get_direction(unsigned int offset)
{
    unsigned int port = offset / NCA9539_BANK_SZ;
    unsigned int pin = offset % NCA9539_BANK_SZ;
    rt_uint8_t value;
    int ret;

    ret = read_nca9539(NCA9539_REG_CONFIG_BASE + port, 1, &value);
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) read config failed\n", __func__, offset);
        return ret;
    }
    if (value & BIT(pin))
        return 0;

    return 1;
}

static int nca9539_gpio_direction_input(unsigned int offset)
{
    unsigned int port = offset / NCA9539_BANK_SZ;
    unsigned int pin = offset % NCA9539_BANK_SZ;
    rt_uint8_t val;
    int ret = 0;

    ret = read_nca9539(NCA9539_REG_CONFIG_BASE + port, 1, &val);
    if (ret == RT_EOK)
    {
        val &= ~BIT(pin);
        val |= BIT(pin);
        ret = write_reg(nca9539_client->bus, NCA9539_REG_CONFIG_BASE + port, &val);
    }

    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) read config failed\n", __func__, offset);
    }

    return ret;
}

static int nca9539_gpio_direction_output(unsigned int offset, int val)
{
    unsigned int port = offset / NCA9539_BANK_SZ;
    unsigned int pin = offset % NCA9539_BANK_SZ;
    rt_uint8_t value;
    int ret;

    ret = read_nca9539(NCA9539_REG_CONFIG_BASE + port, 1, &value);

    if (ret == RT_EOK)
    {
        value &= ~BIT(pin);
        ret = write_reg(nca9539_client->bus, NCA9539_REG_CONFIG_BASE + port, &value);
    }
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) read config failed\n", __func__, offset);
    }

    ret = read_nca9539(NCA9539_REG_OUTPUT_PORT_BASE + port, 1, &value);
    if (ret == RT_EOK)
    {
        value &= ~BIT(pin);
        value |= val ? BIT(pin) : 0;
        ret = write_reg(nca9539_client->bus, NCA9539_REG_OUTPUT_PORT_BASE + port, &value);
    }
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) val(%d) update output failed\n", __func__, offset, val);
    }

    return ret;
}

static int nca9539_gpio_get(struct rt_device *device, rt_base_t offset)
{
    unsigned int port = offset / NCA9539_BANK_SZ;
    unsigned int pin = offset % NCA9539_BANK_SZ;
    int reg;
    rt_uint8_t value;
    int ret;

    ret = read_nca9539(NCA9539_REG_CONFIG_BASE + port, 1, &value);
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) check config failed\n", __func__, offset);
        return ret;
    }
    if (!(BIT(pin) & value))
        reg = NCA9539_REG_OUTPUT_PORT_BASE + port;
    else
        reg = NCA9539_REG_INPUT_PORT_BASE + port;
    ret = read_nca9539(reg, 1, &value);
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) read value failed\n", __func__, offset);
        return -RT_ERROR;
    }

    return !!(BIT(pin) & value);
}

static void nca9539_gpio_set(struct rt_device *device, rt_base_t offset, rt_base_t val)
{
    unsigned int port = offset / NCA9539_BANK_SZ;
    unsigned int pin = offset % NCA9539_BANK_SZ;
    rt_uint8_t value;
    int ret;
    ret = read_nca9539(NCA9539_REG_CONFIG_BASE + port, 1, &value);
    if (ret < 0 || !!(BIT(pin) & value))
    {
        rt_kprintf("%s offset(%d) val(%d) check config failed\n", __func__, offset, val);
    }
    ret = read_nca9539(NCA9539_REG_OUTPUT_PORT_BASE + port, 1, &value);
    if (ret == RT_EOK)
    {
        value &= ~BIT(pin);
        value |= val ? BIT(pin) : 0;
        ret = write_reg(nca9539_client->bus, NCA9539_REG_OUTPUT_PORT_BASE + port, &value);
    }
    if (ret < 0)
    {
        rt_kprintf("%s offset(%d) val(%d) read input failed\n", __func__, offset, val);
    }

}

void  nca9539_gpio_set_mode(struct rt_device *device, rt_base_t offset, rt_base_t mode)
{
    switch (mode)
    {
    case PIN_MODE_OUTPUT:
        nca9539_gpio_direction_output(offset, PIN_HIGH);
    case PIN_MODE_INPUT:
        nca9539_gpio_direction_output(offset, PIN_LOW);
        break;
    }

}

static const struct rt_pin_ops expin_ops =
{
    .pin_mode  = nca9539_gpio_set_mode,
    .pin_write = nca9539_gpio_set,
    .pin_read  = nca9539_gpio_get,
};

rt_err_t rt_nca9539_device_init(struct rt_device_pin *pin, const char *name)
{
    pin->parent.type         = RT_Device_Class_Pin;
    pin->parent.rx_indicate  = RT_NULL;
    pin->parent.tx_complete  = RT_NULL;

#ifdef RT_USING_DEVICE_OPS
    pin->parent.ops          = &expin_ops;
#endif

    pin->ops                 = &expin_ops;

    rt_device_register(&pin->parent, name, RT_DEVICE_FLAG_RDWR);
    return RT_EOK;
}

int rt_hw_nca9539_init(void)
{
    rt_err_t ret = -1;
    uint8_t reg_val[1];

    nca9539_client = (struct rt_i2c_client *)rt_calloc(1, sizeof(struct rt_i2c_client));
    RT_ASSERT(nca9539_client != RT_NULL);
    nca9539_client->client_addr = NCA9539_ADDR;
    nca9539_client->bus = (struct rt_i2c_bus_device *)rt_device_find(NCA9539_I2C_BUS_NAME);
    RT_ASSERT(nca9539_client->bus != RT_NULL);
    ret = rt_device_open((rt_device_t)nca9539_client->bus, RT_DEVICE_FLAG_RDWR);
    RT_ASSERT(ret == RT_EOK);

    pin_device = (rt_expin_t)rt_calloc(1, sizeof(struct rt_device_pin));
    RT_ASSERT(pin_device != RT_NULL);

    pin_device->ops = &expin_ops;

    rt_nca9539_device_init(pin_device, IO_DEV_NAME);

    for (int i = 0; i < 16; i++)
    {
        nca9539_gpio_direction_output(i, PIN_MODE_OUTPUT);
        nca9539_gpio_set((struct rt_device *)pin_device, i, PIN_HIGH);
    }
    return RT_EOK;
}
INIT_DEVICE_EXPORT(rt_hw_nca9539_init);
//MSH_CMD_EXPORT(rt_hw_nca9539_init, rt_hw_nca9539_init);
