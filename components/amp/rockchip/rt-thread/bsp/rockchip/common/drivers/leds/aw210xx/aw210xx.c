/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include <rtthread.h>
#include <rtdevice.h>

#ifdef RT_USING_AW210XX
#include "hal_base.h"
#include "aw210xx.h"

//Iout = K X Vrext/Rext X GCC/255 X WB/255 X COLn/255 X BRn/255

static aw210xx_device_t *g_aw210xx_dev = RT_NULL;

static const struct aw210xxx_chipdef aw21024_cdef =
{
    .channels               = 24,
    .br_base_reg            = 0x01,
    .col_base_reg           = 0x4a,
};

static rt_err_t _aw_write_regs(void *write_buf, rt_uint8_t write_len)
{
    struct rt_i2c_msg msgs[1];
    rt_int32_t ret;

    msgs[0].addr  = g_aw210xx_dev->i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = write_buf;
    msgs[0].len   = write_len;

    ret = rt_i2c_transfer(g_aw210xx_dev->i2c_client->bus, msgs, 1);
    if (ret == 1)
    {
        return RT_EOK;
    }
    else
    {
        return -RT_ERROR;
    }
}

static rt_err_t aw_write_regs(rt_uint8_t u8Offset, rt_uint8_t u8ByteNo, rt_uint8_t *pu8Data)
{
    rt_int8_t *data_buf = RT_NULL;
    rt_err_t ret;
    data_buf = (rt_int8_t *)rt_calloc(1, u8ByteNo + 1);
    if (!data_buf)
    {
        rt_kprintf("i2c write alloc buf size %d fail\n", u8ByteNo);
        return -RT_ERROR;
    }

    data_buf[0] = u8Offset;
    rt_memcpy(data_buf + 1, pu8Data, u8ByteNo);

    ret = _aw_write_regs(data_buf, u8ByteNo + 1);

    rt_free(data_buf);
    return ret;
}

static rt_err_t aw_write_one_byte(rt_uint8_t addr, rt_uint8_t data)
{
    return aw_write_regs(addr, 1, &data);
}

static rt_err_t aw_read_regs(rt_uint8_t cmd, rt_uint8_t read_len, rt_uint8_t *read_buf)
{
    struct rt_i2c_msg msgs[2];
    rt_uint8_t cmd_buf = cmd;

    msgs[0].addr  = g_aw210xx_dev->i2c_client->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = &cmd_buf;
    msgs[0].len   = 1;

    msgs[1].addr  = g_aw210xx_dev->i2c_client->client_addr;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = read_buf;
    msgs[1].len   = read_len;

    if (rt_i2c_transfer(g_aw210xx_dev->i2c_client->bus, msgs, 2) == 2)
    {
        return RT_EOK;
    }

    return -RT_ERROR;
}

static rt_err_t aw_read_one_byte(rt_uint8_t reg_addr, rt_uint8_t *reg_data)
{
    return aw_read_regs(reg_addr, 1, reg_data);
}

static rt_int32_t aw_write_bits(rt_uint8_t reg_addr, rt_uint32_t mask, rt_uint8_t reg_data)
{
    rt_uint8_t reg_val;

    aw_read_one_byte(reg_addr, &reg_val);
    reg_val &= mask;
    reg_val |= (reg_data & (~mask));
    aw_write_one_byte(reg_addr, reg_val);

    return 0;
}

static void aw210xx_soft_rst(void)
{
    aw_write_one_byte(AW210XX_REG_RESET, 0x00);
    /* delay 2ms at least */
    rt_thread_mdelay(2);
};

static void aw210xx_set_global_current(rt_uint8_t current)
{
    aw_write_one_byte(AW210XX_REG_GCCR, current);
}

