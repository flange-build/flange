/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "hal_base.h"

#ifdef HAL_PCIE_MODULE_ENABLED

/** @addtogroup RK_HAL_Driver
 *  @{
 */

/** @addtogroup PCIE
 *  @{
 */

/** @defgroup PCIE_How_To_Use How To Use
 *  @{

Thi PCIe drvier is code for dwc pcie controller driver.

The PCIe driver can be used as follows:

After u-boot or Linux PCIe initialization and enumeration process, we can using the HAL PCIe drivers to do the basically works, like:

- Check PCIe status:
    - Wait for PCIe link up by calling HAL_PCIE_LinkUp()

- Using DMA in poll:
    - Calling HAL_PCIE_ConfigDma() to config uDMA block transfer table
    - Calling HAL_PCIE_StartDma() to start uDMA
    - Get and clear unmask uDMA status for irq mode by calling HAL_PCIE_GetDmaStatus()
    - Get and clear raw uDMA status for poll mode by calling HAL_PCIE_GetDmaStatusRaw()
    - Check uDMA status by calling HAL_PCIE_CheckDmaStatus()

- Configuration:
    - Setting iATU by calling HAL_PCIE_InboundConfig() and HAL_PCIE_OutboundConfig()
    - Setting outbound iATU for CFG by calling HAL_PCIE_OutboundConfigCFG0()
    - Support RC triggers interrupt notification EP by calling HAL_PCIE_EnableELBIIndex0()

- Abort interrupt:
    - Get MISC interrupt status by calling HAL_PCIE_GetMiscStatus()
    - Get ELBI interrupt status by calling HAL_PCIE_GetELBI()
    - EP Trigger triggers MSI interrupt notification EP by calling HAL_PCIE_RaiseMSI()

 @} */

/** @defgroup PCIE_Private_Definition Private Definition
 *  @{
 */
/********************* Private MACRO Definition ******************************/
#ifdef PCIE_DEBUG
#define PCIE_DBG HAL_DBG
#else
#define PCIE_DBG
#endif

#define PCIE_CLIENT_INTR_STATUS_MISC 0x10

#define PCIE_CLIENT_INTR_MASK 0x24

#define PCIE_CLIENT_MSI_GEN_CON    0x38
#define PCIE_CLIENT_HOT_RESET_CTRL 0x180
#define PCIE_LTSSM_APP_DLY2_EN     BIT(1)
#define PCIE_LTSSM_APP_DLY2_DONE   BIT(3)

#define PCIE_CLIENT_LTSSM_STATUS 0x300
#define SMLH_LINKUP              BIT(16)
#define RDLH_LINKUP              BIT(17)

#define PCIE_MISC_CONTROL_1_OFF 0x8BC
#define PCIE_DBI_RO_WR_EN       BIT(0)

#define PCIE_ELBI_BASE    0x200e00
#define PCIE_ELBI_REG_NUM 0x2

#define PCIE_ATU_OFFSET 0x300000

#define PCIE_ATU_ENABLE          BIT(31)
#define PCIE_ATU_BAR_MODE_ENABLE BIT(30)

#define PCIE_ATU_UNR_REGION_CTRL1 0x00
#define PCIE_ATU_UNR_REGION_CTRL2 0x04
#define PCIE_ATU_UNR_LOWER_BASE   0x08
#define PCIE_ATU_UNR_UPPER_BASE   0x0C
#define PCIE_ATU_UNR_LOWER_LIMIT  0x10
#define PCIE_ATU_UNR_LOWER_TARGET 0x14
#define PCIE_ATU_UNR_UPPER_TARGET 0x18
#define PCIE_ATU_UNR_UPPER_LIMIT  0x20

#define LINK_WAIT_IATU 9

#define PCIE_DMA_OFFSET 0x380000

#define PCIE_DMA_WR_ENB        0xc
#define PCIE_DMA_WR_CTRL_LO    0x200
#define PCIE_DMA_WR_CTRL_HI    0x204
#define PCIE_DMA_WR_XFERSIZE   0x208
#define PCIE_DMA_WR_SAR_PTR_LO 0x20c
#define PCIE_DMA_WR_SAR_PTR_HI 0x210
#define PCIE_DMA_WR_DAR_PTR_LO 0x214
#define PCIE_DMA_WR_DAR_PTR_HI 0x218
#define PCIE_DMA_WR_WEILO      0x18
#define PCIE_DMA_WR_WEIHI      0x1c
#define PCIE_DMA_WR_DOORBELL   0x10
#define PCIE_DMA_WR_INT_STATUS 0x4c
#define PCIE_DMA_WR_INT_MASK   0x54
#define PCIE_DMA_WR_INT_CLEAR  0x58

