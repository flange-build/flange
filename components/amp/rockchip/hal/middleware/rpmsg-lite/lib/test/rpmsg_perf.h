/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */
#ifndef _RPMSG_PERF_H_
#define _RPMSG_PERF_H_

#include "hal_conf.h"

/* TODO: Only one test can be selected at a time
 * Default: RPMSG_PERF_TEST_BANDWIDTH
 */
#define RPMSG_PERF_TEST_BANDWIDTH
//#define RPMSG_PERF_TEST_LATENCY

/* TODO: if test uncache RPMsg, packet loss is severe during continuous packet
 * sending and receiving tests, so please enable this configuration
 *
 * time compensation is (2 * RPMSG_PERF_TEST_COMPENSATION) us
 */
//#define RPMSG_PERF_TEST_COMPENSATION (500)

#ifdef RPMSG_PERF_TEST_COMPENSATION
/* Default: recv copy data 4960 KB */
#define RPMSG_PERF_TEST_LOOP (10U * 1024U)
#define RPMSG_PERF_TEST_PINGPONG_LOOP (RPMSG_PERF_TEST_LOOP * 10U)
#else
/* Default: recv copy data 4960 MB */
#define RPMSG_PERF_TEST_LOOP (10U * 1024U * 1024U)
#define RPMSG_PERF_TEST_PINGPONG_LOOP (RPMSG_PERF_TEST_LOOP / 10U)
#endif

#define RPMSG_PERF_TEST_PAYLOAD (496U)

#define RPMSG_PERF_TEST_TIMER_RATE PLL_INPUT_OSC_RATE
#define RPMSG_PERF_TEST_GET_TIMER_COUNT SYS_TIMER->CURRENT_VALUE[0];

#define RPMSG_PERF_TEST_LATENCY_LOOP (1000)
#define RPMSG_PERF_TEST_LATENCY_DELAY (10)

/* Disable RPMSG_PERF_TEST_DBG during the test */
//#define RPMSG_PERF_TEST_DBG

#define MEMCPY_2 \
memcpy(cpy_data, test_data, sizeof(test_data)); \
memcpy(test_data, cpy_data, sizeof(cpy_data)); \

#define MEMCPY_SH2 \
memcpy(cpy_data, test_share_data, RPMSG_PERF_TEST_PAYLOAD); \
memcpy(test_share_data, cpy_data, RPMSG_PERF_TEST_PAYLOAD); \

#define RPMSG_PERF_TEST_MEMCPY MEMCPY_2 MEMCPY_2 MEMCPY_2 MEMCPY_2 MEMCPY_2
#define RPMSG_PERF_TEST_MEMCPY_SH MEMCPY_SH2 MEMCPY_SH2 MEMCPY_SH2 MEMCPY_SH2 MEMCPY_SH2

void rpmsg_perf_master_main(struct rpmsg_lite_instance *test_rpmsg);
void rpmsg_perf_remote_main(struct rpmsg_lite_instance *test_rpmsg);

#endif /* _RPMSG_PERF_H_ */