static void aw210xx_chip_hwen(rt_uint8_t en)
{
    if (en)
    {
        HAL_GPIO_SetPinLevel(AW210XX_EN_GPIO_GRP, AW210XX_EN_GPIO, AW210XX_PIN_HIGH);
    }
    else
    {

        HAL_GPIO_SetPinLevel(AW210XX_EN_GPIO_GRP, AW210XX_EN_GPIO, AW210XX_PIN_LOW);
    }
    /* delay 2ms at least */
    rt_thread_mdelay(2);
}

static void aw210xx_rgb_mode_set(rt_int32_t flag)
{
    if (flag)
    {
        aw_write_bits(AW210XX_REG_GCR2,
                      AW210XX_BIT_RGBMD_MASK,
                      AW210XX_BIT_RGBMD_ENABLE);
        g_aw210xx_dev->rgb_mode = 1;
    }
    else
    {
        aw_write_bits(AW210XX_REG_GCR2,
                      AW210XX_BIT_RGBMD_MASK,
                      AW210XX_BIT_RGBMD_DISENA);
        g_aw210xx_dev->rgb_mode = 0;
    }
}

static void aw210xx_apse_set(bool flag)
{
    if (flag)
    {
        aw_write_bits(AW210XX_REG_GCR,
                      AW210XX_BIT_APSE_MASK,
                      AW210XX_BIT_APSE_ENABLE);
        g_aw210xx_dev->apse = 1;
    }
    else
    {
        aw_write_bits(AW210XX_REG_GCR,
                      AW210XX_BIT_APSE_MASK,
                      AW210XX_BIT_APSE_DISENA);
        g_aw210xx_dev->apse = 0;
    }
}

static void aw210xx_chip_en_set(rt_int32_t en)
{
    if (en)
    {
        aw_write_bits(AW210XX_REG_GCR, AW210XX_BIT_CHIPEN_MASK, AW210XX_BIT_CHIPEN_ENABLE);
        g_aw210xx_dev->chip_en = 1;
    }
    else
    {
        aw_write_bits(AW210XX_REG_GCR, AW210XX_BIT_CHIPEN_MASK, AW210XX_BIT_CHIPEN_DISENA);
        g_aw210xx_dev->chip_en = 0;
    }
}

static void aw210xx_gro_mode_en(rt_int32_t flag)
{
    if (flag)
    {
        aw_write_bits(AW210XX_REG_GCFG1, AW210XX_BIT_GROP_MASK, AW210XX_BIT_GROP_ENABLE);
        g_aw210xx_dev->gro_mode = 1;
    }
    else
    {
        aw_write_bits(AW210XX_REG_GCFG1, AW210XX_BIT_GROP_MASK, AW210XX_BIT_GROP_DISENA);
        g_aw210xx_dev->gro_mode = 0;
    }
}

static void aw210xx_gro_mode_set(rt_uint8_t group)
{
    aw_write_one_byte(AW210XX_REG_GCFG0, group);
}

void aw210xx_uvlo_set(rt_int32_t flag)
{
    if (flag)
    {
        aw_write_bits(AW210XX_REG_UVCR,
                      AW210XX_BIT_UVPD_MASK,
                      AW210XX_BIT_UVPD_DISENA);
        aw_write_bits(AW210XX_REG_UVCR,
                      AW210XX_BIT_UVDIS_MASK,
                      AW210XX_BIT_UVDIS_DISENA);
        g_aw210xx_dev->uvlo = 1;
    }
    else
    {
        aw_write_bits(AW210XX_REG_UVCR,
                      AW210XX_BIT_UVPD_MASK,
                      AW210XX_BIT_UVPD_ENABLE);
        aw_write_bits(AW210XX_REG_UVCR,
                      AW210XX_BIT_UVDIS_MASK,
                      AW210XX_BIT_UVDIS_ENABLE);
        g_aw210xx_dev->uvlo = 0;
    }
}

