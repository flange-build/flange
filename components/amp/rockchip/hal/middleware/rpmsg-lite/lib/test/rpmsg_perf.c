/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "hal_base.h"
#include "rpmsg_lite.h"
#include "rpmsg_ns.h"
#include "rpmsg_perf.h"

#define TEST_M_EPT_ID 0xFEU
#define TEST_R_EPT_ID 0xEFU
#define TEST_M_PINGPONG_EPT_ID 0xBAU
#define TEST_R_PINGPONG_EPT_ID 0xABU
#define TEST_M_LATENCY_EPT_ID 0xDCU
#define TEST_R_LATENCY_EPT_ID 0xCDU

static struct rpmsg_lite_instance *test_instance = NULL;

#ifdef RPMSG_PERF_TEST_BANDWIDTH
static struct rpmsg_lite_endpoint *test_instance_ept = NULL;

static volatile uint32_t test_count = 0;
static volatile uint32_t test_pingpong_count = 0;
#ifdef RPMSG_PERF_TEST_COMPENSATION
void *test_share_data = NULL;
#endif

static int32_t test_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    uint8_t msg_buf[payload_len];

    test_count++;
    memcpy(msg_buf, payload, payload_len);
#ifdef RPMSG_PERF_TEST_DBG
    printf("rpmsg perf msg: test_count = %d\n", test_count);
    for (int i = 0; i < RPMSG_PERF_TEST_PAYLOAD; i++)
    {
        printf("%x ", (uint8_t)msg_buf[i]);
        if(i % 16 == 15)
            printf("\n");
    }
#endif

    return RL_RELEASE;
}

static int32_t test_pingpong_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    uint8_t msg_buf[payload_len];

    test_pingpong_count++;
    memcpy(msg_buf, payload, payload_len);
#ifdef RPMSG_PERF_TEST_DBG
    printf("rpmsg perf msg: test_pingpong_count = %d\n", test_pingpong_count);
    for (int i = 0; i < RPMSG_PERF_TEST_PAYLOAD; i++)
    {
        printf("%x ", (uint8_t)msg_buf[i]);
        if(i % 16 == 15)
            printf("\n");
    }
#endif

    if (test_pingpong_count == RPMSG_PERF_TEST_PINGPONG_LOOP)
    {
        printf("test rpmsg pingpong finish, count = %d\n", test_pingpong_count);
#ifdef RPMSG_PERF_TEST_COMPENSATION
        test_share_data = payload;
#endif
    } else {
        rpmsg_lite_send(test_instance, test_instance_ept, src, msg_buf, sizeof(msg_buf), RL_BLOCK);
    }

    return RL_RELEASE;
}

