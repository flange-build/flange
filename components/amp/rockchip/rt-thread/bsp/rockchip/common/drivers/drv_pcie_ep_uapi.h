/**
  * Copyright (c) 2025 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef _DRV_PCIE_EP_UAPI_H__
#define _DRV_PCIE_EP_UAPI_H__

#include "sys/ioctl.h"

#ifdef RT_USING_PCIE_EP

/* rkep device mode status definition */
#define RKEP_MODE_BOOTROM       1
#define RKEP_MODE_LOADER        2
#define RKEP_MODE_KERNEL        3
#define RKEP_MODE_FUN0          4
/* Common status */
#define RKEP_SMODE_INIT         0
#define RKEP_SMODE_LNKRDY       1
#define RKEP_SMODE_LNKUP        2
#define RKEP_SMODE_ERR          0xff
/* Firmware download status */
#define RKEP_SMODE_FWDLRDY      0x10
#define RKEP_SMODE_FWDLDONE     0x11
/* Application status*/
#define RKEP_SMODE_APPRDY       0x20

/*
 * rockchip driver cache ioctrl input param
 */
struct pcie_ep_dma_cache_cfg
{
    unsigned long long addr;
    unsigned int size;
};

struct pcie_ep_dma_block
{
    unsigned long long bus_paddr;
    unsigned long long local_paddr;
    unsigned int size;
};

struct pcie_ep_dma_block_req
{
    unsigned short vir_id;  /* Default 0 */
    unsigned char chn;
    unsigned char wr;
    unsigned int flag;
#define PCIE_EP_DMA_BLOCK_FLAG_COHERENT BIT(0)      /* Cache coherent, 1-need, 0-None */
    struct pcie_ep_dma_block block;
};

#define PCIE_EP_OBJ_INFO_MAGIC 0x524B4550

enum pcie_ep_obj_irq_type
{
    OBJ_IRQ_UNKNOWN,
    OBJ_IRQ_DMA,
    OBJ_IRQ_USER,
    OBJ_IRQ_ELBI,
};

struct pcie_ep_obj_irq_dma_status
{
    unsigned int wr;
    unsigned int rd;
};

enum pcie_ep_mmap_resource
{
    PCIE_EP_MMAP_RESOURCE_DBI,
    PCIE_EP_MMAP_RESOURCE_BAR0,
    PCIE_EP_MMAP_RESOURCE_BAR2,
    PCIE_EP_MMAP_RESOURCE_BAR4,
    PCIE_EP_MMAP_RESOURCE_USER_MEM,
    PCIE_EP_MMAP_RESOURCE_RK3568_RC_DBI,
    PCIE_EP_MMAP_RESOURCE_RK3588_RC_DBI,
    PCIE_EP_MMAP_RESOURCE_MAX,
};

#define PCIE_EP_OBJ_INFO_MSI_DATA_NUM   0x8
#define RKEP_EP_VIRTUAL_ID_MAX      (PCIE_EP_OBJ_INFO_MSI_DATA_NUM * 32) /* 256 virtual_id */

/*
 * rockchip ep device information which is store in BAR0
 */
struct pcie_ep_obj_info
{
    unsigned int magic;
    unsigned int version;
    struct
    {
        unsigned short mode;
        unsigned short submode;
    } devmode;
    unsigned int msi_data[PCIE_EP_OBJ_INFO_MSI_DATA_NUM];
    unsigned char reserved[0x1D0];

    unsigned int irq_type_rc;                   /* Generate in ep isr, valid only for rc, clear in rc */
    struct pcie_ep_obj_irq_dma_status dma_status_rc;    /* Generate in ep isr, valid only for rc, clear in rc */
    unsigned int irq_type_ep;                   /* Generate in ep isr, valid only for ep, clear in ep */
    struct pcie_ep_obj_irq_dma_status dma_status_ep;    /* Generate in ep isr, valid only for ep, clear in ep */
    unsigned int irq_user_data_rc;                  /* Generate in ep, valid only for rc, No need to clear */
    unsigned int irq_user_data_ep;                  /* Generate in rc, valid only for ep, No need to clear */
};

/*
 * rockchip driver ep_obj poll ioctrl input param
 */
struct pcie_ep_obj_poll_virtual_id_cfg
{
    unsigned int timeout_ms;
    unsigned int sync;
    unsigned int virtual_id;
    unsigned int poll_status;
};

#define PCIE_BASE   'P'
#define PCIE_DMA_CACHE_INVALIDE     _IOW(PCIE_BASE, 1, struct pcie_ep_dma_cache_cfg)
#define PCIE_DMA_CACHE_FLUSH        _IOW(PCIE_BASE, 2, struct pcie_ep_dma_cache_cfg)
#define PCIE_DMA_IRQ_MASK_ALL       _IOW(PCIE_BASE, 3, int)
#define PCIE_EP_RAISE_MSI           _IOW(PCIE_BASE, 4, int)
#define PCIE_EP_SET_MMAP_RESOURCE   _IOW(PCIE_BASE, 6, int)
#define PCIE_EP_RAISE_ELBI          _IOW(PCIE_BASE, 7, int)
#define PCIE_EP_REQUEST_VIRTUAL_ID  _IOR(PCIE_BASE, 16, int)
#define PCIE_EP_RELEASE_VIRTUAL_ID  _IOW(PCIE_BASE, 17, int)
#define PCIE_EP_RAISE_IRQ_USER      _IOW(PCIE_BASE, 18, int)
#define PCIE_EP_POLL_IRQ_USER       _IOW(PCIE_BASE, 19, struct pcie_ep_obj_poll_virtual_id_cfg)
#define PCIE_EP_DMA_XFER_BLOCK      _IOW(PCIE_BASE, 32, struct pcie_ep_dma_block_req)

#endif
#endif