#define PCIE_DMA_RD_ENB        0x2c
#define PCIE_DMA_RD_CTRL_LO    0x300
#define PCIE_DMA_RD_CTRL_HI    0x304
#define PCIE_DMA_RD_XFERSIZE   0x308
#define PCIE_DMA_RD_SAR_PTR_LO 0x30c
#define PCIE_DMA_RD_SAR_PTR_HI 0x310
#define PCIE_DMA_RD_DAR_PTR_LO 0x314
#define PCIE_DMA_RD_DAR_PTR_HI 0x318
#define PCIE_DMA_RD_WEILO      0x38
#define PCIE_DMA_RD_WEIHI      0x3c
#define PCIE_DMA_RD_DOORBELL   0x30
#define PCIE_DMA_RD_INT_STATUS 0xa0
#define PCIE_DMA_RD_INT_MASK   0xa8
#define PCIE_DMA_RD_INT_CLEAR  0xac

#define PCIE_HOTRESET_TMOUT_US 10000

#define BIT(nr) (1 << (nr))
/********************* Private Structure Definition **************************/

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ***************************/

static inline void writel(uintptr_t address, uint32_t value)
{
    *((volatile uint32_t *)address) = value;
}

static inline uint32_t readl(uintptr_t address)
{
    return *((volatile uint32_t *)address);
}

static inline void PCIE_DbiWritel(struct HAL_PCIE_HANDLE *pcie, uint32_t reg, uint32_t val)
{
    writel(pcie->dev->dbiBase + reg, val);
}

static inline uint32_t PCIE_DbiReadl(struct HAL_PCIE_HANDLE *pcie, uint32_t reg)
{
    return readl(pcie->dev->dbiBase + reg);
}

static inline void PCIE_ApbWritel(struct HAL_PCIE_HANDLE *pcie, uint32_t reg, uint32_t val)
{
    writel(pcie->dev->apbBase + reg, val);
}

static inline void PCIE_EnableDbiWrite(struct HAL_PCIE_HANDLE *pcie)
{
    uint32_t reg;
    uint32_t val;

    reg = PCIE_MISC_CONTROL_1_OFF;
    val = PCIE_DbiReadl(pcie, reg);
    val |= PCIE_DBI_RO_WR_EN;
    PCIE_DbiWritel(pcie, reg, val);
}

static inline void PCIE_DisableDbiWrite(struct HAL_PCIE_HANDLE *pcie)
{
    uint32_t reg;
    uint32_t val;

    reg = PCIE_MISC_CONTROL_1_OFF;
    val = PCIE_DbiReadl(pcie, reg);
    val &= ~PCIE_DBI_RO_WR_EN;
    PCIE_DbiWritel(pcie, reg, val);
}

static inline uint32_t PCIE_ApbReadl(struct HAL_PCIE_HANDLE *pcie, uint32_t reg)
{
    return readl(pcie->dev->apbBase + reg);
}

static void PCIE_StartDmaRead(struct HAL_PCIE_HANDLE *pcie, struct DMA_TABLE *cur, int ctrOffset)
{
    PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_ENB, cur->enb.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_CTRL_LO, cur->ctxReg.ctrllo.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_CTRL_HI, cur->ctxReg.ctrlhi.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_XFERSIZE, cur->ctxReg.xfersize);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_SAR_PTR_LO, cur->ctxReg.sarptrlo);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_SAR_PTR_HI, cur->ctxReg.sarptrhi);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_DAR_PTR_LO, cur->ctxReg.darptrlo);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_RD_DAR_PTR_HI, cur->ctxReg.darptrhi);
    PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_DOORBELL, cur->start.asdword);
}

static void PCIE_StartDmaWrite(struct HAL_PCIE_HANDLE *pcie, struct DMA_TABLE *cur, int ctrOffset)
{
    PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_ENB, cur->enb.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_CTRL_LO, cur->ctxReg.ctrllo.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_CTRL_HI, cur->ctxReg.ctrlhi.asdword);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_XFERSIZE, cur->ctxReg.xfersize);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_SAR_PTR_LO, cur->ctxReg.sarptrlo);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_SAR_PTR_HI, cur->ctxReg.sarptrhi);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_DAR_PTR_LO, cur->ctxReg.darptrlo);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_DAR_PTR_HI, cur->ctxReg.darptrhi);
    PCIE_DbiWritel(pcie, ctrOffset + PCIE_DMA_WR_WEILO, cur->weilo.asdword);
    PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_DOORBELL, cur->start.asdword);
}

