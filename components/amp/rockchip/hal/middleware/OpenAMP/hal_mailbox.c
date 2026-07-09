/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#include "hal_base.h"
#include "hal_mailbox.h"
#include "openamp_log.h"

void MBOX_MaskInterrupt(uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
void MBOX_UnmaskInterrupt(uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
void MBOX_SetDefaultCallbacks(MBOX_HandleTypeDef *hmbox);

HAL_StatusTypeDef HAL_MBOX_ActivateNotification(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir, ChannelCb cb)
{
    HAL_StatusTypeDef err = HAL_OK;

    /* Check the MBOX handle allocation */
    if (hmbox != NULL) {
        /* Check the parameters */
        assert_param(IS_MBOX_ALL_INSTANCE(hmbox->Instance));

        /* Check MBOX state */
        if (hmbox->State == HAL_MBOX_STATE_READY) {
            /* Set callback and register masking information */
            if (ChannelDir == MBOX_CHANNEL_DIR_TX)
            hmbox->ChannelCallbackTx[ChannelIndex] = cb;
        else
            hmbox->ChannelCallbackRx[ChannelIndex] = cb;
        } else {
            err = HAL_ERROR;
        }
    } else {
        err = HAL_ERROR;
    }

    return err;
}

MBOX_CHANNELStatusTypeDef HAL_MBOX_GetChannelStatus(MBOX_HandleTypeDef const *const hmbox,
                                                    uint32_t ChannelIndex,
                                                    MBOX_CHANNELDirTypeDef ChannelDir)
{
    return MBOX_CHANNEL_STATUS_FREE;
}

HAL_StatusTypeDef HAL_MBOX_NotifyCPU(MBOX_HandleTypeDef const *const hmbox, uint32_t ChannelIndex,
                                     MBOX_CHANNELDirTypeDef ChannelDir)
{
    HAL_StatusTypeDef err = HAL_OK;
    /*
     * Actual we enable the mailbox interrpt
     * here to notice cpu that the info is ready.
     * Now we only use the channel 0.
     * We can write any value in the cmd & data
     * register to enable the mailbox interrupt.
     * For MBOX_CHANNEL_DIR_TX, set the status.
     * For MBOX_CHANNEL_DIR_RX, clear the status.
     * Then how to known the notification type?
     * The 0 channel is the master, The 1 channel
     * is the slave. Then we transport the channel
     * to the other side.
     */
    log_dbg("%s: Cpuid is %d, ChannelIndex is %d, ChannelDir is %d\n",
            __func__, HAL_CPU_TOPOLOGY_GetCurrentCpuId(), ChannelIndex, ChannelDir);
    if (ChannelIndex == 0) {
        if (ChannelDir == MBOX_CHANNEL_DIR_TX) {
            hmbox->Instance->B2A[ChannelIndex].CMD = ChannelIndex;
            hmbox->Instance->B2A[ChannelIndex].DATA = ChannelIndex;
        } else {
            hmbox->Instance->A2B[ChannelIndex].CMD = ChannelIndex;
            hmbox->Instance->A2B[ChannelIndex].DATA = ChannelIndex;
        }
    } else if (ChannelIndex == 1) {
        if (ChannelDir == MBOX_CHANNEL_DIR_TX) {
            hmbox->Instance->A2B[ChannelIndex].CMD = ChannelIndex;
            hmbox->Instance->A2B[ChannelIndex].DATA = ChannelIndex;
        } else {
            hmbox->Instance->B2A[ChannelIndex].CMD = ChannelIndex;
            hmbox->Instance->B2A[ChannelIndex].DATA = ChannelIndex;
        }
    }

    return err;
}

HAL_Status HAL_MBOX_TX_IRQHandler(uint32_t irq, void *args)
{
    volatile uint32_t temp;
    uint32_t ch_count;
    MBOX_HandleTypeDef *mbox = &hmbox;

    log_dbg("%s: A2B_STATUS is %x, cpuid is %d, irq is %d\n",
            mbox->Instance->A2B_STATUS,
            HAL_CPU_TOPOLOGY_GetCurrentCpuId(), irq);

    temp = mbox->Instance->A2B_STATUS;
    mbox->Instance->A2B_STATUS = temp;
    switch (temp) {
    case 0x1:
        ch_count = 1;
        break;
    case 0x2:
        ch_count = 2;
        break;
    default:
        ch_count = 0;
        break;
    }

    if (ch_count) {
        if (mbox->ChannelCallbackTx[ch_count - 1] != NULL) {
            mbox->ChannelCallbackRx[ch_count - 1](mbox, ch_count - 1, MBOX_CHANNEL_DIR_RX);
        }
    }

    return HAL_OK;
}

extern int msg_received_ch2;
extern int msg_received_ch1;
HAL_Status HAL_MBOX_RX_IRQHandler(uint32_t irq, void *args)
{
    volatile uint32_t temp;
    uint32_t ch_count;
    MBOX_HandleTypeDef *mbox = &hmbox;

    log_dbg("%s: B2A_STATUS is %x, cpuid is %d, irq is %d\n",
            mbox->Instance->B2A_STATUS,
            HAL_CPU_TOPOLOGY_GetCurrentCpuId(), irq);
    temp = mbox->Instance->B2A_STATUS;
    mbox->Instance->B2A_STATUS = temp;
    switch (temp) {
    case 0x1:
        ch_count = 1;
        break;
    case 0x2:
        ch_count = 2;
        break;
    default:
        ch_count = 0;
        break;
    }

    if (ch_count)
        msg_received_ch1 = 2;

    return HAL_OK;
}

void HAL_MBOX_RxCallback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir)
{
    /* Prevent unused argument(s) compilation warning */
    UNUSED(hmbox);
    UNUSED(ChannelIndex);
    UNUSED(ChannelDir);
}

void HAL_MBOX_TxCallback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir)
{
    /* Prevent unused argument(s) compilation warning */
    UNUSED(hmbox);
    UNUSED(ChannelIndex);
    UNUSED(ChannelDir);
}

