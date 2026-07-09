/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#ifndef _HAL_MAILBOX_H_
#define _HAL_MAILBOX_H_

#include "hal_def.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MBOX_CHANNEL_1         0x00000000U
#define MBOX_CHANNEL_2         0x00000001U
#define MBOX_CHANNEL_3         0x00000002U
#define MBOX_CHANNEL_4         0x00000003U
#define MBOX_CHANNEL_NUMBER    4U
#define HAL_StatusTypeDef      HAL_Status
#define __IO    volatile

#define UNUSED(X) (void)X      /* To avoid gcc/g++ warnings */
#define assert_param(expr)     ((void)0U)
#define MBOX                   ((struct MBOX_REG *) MBOX0_BASE)

typedef enum
{
    HAL_MBOX_STATE_RESET             = 0x00U,  /*!< MBOX not yet initialized or disabled  */
    HAL_MBOX_STATE_READY             = 0x01U,  /*!< MBOX initialized and ready for use    */
    HAL_MBOX_STATE_BUSY              = 0x02U   /*!< MBOX internal processing is ongoing   */
} HAL_MBOX_StateTypeDef;


typedef enum
{
    MBOX_CHANNEL_DIR_TX  = 0x00U,  /*!< Channel direction Tx is used by an MCU to transmit */
    MBOX_CHANNEL_DIR_RX  = 0x01U   /*!< Channel direction Rx is used by an MCU to receive */
} MBOX_CHANNELDirTypeDef;

typedef enum
{
    MBOX_CHANNEL_STATUS_FREE       = 0x00U,  /*!< Means that a new msg can be posted on that channel */
    MBOX_CHANNEL_STATUS_OCCUPIED   = 0x01U   /*!< An MCU has posted a msg the other MCU hasn't retrieved */
} MBOX_CHANNELStatusTypeDef;

typedef struct __MBOX_HandleTypeDef
{
    struct MBOX_REG *Instance;     /*!< MBOX registers base address */
    void (* ChannelCallbackRx[MBOX_CHANNEL_NUMBER])(struct __MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);                            /*!< Rx Callback registration table */
    void (* ChannelCallbackTx[MBOX_CHANNEL_NUMBER])(struct __MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);                            /*!< Tx Callback registration table */
    uint32_t                       callbackRequest; /*!< Store information about callback notification by channel */
    __IO HAL_MBOX_StateTypeDef      State;         /*!< MBOX State: initialized or not */
} MBOX_HandleTypeDef;

extern MBOX_HandleTypeDef hmbox;

typedef void ChannelCb(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);

HAL_StatusTypeDef HAL_MBOX_ActivateNotification(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir, ChannelCb cb);
HAL_StatusTypeDef HAL_MBOX_DeActivateNotification(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
MBOX_CHANNELStatusTypeDef HAL_MBOX_GetChannelStatus(MBOX_HandleTypeDef const *const hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
HAL_StatusTypeDef HAL_MBOX_NotifyCPU(MBOX_HandleTypeDef const *const hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
HAL_MBOX_StateTypeDef HAL_MBOX_GetState(MBOX_HandleTypeDef const *const hmbox);
HAL_StatusTypeDef HAL_MAILBOX_Init(MBOX_HandleTypeDef *hmbox, int channel);

HAL_Status HAL_MBOX_TX_IRQHandler(uint32_t irq, void *args);
HAL_Status HAL_MBOX_RX_IRQHandler(uint32_t irq, void *args);
void HAL_MBOX_TxCallback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
void HAL_MBOX_RxCallback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);

#ifdef __cplusplus
}
#endif

#endif