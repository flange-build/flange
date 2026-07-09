/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 */

#include "hal_base.h"

#ifdef HAL_RKNPU_MODULE_ENABLED
#include "hal_rknpu.h"

/** @addtogroup RK_HAL_Driver
 *  @{
 */

/** @addtogroup RKNPU
 *  @{
 */

/** @defgroup RKNPU_How_To_Use How To Use
 *  @{

 The RKNPU driver can be used as follows:

 1. Initialize the RKNPU device:
    - Call HAL_RKNPU_Init() to initialize the RKNPU device
    - Call HAL_RKNPU_Configure() to configure the device with proper settings
    - Register interrupt handler if needed

 2. Power management:
    - Call HAL_RKNPU_PowerOn() to power on the RKNPU device
    - Call HAL_RKNPU_PowerOff() to power off when done

 3. Task submission:
    - Prepare HAL_RKNPU_SUBMIT structure with task information
    - Call HAL_RKNPU_Submit() to submit tasks to RKNPU
    - Wait for task completion through interrupt or timeout

 4. Other operations:
    - HAL_RKNPU_GetHwVersion() to get hardware version
    - HAL_RKNPU_GetDrvVersion() to get driver version
    - HAL_RKNPU_DataRWAmount() to get data R/W statistics

 5. Cleanup:
    - Call HAL_RKNPU_DeInit() to deinitialize the device

 For implementation example, please refer to components/hifi4/dsp/drivers/npu/drv_rknpu/drv_rknpu.c.

 @} */

/** @defgroup RKNPU_Private_Definition Private Definition
 *  @{
 */
/********************* Private MACRO Definition ******************************/

#define HAL_RKNPU_DRIVER_MAJOR      0
#define HAL_RKNPU_DRIVER_MINOR      8
#define HAL_RKNPU_DRIVER_PATCHLEVEL 0

#define HAL_RKNPU_CORE_BASE_ADDR 0x50C80000
#define HAL_RKNPU_RESET_ADDR     0x50C90008

#define HAL_RKNPU_ALIGN_SIZE 64

#define HAL_RKNPU_OFFSET_VERSION          0x0
#define HAL_RKNPU_OFFSET_VERSION_NUM      0x4
#define HAL_RKNPU_OFFSET_PC_OP_EN         0x8
#define HAL_RKNPU_OFFSET_PC_DATA_ADDR     0x10
#define HAL_RKNPU_OFFSET_PC_DATA_AMOUNT   0x14
#define HAL_RKNPU_OFFSET_PC_TASK_CONTROL  0x30
#define HAL_RKNPU_OFFSET_PC_DMA_BASE_ADDR 0x34

#define HAL_RKNPU_OFFSET_INT_MASK       0x20
#define HAL_RKNPU_OFFSET_INT_CLEAR      0x24
#define HAL_RKNPU_OFFSET_INT_STATUS     0x28
#define HAL_RKNPU_OFFSET_INT_RAW_STATUS 0x2c

#define HAL_RKNPU_OFFSET_CLR_ALL_RW_AMOUNT 0x2210
#define HAL_RKNPU_OFFSET_DT_WR_AMOUNT      0x2234
#define HAL_RKNPU_OFFSET_DT_RD_AMOUNT      0x2238
#define HAL_RKNPU_OFFSET_WT_RD_AMOUNT      0x223c

#define HAL_RKNPU_OFFSET_ENABLE_MASK 0xf008

#define HAL_RKNPU_INT_CLEAR 0x1ffff

#define HAL_RKNPU_PC_DATA_EXTRA_AMOUNT 4

#define HAL_RKNPU_TIMEOUT_INFINITE 0xFFFFFFFF

#define HAL_RKNPU_STR_HELPER(x) #x

#define HAL_RKNPU_GET_DRV_VERSION_STRING(MAJOR, MINOR, PATCHLEVEL) \
    HAL_RKNPU_STR_HELPER(MAJOR)                                    \
    "." HAL_RKNPU_STR_HELPER(MINOR) "." HAL_RKNPU_STR_HELPER(PATCHLEVEL)
#define HAL_RKNPU_GET_DRV_VERSION_CODE(MAJOR, MINOR, PATCHLEVEL) \
    (MAJOR * 10000 + MINOR * 100 + PATCHLEVEL)