static int32_t PCIE_GetFreeOutboundAtu(struct HAL_PCIE_HANDLE *pcie)
{
    char i;
    uint32_t off;

    for (i = 0; i < 8; i++) {
        off = PCIE_ATU_OFFSET + 0x200 * i;
        if (!(PCIE_DbiReadl(pcie, off + PCIE_ATU_UNR_REGION_CTRL2) & PCIE_ATU_ENABLE)) {
            return i;
        }
    }

    return -1;
}

static HAL_Status PCIE_CleanWrDmaStatus(struct HAL_PCIE_HANDLE *pcie, union PCIE_DMA_INT_STATUS status, uint8_t chn)
{
    union PCIE_DMA_INI_CLEAR clears;

    if (status.donesta & BIT(chn)) {
        clears.doneclr = 0x1 << chn;
        PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_INT_CLEAR, clears.asdword);
    }

    if (status.abortsta & BIT(chn)) {
        clears.abortclr = 0x1 << chn;
        PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_INT_CLEAR, clears.asdword);
    }

    return HAL_OK;
}

static HAL_Status PCIE_CleanRdDmaStatus(struct HAL_PCIE_HANDLE *pcie, union PCIE_DMA_INT_STATUS status, uint8_t chn)
{
    union PCIE_DMA_INI_CLEAR clears;

    if (status.donesta & BIT(chn)) {
        clears.doneclr = 0x1 << chn;
        PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_INT_CLEAR, clears.asdword);
    }

    if (status.abortsta & BIT(chn)) {
        clears.abortclr = 0x1 << chn;
        PCIE_DbiWritel(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_INT_CLEAR, clears.asdword);
    }

    return HAL_OK;
}

/** @} */
/********************* Public Function Definition ****************************/
/** @defgroup PCIE_Exported_Functions_Group2 State and Errors Functions
 *  @{
 */

/**
 * @brief  Get ELBI status and clear it.
 * @param  pcie: PCIe host.
 * @param  index: ELBI interrupt index
 * @return uint32_t.
 */
uint32_t HAL_PCIE_GetELBI(struct HAL_PCIE_HANDLE *pcie, uint8_t index)
{
    uint32_t val;

    val = PCIE_DbiReadl(pcie, PCIE_ELBI_BASE + index);
    if (val) {
        PCIE_DbiWritel(pcie, PCIE_ELBI_BASE + index * 4, val << 16);
    }

    return val;
}

/**
 * @brief  Get MISC status and clear it.
 * @param  pcie: PCIe host.
 * @return uint32_t.
 */
uint32_t HAL_PCIE_GetMiscStatus(struct HAL_PCIE_HANDLE *pcie)
{
    uint32_t val;

    val = PCIE_DbiReadl(pcie, PCIE_CLIENT_INTR_STATUS_MISC);
    if (val) {
        PCIE_DbiWritel(pcie, PCIE_CLIENT_INTR_STATUS_MISC, val);
    }

    return val;
}

/**
 * @brief  Get DMA unmask status, Clear DMA status when done or abort.
 * @param  pcie: PCIe host.
 * @param  chn: PCIe DMA channal to check.
 * @param  dir: PCIe DMA channal's direction.
 * @return union PCIE_DMA_INT_STATUS status.
 */
union PCIE_DMA_INT_STATUS HAL_PCIE_GetDmaStatus(struct HAL_PCIE_HANDLE *pcie, uint8_t chn,
                                                enum HAL_PCIE_DMA_DIR dir)
{
    union PCIE_DMA_INT_STATUS status;
    uint32_t mask;

    if (dir == DMA_TO_BUS) {
        mask = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_INT_MASK);
        status.asdword = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_INT_STATUS) & (~mask);
        PCIE_CleanWrDmaStatus(pcie, status, chn);
    } else {
        mask = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_INT_STATUS);
        status.asdword = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_INT_STATUS) & (~mask);
        PCIE_CleanRdDmaStatus(pcie, status, chn);
    }

    return status;
}

