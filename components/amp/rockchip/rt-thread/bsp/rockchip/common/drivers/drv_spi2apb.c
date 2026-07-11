/**
  * Copyright (c) 2019 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_spi2apb.c
  * @author  David Wu
  * @version V0.1
  * @date    20-Mar-2019
  * @brief   spi2apb driver
  *
  ******************************************************************************
  */

#include <rthw.h>
#include <rtdevice.h>
#include <rtthread.h>
#include "hal_base.h"
#include "spi2apb.h"

#if defined(RT_USING_SPI2APB)

#define SPI2APB_DEBUG 0

#if SPI2APB_DEBUG
#define spi2apb_dbg(dev, fmt, ...) \
do { \
    rt_kprintf("%s:", ((struct rt_device *)dev)->parent.name); \
    rt_kprintf(fmt, ##__VA_ARGS__); \
} while(0)
#else
#define spi2apb_dbg(dev, fmt, ...) \
do { \
} while(0)
#endif

struct rockchip_spi2apb
{
    struct rt_spi_bus bus;
    struct rt_spi_device dev;
    struct SPI2APB_REG *base;
    rt_uint8_t irq;
    spi2apb_callback callback;
    uint32_t regs_backup[3];
};

static struct rockchip_spi2apb rk_spi2apb =
{
    .base = SPI2APB,
    .irq = SPISLV0_IRQn,
    .callback = NULL,
};

static void rockchip_spi2apb_irq(int irq, void *param)
{
    struct rockchip_spi2apb *spi2apb = &rk_spi2apb;

    /* enter interrupt */
    rt_interrupt_enter();

    HAL_SPI2APB_CleanIrq(spi2apb->base);
    if (spi2apb->callback)
        spi2apb->callback(HAL_SPI2APB_ReadReg1(spi2apb->base));

    /* leave interrupt */
    rt_interrupt_leave();
}

static rt_err_t rockchip_spi2apb_control(rt_device_t dev, int cmd, void *arg)
{
    struct rockchip_spi2apb *spi2apb = dev->user_data;
    struct SPI2APB_REG *pReg;
    rt_err_t ret = RT_EOK;

    RT_ASSERT(spi2apb != RT_NULL);
    RT_ASSERT(arg != RT_NULL);

    pReg = spi2apb->base;
    spi2apb_dbg(dev, "rt_spi2apb_control cmd: %d\n", cmd);

    switch (cmd)
    {
    case RT_DEVICE_CTRL_SPI2APB_QUERY_STATUS:
        *(rt_uint32_t *)arg = HAL_SPI2APB_ReadStatus(pReg);
        break;
    case RT_DEVICE_CTRL_SPI2APB_REGISTER_CB:
        /* Enable irq. */
        spi2apb->callback = (spi2apb_callback)arg;
        rt_hw_interrupt_umask(spi2apb->irq);
        HAL_SPI2APB_UnmaskIrq(pReg, true);
        break;
    case RT_DEVICE_CTRL_SPI2APB_READ_REG0:
        *(rt_uint32_t *)arg = HAL_SPI2APB_ReadReg0(pReg);
        break;
    case RT_DEVICE_CTRL_SPI2APB_READ_REG1:
        *(rt_uint32_t *)arg = HAL_SPI2APB_ReadReg1(pReg);
        break;
    case RT_DEVICE_CTRL_SPI2APB_WRITE_REG2:
        HAL_SPI2APB_WriteReg2(pReg, *((rt_uint32_t *)arg));
        break;
    default:
        ret = RT_EINVAL;
        break;
    }

    return ret;
}

static rt_err_t rockchip_spi2apb_configure(struct rt_spi_device *device,
        struct rt_spi_configuration *cfg)
{
    struct rockchip_spi2apb *spi2apb = device->bus->parent.user_data;
    uint32_t ctrl = 0;

#ifdef SPI2APB_TXCP_INVERT
    if ((cfg->mode & 0x3) == 0)
        ctrl |= SPI2APB_TXCP_INVERT;
    else if ((cfg->mode & 0x3) == 2)
        ctrl |= SPI2APB_RXCP_INVERT;
    else
        return -RT_EINVAL;
#else
    ctrl |= (cfg->mode & 0x3) << SPI2APB_CTRL0_CKM_SHIFT;
#endif

    /* MSB or LSB */
    if (cfg->mode & RT_SPI_MSB)
        ctrl |= SPI2APB_MSB;

    if (cfg->reserved & RK_SPI_RESERVED_BIG_ENDIAN)
        ctrl |= SPI2APB_BIG_ENDIAN;

    spi2apb_dbg("%s mode=%x reserved=%x", __func__, cfg->mode, cfg->reserved);
    HAL_SPI2APB_Configurate(spi2apb->base, ctrl);

    return RT_EOK;
}


static struct rt_spi_ops rockchip_spi2apb_ops =
{
    rockchip_spi2apb_configure,
};

#ifdef RT_USING_PM
/**
 * rockchip_spi_suspend - suspend function for SPI Controller
 * @device: spi device structure
 */
static int rockchip_spi2apb_suspend(const struct rt_device *device, rt_uint8_t mode)
{
    struct rt_spi2apb_device *dev = (struct rt_spi2apb_device *)device;
    struct rockchip_spi2apb *spi2apb = dev->parent.user_data;

    HAL_SPI2APB_Suspend(spi2apb->base, spi2apb->regs_backup);
    return RT_EOK;
}

/**
 * rockchip_spi_resume - resume function for SPI Controller
 * @device: spi device structure
 */
static void rockchip_spi2apb_resume(const struct rt_device *device, rt_uint8_t mode)
{
    struct rt_spi2apb_device *dev = (struct rt_spi2apb_device *)device;
    struct rockchip_spi2apb *spi2apb = dev->parent.user_data;

    HAL_SPI2APB_Resume(spi2apb->base, spi2apb->regs_backup);
}

static struct rt_device_pm_ops rockchip_spi2apb_pm_ops =
{
    .suspend = rockchip_spi2apb_suspend,
    .resume = rockchip_spi2apb_resume,
};
#endif

int rt_hw_spi2apb_init(void)
{
    char *bus_name = "spi2apb_bus";
    char *device_name = "spi2apb";
    struct rockchip_spi2apb *spi2apb = &rk_spi2apb;
    rt_err_t ret;

    /* default mode0, msb, big enadian */
#ifdef SPI2APB_TXCP_INVERT
    HAL_SPI2APB_Configurate(spi2apb->base, SPI2APB_BIG_ENDIAN | SPI2APB_MSB | SPI2APB_TXCP_INVERT);
#else
    HAL_SPI2APB_Configurate(spi2apb->base, SPI2APB_BIG_ENDIAN | SPI2APB_MSB);
#endif

    /* register irq */
    rt_hw_interrupt_install(spi2apb->irq, rockchip_spi2apb_irq, spi2apb, bus_name);
    rt_hw_interrupt_umask(spi2apb->irq);
    HAL_SPI2APB_UnmaskIrq(spi2apb->base, true);

    spi2apb->bus.parent.user_data = spi2apb;

#ifdef RT_USING_PM
    rt_pm_device_register((struct rt_device *)spi2apb, &rockchip_spi2apb_pm_ops);
#endif

    ret = rt_spi_bus_register(&spi2apb->bus, bus_name, &rockchip_spi2apb_ops);
    if (ret)
    {
        rt_kprintf("spi2apb bus register failed, ret=%d\n", ret);
    }

    ret = rt_spi_bus_attach_device(&spi2apb->dev, device_name, bus_name, RT_NULL);
    if (ret)
    {
        rt_kprintf("spi2apb dev register failed, ret=%d\n", ret);
    }

    spi2apb->bus.parent.control = rockchip_spi2apb_control;

    return ret;
}

INIT_DEVICE_EXPORT(rt_hw_spi2apb_init);

#endif