#define HAL_RKNPU_GET_DRV_VERSION_MAJOR(CODE)      (CODE / 10000)
#define HAL_RKNPU_GET_DRV_VERSION_MINOR(CODE)      ((CODE % 10000) / 100)
#define HAL_RKNPU_GET_DRV_VERSION_PATCHLEVEL(CODE) (CODE % 100)
/********************* Private Structure Definition **************************/

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ***************************/

/**
 * @brief  rknpu fuzz status
 * @param  status: the status to fuzz
 * @return fuzz status
 */
static uint32_t HAL_RKNPU_FuzzStatus(uint32_t status)
{
    uint32_t fuzz_status = 0;

    if ((status & 0x3) != 0) {
        fuzz_status |= 0x3;
    }

    if ((status & 0xc) != 0) {
        fuzz_status |= 0xc;
    }

    if ((status & 0x30) != 0) {
        fuzz_status |= 0x30;
    }

    if ((status & 0xc0) != 0) {
        fuzz_status |= 0xc0;
    }

    if ((status & 0x300) != 0) {
        fuzz_status |= 0x300;
    }

    if ((status & 0xc00) != 0) {
        fuzz_status |= 0xc00;
    }

    return fuzz_status;
}

/**
 * @brief  Reset rknpu device.
 * @param  rknpu: The handle of struct rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_Reset(struct HAL_RKNPU_DEV *rknpu)
{
    HAL_ASSERT(rknpu != NULL);

    // 软复位NPU
    WRITE_REG(rknpu->pReg->PC_OP_EN, 0x0);
    // 清除所有中断
    WRITE_REG(rknpu->pReg->INT_CLEAR, HAL_RKNPU_INT_CLEAR);
    // 清除数据统计
    WRITE_REG(rknpu->pReg->CLR_ALL_RW_AMOUNT, 0x1);

    return HAL_OK;
}

/** @} */

/********************* Public Function Definition ****************************/

/** @defgroup RKNPU_Exported_Functions_Group1 Init and DeInit

  This section provides functions allowing to init and deinit the module:

  *  @{
  */

/**
 * @brief  Init rknpu.
 * @param  rknpu: The handle of struct rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_Init(struct HAL_RKNPU_DEV *rknpu)
{
    rknpu->aclkRate = 0;
    rknpu->hclkRate = 0;

#if defined(HAL_PD_MODULE_ENABLED)
    rknpu->pdDomain = PD_NPU;
#endif

    rknpu->irqNum = NPU_IRQn;

    return HAL_OK;
}

/**
 * @brief  DeInit rknpu.
 * @param  rknpu: The handle of struct rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_DeInit(struct HAL_RKNPU_DEV *rknpu)
{
    return HAL_OK;
}

/** @} */

/** @defgroup RKNPU_Exported_Functions_Group2 Configure
 *  @{
 */

/**
 * @brief  Configure rknpu device.
 * @param  rknpu: The handle of struct rknpu.
 * @param  config: The configuration to apply
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_Configure(struct HAL_RKNPU_DEV *rknpu,
                               const struct HAL_RKNPU_CONFIG *config)
{
    if (!rknpu || !config) {
        return HAL_INVAL;
    }

    // 复制配置
    memcpy(&rknpu->config, config, sizeof(struct HAL_RKNPU_CONFIG));

    return HAL_OK;
}

/** @} */

/** @defgroup RKNPU_Exported_Functions_Group3 IRQ Handler
 *  @{
 */

/**
 * @brief  rknpu irq handler
 * @param  rknpu: the handle of rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_DevIrqHandler(struct HAL_RKNPU_DEV *rknpu)
{
    struct RKNPU_REG *pReg;
    uint32_t irqStatus;
    HAL_Status ret = HAL_OK;

    if (!rknpu) {
        return HAL_INVAL;
    }

    pReg = rknpu->pReg;
    if (!IS_RKNPU_INSTANCE(pReg)) {
        return HAL_INVAL;
    }

    // 读取并清除中断状态
    irqStatus = READ_REG(pReg->INT_STATUS);

    // 检查中断状态是否合法
    if (HAL_RKNPU_FuzzStatus(irqStatus) != rknpu->intMask) {
        HAL_DBG_ERR("rknpu: %s: invalid irq status: 0x%lx, raw status: 0x%lx, required mask: 0x%lx\n",
                    __func__, irqStatus, READ_REG(pReg->INT_RAW_STATUS), rknpu->intMask);
    }

    WRITE_REG(pReg->INT_CLEAR, HAL_RKNPU_INT_CLEAR);

    // 保存中断状态
    rknpu->intStatus = irqStatus;

    // 清除忙标志
    rknpu->isBusy = 0;

    return ret;
}

/** @} */