/**
 * @brief  Get DMA raw status, Clear DMA status when done or abort.
 * @param  pcie: PCIe host.
 * @param  chn: PCIe DMA channal to check.
 * @param  dir: PCIe DMA channal's direction.
 * @return union PCIE_DMA_INT_STATUS status.
 */
union PCIE_DMA_INT_STATUS HAL_PCIE_GetDmaStatusRaw(struct HAL_PCIE_HANDLE *pcie, uint8_t chn,
                                                   enum HAL_PCIE_DMA_DIR dir)
{
    union PCIE_DMA_INT_STATUS status;

    if (dir == DMA_TO_BUS) {
        status.asdword = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_WR_INT_STATUS);
        PCIE_CleanWrDmaStatus(pcie, status, chn);
    } else {
        status.asdword = PCIE_DbiReadl(pcie, PCIE_DMA_OFFSET + PCIE_DMA_RD_INT_STATUS);
        PCIE_CleanRdDmaStatus(pcie, status, chn);
    }

    return status;
}

/**
 * @brief  Check DMA status.
 * @param  pcie: PCIe host.
 * @param  chn: PCIe DMA channal to check.
 * @param  status: DMA interrupt status.
 * @return enum PCIE_DMA_RESULT.
 */
enum PCIE_DMA_RESULT HAL_PCIE_CheckDmaStatus(struct HAL_PCIE_HANDLE *pcie, uint8_t chn, union PCIE_DMA_INT_STATUS status)
{
    if (status.donesta & BIT(chn)) {
        return PCIE_DMA_OK;
    } else if (status.abortsta & BIT(chn)) {
        return PCIE_DMA_FAIL;
    } else {
        return PCIE_DMA_NO_STATUS;
    }
}

/**
 * @brief  Wait for ltssm ready when hot rst under ltssm dly2 mode.
 * @param  pcie: PCIe host.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_WaitForHotRstDly2Ready(struct HAL_PCIE_HANDLE *pcie)
{
    int32_t timeout;

    if (PCIE_ApbReadl(pcie, PCIE_CLIENT_HOT_RESET_CTRL) & PCIE_LTSSM_APP_DLY2_EN) {
        timeout = PCIE_HOTRESET_TMOUT_US;
        while (timeout--) {
            if ((PCIE_ApbReadl(pcie, PCIE_CLIENT_LTSSM_STATUS) & 0x3f) == 0) {
                break;
            }
            HAL_DelayUs(1);
        }

        PCIE_ApbWritel(pcie, (PCIE_LTSSM_APP_DLY2_DONE) | (PCIE_LTSSM_APP_DLY2_DONE << 16),
                       PCIE_CLIENT_HOT_RESET_CTRL);
    }

    return 0;
}

/**
 * @brief  Raise MSI to RC.
 * @param  pcie: PCIe host.
 * @param  interrupt: interrupt number.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_RaiseMSI(struct HAL_PCIE_HANDLE *pcie, uint8_t interrupt)
{
    PCIE_ApbWritel(pcie, HAL_BIT(interrupt), PCIE_CLIENT_MSI_GEN_CON);

    return HAL_OK;
}

/**
 * @brief  Check whether the link has been linked.
 * @param  pcie: PCIe host.
 * @return HAL_Check.
 */
HAL_Check HAL_PCIE_LinkUp(struct HAL_PCIE_HANDLE *pcie)
{
    uint32_t val;

    val = PCIE_ApbReadl(pcie, PCIE_CLIENT_LTSSM_STATUS);
    if ((val & RDLH_LINKUP) && (val & SMLH_LINKUP)) {
        return HAL_TRUE;
    }

    return HAL_FALSE;
}

/**
 * @brief  Get PCIe controller LTSSM.
 * @param  pcie: PCIe host.
 * @return uint32_t. LTSSM value.
 */
uint32_t HAL_PCIE_GetLTSSM(struct HAL_PCIE_HANDLE *pcie)
{
    return PCIE_ApbReadl(pcie, PCIE_CLIENT_LTSSM_STATUS);
}

/** @} */

/** @defgroup PCIE_Exported_Functions_Group3 IO Functions

 This section provides functions allowing to IO controlling:

 *  @{
 */