static void aw210xx_br_set(struct aw_br *br)
{
    rt_uint8_t offset, ch;

    rt_kprintf("%s:ch: %d, br: %d\n", __func__, br->ch, br->br);

    //If RGBMD=1. register BR0~BR7 confgure brightness parameters for
    //corresponding 8 RGB groups (every 3 adjacent LEDs form a RGB group).
    //in other words, in RGB mode, only registers BR0~BR7 need to be
    //configured, and the registers BR8~BR23 not valid any more.
    if (g_aw210xx_dev->rgb_mode)
    {
        if (br->ch > g_aw210xx_dev->cdef->channels / 3)
        {
            ch = g_aw210xx_dev->cdef->channels / 3;
        }
        else
        {
            ch = br->ch;
        }
    }
    else
    {
        if (br->ch > g_aw210xx_dev->cdef->channels)
        {
            ch = g_aw210xx_dev->cdef->channels;
        }
        else
        {
            ch = br->ch;
        }
    }

    offset = ch - 1;

    aw_write_one_byte(g_aw210xx_dev->cdef->br_base_reg + offset, br->br);

    //update
    aw_write_one_byte(AW210XX_REG_UPDATE, 0);
}

static void aw210xx_set_global_color(struct aw_color *color)
{
    aw_write_one_byte(AW210XX_REG_GCOLR, color->r);
    aw_write_one_byte(AW210XX_REG_GCOLG, color->g);
    aw_write_one_byte(AW210XX_REG_GCOLB, color->b);
}

static void aw210xx_col_set(struct aw_br *br)
{
    rt_uint8_t offset, ch;

    AW_LOG("%s:ch: %d, col: %d\n", __func__, br->ch, br->br);

    if (br->ch > g_aw210xx_dev->cdef->channels)
    {
        ch = g_aw210xx_dev->cdef->channels;
    }
    else
    {
        ch = br->ch;
    }

    offset = ch - 1;

    aw_write_one_byte(g_aw210xx_dev->cdef->col_base_reg + offset, br->br);

}

static void aw210xx_set_rgb_color(struct aw_rgb_color *rgb)
{
    rt_uint8_t offset, ch;

    if (rgb->ch > g_aw210xx_dev->cdef->channels / 3)
    {
        ch = g_aw210xx_dev->cdef->channels;
    }
    else
    {
        ch = rgb->ch;
    }
    offset = ch - 1;

    aw_write_one_byte(g_aw210xx_dev->cdef->col_base_reg + (offset * 3), rgb->rgb.r);
    aw_write_one_byte(g_aw210xx_dev->cdef->col_base_reg + (offset * 3) + 1, rgb->rgb.g);
    aw_write_one_byte(g_aw210xx_dev->cdef->col_base_reg + (offset * 3) + 2, rgb->rgb.b);
}


