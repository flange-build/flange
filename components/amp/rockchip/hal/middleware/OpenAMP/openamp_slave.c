/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#include "openamp.h"
#include "rsc_table.h"
#include "metal/sys.h"
#include "metal/device.h"

static struct rpmsg_endpoint lept;
static int shutdown_req = 0;
extern struct rpmsg_virtio_device rvdev;

/*-----------------------------------------------------------------------------*
 *  RPMSG endpoint callbacks
 *-----------------------------------------------------------------------------*/
static int rpmsg_endpoint_cb(struct rpmsg_endpoint *ept,
                             void *data, size_t len,
                             uint32_t src, void *priv)
{
    (void)priv;
    (void)src;
    static uint32_t count = 0;
    char payload[RPMSG_BUFFER_SIZE];

    /* Send data back MSG_LIMIT time to master */
    memset(payload, 0, RPMSG_BUFFER_SIZE);
    memcpy(payload, data, len);
    if (++count <= MSG_LIMIT) {
        LPRINTF("echo message number %u: %s\r\n",
        (unsigned int)count, payload);
        if (rpmsg_send(ept, (char *)data, len) < 0) {
            LPERROR("rpmsg_send failed\r\n");
            goto destroy_ept;
        }

        if (count == MSG_LIMIT) {
            goto destroy_ept;
        }
    }

    return RPMSG_SUCCESS;

destroy_ept:
    shutdown_req = 1;

    return RPMSG_SUCCESS;
}

static void rpmsg_service_unbind(struct rpmsg_endpoint *ept)
{
    (void)ept;
    LPRINTF("unexpected Remote endpoint destroy\r\n");
    shutdown_req = 1;
}

/*-----------------------------------------------------------------------------*
 *  Application
 *-----------------------------------------------------------------------------*/
int App_Slave(struct rpmsg_device *rdev, void *priv)
{
    int ret;

    /* Initialize RPMSG framework */
    LPRINTF("Try to create rpmsg endpoint.\r\n");

    ret = rpmsg_create_ept(&lept, rdev, RPMSG_SERV_NAME,
                           SLAVE_CHANNEL1_SRC, SLAVE_CHANNEL1_DEST,
                           rpmsg_endpoint_cb,
                           rpmsg_service_unbind);
    if (ret) {
        LPERROR("Failed to create endpoint.\r\n");
        return -1;
    }

    LPRINTF("Successfully created rpmsg endpoint.\r\n");
    while (1) {
        OPENAMP_check_for_message();
        /* we got a shutdown request, exit */
        if (shutdown_req) {
            break;
        }
    }

    rpmsg_destroy_ept(&lept);

    return 0;
}

void OPENAMP_Slave_Echo(void)
{
     if (HAL_CPU_TOPOLOGY_GetCurrentCpuId() == RPMSG_REMOTE) {
        MX_OPENAMP_Init(RPMSG_REMOTE, NULL);
        App_Slave(&rvdev.rdev, NULL);
     }
}