HAL_MBOX_StateTypeDef HAL_MBOX_GetState(MBOX_HandleTypeDef const *const hmbox)
{
    return hmbox->State;
}

void MBOX_MaskInterrupt(uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir)
{
    hmbox.Instance->A2B_INTEN = 0x0;
    hmbox.Instance->B2A_INTEN = 0x0;
}

void MBOX_UnmaskInterrupt(uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir)
{
    hmbox.Instance->A2B_INTEN = 0xf;
    hmbox.Instance->B2A_INTEN = 0xf;
}

/**
  * @brief Reset all callbacks of the handle to NULL.
  * @param  hmbox MBOX handle
  */
void MBOX_SetDefaultCallbacks(MBOX_HandleTypeDef *hmbox)
{
    uint32_t i;
    /* Set all callbacks to default */
    for (i = 0; i < MBOX_CHANNEL_NUMBER; i++) {
        hmbox->ChannelCallbackRx[i] = HAL_MBOX_RxCallback;
        hmbox->ChannelCallbackTx[i] = HAL_MBOX_TxCallback;
    }
}

HAL_StatusTypeDef HAL_MAILBOX_Init(MBOX_HandleTypeDef *hmbox, int channel)
{
    HAL_StatusTypeDef err = HAL_OK;

    if (hmbox != NULL) {
        /* Open the entire mailbox intterupt here */
        hmbox->Instance->A2B_INTEN = 0xf;
        hmbox->Instance->B2A_INTEN = 0xf;
        if (channel == 0) {
            HAL_IRQ_HANDLER_SetIRQHandler(MBOX0_CH0_A2B_IRQn, HAL_MBOX_RX_IRQHandler, NULL);
            HAL_GIC_Enable(MBOX0_CH0_A2B_IRQn);
            HAL_IRQ_HANDLER_SetIRQHandler(MBOX0_CH1_A2B_IRQn, HAL_MBOX_RX_IRQHandler, NULL);
            HAL_GIC_Enable(MBOX0_CH1_A2B_IRQn);
        } else if (channel == 1) {
            HAL_IRQ_HANDLER_SetIRQHandler(MBOX0_CH0_B2A_IRQn, HAL_MBOX_TX_IRQHandler, NULL);
            HAL_GIC_Enable(MBOX0_CH0_B2A_IRQn);
            HAL_IRQ_HANDLER_SetIRQHandler(MBOX0_CH1_B2A_IRQn, HAL_MBOX_TX_IRQHandler, NULL);
            HAL_GIC_Enable(MBOX0_CH1_B2A_IRQn);
        } else {
            err = HAL_ERROR;
        }

        MBOX_SetDefaultCallbacks(hmbox);
        /* Reset all callback notification request */
        hmbox->callbackRequest = 0;
        hmbox->State = HAL_MBOX_STATE_READY;
    }

    return err;
}
