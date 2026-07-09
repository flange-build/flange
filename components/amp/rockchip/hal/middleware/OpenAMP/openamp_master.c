/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#include "openamp.h"
#include "rsc_table.h"
#include "metal/sys.h"
#include "metal/device.h"

static int err_cnt;
static struct rpmsg_endpoint lept;
static int rnum = 0;
static int err_cnt = 0;
static int ept_deleted = 0;
extern struct rpmsg_virtio_device rvdev;

static int rpmsg_endpoint_cb(struct rpmsg_endpoint *ept, void *data, size_t len,
			     uint32_t src, void *priv)
{
    char payload[RPMSG_BUFFER_SIZE];
    char seed[20];

    (void)ept;
    (void)src;
    (void)priv;

    memset(payload, 0, RPMSG_BUFFER_SIZE);
    memcpy(payload, data, len);
    LPRINTF("received message %d: %s of size %lu \r\n",
            rnum + 1, payload, (unsigned long)len);

    if (rnum == (MSG_LIMIT - 1))
        sprintf (seed, "%s", BYE_MSG);
    else
        sprintf (seed, "%s", HELLO_MSG);

    LPRINTF(" seed %s: \r\n", seed);

    if (strncmp(payload, seed, len)) {
        LPERROR(" Invalid message is received.\r\n");
                err_cnt++;
        return RPMSG_SUCCESS;
    }
    LPRINTF(" rnum %d: \r\n", rnum);
    rnum++;

    return RPMSG_SUCCESS;
}

static void rpmsg_service_unbind(struct rpmsg_endpoint *ept)
{
    (void)ept;
    rpmsg_destroy_ept(&lept);
    LPRINTF("echo test: service is destroyed\r\n");
    ept_deleted = 1;
}

static void rpmsg_name_service_bind_cb(struct rpmsg_device *rdev,
                                       const char *name, uint32_t dest)
{
    LPRINTF("new endpoint notification is received.\r\n");
    if (strcmp(name, RPMSG_SERV_NAME))
        LPERROR("Unexpected name service %s.\r\n", name);
    else
        (void)rpmsg_create_ept(&lept, rdev, RPMSG_SERV_NAME,
                               RPMSG_ADDR_ANY, dest,
                               rpmsg_endpoint_cb,
                               rpmsg_service_unbind);

}

int App_Master(struct rpmsg_device *rdev, void *priv)
{
    int ret;
    int i;

    LPRINTF(" 1 - Send data to remote core, retrieve the echo");
    LPRINTF(" and validate its integrity ..\r\n");

    /* Create RPMsg endpoint */
    ret = rpmsg_create_ept(&lept, rdev, RPMSG_SERV_NAME,
                           MASTER_CHANNEL1_SRC, MASTER_CHANNEL1_DEST,
                           rpmsg_endpoint_cb, rpmsg_service_unbind);

    if (ret) {
        LPERROR("Failed to create RPMsg endpoint.\r\n");
        return ret;
    }

    while (!is_rpmsg_ept_ready(&lept))
           OPENAMP_check_for_message();

    LPRINTF("RPMSG endpoint is binded with remote.\r\n");
    HAL_DelayMs(10);
    for (i = 1; i <= MSG_LIMIT; i++) {
        if (i < MSG_LIMIT)
            ret = rpmsg_send(&lept, HELLO_MSG, strlen(HELLO_MSG));
        else
            ret = rpmsg_send(&lept, BYE_MSG, strlen(BYE_MSG));

        if (ret < 0) {
            LPERROR("Failed to send data...\r\n");
            break;
        }
        LPRINTF("rpmsg sample test: message %d sent\r\n", i);

        do {
            OPENAMP_check_for_message();
        } while ((rnum < i) && !err_cnt);

    }

    LPRINTF("**********************************\r\n");
    LPRINTF(" Test Results: Error count = %d\r\n", err_cnt);
    LPRINTF("**********************************\r\n");
    while (!ept_deleted)
        OPENAMP_check_for_message();
    LPRINTF("Quitting application .. rpmsg sample test end\r\n");

    return 0;
}

void OPENAMP_Master_Ping(void)
{
    if (HAL_CPU_TOPOLOGY_GetCurrentCpuId() == RPMSG_MASTER) {
        MX_OPENAMP_Init(RPMSG_MASTER, NULL);
        App_Master(&rvdev.rdev, rpmsg_name_service_bind_cb);
    }
}