/**
 * @brief  Config DMA table from user configuration to hw parameter.
 * @param  pcie: PCIe host.
 * @param  table: PCIe DMA table.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_ConfigDma(struct HAL_PCIE_HANDLE *pcie, struct DMA_TABLE *table)
{
    table->enb.enb = 0x1;
    table->ctxReg.ctrllo.lie = 0x1;
    table->ctxReg.ctrllo.rie = 0x0;
    table->ctxReg.ctrllo.td = 0x1;
    table->ctxReg.ctrlhi.asdword = 0x0;
    table->ctxReg.xfersize = table->bufSize;
    if (table->dir == DMA_FROM_BUS) {
        table->ctxReg.sarptrlo = (uint32_t)(table->bus & 0xffffffff);
        table->ctxReg.sarptrhi = (uint32_t)(table->bus >> 32);
        table->ctxReg.darptrlo = (uint32_t)(table->local & 0xffffffff);
        table->ctxReg.darptrhi = (uint32_t)(table->local >> 32);
    } else if (table->dir == DMA_TO_BUS) {
        table->ctxReg.sarptrlo = (uint32_t)(table->local & 0xffffffff);
        table->ctxReg.sarptrhi = (uint32_t)(table->local >> 32);
        table->ctxReg.darptrlo = (uint32_t)(table->bus & 0xffffffff);
        table->ctxReg.darptrhi = (uint32_t)(table->bus >> 32);
    }
    table->weilo.weight0 = 0x0;
    table->start.stop = 0x0;
    table->start.chnl = table->chn;

    return HAL_OK;
}

/**
 * @brief  Start DMA transmition.
 * @param  pcie: PCIe host.
 * @param  table: PCIe DMA table.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_StartDma(struct HAL_PCIE_HANDLE *pcie, struct DMA_TABLE *table)
{
    int dir = table->dir;
    int chn = table->chn;
    int ctrOffset = PCIE_DMA_OFFSET + chn * 0x200;

    if (dir == DMA_FROM_BUS) {
        PCIE_StartDmaRead(pcie, table, ctrOffset);
    } else if (dir == DMA_TO_BUS) {
        PCIE_StartDmaWrite(pcie, table, ctrOffset);
    }

    return HAL_OK;
}

/** @} */

/** @defgroup PCIE_Exported_Functions_Group4 Init and DeInit Functions
 *  @{
 */

/**
 * @brief  Initialial PCIe host.
 * @param  pcie: PCIe host.
 * @param  dev: PCIe device.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_Init(struct HAL_PCIE_HANDLE *pcie, struct HAL_PCIE_DEV *dev)
{
    pcie->dev = dev;

    return HAL_OK;
}

/**
 * @brief  De-Initialial PCIe host.
 * @param  pcie: PCIe host.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_DeInit(struct HAL_PCIE_HANDLE *pcie)
{
    return HAL_OK;
}

/** @} */

/** @defgroup PCIe_Exported_Functions_Group5 Other Functions
 *  @{
 */

/**
 * @brief  Setting PCIe inbound atu.
 * @param  pcie: PCIe host.
 * @param  index: atu index.
 * @param  bar: bar index.
 * @param  cpuAddr: mapped memory address.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_InboundConfig(struct HAL_PCIE_HANDLE *pcie, int32_t index, int32_t bar, uint64_t cpuAddr)
{
    uint32_t val, off;
    int32_t i;

    off = PCIE_ATU_OFFSET + 0x200 * index + 0x100;
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_LOWER_TARGET, cpuAddr & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_UPPER_TARGET, (cpuAddr >> 32) & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_REGION_CTRL1, 0);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_REGION_CTRL2, PCIE_ATU_ENABLE | PCIE_ATU_BAR_MODE_ENABLE | (bar << 8));
    for (i = 0; i < 5000; i++) {
        val = PCIE_DbiReadl(pcie, off + PCIE_ATU_UNR_REGION_CTRL2);
        if (val & PCIE_ATU_ENABLE) {
            return HAL_OK;
        }
        HAL_DelayUs(LINK_WAIT_IATU);
    }

    return HAL_ERROR;
}

/**
 * @brief  Setting PCIe outbound atu.
 * @param  pcie: PCIe host.
 * @param  index: atu index.
 * @param  type: outbound type.
 * @param  cpuAddr: mapped memory address.
 * @param  busAddr: pci bus address.
 * @param  size: outbound atu size limit.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_OutboundConfig(struct HAL_PCIE_HANDLE *pcie, int32_t index, int type, uint64_t cpuAddr, uint64_t busAddr, uint32_t size)
{
    uint32_t val, off;
    int32_t i;

    off = PCIE_ATU_OFFSET + 0x200 * index;
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_LOWER_BASE, cpuAddr & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_UPPER_BASE, (cpuAddr >> 32) & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_LOWER_LIMIT, (cpuAddr + size - 1) & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_LOWER_TARGET, busAddr & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_UPPER_TARGET, (busAddr >> 32) & 0xFFFFFFFF);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_REGION_CTRL1, type);
    PCIE_DbiWritel(pcie, off + PCIE_ATU_UNR_REGION_CTRL2, PCIE_ATU_ENABLE);
    for (i = 0; i < 5000; i++) {
        val = PCIE_DbiReadl(pcie, off + PCIE_ATU_UNR_REGION_CTRL2);
        if (val & PCIE_ATU_ENABLE) {
            return HAL_OK;
        }
        HAL_DelayUs(LINK_WAIT_IATU);
    }

    return HAL_ERROR;
}

/**
 * @brief  Setting PCIe config space outbound atu.
 * @param  pcie: PCIe host.
 * @param  dev: pci device.
 * @param  size: atu size.
 * @return -1 - fail, >= 0 return the atu index.
 */
