/**
  * Copyright (c) 2019 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    spi2apb_test.c
  * @author  David Wu
  * @version V0.1
  * @date    20-Mar-2019
  * @brief   spi2apb test for pisces
  *
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>

#ifdef RT_USING_COMMON_TEST_SPI2APB

#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdlib.h>
#include "../drivers/spi2apb.h"

#include "spi2apb_flash_obj.h"

// #define SLV_DEBUG
#ifdef SLV_DEBUG
#define slv_dbg(...)     rt_kprintf(__VA_ARGS__)
#else
#define slv_dbg(...)
#endif

#ifdef RKMCU_RK2118
#define SPI2APB_CS0_PIN BANK_PIN(GPIO_BANK2, 1) /* SPI0(SPI2APB) CSN0 M0 */
#else
#error "Please define SPI2APB_CS0_PIN for cs irq function!"
#endif

struct rt_spi_device *spi2apb_device = RT_NULL;
extern uint32_t __spi2apb_buffer_start__[];
#define SRAM_SPI2APB_BASE (uint32_t)__spi2apb_buffer_start__
#define SRAM_TEST_BUFFER_SIZE 0x40

#ifdef RT_USING_COMMON_TEST_SPI2APB_FLASH_OBJ

struct rt_mtd_nor_device *snor_device = RT_NULL;
struct rt_workqueue *isr_workqueue;
struct rt_work isr_work;

rt_err_t spi_test_spi2apb_flash_obj_set_status(rt_uint8_t index, rt_uint8_t status)
{
    spi2apb_flash_obj_status packet;
    rt_err_t ret;

    slv_dbg("%s index=%x status=%x\n", __func__, index, status);

    packet.item.index = index;
    packet.item.status = status & 0xff;
    packet.item.reserved = 0;
    ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_WRITE_REG2, &packet.d32);
    if (ret)
    {
        rt_kprintf("spi2apb test write reg2 failed.\n");
    }

    return ret;
}

rt_err_t spi_test_spi2apb_flash_obj_read(rt_uint8_t index, rt_uint16_t addr, void *buffer)
{
    rt_err_t ret;

    if (!snor_device)
    {
        rt_kprintf("Did not find device: snor....\n");
        return -RT_EINVAL;
    }

    spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_BUSY);
    ret = rt_mtd_nor_read(snor_device, addr * SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE, buffer, SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE);
    if (ret != SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE)
    {
        spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_ERROR);
        rt_kprintf("%s failed, ret=%d\n", __func__, ret);
    }
    else
    {
        spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_READ_DATA_READY);
    }

    return ret;
}

rt_err_t spi_test_spi2apb_flash_obj_write(rt_uint8_t index, rt_uint16_t addr, void *buffer)
{
    rt_err_t ret;

    if (!snor_device)
    {
        rt_kprintf("Did not find device: snor....\n");
        return -RT_EINVAL;
    }

    spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_BUSY);
    ret = rt_mtd_nor_erase_block(snor_device, addr * SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE, SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE);
    if (ret)
    {
        spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_ERROR);
        rt_kprintf("%s erase failed, ret=%d\n", __func__, ret);
    }
    ret = rt_mtd_nor_write(snor_device, addr * SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE, buffer, SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE);
    if (ret != SPI2APB_FLASH_OBJ_PACKET_NOR_SECTOR_SIZE)
    {
        spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_ERROR);
        rt_kprintf("%s write failed, ret=%d\n", __func__, ret);
    }
    else
    {
        spi_test_spi2apb_flash_obj_set_status(index, SPI2APB_FLASH_OBJ_SLAVE_SUCCESS);
    }

    return ret;
}

