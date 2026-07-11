/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rtdevice.h>
#include <rtthread.h>

#ifdef RT_USING_IS31FL32XX
#include "hal_def.h"
#include "hal_base.h"
#include "is31fl32xx.h"

struct is31fl32xx_priv *g_is31fl32xx_priv = RT_NULL;

/**
 * struct is31fl32xx_chipdef - chip-specific attributes
 * @channels            : Number of LED channels
 * @shutdown_reg        : address of Shutdown register (optional)
 * @pwm_update_reg      : address of PWM Update register
 * @global_control_reg  : address of Global Control register (optional)
 * @reset_reg           : address of Reset register (optional)
 * @pwm_register_base   : address of first PWM register
 * @pwm_registers_reversed: : true if PWM registers count down instead of up
 * @led_control_register_base : address of first LED control register (optional)
 * @enable_bits_per_led_control_register: number of LEDs enable bits in each
 * @reset_func:         : pointer to reset function
 *
 * For all optional register addresses, the sentinel value %IS31FL32XX_REG_NONE
 * indicates that this chip has no such register.
 *
 * If non-NULL, @reset_func will be called during probing to set all
 * necessary registers to a known initialization state. This is needed
 * for chips that do not have a @reset_reg.
 *
 * @enable_bits_per_led_control_register must be >=1 if
 * @led_control_register_base != %IS31FL32XX_REG_NONE.
 */
struct is31fl32xx_chipdef
{
    rt_uint8_t  channels;
    rt_uint8_t  shutdown_reg;
    rt_uint8_t  pwm_update_reg;
    rt_uint8_t  global_control_reg;
    rt_uint8_t  reset_reg;
    rt_uint8_t  pwm_register_base;
    bool    pwm_registers_reversed;
    rt_uint8_t  led_control_register_base;
    rt_uint8_t  enable_bits_per_led_control_register;
    rt_int32_t (*reset_func)(struct is31fl32xx_priv *priv);
    rt_int32_t (*sw_shutdown_func)(struct is31fl32xx_priv *priv, bool enable);
};

#ifdef IS31FL3236
static const struct is31fl32xx_chipdef is31fl3236_cdef =
{
    .channels               = 36,
    .shutdown_reg               = 0x00,
    .pwm_update_reg             = 0x25,
    .global_control_reg         = 0x4a,
    .reset_reg              = 0x4f,
    .pwm_register_base          = 0x01,
    .led_control_register_base      = 0x26,
    .enable_bits_per_led_control_register   = 1,
};
#endif

#ifdef IS31FL3235
static const struct is31fl32xx_chipdef is31fl3235_cdef =
{
    .channels               = 28,
    .shutdown_reg               = 0x00,
    .pwm_update_reg             = 0x25,
    .global_control_reg         = 0x4a,
    .reset_reg              = 0x4f,
    .pwm_register_base          = 0x05,
    .led_control_register_base      = 0x2a,
    .enable_bits_per_led_control_register   = 1,
};
#endif

#ifdef IS31FL3218
static const struct is31fl32xx_chipdef is31fl3218_cdef =
{
    .channels               = 18,
    .shutdown_reg               = 0x00,
    .pwm_update_reg             = 0x16,
    .global_control_reg         = IS31FL32XX_REG_NONE,
    .reset_reg              = 0x17,
    .pwm_register_base          = 0x01,
    .led_control_register_base      = 0x13,
    .enable_bits_per_led_control_register   = 6,
};
#endif

#ifdef IS31FL3216
static rt_int32_t is31fl3216_reset(struct is31fl32xx_priv *priv);
static rt_int32_t is31fl3216_software_shutdown(struct is31fl32xx_priv *priv,
        bool enable);
static const struct is31fl32xx_chipdef is31fl3216_cdef =
{
    .channels               = 16,
    .shutdown_reg               = IS31FL32XX_REG_NONE,
    .pwm_update_reg             = 0xB0,
    .global_control_reg         = IS31FL32XX_REG_NONE,
    .reset_reg              = IS31FL32XX_REG_NONE,
    .pwm_register_base          = 0x10,
    .pwm_registers_reversed         = true,
    .led_control_register_base      = 0x01,
    .enable_bits_per_led_control_register   = 8,
    .reset_func             = is31fl3216_reset,
    .sw_shutdown_func           = is31fl3216_software_shutdown,
};
#endif

static rt_err_t is31fl32xx_wr_reg(struct rt_i2c_client *i2c_client, rt_uint8_t reg_addr, rt_uint8_t reg_data)
{
    struct rt_i2c_msg msgs[1];
    rt_uint8_t reg_info[2];
    rt_int32_t ret;

    reg_info[0] = reg_addr;
    reg_info[1] = reg_data;

    msgs[0].addr = i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf = reg_info;
    msgs[0].len = 2;

    ret = rt_i2c_transfer(i2c_client->bus, msgs, 1);
    if (ret != 1)
    {
        rt_kprintf("ERR: %s: failed: (%d)\n", __func__, ret);
        return ret;
    }

    return RT_EOK;
}

