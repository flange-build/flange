/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    libdsp.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.24
  * @brief   The dsp app layer
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>
#include <stdint.h>

#if defined(SMART_MEETING_RKAUDIO) || \
    defined(SMART_MEETING_RKSTUDIO_GAIN) || \
    defined(SMART_MEETING_RKSTUDIO_EQDRC)

#define DBG_SECTION_NAME    "DSP"
#define DBG_LEVEL           DBG_INFO
#include "rtdbg.h"

#include "hal_base.h"

#include "drv_dsp.h"
#include "drv_dvfs.h"
#include "drv_heap.h"

#define LIBDSP_WORK         0

#define WORK_QUEUE_STACK_SIZE       2048
#define WORK_QUEUE_PRIORITY         0

#if LIBDSP_WORK
struct libdsp_work {
    struct dsp_work work;
    struct rt_work rt_work;
    struct rt_semaphore sem;
    int done;
    rt_err_t ret;
};
#endif
static struct rt_device *dsp = NULL;
static uint32_t freq;
#if !LIBDSP_WORK
static struct rt_mutex dsp_lock;
#else
static struct rt_workqueue *workqueue = NULL;

static inline struct libdsp_work *to_libdsp_work(struct dsp_work *work)
{
    return rt_container_of(work, struct libdsp_work, work);
}

static void _libdsp_do_work(struct rt_work *work, void *work_data)
{
    struct libdsp_work *_work = (struct libdsp_work *)work_data;
    rt_err_t ret;

    rt_hw_cpu_dcache_ops(RT_HW_CACHE_FLUSH | RT_HW_CACHE_INVALIDATE, (void *)_work,
                         RT_ALIGN(sizeof(struct libdsp_work), 128));
    ret = rt_device_control(dsp, RKDSP_CTL_QUEUE_WORK, &_work->work);
    if (ret == RT_EOK)
        ret = rt_device_control(dsp, RKDSP_CTL_DEQUEUE_WORK, &_work->work);

    _work->ret = ret;
    _work->done = 1;

    rt_sem_release(&_work->sem);
}
#endif

struct dsp_work *libdsp_create_work(uint32_t id,
                                    uint32_t algo_type,
                                    uint32_t param,
                                    uint32_t param_size)
{
#if !LIBDSP_WORK
    struct dsp_work *work;

    work = rkdsp_malloc(sizeof(struct dsp_work));
    if (!work)
        return NULL;
    rt_memset(work, 0, sizeof(struct dsp_work));
    work->work_type = RKDSP_ALGO_WORK;
    work->id = id;
    work->algo_type = algo_type;
    work->param = param;
    work->param_size = param_size;

    return work;
#else
    struct libdsp_work *work;

    work = rkdsp_malloc(sizeof(struct libdsp_work));
    if (!work)
        return NULL;

    rt_memset(work, 0, sizeof(struct libdsp_work));

    rt_sem_init(&work->sem, "dsp_work", 0, RT_IPC_FLAG_FIFO);
    work->work.work_type = RKDSP_ALGO_WORK;
    work->work.id = id;
    work->work.algo_type = algo_type;
    work->work.param = param;
    work->work.param_size = param_size;

    rt_work_init(&work->rt_work, _libdsp_do_work, work);

    return &work->work;
#endif
}

void libdsp_destroy_work(struct dsp_work *work)
{
#if !LIBDSP_WORK
    rkdsp_free(work);
#else
    struct libdsp_work *_work = to_libdsp_work(work);
    if (_work)
    {
        rt_sem_detach(&_work->sem);
        rkdsp_free(_work);
    }
#endif
}

int libdsp_do_work(struct dsp_work *work)
{
    static uint32_t last = 0;
    static uint32_t cycles = 0;
    uint32_t tick;
#if !LIBDSP_WORK
    rt_err_t ret;

    rt_mutex_take(&dsp_lock, RT_WAITING_FOREVER);
    ret = rt_device_control(dsp, RKDSP_CTL_QUEUE_WORK, work);
    if (ret == RT_EOK)
        ret = rt_device_control(dsp, RKDSP_CTL_DEQUEUE_WORK, work);
    rt_mutex_release(&dsp_lock);
    cycles += work->cycles;
    tick = HAL_GetTick();
    if (freq && (tick - last) >= 3000)
    {
        float used;
        used = (float)cycles / freq / ((tick - last) / 1000);
        LOG_I("%lu MHZ, DSP used %d%%", cycles, (int)(used * 100));
        cycles = 0;
        last = tick;
    }

    return ret;
#else
    struct libdsp_work *_work = to_libdsp_work(work);
    if (!dsp)
        return 0;

    _work->done = 0;
    rt_workqueue_dowork(workqueue, &_work->rt_work);
    if (!_work->done)
        rt_sem_take(&_work->sem, 40);

    return _work->ret;
#endif
}

static int libdsp_open_dsp(void)
{
    rt_err_t ret;

    dsp = rt_device_find("dsp0");
    RT_ASSERT(dsp);
    ret = rt_device_open(dsp, RT_DEVICE_OFLAG_RDWR);
    RT_ASSERT(ret == RT_EOK);

    rt_device_control(dsp, RKDSP_CTL_SET_FREQ, (void *)(594 * MHZ));
    rt_device_control(dsp, RKDSP_CTL_GET_FREQ, (void *)&freq);
    rt_kprintf("current dsp freq: %d MHz\n", freq / MHZ);

#if !LIBDSP_WORK
    rt_mutex_init(&dsp_lock, "dsp_lock", RT_IPC_FLAG_FIFO);
#else
    workqueue = rt_workqueue_create("dsp_wq", WORK_QUEUE_STACK_SIZE,
                                    WORK_QUEUE_PRIORITY);
    RT_ASSERT(workqueue);
#endif

    return RT_EOK;
}

INIT_APP_EXPORT(libdsp_open_dsp);
#endif