static void rpmsg_perf_bw_master(void)
{
    struct rpmsg_lite_endpoint *test_ept, *test_pingpong_ept;
    void *test_cb_data, *test_pingpong_cb_data;
    uint8_t test_data[RPMSG_PERF_TEST_PAYLOAD];
    uint8_t cpy_data[RPMSG_PERF_TEST_PAYLOAD];
    int i;
    uint32_t data_size;
#ifdef RPMSG_PERF_TEST_COMPENSATION
    uint32_t data_size_KB;
    double time_compensation;
    uint64_t time_share_start, time_share_end;
    double time_share;
#endif
    uint64_t time_send_start, time_send_end;
    uint64_t time_recv_start, time_recv_end;
    uint64_t time_cpy_start, time_cpy_end;
    uint64_t time_pingpong_start, time_pingpong_end;
    double time_send, time_recv, time_cpy, time_pingpong;
    double avg_send, avg_recv;

#ifdef RPMSG_PERF_TEST_COMPENSATION
    data_size_KB = RPMSG_PERF_TEST_LOOP * RPMSG_PERF_TEST_PAYLOAD / 1024U;
    data_size = data_size_KB / 1024U;
    printf("rpmsg perf test: send loop %d and recv copy data %d MB(%d KB).\n",
           RPMSG_PERF_TEST_LOOP, data_size, data_size_KB);
    time_compensation = 2 * RPMSG_PERF_TEST_COMPENSATION * RPMSG_PERF_TEST_LOOP / 1000000.0;
    printf("rpmsg perf test: time_compensation = %.2f s.\n", time_compensation);
#else
    data_size = (RPMSG_PERF_TEST_LOOP / (1024U * 1024U)) * RPMSG_PERF_TEST_PAYLOAD;
    printf("rpmsg perf test: send loop %d and recv copy data %d MB.\n",
           RPMSG_PERF_TEST_LOOP, data_size);
#endif
    memset(test_data, 0, sizeof(test_data));
    for (i = 0; i < RPMSG_PERF_TEST_PAYLOAD; i++)
    {
        test_data[i] = (uint8_t)i;
    }
    test_ept = rpmsg_lite_create_ept(test_instance, TEST_M_EPT_ID, test_ept_cb, &test_cb_data);
    test_pingpong_ept = rpmsg_lite_create_ept(test_instance, TEST_M_PINGPONG_EPT_ID,
                                              test_pingpong_ept_cb, &test_pingpong_cb_data);
    test_instance_ept = test_pingpong_ept;
    time_send_start = HAL_GetSysTimerCount();
    for (i = 0; i < RPMSG_PERF_TEST_LOOP; i++)
    {
#ifdef RPMSG_PERF_TEST_COMPENSATION
        HAL_DelayUs(RPMSG_PERF_TEST_COMPENSATION);
#endif
        rpmsg_lite_send(test_instance, test_ept, TEST_R_EPT_ID, test_data, sizeof(test_data), RL_BLOCK);
#ifdef RPMSG_PERF_TEST_COMPENSATION
        HAL_DelayUs(RPMSG_PERF_TEST_COMPENSATION);
#endif
    }
    time_send_end = HAL_GetSysTimerCount();
#ifdef RPMSG_PERF_TEST_COMPENSATION
    time_send = ((time_send_end - time_send_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE - time_compensation;
    avg_send = time_send * 1000000.0 / RPMSG_PERF_TEST_LOOP;
#else
    time_send = ((time_send_end - time_send_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;
    avg_send = ((time_send_end - time_send_start) * 1000000.0) / RPMSG_PERF_TEST_TIMER_RATE / RPMSG_PERF_TEST_LOOP;
#endif
    time_recv_start = HAL_GetSysTimerCount();
    while (test_count != RPMSG_PERF_TEST_LOOP)
    {
    }
    time_recv_end = HAL_GetSysTimerCount();
#ifdef RPMSG_PERF_TEST_COMPENSATION
    time_recv = ((time_recv_end - time_recv_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE - time_compensation;
    avg_recv = time_recv * 1000000.0 / RPMSG_PERF_TEST_LOOP;
#else
    time_recv = ((time_recv_end - time_recv_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;
    avg_recv = ((time_recv_end - time_recv_start) * 1000000.0) / RPMSG_PERF_TEST_TIMER_RATE / RPMSG_PERF_TEST_LOOP;
#endif
    test_count = 0;
    memset(cpy_data, 0, sizeof(cpy_data));
    time_cpy_start = HAL_GetSysTimerCount();
    for (i = 0; i < RPMSG_PERF_TEST_LOOP; i++)
    {
        RPMSG_PERF_TEST_MEMCPY
    }
    time_cpy_end = HAL_GetSysTimerCount();
    time_cpy = ((time_cpy_end - time_cpy_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;

    printf("test rpmsg pingpong start, count = %d\n", test_pingpong_count);
    time_pingpong_start = HAL_GetSysTimerCount();
    rpmsg_lite_send(test_instance, test_pingpong_ept, TEST_R_PINGPONG_EPT_ID, test_data, sizeof(test_data), RL_BLOCK);
    while (test_pingpong_count != RPMSG_PERF_TEST_PINGPONG_LOOP)
    {
    }
    time_pingpong_end = HAL_GetSysTimerCount();
    time_pingpong = ((time_pingpong_end - time_pingpong_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;

#ifdef RPMSG_PERF_TEST_COMPENSATION
    memset(cpy_data, 0, sizeof(cpy_data));
    time_share_start = HAL_GetSysTimerCount();
    for (i = 0; i < RPMSG_PERF_TEST_LOOP; i++)
    {
        RPMSG_PERF_TEST_MEMCPY_SH
    }
    time_share_end = HAL_GetSysTimerCount();
    time_share = ((time_share_end - time_share_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;
#endif

    printf("rpmsg perf master test result:\n");
#ifdef RPMSG_PERF_TEST_COMPENSATION
    printf("uncache test: send loop %d and recv copy data %d MB(%d KB).\n", RPMSG_PERF_TEST_LOOP, data_size, data_size_KB);
    printf("payload_size %d B.\n", RPMSG_PERF_TEST_PAYLOAD);
    printf("memcpy = %.2f MB/s, time = %.2f s\n", (data_size_KB * 10 / 1024U) / time_cpy, time_cpy);
    printf("memcpy(share) = %.2f MB/s, time = %.2f s\n", (data_size_KB * 10 / 1024U) / time_share, time_share);
    printf("rpmsg send bandwidth = %.2f MB/s, time = %.2f s, avg_time = %.2f us\n",
           data_size_KB / time_send / 1024U, time_send, avg_send);
    printf("rpmsg recv bandwidth = %.2f MB/s, time = %.2f s, avg_time = %.2f us\n",
           data_size_KB / time_recv / 1024U, time_recv, avg_recv);
    printf("rpmsg pingpong: payload = %d B, loop = %d\n", RPMSG_PERF_TEST_PAYLOAD, RPMSG_PERF_TEST_PINGPONG_LOOP);
    printf("rpmsg pingpong: rate = %.2f pingpong/s, time = %.2f s\n",
           RPMSG_PERF_TEST_PINGPONG_LOOP / time_pingpong, time_pingpong);
    printf("rpmsg pingpong: 2 * payload * rate = %.2f MB/s\n",
           2 * RPMSG_PERF_TEST_PAYLOAD * RPMSG_PERF_TEST_PINGPONG_LOOP / time_pingpong / (1024U * 1024U));
#else
    printf("cache test: send loop %d and recv copy data %d MB.\n", RPMSG_PERF_TEST_LOOP, data_size);
    printf("payload_size %d B.\n", RPMSG_PERF_TEST_PAYLOAD);
    printf("memcpy = %.2f MB/s, time = %.2f s\n", (data_size * 10) / time_cpy, time_cpy);
    printf("rpmsg send bandwidth = %.2f MB/s, time = %.2f s, avg = %.2f us\n",
           data_size / time_send, time_send, avg_send);
    printf("rpmsg recv bandwidth = %.2f MB/s, time = %.2f s, avg = %.2f us\n",
           data_size / time_recv, time_recv, avg_recv);
    printf("rpmsg pingpong: payload = %d B, loop = %d\n", RPMSG_PERF_TEST_PAYLOAD, RPMSG_PERF_TEST_PINGPONG_LOOP);
    printf("rpmsg pingpong: rate = %.2f pingpong/s, time = %.2f s\n",
           RPMSG_PERF_TEST_PINGPONG_LOOP / time_pingpong, time_pingpong);
    printf("rpmsg pingpong: 2 * payload * rate = %.2f MB/s\n",
           2 * RPMSG_PERF_TEST_PAYLOAD * RPMSG_PERF_TEST_PINGPONG_LOOP / time_pingpong / (1024U * 1024U));
#endif
}

static void rpmsg_perf_bw_remote(void)
{
    struct rpmsg_lite_endpoint *test_ept, *test_pingpong_ept;
    void *test_cb_data, *test_pingpong_cb_data;
    uint8_t test_data[RPMSG_PERF_TEST_PAYLOAD];
    int i;
    uint32_t data_size;
#ifdef RPMSG_PERF_TEST_COMPENSATION
    uint32_t data_size_KB;
    double time_compensation;
#endif
    uint64_t time_send_start, time_send_end;
    uint64_t time_recv_start, time_recv_end;
    double time_send, time_recv;
    double avg_send, avg_recv;

#ifdef RPMSG_PERF_TEST_COMPENSATION
    data_size_KB = RPMSG_PERF_TEST_LOOP * RPMSG_PERF_TEST_PAYLOAD / 1024U;
    data_size = data_size_KB / 1024U;
    printf("rpmsg perf test: send loop %d and recv copy data %d MB(%d KB).\n",
           RPMSG_PERF_TEST_LOOP, data_size, data_size_KB);
    time_compensation = 2 * RPMSG_PERF_TEST_COMPENSATION * RPMSG_PERF_TEST_LOOP / 1000000.0;
    printf("rpmsg perf test: time_compensation = %.2f s.\n", time_compensation);
#else
    data_size = (RPMSG_PERF_TEST_LOOP / (1024U * 1024U)) * RPMSG_PERF_TEST_PAYLOAD;
    printf("rpmsg perf test: send loop %d and recv copy data %d MB.\n",
           RPMSG_PERF_TEST_LOOP, data_size);
#endif
    memset(test_data, 0, sizeof(test_data));
    for (i = 0; i < RPMSG_PERF_TEST_PAYLOAD; i++)
    {
        test_data[i] = (uint8_t)i;
    }
    test_ept = rpmsg_lite_create_ept(test_instance, TEST_R_EPT_ID, test_ept_cb, &test_cb_data);
    test_pingpong_ept = rpmsg_lite_create_ept(test_instance, TEST_R_PINGPONG_EPT_ID,
                                              test_pingpong_ept_cb, &test_pingpong_cb_data);
    test_instance_ept = test_pingpong_ept;
    time_recv_start = HAL_GetSysTimerCount();
    while (test_count != RPMSG_PERF_TEST_LOOP)
    {
    }
    time_recv_end = HAL_GetSysTimerCount();
#ifdef RPMSG_PERF_TEST_COMPENSATION
    time_recv = ((time_recv_end - time_recv_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE - time_compensation;
    avg_recv = time_recv * 1000000.0 / RPMSG_PERF_TEST_LOOP;
#else
    time_recv = ((time_recv_end - time_recv_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;
    avg_recv = ((time_recv_end - time_recv_start) * 1000000.0) / RPMSG_PERF_TEST_TIMER_RATE / RPMSG_PERF_TEST_LOOP;
#endif
    test_count = 0;
    time_send_start = HAL_GetSysTimerCount();
    for (i = 0; i < RPMSG_PERF_TEST_LOOP; i++)
    {
#ifdef RPMSG_PERF_TEST_COMPENSATION
        HAL_DelayUs(RPMSG_PERF_TEST_COMPENSATION);
#endif
        rpmsg_lite_send(test_instance, test_ept, TEST_M_EPT_ID, test_data, sizeof(test_data), RL_BLOCK);
#ifdef RPMSG_PERF_TEST_COMPENSATION
        HAL_DelayUs(RPMSG_PERF_TEST_COMPENSATION);
#endif
    }
    time_send_end = HAL_GetSysTimerCount();
#ifdef RPMSG_PERF_TEST_COMPENSATION
    time_send = ((time_send_end - time_send_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE - time_compensation;
    avg_send = time_send * 1000000.0 / RPMSG_PERF_TEST_LOOP;
#else
    time_send = ((time_send_end - time_send_start) * 1.0) / RPMSG_PERF_TEST_TIMER_RATE;
    avg_send = ((time_send_end - time_send_start) * 1000000.0) / RPMSG_PERF_TEST_TIMER_RATE / RPMSG_PERF_TEST_LOOP;
#endif

    while (test_pingpong_count != RPMSG_PERF_TEST_PINGPONG_LOOP)
    {
    }
    rpmsg_lite_send(test_instance, test_pingpong_ept, TEST_M_PINGPONG_EPT_ID, test_data, sizeof(test_data), RL_BLOCK);

    printf("rpmsg perf remote test result:\n");
#ifdef RPMSG_PERF_TEST_COMPENSATION
    printf("uncache test: send loop %d and recv copy data %d MB(%d KB).\n", RPMSG_PERF_TEST_LOOP, data_size, data_size_KB);
    printf("rpmsg send bandwidth = %.2f MB/s, time = %.2f s, avg_time = %.2f us\n",
           data_size_KB / time_send / 1024U, time_send, avg_send);
    printf("rpmsg recv bandwidth = %.2f MB/s, time = %.2f s, avg_time = %.2f us\n",
           data_size_KB / time_recv / 1024U, time_recv, avg_recv);
#else
    printf("cache test: send loop %d and recv copy data %d MB.\n", RPMSG_PERF_TEST_LOOP, data_size);
    printf("rpmsg send bandwidth = %.2f MB/s, time = %.2f s. avg_time = %.2f us\n",
           data_size / time_send, time_send, avg_send);
    printf("rpmsg recv bandwidth = %.2f MB/s, time = %.2f s. avg_time = %.2f us\n",
           data_size / time_recv, time_recv, avg_recv);
#endif
}
#endif /* RPMSG_PERF_TEST_BANDWIDTH */

#ifdef RPMSG_PERF_TEST_LATENCY
static volatile uint32_t test_latency_count = 0;
static volatile uint32_t test_latency_sum = 0;
static volatile uint32_t test_latency_max = 0;
static volatile uint32_t test_latency_min = 0xFFFFFFFFU;

static int32_t test_latency_ept_cb(void *payload, uint32_t payload_len, uint32_t src, void *priv)
{
    uint8_t latency_data[payload_len];
    uint32_t time_latency_start, time_latency_end;
    uint32_t time_latency, time_latency_max, time_latency_min;
    int i;

    memcpy(latency_data, payload, payload_len);
    time_latency_end = RPMSG_PERF_TEST_GET_TIMER_COUNT;
    time_latency_start = 0;
    for (i = 0; i < payload_len; i++)
    {
        time_latency_start |= (latency_data[i] << (8 * i));
    }
    time_latency = ((time_latency_end - time_latency_start) * 1000000) / RPMSG_PERF_TEST_TIMER_RATE;

#ifdef RPMSG_PERF_TEST_DBG
    printf("rpmsg perf time: start = 0x%lx, end = 0x%lx\n", time_latency_start, time_latency_end);
#endif
    if (time_latency > 0)
    {
        test_latency_count++;
        test_latency_sum += time_latency;
        if (time_latency > test_latency_max)
        {
            test_latency_max = time_latency;
        }
        if (time_latency < test_latency_min)
        {
            test_latency_min = time_latency;
        }
        printf("rpmsg perf test: latency = %d us, avg = %d us. max = %d us, min = %d us, count = %d\n",
               time_latency, test_latency_sum / test_latency_count,
               test_latency_max, test_latency_min, test_latency_count);
    } else {
        printf("rpmsg perf test: data abort.\n");
    }

    return RL_RELEASE;
}

static void rpmsg_perf_latency_master(void)
{
    struct rpmsg_lite_endpoint *test_latency_ept;
    void *test_cb_data;
    uint32_t time_master;
    uint8_t latency_data[4];
    int i, j;

    test_latency_ept = rpmsg_lite_create_ept(test_instance, TEST_M_LATENCY_EPT_ID, test_latency_ept_cb, &test_cb_data);
    HAL_DelayMs(2 * RPMSG_PERF_TEST_LATENCY_LOOP * RPMSG_PERF_TEST_LATENCY_DELAY);
    for (i = 0; i < RPMSG_PERF_TEST_LATENCY_LOOP; i++)
    {
        HAL_DelayMs(RPMSG_PERF_TEST_LATENCY_DELAY);
        /* get timer count low 32 bits */
        time_master = RPMSG_PERF_TEST_GET_TIMER_COUNT;
        for (j = 0; j < 4; j++)
        {
            latency_data[j] = (time_master >> (8 * j)) & 0xFFU;
        }
        rpmsg_lite_send(test_instance, test_latency_ept, TEST_R_LATENCY_EPT_ID, latency_data, 4, RL_BLOCK);
    }
}

static void rpmsg_perf_latency_remote(void)
{
    struct rpmsg_lite_endpoint *test_latency_ept;
    void *test_cb_data;
    uint32_t time_remote;
    uint8_t latency_data[4];
    int i, j;

    test_latency_ept = rpmsg_lite_create_ept(test_instance, TEST_R_LATENCY_EPT_ID, test_latency_ept_cb, &test_cb_data);
    for (i = 0; i < RPMSG_PERF_TEST_LATENCY_LOOP; i++)
    {
        HAL_DelayMs(RPMSG_PERF_TEST_LATENCY_DELAY);
        /* get timer count low 32 bits */
        time_remote = RPMSG_PERF_TEST_GET_TIMER_COUNT;
        for (j = 0; j < 4; j++)
        {
            latency_data[j] = (time_remote >> (8 * j)) & 0xFFU;
        }
        rpmsg_lite_send(test_instance, test_latency_ept, TEST_M_LATENCY_EPT_ID, latency_data, 4, RL_BLOCK);
    }
}
#endif /* RPMSG_PERF_TEST_LATENCY */

void rpmsg_perf_master_main(struct rpmsg_lite_instance *test_rpmsg)
{
    test_instance = test_rpmsg;

#if defined(RPMSG_PERF_TEST_BANDWIDTH) && defined(RPMSG_PERF_TEST_LATENCY)
#error "Only one test can be selected at a time"
#endif

#ifdef RPMSG_PERF_TEST_BANDWIDTH
    rpmsg_perf_bw_master();
#endif

#ifdef RPMSG_PERF_TEST_LATENCY
    rpmsg_perf_latency_master();
#endif
}

void rpmsg_perf_remote_main(struct rpmsg_lite_instance *test_rpmsg)
{
    test_instance = test_rpmsg;

#ifdef RPMSG_PERF_TEST_BANDWIDTH
    rpmsg_perf_bw_remote();
#endif

#ifdef RPMSG_PERF_TEST_LATENCY
    rpmsg_perf_latency_remote();
#endif
}
