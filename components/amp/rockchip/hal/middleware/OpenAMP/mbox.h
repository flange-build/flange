/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#ifndef MBOX_H_
#define MBOX_H_

int MAILBOX_Notify(void *priv, uint32_t id);
int MAILBOX_Init(void);
int MAILBOX_Poll(struct virtio_device *vdev);

#endif