int32_t HAL_PCIE_OutboundConfigCFG0(struct HAL_PCIE_HANDLE *pcie, HAL_PCI_DevT dev, uint32_t size)
{
    int32_t index;
    int b = PCI_BUS(dev) - pcie->dev->firstBusNo;
    int df;

    index = PCIE_GetFreeOutboundAtu(pcie);
    if (index < 0) {
        return -1;
    }

    df = PCI_MASK_BUS(dev);
    dev = PCI_ADD_BUS(b, df);
    HAL_PCIE_OutboundConfig(pcie, index, PCIE_ATU_TYPE_CFG0, pcie->dev->cfgBase, dev << 8, size);

    return index;
}

/**
 * @brief  Enable client elbi index 0 interrupt.
 * @param  pcie: PCIe host.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_EnableELBIIndex0(struct HAL_PCIE_HANDLE *pcie)
{
    PCIE_ApbWritel(pcie, PCIE_CLIENT_INTR_MASK, 0x80000000);
    PCIE_DbiWritel(pcie, PCIE_ELBI_BASE + PCIE_ELBI_LOCAL_ENABLE_OFF, 0xffff0000);

    return HAL_OK;
}

/**
 * @brief  Enable client reset or link down interrupt.
 * @param  pcie: PCIe host.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_EnableRstInt(struct HAL_PCIE_HANDLE *pcie)
{
    PCIE_ApbWritel(pcie, PCIE_CLIENT_INTR_MASK, 0x40000);

    return HAL_OK;
}

/**
 * @brief  Set BAR.
 * @param  pcie: PCIe host.
 * @param  barno: bar number.
 * @param  flags: bar flags.
 * @param  log2: bar size(MB) in log2.
 * @return HAL_Status.
 */
HAL_Status HAL_PCIE_SetBar(struct HAL_PCIE_HANDLE *pcie, uint32_t barno, int flags, int log2)
{
    uint32_t reg, resizeBase;

    PCIE_EnableDbiWrite(pcie);

    reg = PCI_BASE_ADDRESS_0 + (4 * barno);

    /* Disabled the upper 32bits BAR to make a 64bits bar pair */
    if (flags & PCI_BASE_ADDRESS_MEM_TYPE_64) {
        PCIE_DbiWritel(pcie, reg + 4, 0);
    }

    PCIE_DbiWritel(pcie, reg, flags);
    if (flags & PCI_BASE_ADDRESS_MEM_TYPE_64) {
        PCIE_DbiWritel(pcie, reg + 4, 0);
    }

    resizeBase = pcie->dev->resbarBase;
    PCIE_DbiWritel(pcie, resizeBase + 0x4 + barno * 0x8, (1 << log2) << 4);
    PCIE_DbiWritel(pcie, resizeBase + 0x8 + barno * 0x8, (log2 << 8) | 0xc0);

    PCIE_DisableDbiWrite(pcie);

    return HAL_OK;
}

HAL_Status HAL_PCIE_DisableBar(struct HAL_PCIE_HANDLE *pcie, uint32_t barno)
{
    PCIE_EnableDbiWrite(pcie);
    PCIE_DbiWritel(pcie, PCIE_TYPE0_HDR_DBI2_OFFSET + 0x10 + barno * 4, 0);
    PCIE_DisableDbiWrite(pcie);

    return HAL_OK;
}

/** @} */

/** @} */

/** @} */

#endif /* HAL_PCIE_MODULE_ENABLED */
