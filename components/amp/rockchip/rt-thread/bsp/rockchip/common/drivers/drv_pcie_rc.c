/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

/** @addtogroup RKBSP_Driver_Reference
 *  @{
 */

/** @addtogroup PCIE_RC
 *  @{
 */

/** @defgroup PCIE_How_To_Use How To Use
 *  @{

 @} */

#include <rthw.h>
#include <rtthread.h>
#include <rtdevice.h>

#include "hal_bsp.h"
#include "drv_pcie_dma.h"

#ifdef RT_USING_PCIE_RC

/********************* Private MACRO Definition ******************************/

#define PCIE_DMA_CHANEL_MAX_NUM         2

#define PCIE_DEBUG 0

#if PCIE_DEBUG
#define dev_dbg(dev, fmt, ...) \
do { \
    rt_kprintf("[D/rkrc] " fmt, ##__VA_ARGS__); \
} while(0)
#else
#define dev_dbg(dev, fmt, ...) \
do { \
} while(0)
#endif
#define dev_info(dev, fmt, ...) \
do { \
    rt_kprintf("[I/rkrc] " fmt, ##__VA_ARGS__); \
} while(0)
#define dev_err(dev, fmt, ...) \
do { \
    rt_kprintf("[E/rkrc] " fmt, ##__VA_ARGS__); \
} while(0)

/********************* Private Structure Definition **************************/

struct rk_pcie_rc
{
    struct rt_device parent;

    /* Info */
    struct HAL_PCIE_HANDLE *pcie;

    /* status */
    struct rt_mutex lock;
    rt_wqueue_t wq_head;

    /* misc */
    struct rk_pcie_dma_device *obj;
};

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ****************************/
static void rk_pcie_start_dma(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table)
{
    struct rk_pcie_rc *rk_pcie = (struct rk_pcie_rc *)(obj->parent.user_data);

    HAL_PCIE_StartDma(rk_pcie->pcie, table);
}

static void rk_pcie_config_dma(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table)
{
    struct rk_pcie_rc *rk_pcie = (struct rk_pcie_rc *)(obj->parent.user_data);

    HAL_PCIE_ConfigDma(rk_pcie->pcie, table);
}

static int rk_pcie_dma_wait_for_finished(struct rk_pcie_dma_device *obj, struct DMA_TABLE *table, uint32_t timeout_us)
{
    struct rk_pcie_rc *rk_pcie = (struct rk_pcie_rc *)(obj->parent.user_data);
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

static struct rk_pcie_rc *rk_pcie_get_resource(void)
{
    struct rk_pcie_rc *rk_pcie;
    struct HAL_PCIE_HANDLE *pcie;

    rk_pcie = rt_malloc(sizeof(struct rk_pcie_rc));
    if (!rk_pcie)
    {
        dev_err(rk_pcie, "%s alloc rk_pcie failed\n", __func__);
        return RT_NULL;
    }
    rt_memset(rk_pcie, 0, sizeof(struct rk_pcie_rc));

    pcie = rt_malloc(sizeof(struct HAL_PCIE_HANDLE));
    if (!pcie)
    {
        dev_err(rk_pcie, "%s alloc pcie failed\n", __func__);
        rt_free(rk_pcie);
        return RT_NULL;
    }
    pcie->dev = &g_pcieDev;
    rk_pcie->pcie = pcie;

    if (rt_mutex_init(&rk_pcie->lock, "pcie_rc_lock", RT_IPC_FLAG_FIFO) != RT_EOK)
    {
        dev_err(rk_pcie, "Init pcie dma mutex error\n");
        RT_ASSERT(0);
    }

    rk_pcie->parent.type = RT_Device_Class_Char;
    rk_pcie->parent.user_data = rk_pcie;

    return rk_pcie;
}

static void rk_pcie_release_resource(struct rk_pcie_rc *rk_pcie)
{
    rt_free(rk_pcie->pcie);
    rt_free(rk_pcie);
}

static void rk_pcie_sys_irq_handler(int irq, void *param)
{
    struct rk_pcie_rc *rk_pcie = (struct rk_pcie_rc *)param;
    struct HAL_PCIE_HANDLE *pcie = rk_pcie->pcie;
    union PCIE_DMA_INT_STATUS wr_status, rd_status;
    uint32_t chn, reg;
    int ret;

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

    reg = HAL_PCIE_GetMiscStatus(pcie);
    if (reg & HAL_BIT(2))
    {
        HAL_PCIE_WaitForHotRstDly2Ready(rk_pcie->pcie);
    }
}

static int rk_pcie_config_host(struct rk_pcie_rc *rk_pcie)
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

    rt_hw_interrupt_install(rk_pcie->pcie->dev->sysIrqNum, rk_pcie_sys_irq_handler, rk_pcie, RT_NULL);
    rt_hw_interrupt_umask(rk_pcie->pcie->dev->sysIrqNum);

    return 0;
}

static int rk_pcie_init_dma_trx(struct rk_pcie_rc *rk_pcie)
{
    rk_pcie->obj = rk_pcie_dma_register(rk_pcie, &rk_pcie_dma_ops);
    if (!rk_pcie->obj)
    {
        dev_dbg(rk_pcie, "rk_pcie_dma_register failed\n");
    }

    return 0;
}

/********************* Public Function Definition ****************************/
/**
 * @brief  rk pcie endpoint initial thread.
 */
void rt_pcie_rc_init_thread(void *para)
{
    rt_err_t ret = -RT_ERROR;
    struct rk_pcie_rc *rk_pcie;

    rk_pcie = rk_pcie_get_resource();
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

    ret = rt_device_register(&rk_pcie->parent, "rkrc", RT_DEVICE_FLAG_STANDALONE);
    if (ret)
    {
        goto err_config;
    }

    return;
err_config:
    rk_pcie_release_resource(rk_pcie);
}

/**
 * @brief  Init rk pcie endpoint framwork and apply to use.
 */
int rt_hw_pcie_rc_init(void)
{
    static rt_thread_t pcie_thread;

    pcie_thread = rt_thread_create("pcie_rc_init", rt_pcie_rc_init_thread, NULL, 2048, 10, 20);
    RT_ASSERT(pcie_thread);
    rt_thread_startup(pcie_thread);

    return RT_EOK;
}
INIT_APP_EXPORT(rt_hw_pcie_rc_init);

/** @} */  // PCIE_DMA_Public_Function

#endif

/** @} */  // PCIE_DMA

/** @} */  // RKBSP_Common_Driver
