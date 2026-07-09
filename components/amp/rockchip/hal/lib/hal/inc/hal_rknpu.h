/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 */

#include "hal_conf.h"

#ifdef HAL_RKNPU_MODULE_ENABLED

/** @addtogroup RK_HAL_Driver
 *  @{
 */

/** @addtogroup RKNPU
 *  @{
 */

#ifndef _HAL_RKNPU_H_
#define _HAL_RKNPU_H_

#include "hal_def.h"

/***************************** MACRO Definition ******************************/
/** @defgroup RKNPU_Exported_Definition_Group1 Basic Definition
 *  @{
 */

/***************************** Structure Definition **************************/

/**
 * @brief  job mode definitions.
 */
typedef enum HAL_RKNPU_JOB_MODE {
    HAL_RKNPU_JOB_SLAVE     = 0 << 0,
    HAL_RKNPU_JOB_PC        = 1 << 0,
    HAL_RKNPU_JOB_BLOCK     = 0 << 1,
    HAL_RKNPU_JOB_NONBLOCK  = 1 << 1,
    HAL_RKNPU_JOB_PINGPONG  = 1 << 2,
    HAL_RKNPU_JOB_FENCE_IN  = 1 << 3,
    HAL_RKNPU_JOB_FENCE_OUT = 1 << 4,
    HAL_RKNPU_JOB_MASK      = HAL_RKNPU_JOB_PC | HAL_RKNPU_JOB_NONBLOCK |
                              HAL_RKNPU_JOB_PINGPONG | HAL_RKNPU_JOB_FENCE_IN |
                              HAL_RKNPU_JOB_FENCE_OUT
} eRKNPU_JobMode;

/**
 * @brief  RKNPU configuration structure
 */
struct HAL_RKNPU_CONFIG {
    uint32_t bwPriorityAddr;
    uint32_t bwPriorityLength;
    uint32_t dmaMask;
    uint32_t pcDataAmountScale;
    uint32_t pcTaskNumberBits;
    uint32_t pcTaskNumberMask;
    uint32_t pcTaskStatusOffset;
    uint32_t pcDmaCtrl;
    uint32_t bwEnable;
    int32_t numIrqs;
    uint32_t nbufPhyaddr;
    uint32_t nbufSize;
    uint32_t maxSubmitNumber;
    uint32_t coreMask;
};

/**
 * @brief RKNPU task structure
 */
struct HAL_RKNPU_TASK {
    uint32_t flags;
    uint32_t opIdx;
    uint32_t enableMask;
    uint32_t intMask;
    uint32_t intClear;
    uint32_t intStatus;
    uint32_t regcfgAmount;
    uint32_t regcfgOffset;
    uint64_t regcmdAddr;
};

/**
 * @brief RKNPU task submit structure
 */
struct HAL_RKNPU_SUBMIT {
    uint32_t flags;
    uint32_t timeout;
    uint32_t taskStart;
    uint32_t taskNumber;
    uint32_t taskCounter;
    int32_t priority;
    uint64_t taskObjAddr;
    uint64_t regcfgObjAddr;
    uint64_t taskBaseAddr;
    int64_t hwElapseTime;
    struct HAL_RKNPU_TASK task;
};

/**
 * @brief RKNPU device structure
 */
struct HAL_RKNPU_DEV {
    struct RKNPU_REG *pReg;     /* NPU 寄存器基地址 */
    uint32_t irqNum;            /* NPU 中断号 */
    uint32_t aclkRate;          /* NPU ACLK时钟 */
    uint32_t hclkRate;          /* NPU HCLK时钟 */
#if defined(HAL_PD_MODULE_ENABLED)
    uint32_t pdDomain;          /* NPU 电源域 */
#endif
    struct HAL_RKNPU_CONFIG config;
    int32_t intStatus;
    int32_t intMask;
    volatile uint32_t isBusy;
};

/** @} */
/***************************** Function Declare ******************************/
/** @defgroup RKNPU_Public_Function_Declare Public Function Declare
 *  @{
 */

HAL_Status HAL_RKNPU_Init(struct HAL_RKNPU_DEV *rknpu);
HAL_Status HAL_RKNPU_DeInit(struct HAL_RKNPU_DEV *rknpu);
HAL_Status HAL_RKNPU_PowerOn(struct HAL_RKNPU_DEV *rknpu);
HAL_Status HAL_RKNPU_PowerOff(struct HAL_RKNPU_DEV *rknpu);
HAL_Status HAL_RKNPU_Submit(struct HAL_RKNPU_DEV *rknpu, struct HAL_RKNPU_SUBMIT *submit);
HAL_Status HAL_RKNPU_DevIrqHandler(struct HAL_RKNPU_DEV *rknpu);
HAL_Status HAL_RKNPU_Configure(struct HAL_RKNPU_DEV *rknpu,
                               const struct HAL_RKNPU_CONFIG *config);
HAL_Status HAL_RKNPU_Reset(struct HAL_RKNPU_DEV *rknpu);

HAL_Status HAL_RKNPU_GetHwVersion(struct HAL_RKNPU_DEV *rknpu, uint32_t *version);
HAL_Status HAL_RKNPU_GetDrvVersion(struct HAL_RKNPU_DEV *rknpu, uint32_t *version);
HAL_Status HAL_RKNPU_DataRWAmount(struct HAL_RKNPU_DEV *rknpu, uint32_t *dt_wr,
                                  uint32_t *dt_rd, uint32_t *wd_rd);
/** @} */

#endif

/** @} */

/** @} */
#endif
