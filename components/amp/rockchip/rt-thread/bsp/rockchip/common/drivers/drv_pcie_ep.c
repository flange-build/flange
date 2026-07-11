/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

/** @addtogroup RKBSP_Driver_Reference
 *  @{
 */

/** @addtogroup PCIE_EP
 *  @{
 */

/** @defgroup PCIE_How_To_Use How To Use
 *  @{

 @} */

#include <rthw.h>
#include <rtthread.h>
#include <rtdevice.h>

#include "hal_bsp.h"
#include "drv_pcie_ep.h"
#include "drv_pcie_ep_uapi.h"
#include "drv_pcie_dma.h"

#ifdef RT_USING_PCIE_EP

/********************* Private MACRO Definition ******************************/

#define PCIE_DMA_CHANEL_MAX_NUM         2
#define PCIE_ELBI_APP_ELBI_INT_GEN0     0x0
#define PCIE_ELBI_APP_ELBI_INT_GEN0_IRQ_USER HAL_BIT(0)

#define PCIe_CLIENT_MSI_OBJ_IRQ         0 /* rockchip ep object special irq */

#define PCIE_EP_OBJ_INFO_DRV_VERSION    0x00000001

#define PCIE_EP_BAR0_CPU_DEFAULT 0x3c000000
#define PCIE_EP_BAR2_CPU_DEFAULT 0x40000000

/*
 * SIGPOLL (or any other signal without signal specific si_codes) si_codes
 */
#define POLL_IN     1   /* data input available */
#define POLL_OUT    2   /* output buffers available */
#define POLL_MSG    3   /* input message available */
#define POLL_ERR    4   /* i/o error */
#define POLL_PRI    5   /* high priority input available */
#define POLL_HUP    6   /* device disconnected */
#define NSIGPOLL    6

#define DECLARE_BITMAP(name, bits) \
    unsigned long name[(bits + (sizeof(unsigned long) * 8 - 1)) / (sizeof(unsigned long) * 8)]

#define PCIE_DEBUG 0