static void spi_test_spi2apb_flash_obj_work(struct rt_work *work, void *work_data)
{
    spi2apb_flash_obj_packet packet;

    rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_READ_REG1, (void *)&packet.d32);

    slv_dbg("cmd=0x%x index=0x%x addr=0x%x\n", packet.item.cmd, packet.item.index, packet.item.addr);
    switch (packet.item.cmd)
    {
    case SPI2APB_FLASH_OBJ_CMD_READ:
        spi_test_spi2apb_flash_obj_read(packet.item.index, packet.item.addr, (void *)SRAM_SPI2APB_BASE);
        break;
    case SPI2APB_FLASH_OBJ_CMD_PROG:
        spi_test_spi2apb_flash_obj_write(packet.item.index, packet.item.addr, (void *)SRAM_SPI2APB_BASE);
        break;
    case SPI2APB_FLASH_OBJ_CMD_PROG_SRAM:
        /* to-do */
        break;
    default:
        break;
    }
}

void spi_test_spi2apb_flash_obj_callback(rt_uint32_t value)
{
    rt_workqueue_dowork(isr_workqueue, &isr_work);
}

rt_err_t spi_test_spi2apb_flash_obj_init(void)
{
    rt_err_t ret;

    if (!snor_device)
    {
        snor_device = (struct rt_mtd_nor_device *)rt_device_find("snor");
        if (snor_device == RT_NULL)
        {
            rt_kprintf("Did not find device: snor....\n");
        }
    }

    isr_workqueue = rt_workqueue_create("flash_obj_workqueue", 1024, 5);
    rt_work_init(&isr_work, spi_test_spi2apb_flash_obj_work, NULL);

    ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_REGISTER_CB,
                            (void *)spi_test_spi2apb_flash_obj_callback);
    if (ret)
    {
        rt_kprintf("flash_obj register callback failed\n");
        return -RT_ERROR;
    }
    else
    {
        rt_kprintf("flash_obj init success\n");
    }

    return spi_test_spi2apb_flash_obj_set_status(0, SPI2APB_FLASH_OBJ_SLAVE_IDLE);
}

#endif

static void spi2apb_cs_gpio_irq_callback(void *args)
{
    uint32_t *buffer = (uint32_t *)(SRAM_SPI2APB_BASE);

#ifdef RT_USING_CACHE
    rt_hw_cpu_dcache_ops(RT_HW_CACHE_INVALIDATE, (void *)SRAM_SPI2APB_BASE, SRAM_TEST_BUFFER_SIZE);
#endif
    rt_kprintf("A transmission has arrived, SRAM_SPI2APB_BASE(0x%x)=0x%x\n",
               SRAM_SPI2APB_BASE, buffer[0]);
}

int spi2apb_test_cs_gpio_irq(rt_base_t pin)
{
#ifdef RT_USING_CACHE
    rt_hw_cpu_dcache_ops(RT_HW_CACHE_FLUSH, (void *)SRAM_SPI2APB_BASE, SRAM_TEST_BUFFER_SIZE);
#endif

    rt_pin_attach_irq(BANK_PIN(GPIO_BANK2, 1), PIN_IRQ_MODE_RISING, spi2apb_cs_gpio_irq_callback, NULL);
    rt_pin_irq_enable(BANK_PIN(GPIO_BANK2, 1), PIN_IRQ_ENABLE);

    return 0;
}

void spi2apb_test_callback(rt_uint32_t value)
{
    rt_kprintf("spi2apb_test_callback reg1: 0x%x\n", value);
}

void spi2apb_test_show_usage()
{
    rt_kprintf("spi2apb_test cmd demo as following:\n\n");
    rt_kprintf("spi2apb_test config spi2apb <mode> <is_msb>\n");
    rt_kprintf("spi2apb_test cb spi2apb\n");
    rt_kprintf("spi2apb_test read spi2apb <reg_index>\n");
    rt_kprintf("spi2apb_test query spi2apb\n");
    rt_kprintf("spi2apb_test write spi2apb <data>\n");
    rt_kprintf("spi2apb_test flash_obj spi2apb\n");
    rt_kprintf("like:\n");
    rt_kprintf("\tspi2apb_test config spi2apb 0 1\n");
    rt_kprintf("\tspi2apb_test cb spi2apb\n");
    rt_kprintf("\tspi2apb_test read spi2apb 0\n");
    rt_kprintf("\tspi2apb_test query spi2apb\n");
    rt_kprintf("\tspi2apb_test write spi2apb 0x500\n");
    rt_kprintf("\tspi2apb_test flash_obj spi2apb\n");
}