static void aw210xx_breath_config(struct aw_breath *breath)
{
    if (breath->breath_enable)
    {
        /* set GCOLR/G/B, FADEH/L parameter */
        aw_write_one_byte(AW210XX_REG_GCOLR, breath->color.r); //0xa8
        aw_write_one_byte(AW210XX_REG_GCOLG, breath->color.g); //0xa9
        aw_write_one_byte(AW210XX_REG_GCOLB, breath->color.b); //0xaa

        aw_write_one_byte(AW210XX_REG_FADEH, breath->br_max); //0xa6
        aw_write_one_byte(AW210XX_REG_FADEL, breath->br_min); //0xa7

        /* set GCFG0  */
        aw_write_one_byte(AW210XX_REG_GCFG0, breath->group);  //0xab
        aw_write_one_byte(AW210XX_REG_GCFG1, 0x0f);  //0xac

        /* config PATT0 PATT1 PATT2 PATT3 */
        /* set pattern times T0/T1/T2/T3 */
        aw_write_one_byte(AW210XX_REG_PATCT0,      //0xa2
                          (breath->auto_breath.t0 << 4) |
                          (breath->auto_breath.t1 & 0xf));
        aw_write_one_byte(AW210XX_REG_PATCT1,     //0xa3
                          (breath->auto_breath.t2 << 4) |
                          (breath->auto_breath.t3 & 0xf));

        /* set pattern0_breath start/end phase */
        aw_write_bits(AW210XX_REG_PATCT2, 0xf0,    //0xa4
                      ((breath->auto_breath.stop_state & 0x3) << 6 |
                       (breath->auto_breath.start_state & 0x3) << 4));
        /* set pattern0_breath loop times */
        aw_write_bits(AW210XX_REG_PATCT2, 0x0f,      //0xa4
                      ((breath->auto_breath.repeat_times & 0xf00) >> 8));
        aw_write_one_byte(AW210XX_REG_PATCT3,        //0xa4
                          (breath->auto_breath.repeat_times & 0xff));

        /* set PATCFG */
        if (breath->auto_mode)
        {
            aw_write_one_byte(AW210XX_REG_PATCFG, 0x07); //0xa0
            aw_write_one_byte(AW210XX_REG_PATGO, 0x01); //0xa1
        }
        else
        {
            aw_write_one_byte(AW210XX_REG_PATCFG, (((breath->manual_breath.sw & 0x01) << 3) | ((breath->manual_breath.rampe & 0x01) << 2) | 0x01) & 0xfd);
            aw_write_one_byte(AW210XX_REG_PATGO, 0x01); //0xa1
        }
        /* start breath */
    }
    else
    {
        aw_write_one_byte(AW210XX_REG_PATCFG, 0x00);
        aw210xx_gro_mode_en(0);
        aw_write_one_byte(AW210XX_REG_GCFG0, 0x00);
        aw_write_one_byte(AW210XX_REG_PATGO, 0x00);
    }
}

rt_int32_t aw210xx_init(void)
{
    rt_uint8_t val = 0;

    aw210xx_chip_hwen(1);

    aw210xx_soft_rst();

    /* 1. enable chip and enable auto power-saving */
    aw210xx_chip_en_set(1);
    aw210xx_apse_set(1);

    /* 2. check id */
    aw_read_one_byte(AW210XX_REG_RESET, &val); /* 0x7f 0x18 */
    if (val != AW210XX_CHIPID)
    {
        AW_LOG("%s:read chip id failed. val = %#x\n", __func__, val);
    }

    /* 4. config global current */
    aw210xx_set_global_current(AW210XX_DEFAULT_GOL_CUR);

    aw210xx_uvlo_set(1);

    aw210xx_gro_mode_en(0);
    aw210xx_rgb_mode_set(0);

    return 0;
}

static rt_err_t aw210xx_control(rt_device_t dev, int cmd, void *args)
{
    switch (cmd)
    {
    case RT_AW210XX_BR_SET:
    case RT_AW210XX_RGB_BR_SET:
        aw210xx_br_set((struct aw_br *)args);
        break;
    case RT_AW210XX_RGB_MODE_SET:
        aw210xx_rgb_mode_set(*(rt_uint8_t *)args);
        break;
    case RT_AW210XX_GRO_MODE_EN:
        aw210xx_gro_mode_en(*(rt_uint8_t *)args);
        break;
    case RT_AW210XX_GRO_MODE_SET:
        aw210xx_gro_mode_set(*(rt_uint8_t *)args);
        break;
    case RT_AW210XX_PWR_MODE_SET:
        aw210xx_chip_hwen(*(rt_uint8_t *)args);
        break;
    case RT_AW210XX_GLO_CUR_SET:
        aw210xx_set_global_current(*(rt_uint8_t *)args);
        break;
    case RT_AW210XX_GLO_COL_SET:
        aw210xx_set_global_color((struct aw_color *)args);
        break;
    case RT_AW210XX_RGB_COL_SET:
        aw210xx_set_rgb_color((struct aw_rgb_color *)args);
        break;
    case RT_AW210XX_COL_SET:
        aw210xx_col_set((struct aw_br *)args);
        break;
    case RT_AW210XX_BREATH_SET:
        aw210xx_breath_config((struct aw_breath *)args);
        break;
    default:
        rt_kprintf("Unsupport cmd: %d\n", cmd);
        break;
    }
    return RT_EOK;
}

