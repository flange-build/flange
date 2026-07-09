/**
  ******************************************************************************
  * @file    rsc_table.c
  * @author  MCD Application Team
  * @brief   Ressource table
  *
  *   This file provides a default resource table requested by remote proc to
  *  load the elf file. It also allows to add debug trace using a shared buffer.
  *
  ******************************************************************************
  * @attention
  *
  * <h2><center>&copy; Copyright (c) 2019 STMicroelectronics.
  * All rights reserved.</center></h2>
  *
  * This software component is licensed by ST under BSD 3-Clause license,
  * the "License"; You may not use this file except in compliance with the
  * License. You may obtain a copy of the License at:
  *                       opensource.org/licenses/BSD-3-Clause
  *
  ******************************************************************************
  */

/** @addtogroup RSC_TABLE
  * @{
  */

/** @addtogroup resource_table
  * @{
  */

/** @addtogroup resource_table_Private_Includes
  * @{
  */

#if defined(__ICCARM__) || defined (__CC_ARM)
#include <stddef.h> /* needed  for offsetof definition*/
#endif
#include "rsc_table.h"
#include "openamp/open_amp.h"

/**
  * @}
  */

/** @addtogroup resource_table_Private_TypesDefinitions
  * @{
  */

/**
  * @}
  */

/** @addtogroup resource_table_Private_Defines
  * @{
  */

/* Place resource table in special ELF section */
#if defined(__GNUC__)
#define __section_t(S)          __attribute__((__section__(#S)))
#define __resource              __section_t(.resource_table)
#endif

#if defined (LINUX_RPROC_MASTER)
 #ifdef VIRTIO_MASTER_ONLY
  #define CONST
 #else
  #define CONST const
 #endif
#else
 #define CONST
#endif

#define RPMSG_IPU_C0_FEATURES   1
#define VRING_COUNT         		2

/* VirtIO rpmsg device id */
#define VIRTIO_ID_RPMSG_        7

struct shared_resource_table *resource_table = (struct shared_resource_table *)RSC_TABLE_ADDR;

void resource_table_init(int RPMsgRole, void **table_ptr, int *length)
{
    resource_table->num = 1;
    resource_table->version = 1;
    resource_table->offset[0] = offsetof(struct shared_resource_table, vdev);

    resource_table->vring0.da = VRING_TX_ADDRESS;
    resource_table->vring0.align = VRING_ALIGNMENT;
    resource_table->vring0.num = VRING_NUM_BUFFS;
    resource_table->vring0.notifyid = VRING0_ID;

    resource_table->vring1.da = VRING_RX_ADDRESS;
    resource_table->vring1.align = VRING_ALIGNMENT;
    resource_table->vring1.num = VRING_NUM_BUFFS;
    resource_table->vring1.notifyid = VRING1_ID;

    resource_table->vdev.type = RSC_VDEV;
    resource_table->vdev.id = VIRTIO_ID_RPMSG_;
    resource_table->vdev.num_of_vrings=VRING_COUNT;
    resource_table->vdev.dfeatures = RPMSG_IPU_C0_FEATURES;

    (void)RPMsgRole;
    *length = sizeof(struct shared_resource_table);
    *table_ptr = (void *)resource_table;
}