/** @defgroup RKNPU_Exported_Functions_Group4 Submit Task
 *  @{
 */

/**
 * @brief submit task to rknpu
 * @param rknpu: the handle of rknpu
 * @param submit: the task to submit
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_Submit(struct HAL_RKNPU_DEV *rknpu, struct HAL_RKNPU_SUBMIT *submit)
{
    struct RKNPU_REG *pReg;
    struct HAL_RKNPU_TASK *taskBase;
    struct HAL_RKNPU_TASK *firstTask;
    struct HAL_RKNPU_TASK *lastTask;
    uint32_t timeout;
    uint32_t startTime;
    int taskStart, taskNumber, taskEnd;
    int taskPpEn, pcDataAmountScale, pcTaskNumberBits;
    HAL_Status ret = HAL_OK;

    // 参数检查
    if (!rknpu || !submit) {
        return HAL_INVAL;
    }

    pReg = rknpu->pReg;
    if (!IS_RKNPU_INSTANCE(pReg)) {
        return HAL_INVAL;
    }

    timeout = submit->timeout;

    // 任务数量检查
    if (submit->taskNumber == 0) {
        HAL_DBG_ERR("rknpu: %s: task number is 0\n", __func__);

        return HAL_ERROR;
    }

    taskBase = (struct HAL_RKNPU_TASK *)(uintptr_t)submit->taskObjAddr;
    taskStart = submit->taskStart;
    taskNumber = submit->taskNumber;
    taskEnd = taskStart + taskNumber - 1;
    taskPpEn = submit->flags & HAL_RKNPU_JOB_PINGPONG ? 1 : 0;
    pcDataAmountScale = rknpu->config.pcDataAmountScale;
    pcTaskNumberBits = rknpu->config.pcTaskNumberBits;

    firstTask = &taskBase[taskStart];
    lastTask = &taskBase[taskEnd];

    WRITE_REG(pReg->PC_DATA_ADDR, 0x1);

    // 1. 配置任务命令地址
    WRITE_REG(pReg->PC_DATA_ADDR, firstTask->regcmdAddr);

    // 2. 配置数据量
    WRITE_REG(pReg->PC_DATA_AMOUNT,
              (firstTask->regcfgAmount + HAL_RKNPU_PC_DATA_EXTRA_AMOUNT + pcDataAmountScale - 1) / pcDataAmountScale - 1);

    // 3. 配置中断掩码
    WRITE_REG(pReg->INT_MASK, lastTask->intMask);
    WRITE_REG(pReg->INT_CLEAR, firstTask->intMask);

    // 4. 配置任务控制
    WRITE_REG(pReg->PC_TASK_CONTROL, ((0x6 | taskPpEn) << pcTaskNumberBits) | taskNumber);

    // 5. 配置DMA基地址
    WRITE_REG(pReg->PC_DMA_BASE_ADDR, submit->taskBaseAddr);

    rknpu->intMask = lastTask->intMask;

    // 6. 启动任务
    WRITE_REG(pReg->PC_OP_EN, 0x1);
    WRITE_REG(pReg->PC_OP_EN, 0x0);

    // 设置忙标志
    rknpu->isBusy = 1;

    // 等待直到设备不忙
    startTime = HAL_GetTick();
    while (rknpu->isBusy) {
        // 检查是否超时
        if (timeout != HAL_RKNPU_TIMEOUT_INFINITE &&
            HAL_GetTick() - startTime >= timeout) {
            HAL_DBG_ERR("rknpu: device busy timeout after %" PRIu32 "ms\n", timeout);
            ret = HAL_TIMEOUT;
            break;
        }
    }

    // 超时时强制复位NPU
    if (ret == HAL_TIMEOUT) {
        HAL_RKNPU_Reset(rknpu);
    }

    return ret;
}

/** @} */