static rt_int32_t is31fl32xx_write(struct is31fl32xx_priv *priv, rt_uint8_t reg, rt_uint8_t val)
{
    rt_int32_t ret;
    rt_int32_t retries = 3;

    //rt_kprintf("writing register 0x%02X=0x%02X\n", reg, val);

    ret =  is31fl32xx_wr_reg(&priv->clientDevice, reg, val);
    while (ret && (retries-- > 0))
    {
        rt_kprintf("register write to 0x%02X failed (error %d),val=%d",
                   reg, ret, val);
        rt_thread_mdelay(100);
        ret = is31fl32xx_wr_reg(&priv->clientDevice, reg, val);
    }
    return ret;
}

#ifdef IS31FL3216
/*
 * Custom reset function for IS31FL3216 because it does not have a RESET
 * register the way that the other IS31FL32xx chips do. We don't bother
 * writing the GPIO and animation registers, because the registers we
 * do write ensure those will have no effect.
 */
static rt_int32_t is31fl3216_reset(struct is31fl32xx_priv *priv)
{
    rt_uint32_t i;
    rt_int32_t ret;

    ret = is31fl32xx_write(priv, IS31FL3216_CONFIG_REG,
                           IS31FL3216_CONFIG_SSD_ENABLE);
    if (ret)
        return ret;
    for (i = 0; i < priv->cdef->channels; i++)
    {
        ret = is31fl32xx_write(priv, priv->cdef->pwm_register_base + i,
                               0x00);
        if (ret)
            return ret;
    }
    ret = is31fl32xx_write(priv, priv->cdef->pwm_update_reg, 0);
    if (ret)
        return ret;
    ret = is31fl32xx_write(priv, IS31FL3216_LIGHTING_EFFECT_REG, 0x00);
    if (ret)
        return ret;
    ret = is31fl32xx_write(priv, IS31FL3216_CHANNEL_CONFIG_REG, 0x00);
    if (ret)
        return ret;

    return 0;
}

/*
 * Custom Software-Shutdown function for IS31FL3216 because it does not have
 * a SHUTDOWN register the way that the other IS31FL32xx chips do.
 * We don't bother doing a read/modify/write on the CONFIG register because
 * we only ever use a value of '0' for the other fields in that register.
 */
static rt_int32_t is31fl3216_software_shutdown(struct is31fl32xx_priv *priv, bool enable)
{
    rt_uint8_t value = enable ? IS31FL3216_CONFIG_SSD_ENABLE :
                       IS31FL3216_CONFIG_SSD_DISABLE;

    return is31fl32xx_write(priv, IS31FL3216_CONFIG_REG, value);
}
#endif

static rt_int32_t is31fl32xx_software_shutdown(struct is31fl32xx_priv *priv, bool enable)
{
    const struct is31fl32xx_chipdef *cdef = priv->cdef;
    rt_int32_t ret;

    if (cdef->shutdown_reg != IS31FL32XX_REG_NONE)
    {
        rt_uint8_t value = enable ? IS31FL32XX_SHUTDOWN_SSD_ENABLE :
                           IS31FL32XX_SHUTDOWN_SSD_DISABLE;
        ret = is31fl32xx_write(priv, cdef->shutdown_reg, value);
        if (ret)
            return ret;
    }

    if (cdef->sw_shutdown_func)
        return cdef->sw_shutdown_func(priv, enable);

    return 0;
}

static rt_int32_t is31fl32xx_init_regs(struct is31fl32xx_priv *priv)
{
    const struct is31fl32xx_chipdef *cdef = priv->cdef;
    rt_int32_t ret;

    ret = is31fl32xx_software_shutdown(priv, true);
    if (ret)
        rt_kprintf("%s, write to shutdown register failed\n", __func__);

    /*
     * Set enable bit for all channels.
     * We will control state with PWM registers alone.
     */
    if (cdef->led_control_register_base != IS31FL32XX_REG_NONE)
    {
        rt_uint8_t value =
            GENMASK(cdef->enable_bits_per_led_control_register - 1, 0);
        rt_uint8_t num_regs = cdef->channels /
                              cdef->enable_bits_per_led_control_register;
        rt_int32_t i;

        for (i = 0; i < num_regs; i++)
        {
            ret = is31fl32xx_write(priv,
                                   cdef->led_control_register_base + i,
                                   value);
            if (ret)
                return ret;
        }
    }

    ret = is31fl32xx_software_shutdown(priv, false);
    if (ret)
        return ret;

    if (cdef->global_control_reg != IS31FL32XX_REG_NONE)
    {
        ret = is31fl32xx_write(priv, cdef->global_control_reg, 0x00);
        if (ret)
            return ret;
    }

    return 0;
}

static void is31fl32xx_brightness_set(struct is31fl32xx_priv *priv, rt_uint32_t channel, rt_uint32_t brightness)
{
    const struct is31fl32xx_chipdef *cdef = priv->cdef;
    rt_uint8_t pwm_register_offset;

    rt_kprintf("%s:channel: %d, brightness: %d\n", __func__, channel, brightness);
    /* NOTE: led_data->channel is 1-based */
    if (cdef->pwm_registers_reversed)
        pwm_register_offset = cdef->channels - channel;
    else
        pwm_register_offset = channel - 1;

    is31fl32xx_write(priv, cdef->pwm_register_base + pwm_register_offset,
                     brightness);

    is31fl32xx_write(priv, cdef->pwm_update_reg, 0);
}