#ifdef RT_USING_DEVICE_OPS
static const struct rt_device_ops aw210xx_device_ops =
{
    RT_NULL,
    RT_NULL,
    RT_NULL,
    RT_NULL,
    RT_NULL,
    aw210xx_control
};
#endif /* RT_USING_DEVICE_OPS */

static rt_err_t rt_device_aw210xx_register(aw210xx_device_t *dev, const char *name, const void *user_data)
{
    rt_err_t result = RT_EOK;

#ifdef RT_USING_DEVICE_OPS
    dev->dev.ops = &aw210xx_device_ops;
#else
    dev->dev.init = RT_NULL;
    dev->dev.open = RT_NULL;
    dev->dev.close = RT_NULL;
    dev->dev.read  = RT_NULL;
    dev->dev.write = RT_NULL;
    dev->dev.control = aw210xx_control;
#endif /* RT_USING_DEVICE_OPS */

    dev->dev.type         = RT_Device_Class_Miscellaneous;
    dev->dev.user_data    = (void *)user_data;

    result = rt_device_register(&dev->dev, name, RT_DEVICE_FLAG_RDWR);

    return result;
}

static int rt_hw_aw210xx_init(void)
{
    rt_err_t ret;
    aw210xx_device_t *dev;

    g_aw210xx_dev = dev = (aw210xx_device_t *)rt_calloc(1, sizeof(aw210xx_device_t));
    RT_ASSERT(dev != RT_NULL);
    rt_memset((void *)dev, 0, sizeof(aw210xx_device_t));

    struct rt_i2c_client *i2c_client;
    dev->i2c_client = i2c_client = (struct rt_i2c_client *)rt_calloc(1, sizeof(struct rt_i2c_client));
    RT_ASSERT(i2c_client != RT_NULL);

    i2c_client->client_addr = AW210XX_I2C_ADDR;
    i2c_client->bus = (struct rt_i2c_bus_device *)rt_device_find(AW210XX_I2C_DEV);
    RT_ASSERT(i2c_client->bus != RT_NULL);

    /* before here, IOMUX must be initialized in board_xxxx.c*/
    HAL_GPIO_SetPinDirection(AW210XX_EN_GPIO_GRP, AW210XX_EN_GPIO, GPIO_OUT);
    HAL_GPIO_SetPinLevel(AW210XX_EN_GPIO_GRP, AW210XX_EN_GPIO, AW210XX_PIN_HIGH);

    dev->cdef = &aw21024_cdef;
    ret = aw210xx_init();
    if (ret)
    {
        AW_LOG("aw210xx init failed\n");
    }

    ret = rt_device_aw210xx_register(dev, AW210XX_DEVICE_NAME, (void *)dev);
    RT_ASSERT(ret == RT_EOK);

    return RT_EOK;
}

INIT_DEVICE_EXPORT(rt_hw_aw210xx_init);
MSH_CMD_EXPORT(rt_hw_aw210xx_init, aw210xx function);

#if defined(RT_USING_FINSH) && defined(AWINIC_DEBUG)