/** @defgroup RKNPU_Exported_Functions_Group5 Power Control
 *  @{
 */

/**
 * @brief  PowerON rknpu.
 * @param  rknpu: The handle of struct rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_PowerOn(struct HAL_RKNPU_DEV *rknpu)
{
    HAL_Status ret;

    HAL_CRU_ClkEnable((uint32_t)rknpu->aclkRate);
    HAL_CRU_ClkEnable((uint32_t)rknpu->hclkRate);

#if defined(HAL_PD_MODULE_ENABLED)
    ret = HAL_PD_On(PD_NPU);
    if (ret != HAL_OK) {
        goto err_pd;
    }
#endif

    // 上电后复位
    ret = HAL_RKNPU_Reset(rknpu);
    if (ret != HAL_OK) {
        goto err_reset;
    }

    return HAL_OK;

err_reset:
#if defined(HAL_PD_MODULE_ENABLED)
    HAL_PD_Off(PD_NPU);
err_pd:
#endif
    HAL_CRU_ClkDisable((uint32_t)rknpu->hclkRate);
    HAL_CRU_ClkDisable((uint32_t)rknpu->aclkRate);

    return ret;
}

/**
 * @brief  Poweroff rknpu.
 * @param  rknpu: The handle of struct rknpu.
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_PowerOff(struct HAL_RKNPU_DEV *rknpu)
{
#if defined(HAL_PD_MODULE_ENABLED)
    HAL_PD_Off(PD_NPU);
#endif
    HAL_CRU_ClkDisable((uint32_t)rknpu->hclkRate);
    HAL_CRU_ClkDisable((uint32_t)rknpu->aclkRate);

    return HAL_OK;
}

/** @} */

/** @defgroup RKNPU_Exported_Functions_Group6 Other Functions
 *  @{
 */

/**
 * @brief  Get hardware version
 * @param  rknpu: The handle of struct rknpu.
 * @param  version: Pointer to store version
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_GetHwVersion(struct HAL_RKNPU_DEV *rknpu, uint32_t *version)
{
    if (!rknpu || !version) {
        return HAL_INVAL;
    }

    if (!IS_RKNPU_INSTANCE(rknpu->pReg)) {
        return HAL_INVAL;
    }

    *version = READ_REG(rknpu->pReg->VERSION);

    return HAL_OK;
}

/**
 * @brief  Get data read/write amount statistics
 * @param  rknpu: The handle of struct rknpu.
 * @param  dt_wr: Pointer to store data write amount
 * @param  dt_rd: Pointer to store data read amount
 * @param  wd_rd: Pointer to store weight read amount
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_DataRWAmount(struct HAL_RKNPU_DEV *rknpu, uint32_t *dt_wr,
                                  uint32_t *dt_rd, uint32_t *wd_rd)
{
    struct RKNPU_REG *pReg;

    // 参数合法性检查
    if (!rknpu || !dt_wr || !dt_rd || !wd_rd) {
        return HAL_INVAL;
    }

    pReg = rknpu->pReg;
    if (!IS_RKNPU_INSTANCE(pReg)) {
        return HAL_INVAL;
    }

    // 读取数据
    *dt_wr = READ_REG(pReg->DT_WR_AMOUNT);
    *dt_rd = READ_REG(pReg->DT_RD_AMOUNT);
    *wd_rd = READ_REG(pReg->WT_RD_AMOUNT);

    return HAL_OK;
}

/**
 * @brief  Get driver version
 * @param  rknpu: The handle of struct rknpu.
 * @param  version: Pointer to store version
 * @return HAL_Status
 */
HAL_Status HAL_RKNPU_GetDrvVersion(struct HAL_RKNPU_DEV *rknpu, uint32_t *version)
{
    HAL_ASSERT(rknpu != NULL);
    HAL_ASSERT(version != NULL);

    *version = HAL_RKNPU_GET_DRV_VERSION_CODE(HAL_RKNPU_DRIVER_MAJOR, HAL_RKNPU_DRIVER_MINOR,
                                              HAL_RKNPU_DRIVER_PATCHLEVEL);

    return HAL_OK;
}

/** @} */

/** @} */

/** @} */

#endif /* HAL_RKNPU_MODULE_ENABLED */
