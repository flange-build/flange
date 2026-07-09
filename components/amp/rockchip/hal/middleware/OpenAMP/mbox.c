/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#include "openamp/open_amp.h"
#include "openamp_conf.h"
#include <hal_mailbox.h>

#define MASTER_CPU_ID    0
#define REMOTE_CPU_ID    1
#define RX_NO_MSG        0
#define RX_NEW_MSG       1
#define RX_BUF_FREE      2

extern MBOX_HandleTypeDef hmbox;
int msg_received_ch1 = RX_NO_MSG;
int msg_received_ch2 = RX_NO_MSG;
uint32_t vring0_id = 0; /* used for channel 1 */
uint32_t vring1_id = 1; /* used for channel 2 */

void MBOX_channel1_callback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);
void MBOX_channel2_callback(MBOX_HandleTypeDef *hmbox, uint32_t ChannelIndex, MBOX_CHANNELDirTypeDef ChannelDir);

int MAILBOX_Init(void)
{
    if (HAL_MBOX_ActivateNotification(&hmbox, MBOX_CHANNEL_1, MBOX_CHANNEL_DIR_RX,
                                      MBOX_channel1_callback) != HAL_OK) {
	      OPENAMP_log_err("%s: ch_1 RX fail\n", __func__);
        return -1;
    }

    if (HAL_MBOX_ActivateNotification(&hmbox, MBOX_CHANNEL_2, MBOX_CHANNEL_DIR_RX,
                                      MBOX_channel2_callback) != HAL_OK) {
	      OPENAMP_log_err("%s: ch_2 RX fail\n", __func__);
        return -1;
    }

    return 0;
}

int MAILBOX_Poll(struct virtio_device *vdev)
{
    if (msg_received_ch1 == RX_BUF_FREE) {
        rproc_virtio_notified(vdev, VRING0_ID);
        msg_received_ch1 = RX_NO_MSG;
        return 0;
    }

    if (msg_received_ch2 == RX_NEW_MSG) {
        rproc_virtio_notified(vdev, VRING1_ID);
        msg_received_ch2 = RX_NO_MSG;

        /* The OpenAMP framework does not notify for free buf: do it here */
        rproc_virtio_notified(NULL, VRING1_ID);
        return 0;
    }

    return -1;
}

int MAILBOX_Notify(void *priv, uint32_t id)
{
    uint32_t channel;
    (void)priv;

    /* Called after virtqueue processing: time to inform the remote */
    if (id == VRING0_ID) {
        channel = MBOX_CHANNEL_1;
        log_dbg("Send msg on ch_1\r\n");
    } else if (id == VRING1_ID) {
        /* Note: the OpenAMP framework never notifies this */
        channel = MBOX_CHANNEL_2;
        log_dbg("Send 'buff free' on ch_2\r\n");
    } else {
        log_dbg("invalid vring (%d)\r\n", (int)id);
        return -1;
    }

    /* Check that the channel is free (otherwise wait until it is) */
    if (HAL_MBOX_GetChannelStatus(&hmbox, channel, MBOX_CHANNEL_DIR_TX) == MBOX_CHANNEL_STATUS_OCCUPIED) {
        log_dbg("Waiting for channel to be freed\r\n");
        while (HAL_MBOX_GetChannelStatus(&hmbox, channel, MBOX_CHANNEL_DIR_TX) == MBOX_CHANNEL_STATUS_OCCUPIED)
            ;
    }

    HAL_MBOX_NotifyCPU(&hmbox, channel, MBOX_CHANNEL_DIR_TX);

    return 0;
}

void MBOX_channel1_callback(MBOX_HandleTypeDef * hmbox, uint32_t ChannelIndex,
                            MBOX_CHANNELDirTypeDef ChannelDir)
{
    if (msg_received_ch1 != RX_NO_MSG)
        log_dbg("MBOX_channel1_callback: previous IRQ not treated (status = %d)\r\n", msg_received_ch1);

    msg_received_ch1 = RX_BUF_FREE;

    log_dbg("Ack 'buff free' message on ch1\r\n");
    HAL_MBOX_NotifyCPU(hmbox, ChannelIndex, MBOX_CHANNEL_DIR_RX);
}

/* Callback from MBOX Interrupt Handler: new message received from Master Processor */
void MBOX_channel2_callback(MBOX_HandleTypeDef * hmbox, uint32_t ChannelIndex,
                            MBOX_CHANNELDirTypeDef ChannelDir)
{
    if (msg_received_ch2 != RX_NO_MSG)
        log_dbg("MBOX_channel2_callback: previous IRQ not treated (status = %d)\r\n", msg_received_ch2);

    msg_received_ch2 = RX_NEW_MSG;
    log_dbg("Ack new message on ch2\r\n");
    HAL_MBOX_NotifyCPU(hmbox, ChannelIndex, MBOX_CHANNEL_DIR_RX);
}
