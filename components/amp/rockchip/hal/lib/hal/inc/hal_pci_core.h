/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#include "hal_conf.h"

#ifdef HAL_PCIE_MODULE_ENABLED

/** @addtogroup RK_HAL_Driver
 *  @{
 */

/** @addtogroup PCI
 *  @{
 */

#ifndef _HAL_PCI_H_
#define _HAL_PCI_H_

#include "hal_def.h"

/***************************** MACRO Definition ******************************/
/** @defgroup PCI_Exported_Definition_Group1 Basic Definition
 *  @{
 */

#define PCI_VENDOR_ID 0x00  /* 16 bits */
#define PCI_DEVICE_ID 0x02  /* 16 bits */

#define PCI_CLASS_REVISION 0x08 /* High 24 bits are class, low 8 revision */
#define PCI_CLASS_DEVICE   0x0a /* Device class */
#define PCI_CLASS_CODE     0x0b /* Device class code */

typedef int32_t HAL_PCI_DevT;

#define PCI_BUS(d)              (((d) >> 16) & 0xff)
#define PCI_DEVFN(d, f)         ((d) << 11 | (f) << 8)
#define PCI_MASK_BUS(bdf)       ((bdf) & 0xffff)
#define PCI_ADD_BUS(bus, devfn) (((bus) << 16) | (devfn))
#define PCI_BDF(b, d, f)        ((b) << 16 | PCI_DEVFN(d, f))

#define PCI_BASE_ADDRESS_0 0x10
#define PCI_BASE_ADDRESS_1 0x14
#define PCI_BASE_ADDRESS_2 0x18
#define PCI_BASE_ADDRESS_3 0x1C
#define PCI_BASE_ADDRESS_4 0x20
#define PCI_BASE_ADDRESS_5 0x24

#define PCI_BASE_ADDRESS_MEM_TYPE_32  0x00
#define PCI_BASE_ADDRESS_MEM_TYPE_64  0x04
#define PCI_BASE_ADDRESS_MEM_PREFETCH 0x08

#define PCIE_TYPE0_HDR_DBI2_OFFSET 0x100
#define PCIE_ELBI_LOCAL_BASE       0x1000
#define PCIE_ELBI_LOCAL_ENABLE_OFF 0x08

enum PCI_BARNO {
    NO_BAR = -1,
    BAR_0,
    BAR_1,
    BAR_2,
    BAR_3,
    BAR_4,
    BAR_5,
};

/**
 * @brief PCI size type
 */
typedef enum {
    PCI_SIZE_8,
    PCI_SIZE_16,
    PCI_SIZE_32,
} ePCI_Size;

/***************************** Structure Definition **************************/

/** @} */
/***************************** Function Declare ******************************/
/** @defgroup PCI_Public_Function_Declare Public Function Declare
 *  @{
 */

int32_t HAL_PCI_WriteConfigDWord(uintptr_t cfgBase, int32_t offset, uint32_t value);
int32_t HAL_PCI_ReadConfigDWord(uintptr_t cfgBase, int32_t offset, uint32_t *valuep);
int32_t HAL_PCI_WriteConfigWord(uintptr_t cfgBase, int32_t offset, uint32_t value);
int32_t HAL_PCI_ReadConfigWord(uintptr_t cfgBase, int32_t offset, uint32_t *valuep);
int32_t HAL_PCI_WriteConfigByte(uintptr_t cfgBase, int32_t offset, uint32_t value);
int32_t HAL_PCI_ReadConfigByte(uintptr_t cfgBase, int32_t offset, uint32_t *valuep);

/** @} */

#endif

/** @} */

/** @} */

#endif /* HAL_PCIE_MODULE_ENABLED */