void spi2apb_test(int argc, char **argv)
{
    rt_err_t ret;
    char *cmd;
    int value = 0;

    if (argc < 3)
    {
        spi2apb_test_show_usage();
        return;
    }

    spi2apb_device = (struct rt_spi_device *)rt_device_find(argv[2]);
    RT_ASSERT(spi2apb_device != RT_NULL);

    ret = rt_spi_take_bus(spi2apb_device);
    if (ret)
    {
        rt_kprintf("spi2apb take buf failed\n");
        return;
    }

    cmd = argv[1];

    if (!rt_strcmp(cmd, "config"))
    {
        struct rt_spi_configuration cfg = { 0 };
        int32_t mode, is_msb;

        mode = atoi(argv[3]);
        is_msb = atoi(argv[4]);

        cfg.mode = mode & 0x3;
        if (is_msb)
            cfg.mode |= RT_SPI_MSB;
        else
            cfg.mode |= RT_SPI_LSB;

        cfg.reserved = RK_SPI_RESERVED_LITTLE_ENDIAN;

        ret = rt_spi_configure(spi2apb_device, &cfg);
        if (ret)
        {
            rt_kprintf("spi2apb test config failed\n");
            goto out;
        }

        rt_kprintf("spi2apb config mode%d, is_msb=%d\n", mode, is_msb);
    }
    else if (!rt_strcmp(cmd, "cb"))
    {
        ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_REGISTER_CB,
                                (void *)spi2apb_test_callback);
        if (ret)
            rt_kprintf("spi2apb test register callback failed\n");
    }
    else if (!rt_strcmp(cmd, "read"))
    {
        int reg;

        reg = atoi(argv[3]);
        if (reg)
            ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_READ_REG1,
                                    (void *)&value);
        else
            ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_READ_REG0,
                                    (void *)&value);
        if (ret)
        {
            rt_kprintf("spi2apb test read reg%d failed\n", (reg) ? 1 : 0);
            goto out;
        }

        rt_kprintf("read reg%d value: 0x%x\n", (reg) ? 1 : 0, value);
    }
    else if (!rt_strcmp(cmd, "query"))
    {
        ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_QUERY_STATUS,
                                (void *)&value);
        if (ret)
        {
            rt_kprintf("spi2apb test query status failed\n");
            goto out;
        }

        rt_kprintf("query state: 0x%x\n", value);
    }
    else if (!rt_strcmp(cmd, "write"))
    {
        sscanf(argv[3], "%x", &value);
        ret = rt_device_control(&spi2apb_device->bus->parent, RT_DEVICE_CTRL_SPI2APB_WRITE_REG2,
                                (void *)&value);
        if (ret)
        {
            rt_kprintf("spi2apb test write reg2 failed.\n");
            goto out;
        }
    }
    else if (!rt_strcmp(cmd, "cs_gpio_irq"))
    {
        spi2apb_test_cs_gpio_irq(SPI2APB_CS0_PIN);
    }
    else if (!rt_strcmp(cmd, "flash_obj"))
    {
#ifdef RT_USING_COMMON_TEST_SPI2APB_FLASH_OBJ
        ret = spi_test_spi2apb_flash_obj_init();
        if (ret)
        {
            rt_kprintf("flash_obj initital failed\n");
            goto out;
        }
        goto out;
#else
        rt_kprintf("please define RT_USING_COMMON_TEST_SPI2APB_FLASH_OBJ firstly\n");
        goto out;
#endif
    }
    else
    {
        spi2apb_test_show_usage();
    }

out:
    rt_spi_release_bus(spi2apb_device);
    return;
}

#ifdef RT_USING_FINSH
#include <finsh.h>
MSH_CMD_EXPORT(spi2apb_test, spt2apb test cmd);
#endif

#endif