static void aw210xx_breath_parameter_dump(struct aw_breath *breath)
{

    rt_kprintf("global r:%d g:%d b:%d\n", breath->color.r, breath->color.g, breath->color.b);
    rt_kprintf("fade l:%d h:%d\n", breath->br_min, breath->br_max);

    rt_kprintf("ramp rise time:");
    switch (breath->auto_breath.t0)
    {
    case 0:
        rt_kprintf("0s");
        break;
    case 1:
        rt_kprintf("0.13s");
        break;
    case 2:
        rt_kprintf("0.26s");
        break;
    case 3:
        rt_kprintf("0.38s");
        break;
    case 4:
        rt_kprintf("0.51s");
        break;
    case 5:
        rt_kprintf("0.77s");
        break;
    case 6:
        rt_kprintf("1.04s");
        break;
    case 7:
        rt_kprintf("1.6S");
        break;
    case 8:
        rt_kprintf("2.1s");
        break;
    case 9:
        rt_kprintf("2.6s");
        break;
    case 10:
        rt_kprintf("3.1s");
        break;
    case 11:
        rt_kprintf("4.2s");
        break;
    case 12:
        rt_kprintf("5.2s");
        break;
    case 13:
        rt_kprintf("6.2s");
        break;
    case 14:
        rt_kprintf("7.3s");
        break;
    case 15:
        rt_kprintf("8.3s");
        break;
    }
    rt_kprintf("\n");
    rt_kprintf("hold on time:");
    switch (breath->auto_breath.t1)
    {
    case 0:
        rt_kprintf("0.04s");
        break;
    case 1:
        rt_kprintf("0.13s");
        break;
    case 2:
        rt_kprintf("0.26s");
        break;
    case 3:
        rt_kprintf("0.38s");
        break;
    case 4:
        rt_kprintf("0.51s");
        break;
    case 5:
        rt_kprintf("0.77s");
        break;
    case 6:
        rt_kprintf("1.04s");
        break;
    case 7:
        rt_kprintf("1.6S");
        break;
    case 8:
        rt_kprintf("2.1s");
        break;
    case 9:
        rt_kprintf("2.6s");
        break;
    case 10:
        rt_kprintf("3.1s");
        break;
    case 11:
        rt_kprintf("4.2s");
        break;
    case 12:
        rt_kprintf("5.2s");
        break;
    case 13:
        rt_kprintf("6.2s");
        break;
    case 14:
        rt_kprintf("7.3s");
        break;
    case 15:
        rt_kprintf("8.3s");
        break;
    }
    rt_kprintf("\n");
    rt_kprintf("ramp fall time:");
    switch (breath->auto_breath.t2)
    {
    case 0:
        rt_kprintf("0s");
        break;
    case 1:
        rt_kprintf("0.13s");
        break;
    case 2:
        rt_kprintf("0.26s");
        break;
    case 3:
        rt_kprintf("0.38s");
        break;
    case 4:
        rt_kprintf("0.51s");
        break;
    case 5:
        rt_kprintf("0.77s");
        break;
    case 6:
        rt_kprintf("1.04s");
        break;
    case 7:
        rt_kprintf("1.6S");
        break;
    case 8:
        rt_kprintf("2.1s");
        break;
    case 9:
        rt_kprintf("2.6s");
        break;
    case 10:
        rt_kprintf("3.1s");
        break;
    case 11:
        rt_kprintf("4.2s");
        break;
    case 12:
        rt_kprintf("5.2s");
        break;
    case 13:
        rt_kprintf("6.2s");
        break;
    case 14:
        rt_kprintf("7.3s");
        break;
    case 15:
        rt_kprintf("8.3s");
        break;
    }
    rt_kprintf("\n");
    rt_kprintf("hold off time:");
    switch (breath->auto_breath.t3)
    {
    case 0:
        rt_kprintf("0.04s");
        break;
    case 1:
        rt_kprintf("0.13s");
        break;
    case 2:
        rt_kprintf("0.26s");
        break;
    case 3:
        rt_kprintf("0.38s");
        break;
    case 4:
        rt_kprintf("0.51s");
        break;
    case 5:
        rt_kprintf("0.77s");
        break;
    case 6:
        rt_kprintf("1.04s");
        break;
    case 7:
        rt_kprintf("1.6S");
        break;
    case 8:
        rt_kprintf("2.1s");
        break;
    case 9:
        rt_kprintf("2.6s");
        break;
    case 10:
        rt_kprintf("3.1s");
        break;
    case 11:
        rt_kprintf("4.2s");
        break;
    case 12:
        rt_kprintf("5.2s");
        break;
    case 13:
        rt_kprintf("6.2s");
        break;
    case 14:
        rt_kprintf("7.3s");
        break;
    case 15:
        rt_kprintf("8.3s");
        break;
    }
    rt_kprintf("\n");
    switch (breath->auto_breath.start_state)
    {
    case 0:
        rt_kprintf("start from RISE state\n");
        break;
    case 1:
        rt_kprintf("start from ON state\n");
        break;
    case 2:
        rt_kprintf("start from FALL state\n");
        break;
    case 3:
        rt_kprintf("start from OFF state\n");
        break;
    }
    if (breath->auto_breath.stop_state)
    {
        rt_kprintf("stop at ON state\n");
    }
    else
    {
        rt_kprintf("stop at OFF state\n");
    }
    if (breath->auto_breath.repeat_times)
    {
        rt_kprintf("repeat times:%d\n", breath->auto_breath.repeat_times & 0xfff);
    }
    else
    {
        rt_kprintf("repeat times:forever\n");
    }
    rt_kprintf("sw:%d\n", breath->manual_breath.sw);
    rt_kprintf("rampe:%d\n", breath->manual_breath.rampe);
}
struct aw_breath gb =
{
    0,         //breath_enable;
    0,         //br_min;
    0xff,      //br_max;
    0xff,      //group;
    {
        0xff,    //r
        0xff,    //g
        0xff,    //b
    },
    {
        2,       //t0
        2,       //t1
        2,       //t2
        2,       //t3
        0,       //start_state
        0,       //stop_state
        0,       //repeat_times
    },
    {
        0,       //sw
        1,       //rampe
    },
    1,              //auto_mode
};