#if PCIE_DEBUG
#define dev_dbg(dev, fmt, ...) \
do { \
    rt_kprintf("[D/rkep] " fmt, ##__VA_ARGS__); \
} while(0)
#else
#define dev_dbg(dev, fmt, ...) \
do { \
} while(0)
#endif
#define dev_info(dev, fmt, ...) \
do { \
    rt_kprintf("[I/rkep] " fmt, ##__VA_ARGS__); \
} while(0)
#define dev_err(dev, fmt, ...) \
do { \
    rt_kprintf("[E/rkep] " fmt, ##__VA_ARGS__); \
} while(0)

/********************* Private Structure Definition **************************/

struct rk_pcie_ep
{
    struct rt_device parent;

    /* Info */
    struct HAL_PCIE_HANDLE *pcie;
    struct rt_hw_pcie_ep_board *board;

    /* status */
    struct rt_mutex lock;
    rt_wqueue_t wq_head;

    /* misc */
    struct rk_pcie_dma_device *obj;
    struct pcie_ep_obj_info *obj_info;
    DECLARE_BITMAP(virtual_id_irq_bitmap, RKEP_EP_VIRTUAL_ID_MAX);
};

/********************* Private Variable Definition ***************************/

static struct rt_semaphore bit_sem_lock;

/********************* Private Function Definition ****************************/
static void  __attribute__((noinline)) *memset_io(void *addr, int val, size_t count)
{
    volatile unsigned char *ptr = (volatile unsigned char *)addr;
    size_t i;

    for (i = 0; i < count; i++)
    {
        *ptr++ = (unsigned char)val;
        __asm__ __volatile__("" : : : "memory");
    }

    return addr;
}

static int test_bit(int bit, unsigned long *bitmap)
{
    unsigned long mask = 1UL << (bit % (sizeof(unsigned long) * 8));
    unsigned long *addr = &bitmap[bit / (sizeof(unsigned long) * 8)];
    return (*addr & mask) ? 1 : 0;
}

static void set_bit(int bit, unsigned long *bitmap)
{
    unsigned long mask = 1UL << (bit % (sizeof(unsigned long) * 8));
    unsigned long *addr = &bitmap[bit / (sizeof(unsigned long) * 8)];

    rt_sem_take(&bit_sem_lock, RT_WAITING_FOREVER);
    *addr |= mask;
    rt_sem_release(&bit_sem_lock);
}

static int test_and_clear_bit(int bit, unsigned long *bitmap)
{
    unsigned long mask = 1UL << (bit % (sizeof(unsigned long) * 8));
    unsigned long *addr = &bitmap[bit / (sizeof(unsigned long) * 8)];
    int ret;

    rt_sem_take(&bit_sem_lock, RT_WAITING_FOREVER);
    ret = (*addr & mask) ? 1 : 0;       // 测试位
    *addr &= ~mask;                     // 清除位
    rt_sem_release(&bit_sem_lock);

    return ret;
}

static void rk_pcie_start_dma(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table)
{
    struct rk_pcie_ep *rk_pcie = (struct rk_pcie_ep *)(obj->parent.user_data);

    HAL_PCIE_StartDma(rk_pcie->pcie, table);
}

static void rk_pcie_config_dma(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table)
{
    struct rk_pcie_ep *rk_pcie = (struct rk_pcie_ep *)(obj->parent.user_data);

    HAL_PCIE_ConfigDma(rk_pcie->pcie, table);
}

static int rk_pcie_dma_wait_for_finished(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table, uint32_t timeout_us)
{
    struct rk_pcie_ep *rk_pcie = (struct rk_pcie_ep *)(obj->parent.user_data);
    union PCIE_DMA_INT_STATUS status;
    enum PCIE_DMA_RESULT ret;

    do
    {
        status = HAL_PCIE_GetDmaStatusRaw(rk_pcie->pcie, table->chn, table->dir);
        ret = HAL_PCIE_CheckDmaStatus(rk_pcie->pcie, table->chn, status);
        HAL_DelayUs(1);
    }
    while (ret == PCIE_DMA_NO_STATUS && timeout_us--);

    if (ret == PCIE_DMA_OK)
    {
        return RT_EOK;
    }
    if (PCIE_DMA_FAIL == 0)
    {
        return -RT_ETIMEOUT;
    }

    return -RT_ERROR;
}

static const struct rk_pcie_dma_ops rk_pcie_dma_ops =
{
    .start_dma_func = rk_pcie_start_dma,
    .config_dma_func = rk_pcie_config_dma,
    .wait_for_finished = rk_pcie_dma_wait_for_finished,
};

static int rk_pcie_poll_irq_user(struct rk_pcie_ep *rk_pcie,
                                 struct pcie_ep_obj_poll_virtual_id_cfg *cfg)
{
    uint32_t index = cfg->virtual_id;

    if (index >= RKEP_EP_VIRTUAL_ID_MAX)
    {
        dev_err(rk_pcie, "poll irq_user, virtual id %d out of range", index);
        return -RT_EINVAL;
    }

    cfg->poll_status = NSIGPOLL;
    if (cfg->sync)
    {
        rt_wqueue_wait(&rk_pcie->wq_head, test_bit(index, rk_pcie->virtual_id_irq_bitmap), RT_WAITING_FOREVER);
    }
    else
    {
        rt_wqueue_wait(&rk_pcie->wq_head, test_bit(index, rk_pcie->virtual_id_irq_bitmap), cfg->timeout_ms);
    }

    if (test_and_clear_bit(index, rk_pcie->virtual_id_irq_bitmap))
        cfg->poll_status = POLL_IN;

    return 0;
}

static rt_err_t rk_pcie_control(rt_device_t dev, int cmd, void *args)
{
    struct rk_pcie_ep *rk_pcie;
    struct pcie_ep_obj_poll_virtual_id_cfg poll_cfg;
    int ret, index;

    RT_ASSERT(dev != RT_NULL);

    rk_pcie = (struct rk_pcie_ep *)dev->user_data;

    switch (cmd)
    {
    case PCIE_EP_RAISE_MSI:
    {
        HAL_PCIE_RaiseMSI(rk_pcie->pcie, PCIe_CLIENT_MSI_OBJ_IRQ);
        break;
    }
    case PCIE_EP_RAISE_IRQ_USER:
    {
        rt_memcpy(&index, args, sizeof(index));
        ret = HAL_PCIE_RaiseMSI(rk_pcie->pcie, index);
        if (ret < 0)
            return -RT_ERROR;
        break;
    }
    case PCIE_EP_POLL_IRQ_USER:
    {
        rt_memcpy(&poll_cfg, args, sizeof(poll_cfg));
        ret = rk_pcie_poll_irq_user(rk_pcie, &poll_cfg);
        if (ret < 0)
            return -RT_ERROR;

        if (rt_memcpy(args, &poll_cfg, sizeof(poll_cfg)))
            return -RT_ERROR;
        break;
    }
    default:
        break;
    }

    return RT_EOK;
}

#ifdef RT_USING_DEVICE_OPS
struct rt_device_ops rk_pcie_ops =
{
    .control = rk_pcie_control,
};
#endif

static struct rk_pcie_ep *rk_pcie_get_resource(struct rt_hw_pcie_ep_board *board)
{
    struct rk_pcie_ep *rk_pcie;
    struct HAL_PCIE_HANDLE *pcie;

    rk_pcie = rt_malloc(sizeof(struct rk_pcie_ep));
    if (!rk_pcie)
    {
        dev_err(rk_pcie, "%s alloc rk_pcie failed\n", __func__);
        return RT_NULL;
    }
    rt_memset(rk_pcie, 0, sizeof(struct rk_pcie_ep));

    pcie = rt_malloc(sizeof(struct HAL_PCIE_HANDLE));
    if (!pcie)
    {
        dev_err(rk_pcie, "%s alloc pcie failed\n", __func__);
        rt_free(rk_pcie);
        return RT_NULL;
    }
    pcie->dev = &g_pcieDev;
    rk_pcie->pcie = pcie;
    rk_pcie->board = board;

    if (rt_mutex_init(&rk_pcie->lock, "pcie_lock", RT_IPC_FLAG_FIFO) != RT_EOK)
    {
        dev_err(rk_pcie, "Init pcie dma mutex error\n");
        RT_ASSERT(0);
    }
    rt_sem_init(&bit_sem_lock, "bit_lock", 1, RT_IPC_FLAG_FIFO);

    rk_pcie->parent.type = RT_Device_Class_Char;
    rk_pcie->parent.user_data = rk_pcie;
#ifdef RT_USING_DEVICE_OPS
    rk_pcie->parent.ops = &rk_pcie_ops;
#else
    rk_pcie->parent.control = rk_pcie_control;
#endif

#ifdef RT_USING_PCIE_EP_BAR0_RESERVED_SIZE
    rk_pcie->obj_info = (struct pcie_ep_obj_info *)(rk_pcie->board->bar0_cpu_addr + RT_USING_PCIE_EP_BAR0_RESERVED_SIZE);
#else
    rk_pcie->obj_info = (struct pcie_ep_obj_info *)(rk_pcie->board->bar0_cpu_addr);
#endif

    memset_io(rk_pcie->obj_info, 0, sizeof(struct pcie_ep_obj_info));
    rk_pcie->obj_info->magic = PCIE_EP_OBJ_INFO_MAGIC;
    rk_pcie->obj_info->version = PCIE_EP_OBJ_INFO_DRV_VERSION;

    return rk_pcie;
}

static void rk_pcie_release_resource(struct rk_pcie_ep *rk_pcie)
{
    rt_free(rk_pcie->pcie);
    rt_free(rk_pcie);
}

static void rk_pcie_resize_bar_nsticky(struct rk_pcie_ep *rk_pcie)
{
    HAL_PCIE_SetBar(rk_pcie->pcie, BAR_0, PCI_BASE_ADDRESS_MEM_TYPE_32, 2);
    HAL_PCIE_SetBar(rk_pcie->pcie, BAR_1, PCI_BASE_ADDRESS_MEM_TYPE_32, 0);
    HAL_PCIE_SetBar(rk_pcie->pcie, BAR_2, PCI_BASE_ADDRESS_MEM_PREFETCH | PCI_BASE_ADDRESS_MEM_TYPE_64, 6);
    HAL_PCIE_SetBar(rk_pcie->pcie, BAR_4, PCI_BASE_ADDRESS_MEM_TYPE_32, 0);
    HAL_PCIE_SetBar(rk_pcie->pcie, BAR_5, PCI_BASE_ADDRESS_MEM_TYPE_32, 0);

    HAL_PCIE_DisableBar(rk_pcie->pcie, BAR_1);
    HAL_PCIE_DisableBar(rk_pcie->pcie, BAR_5);
}

static void rk_pcie_sys_irq_handler(int irq, void *param)
{
    struct rk_pcie_ep *rk_pcie = (struct rk_pcie_ep *)param;
    struct HAL_PCIE_HANDLE *pcie = rk_pcie->pcie;
    union PCIE_DMA_INT_STATUS wr_status, rd_status;
    uint32_t elbi_reg;
    uint32_t chn, reg;
    int ret;

    /* ELBI helper, only check the valid bits, and discard the rest interrupts */
    elbi_reg = HAL_PCIE_GetELBI(pcie, PCIE_ELBI_APP_ELBI_INT_GEN0);
    if (elbi_reg & PCIE_ELBI_APP_ELBI_INT_GEN0_IRQ_USER)
    {
        if (rk_pcie->obj_info->irq_type_ep == OBJ_IRQ_USER)
        {
            reg = rk_pcie->obj_info->irq_user_data_ep;
            if (reg < RKEP_EP_VIRTUAL_ID_MAX)
            {
                set_bit(reg, rk_pcie->virtual_id_irq_bitmap);
                rt_wqueue_wakeup(&rk_pcie->wq_head, (void *)(POLL_IN));
            }
        }
        goto out;
    }

    /* DMA helper */
    for (chn = 0; chn < PCIE_DMA_CHANEL_MAX_NUM; chn++)
    {
        wr_status = HAL_PCIE_GetDmaStatus(pcie, chn, DMA_TO_BUS);
        ret = HAL_PCIE_CheckDmaStatus(pcie, chn, wr_status);
        if (ret == 1)
        {
            dev_dbg(rk_pcie, "wr dma done\n");;
        }
        else if (ret < 0)
        {
            dev_err(rk_pcie, "wr dma abort\n");;
        }

        rd_status = HAL_PCIE_GetDmaStatus(pcie, chn, DMA_FROM_BUS);
        ret = HAL_PCIE_CheckDmaStatus(pcie, chn, rd_status);
        if (ret == 1)
        {
            dev_dbg(rk_pcie, "rd dma done\n");;
        }
        else if (ret < 0)
        {
            dev_err(rk_pcie, "rd dma abort\n");;
        }
    }

    if (wr_status.asdword || rd_status.asdword)
    {
        rk_pcie->obj_info->irq_type_rc = OBJ_IRQ_DMA;
        rk_pcie->obj_info->dma_status_rc.wr |= wr_status.asdword;
        rk_pcie->obj_info->dma_status_rc.rd |= rd_status.asdword;
        HAL_PCIE_RaiseMSI(pcie, PCIe_CLIENT_MSI_OBJ_IRQ);

        rk_pcie->obj_info->irq_type_ep = OBJ_IRQ_DMA;
        rk_pcie->obj_info->dma_status_ep.wr |= wr_status.asdword;
        rk_pcie->obj_info->dma_status_ep.rd |= rd_status.asdword;
    }

out:
    reg = HAL_PCIE_GetMiscStatus(pcie);
    if (reg & HAL_BIT(2))
    {
        rk_pcie_resize_bar_nsticky(rk_pcie);
        HAL_PCIE_WaitForHotRstDly2Ready(rk_pcie->pcie);
    }
}

static int rk_pcie_config_host(struct rk_pcie_ep *rk_pcie)
{
    int i, retries = 100000;

    for (i = 0; i < retries; i++)
    {
        if (HAL_PCIE_LinkUp(rk_pcie->pcie))
        {
            /*
             * We may be here in case of L0 in Gen1. But if EP is capable
             * of Gen2 or Gen3, Gen switch may happen just in this time, but
             * we keep on accessing devices in unstable link status. Given
             * that LTSSM max timeout is 24ms per period, we can wait a bit
             * more for Gen switch.
             */
            rt_thread_mdelay(50);
            dev_info(rk_pcie, "PCIe Link up, LTSSM is 0x%x\n", HAL_PCIE_GetLTSSM(rk_pcie->pcie));
            break;
        }

        dev_info(rk_pcie, "PCIe Linking... LTSSM is 0x%x\n", HAL_PCIE_GetLTSSM(rk_pcie->pcie));
        rt_thread_mdelay(20);
    }
    if (i >= retries)
    {
        dev_err(rk_pcie, "PCIe Link failed. LTSSM is 0x%x\n", HAL_PCIE_GetLTSSM(rk_pcie->pcie));
        return -RT_EIO;
    }

    /* Enable client reset or link down interrupt */
    HAL_PCIE_EnableRstInt(rk_pcie->pcie);
    rt_wqueue_init(&rk_pcie->wq_head);

    /* Enable client elbi interrupt */
    HAL_PCIE_EnableELBIIndex0(rk_pcie->pcie);

    rt_hw_interrupt_install(rk_pcie->pcie->dev->sysIrqNum, rk_pcie_sys_irq_handler, rk_pcie, RT_NULL);
    rt_hw_interrupt_umask(rk_pcie->pcie->dev->sysIrqNum);

    return 0;
}

static int rk_pcie_init_dma_trx(struct rk_pcie_ep *rk_pcie)
{
    rk_pcie->obj = rk_pcie_dma_register(rk_pcie, &rk_pcie_dma_ops);
    if (!rk_pcie->obj)
    {
        dev_dbg(rk_pcie, "rk_pcie_dma_register failed\n");
    }

    return 0;
}

static void rk_pcie_devmode_update(struct rk_pcie_ep *rk_pcie, int mode, int submode)
{
    rk_pcie->obj_info->devmode.mode = mode;
    rk_pcie->obj_info->devmode.submode = submode;
}

/********************* Public Function Definition ****************************/
/**
 * @brief  Get pcie endpoint mmap resource.
 */
uintptr_t rk_pcie_ep_mmap(rt_device_t dev, uint32_t cur_mmap_res)
{
    uintptr_t addr;
    struct rk_pcie_ep *rk_pcie;

    RT_ASSERT(dev != RT_NULL);

    rk_pcie = (struct rk_pcie_ep *)dev->user_data;

    switch (cur_mmap_res)
    {
    case PCIE_EP_MMAP_RESOURCE_DBI:
        addr = rk_pcie->pcie->dev->dbiBase;
        break;
    case PCIE_EP_MMAP_RESOURCE_BAR0:
        addr = rk_pcie->board->bar0_cpu_addr;
        break;
    case PCIE_EP_MMAP_RESOURCE_BAR2:
        addr = rk_pcie->board->bar2_cpu_addr;
        break;
    default:
        dev_err(rk_pcie, "cur mmap_res %d is unsurreport\n", cur_mmap_res);
        return 0;
    }

    return addr;
}

/**
 * @brief  rk pcie endpoint initial thread.
 */
void rt_pcie_ep_init_thread(void *para)
{
    rt_err_t ret = -RT_ERROR;
    struct rk_pcie_ep *rk_pcie;
    struct rt_hw_pcie_ep_board *board = (struct rt_hw_pcie_ep_board *)para;

    rk_pcie = rk_pcie_get_resource(board);
    if (!rk_pcie)
    {
        return;
    }

    ret = rk_pcie_config_host(rk_pcie);
    if (ret)
    {
        goto err_config;
    }

    rk_pcie_init_dma_trx(rk_pcie);

    ret = rt_device_register(&rk_pcie->parent, "rkep", RT_DEVICE_FLAG_STANDALONE);
    if (ret)
    {
        goto err_config;
    }

    rk_pcie_devmode_update(rk_pcie, RKEP_MODE_KERNEL, RKEP_SMODE_INIT);

    return;
err_config:
    rk_pcie_release_resource(rk_pcie);
}

RT_WEAK struct rt_hw_pcie_ep_board rk_pcie_ep_baord =
{
    .bar0_cpu_addr = PCIE_EP_BAR0_CPU_DEFAULT,
    .bar2_cpu_addr = PCIE_EP_BAR2_CPU_DEFAULT,
};

/**
 * @brief  Init rk pcie endpoint framwork and apply to use.
 */
int rt_hw_pcie_ep_init(void)
{
    static rt_thread_t pcie_thread;

    pcie_thread = rt_thread_create("pcie_ep_init", rt_pcie_ep_init_thread, &rk_pcie_ep_baord, 2048, 10, 20);
    RT_ASSERT(pcie_thread);
    rt_thread_startup(pcie_thread);

    return RT_EOK;
}
INIT_APP_EXPORT(rt_hw_pcie_ep_init);

/** @} */  // PCIE_DMA_Public_Function

#endif

/** @} */  // PCIE_DMA

/** @} */  // RKBSP_Common_Driver
