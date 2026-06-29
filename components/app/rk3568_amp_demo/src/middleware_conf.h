/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 * rpmsg-lite 中间件配置（SDK init/platform/RK3568/rpmsg_init.c 等会引用）。
 * 取自 SDK project/rk3568/src/middleware_conf.h。本 demo 的 Linux↔AMP 通信
 * 不走这里的 rpmsg_init()（那是 AMP 核间），而是 main.c 直接用 rpmsg-lite API；
 * 但 SDK 的 rpmsg_init.c 仍被编译，故保留本头供其使用。
 */

#ifndef __MIDDLEWARE_CONF_H__
#define __MIDDLEWARE_CONF_H__

#define MASTER_ID   ((uint32_t)1)
#define REMOTE_ID_2 ((uint32_t)2)
#define REMOTE_ID_3 ((uint32_t)3)
#define REMOTE_ID_0 ((uint32_t)0)

/* RPMSG endpoint addr covert */
#define EPT_M2R_ADDR(addr) (addr + VRING_SIZE)   // master to remote covert
#define EPT_R2M_ADDR(addr) (addr - VRING_SIZE)   // remote to master covert

/* RPMSG ID Define */
#define EPT_M1R2_INIT 0UL
#define EPT_M1R3_INIT 0UL
#define EPT_M1R0_INIT 0UL

/* RPMSG API Functions */
void rpmsg_init(void);
#ifdef PRIMARY_CPU
struct rpmsg_lite_instance *rpmsg_master_get_instance(uint32_t master_id, uint32_t remote_id);
#else
struct rpmsg_lite_instance *rpmsg_remote_get_instance(uint32_t master_id, uint32_t remote_id);
#endif

#endif