static int aw210xx(int argc, char **argv)
{
    static rt_device_t aw210xx_dev = RT_NULL;

    aw210xx_dev = rt_device_find(AW210XX_DEVICE_NAME);
    if (!aw210xx_dev)
    {
        rt_kprintf("find %s failed!\n", AW210XX_DEVICE_NAME);
        return -RT_ERROR;
    }

    if (argc > 1)
    {
        if (!strcmp(argv[1], "br"))
        {
            if (argc == 4)
            {
                struct aw_br data;
                data.ch = atoi(argv[2]);
                data.br = atoi(argv[3]);

                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_BR_SET, (void *)&data);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }

        }
        else if (!strcmp(argv[1], "col"))
        {
            if (argc == 4)
            {
                struct aw_br data;
                data.ch = atoi(argv[2]);
                data.br = atoi(argv[3]);

                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_COL_SET, (void *)&data);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }

        }
        else if (!strcmp(argv[1], "rgbmode"))
        {
            if (argc == 3)
            {
                rt_uint8_t en;
                en = atoi(argv[2]);

                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_RGB_MODE_SET, (void *)&en);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "gcol"))
        {
            if (argc == 5)
            {
                struct aw_color col;
                col.r = atoi(argv[2]);
                col.g = atoi(argv[3]);
                col.b = atoi(argv[4]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_GLO_COL_SET, (void *)&col);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "rgbcol"))
        {
            if (argc == 6)
            {
                struct aw_rgb_color col;
                col.ch = atoi(argv[2]);
                col.rgb.r = atoi(argv[3]);
                col.rgb.g = atoi(argv[4]);
                col.rgb.b = atoi(argv[5]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_RGB_COL_SET, (void *)&col);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "gcur"))
        {
            if (argc == 3)
            {
                rt_uint8_t cur;
                cur = atoi(argv[2]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_GLO_CUR_SET, (void *)&cur);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "group"))
        {
            if (argc == 3)
            {
                rt_uint8_t en;
                en = atoi(argv[2]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_GRO_MODE_EN, (void *)&en);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "groupset"))
        {
            if (argc == 3)
            {
                rt_uint8_t group;
                group = atoi(argv[2]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_GRO_MODE_SET, (void *)&group);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "bp1"))
        {
            if (argc == 8)
            {
                gb.br_min = atoi(argv[2]);
                gb.br_max = atoi(argv[3]);
                gb.group = atoi(argv[4]);
                gb.color.r = atoi(argv[5]);
                gb.color.g = atoi(argv[6]);
                gb.color.b = atoi(argv[7]);
                aw210xx_breath_parameter_dump(&gb);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "bp2"))
        {
            if (argc == 9)
            {
                gb.auto_breath.t0 = atoi(argv[2]);
                gb.auto_breath.t1 = atoi(argv[3]);
                gb.auto_breath.t2 = atoi(argv[4]);
                gb.auto_breath.t3 = atoi(argv[5]);
                gb.auto_breath.start_state = atoi(argv[6]);
                gb.auto_breath.stop_state = atoi(argv[7]);
                gb.auto_breath.repeat_times = atoi(argv[8]);
                aw210xx_breath_parameter_dump(&gb);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "bp3"))
        {
            if (argc == 4)
            {
                gb.manual_breath.sw = atoi(argv[2]);
                gb.manual_breath.rampe = atoi(argv[3]);
                aw210xx_breath_parameter_dump(&gb);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "bauto"))
        {
            if (argc == 3)
            {
                gb.auto_mode = 1;
                gb.breath_enable = atoi(argv[2]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_BREATH_SET, (void *)&gb);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else if (!strcmp(argv[1], "bmanual"))
        {
            if (argc == 5)
            {
                gb.auto_mode = 0;
                gb.breath_enable = atoi(argv[2]);
                gb.manual_breath.sw = atoi(argv[3]);
                gb.manual_breath.rampe = atoi(argv[4]);
                rt_device_control((rt_device_t)aw210xx_dev, RT_AW210XX_BREATH_SET, (void *)&gb);
            }
            else
            {
                rt_kprintf("Wrong parameter. Please enter 'aw210xx' for help\n");
            }
        }
        else
        {
            rt_kprintf("Unknown command. Please enter 'aw210xx' for help\n");
        }
    }
    else
    {
        rt_kprintf("Usage: \n");
        rt_kprintf("aw210xx br <ch> <br>                                                         --set the brightness of a single channel\n");
        rt_kprintf("aw210xx col <ch> <col>                                                       --set the color of a single channel\n");
        rt_kprintf("aw210xx rbgmode <en>                                                         --config rgb mode: 0:disable 1:enable,\n");
        rt_kprintf("aw210xx rgbcol <ch> <r> <g> <b>                                              --set the color of a rgb channel\n");
        rt_kprintf("aw210xx gcol <r> <g> <b>                                                     --set the global color\n");
        rt_kprintf("aw210xx gcur <cur>                                                           --set the global current\n");
        rt_kprintf("aw210xx group <en>                                                           --config the group mode: 0:disable 1:enable\n");
        rt_kprintf("aw210xx groupset <gro>                                                       --set the group\n");
        rt_kprintf("aw210xx bp1 <br_min> <br_max> <group> <r> <g> <b>                            --breath parameter part1\n");
        rt_kprintf("aw210xx bp2 <t0> <t1> <t2> <t3> <start_state> <stop_state> <repeat_times>    --breath parameter part2\n");
        rt_kprintf("aw210xx bauto <en>                                                           --auto breath enable: 0:disable 1:enable\n");
        rt_kprintf("aw210xx bmanual <en> <sw> <rampe>                                            --manual breath en: 0: disable 1:enable sw: 0:off 1:on rampe: 0:wthout rampe 1:with rampe\n");
    }

    return RT_EOK;
}

MSH_CMD_EXPORT(aw210xx, aw210xx function);
#endif
#endif
