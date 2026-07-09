/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#ifndef __openamp_H
#define __openamp_H
#ifdef __cplusplus
 extern "C" {
#endif

#include "openamp/open_amp.h"
#include "openamp_conf.h"
#include "hal_base.h"

#define SHM_DEVICE_NAME "RK_SHM"
#define RPMSG_SERV_NAME "rpmsg-client-sample"
#define MSG_LIMIT       100
#define HELLO_MSG       "hello world!"
#define BYE_MSG         "goodbye!"
#define LPRINTF(format, ...) printf(format, ##__VA_ARGS__)
#define LPERROR(format, ...) LPRINTF("ERROR: " format, ##__VA_ARGS__)

#define OPENAMP_send  rpmsg_send
#define OPENAMP_destroy_ept rpmsg_destroy_ept

/* Initialize the openamp framework*/
int MX_OPENAMP_Init(int RPMsgRole, rpmsg_ns_bind_cb ns_bind_cb);
/* Create and register the endpoint */
int OPENAMP_create_endpoint(struct rpmsg_endpoint *ept, const char *name,
                            uint32_t dest, rpmsg_ept_cb cb,
                            rpmsg_ns_unbind_cb unbind_cb);
/* Check for new rpmsg reception */
void OPENAMP_check_for_message(void);
int OPENAMP_Init(void);
void OPENAMP_Slave_Echo(void);
void OPENAMP_Master_Ping(void);

#ifdef __cplusplus
}
#endif

#endif