static rt_err_t is31fl32xx_control(rt_device_t dev, int cmd, void *args)
{
    rt_err_t result = RT_EOK;
    struct is31fl32xx_priv *is31fl32xxp = (struct is31fl32xx_priv *)dev;

    struct is31fl32x_brightness *data;

    switch (cmd)
    {
    case RT_IS31FL32XX_CMD_SET_BRIGHTNESS:
        data = (struct is31fl32x_brightness *)args;
        is31fl32xx_brightness_set(is31fl32xxp, data->channel, data->brightness);
        break;
    default:
        // Handle unknown command or add a log message if necessary
        result = -RT_ERROR;
        break;
    }
    return result;
}

#ifdef RT_USING_DEVICE_OPS
const static struct rt_device_ops is31fl32xx_ops =
{
    RT_NULL,
    RT_NULL,
    RT_NULL,
    RT_NULL,
    RT_NULL,
    is31fl32xx_control,
};
#endif

static rt_err_t rt_hw_is31fl32xx_register(struct is31fl32xx_priv *device, const char *name, const void *user_data)
{
    rt_err_t result = RT_EOK;

    device->parent.type = RT_Device_Class_Miscellaneous;
    device->parent.rx_indicate = RT_NULL;
    device->parent.tx_complete = RT_NULL;

#ifdef RT_USING_DEVICE_OPS
    device->parent.ops         = &is31fl32xx_ops;
#else
    device->parent.init        = RT_NULL;
    device->parent.open        = RT_NULL;
    device->parent.close       = RT_NULL;
    device->parent.read        = RT_NULL;
    device->parent.write       = RT_NULL;
    device->parent.control     = is31fl32xx_control;
#endif
    device->parent.user_data = (void *)user_data;

    result = rt_device_register(&device->parent, name, RT_DEVICE_FLAG_RDWR);

    return result;
}

static int rt_hw_is31fl32xx_init(void)
{
    rt_err_t ret;
    struct is31fl32xx_priv *dev = RT_NULL;

    /* init it6632x device */
    g_is31fl32xx_priv = dev = (struct is31fl32xx_priv *)rt_calloc(1, sizeof(struct is31fl32xx_priv));

    /* i2c interface bus */
    dev->clientDevice.bus = rt_i2c_bus_device_find(IS31FL32XX_I2C_BUS);
    if (!dev->clientDevice.bus)
    {
        rt_kprintf("ERR: %s: is31fl32xx i2c bus find failed!\n", __func__);
        return -1;
    }
    dev->clientDevice.client_addr = IS31FL32XX_I2C_ADR;
    dev->cdef = &is31fl3235_cdef;


    /* before here, IOMUX must be initialized in board_xxxx.c*/
    HAL_GPIO_SetPinDirection(IS31FL32XX_SDB_GPIO_GRP, IS31FL32XX_SDB_GPIO, GPIO_OUT);
    HAL_GPIO_SetPinLevel(IS31FL32XX_SDB_GPIO_GRP, IS31FL32XX_SDB_GPIO, IS31FL32XX_PIN_HIGH);


    is31fl32xx_init_regs(dev);

    ret = rt_hw_is31fl32xx_register(dev, IS31FL32XX_DEV_NAME, RT_NULL);
    RT_ASSERT(ret == RT_EOK);

    return RT_EOK;
}

INIT_DEVICE_EXPORT(rt_hw_is31fl32xx_init);

#if defined(RT_USING_FINSH) && defined(IS31FL32XX_DEBUG)
static int is31fl32xx(int argc, char **argv)
{
    static rt_device_t is31fl32xx_dev = RT_NULL;

    is31fl32xx_dev = rt_device_find(IS31FL32XX_DEV_NAME);
    if (!is31fl32xx_dev)
    {
        rt_kprintf("find %s failed!\n", IS31FL32XX_DEV_NAME);
        return -RT_ERROR;
    }

    if (argc > 1)
    {

        if (!strcmp(argv[1], "b"))
        {
            if (argc > 3)
            {
                struct is31fl32x_brightness data;
                data.channel = atoi(argv[2]);
                data.brightness = atoi(argv[3]);

                rt_device_control((rt_device_t)is31fl32xx_dev, RT_IS31FL32XX_CMD_SET_BRIGHTNESS, (void *)&data);
            }
            else
            {
                rt_kprintf("Unknown command. Please enter 'is31fl32xx' for help\n");
            }

        }
        else
        {
            rt_kprintf("Unknown command. Please enter 'is31fl32xx' for help\n");
        }
    }
    else
    {
        rt_kprintf("Usage: \n");
        rt_kprintf("is31fl32xx b <channel> <brightness>\n");
    }

    return RT_EOK;
}
MSH_CMD_EXPORT(is31fl32xx, is31fl32xx function);
#endif
#endif
