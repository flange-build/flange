/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkaudio.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.28
  * @brief   The rkaudio demo
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>
#include <stdint.h>

#define DBG_SECTION_NAME    "RKA"
#define DBG_LEVEL           DBG_INFO
#include "rtdbg.h"

#include "hal_base.h"

#include "audio_server.h"
#include "drv_dsp.h"
#include "drv_dvfs.h"
#include "drv_heap.h"
#include "libdsp.h"
#include "rk_audio.h"

#include "rkaudio_param.h"
#ifdef RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL
#include "pcm_plugin_provider.h"
#endif

#define MIC_CH                      4
#define REF_CH                      2
#define IN_CH                       (MIC_CH + REF_CH)
#define OUT_CH                      1

#define IN_SIZE                     256
#define IN_BUF_LEN                  (IN_SIZE * 2 * IN_CH)
#define OUT_BUF_LEN                 (IN_SIZE * 2 * OUT_CH)

struct bf_work_param
{
    uint32_t in_buf;
    uint32_t in_size;

    uint32_t out_buf;
    uint32_t out_size;
};

struct ps_param
{
#define NXM_MAX_PATHS   8
    short *in[NXM_MAX_PATHS];
    int    in_ch[NXM_MAX_PATHS];
    int    cp_ch[NXM_MAX_PATHS];
    int    pos[NXM_MAX_PATHS];
    int    in_paths;
    short *out;
    int    out_ch;
    int    samples;
};

static struct rt_device *card = NULL;
static struct AUDIO_PARAMS param;
static struct audio_buf abuf;
static audio_player_stream_t *stream;
#ifdef SMART_MEETING_RKAUDIO
static struct bf_cfg_param *cfg_param;
static int cfg_param_size;
#endif
static int vol_mute = 0;
static int reset = 0;

static int out_ch = 8;
static int out_bytes = 4096;

static inline int _samples_to_bytes(int samples)
{
    return samples * out_ch * (param.sampleBits >> 3);
}

#ifdef SMART_MEETING_RKAUDIO
static struct bf_work_param *dsp_bf_param_prepare(void)
{
    struct bf_work_param *param = rkdsp_malloc(sizeof(struct bf_work_param));
    if (!param)
        goto null_param;
    /* Can change to use voice buffer */
    param->in_buf   = (uint32_t)rkdsp_malloc(IN_BUF_LEN);
    if (!param->in_buf)
        goto null_in;
    param->in_size  = IN_BUF_LEN;

    param->out_buf  = (uint32_t)rkdsp_malloc(OUT_BUF_LEN);
    if (!param->out_buf)
        goto null_out;
    param->out_size = OUT_BUF_LEN;

    return param;

null_out:
    rkdsp_free((void *)param->in_buf);
null_in:
    rkdsp_free(param);
null_param:
    return NULL;
}

static void dsp_bf_param_destroy(struct bf_work_param *param)
{
    if (!param)
        return;

    if (param->in_buf)
        rkdsp_free((void *)param->in_buf);
    if (param->out_buf)
        rkdsp_free((void *)param->out_buf);
    rkdsp_free(param);
}
#endif

static int sound_card_open(char *cardname, int rate, int bits, int channels)
{
    int size;
    rt_err_t ret = RT_ERROR;

    card = rt_device_find(cardname);
    if (!card ||
            (RT_EOK != rt_device_open(card, RT_DEVICE_OFLAG_RDONLY)))
    {
        rt_kprintf("open %s failed\n", cardname);
        goto no_card;
    }

    abuf.period_size = IN_SIZE;
    abuf.buf_size = IN_SIZE * 4;
    size = abuf.buf_size * channels * (bits >> 3); /* frames to bytes */
    abuf.buf = rt_malloc_uncache(size);
    if (!abuf.buf)
    {
        rt_kprintf("Buffer alloc failed!\n");
        goto null_buf;
    }

    param.channels = channels;
    param.sampleRate = rate;
    param.sampleBits = bits;
#ifdef RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL
    snd_pcm_type_t type = SND_PCM_TYPE_SOFTVOL;
    ret = rt_device_control(card, RK_AUDIO_CTL_PLUGIN_PREPARE, (void *)type);
    RT_ASSERT(ret == RT_EOK);
#endif
    ret = rt_device_control(card, RK_AUDIO_CTL_HW_PARAMS, &param);
    RT_ASSERT(ret == RT_EOK);

    ret = rt_device_control(card, RK_AUDIO_CTL_PCM_PREPARE, &abuf);
    RT_ASSERT(ret == RT_EOK);

    return RT_EOK;

null_buf:
    rt_device_close(card);
no_card:
    card = NULL;
    return ret;
}

static void sound_card_close(void)
{
    rt_err_t ret;

    if (!card)
        return;

    rt_free_uncache(abuf.buf);
#ifdef RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL
    snd_pcm_type_t type = SND_PCM_TYPE_SOFTVOL;
    ret = rt_device_control(card, RK_AUDIO_CTL_PLUGIN_RELEASE, (void *)type);
    RT_ASSERT(ret == RT_EOK);
#endif
    ret = rt_device_control(card, RK_AUDIO_CTL_STOP, NULL);
    RT_ASSERT(ret == RT_EOK);
    ret = rt_device_control(card, RK_AUDIO_CTL_PCM_RELEASE, NULL);
    RT_ASSERT(ret == RT_EOK);

    rt_device_close(card);
    card = NULL;
}

static void path_select(struct ps_param *param)
{
    int paths = param->in_paths;
    int samples = param->samples;
    short *out = param->out;
    int out_ch = param->out_ch;
    short *in;
    int in_ch;
    int cp_ch;
    int ch_cnt = 0;
    int pos;

    for (int i = 0; i < paths; i++)
    {
        in_ch = param->in_ch[i];
        cp_ch = param->cp_ch[i];
        if (cp_ch + ch_cnt > out_ch)
        {
            cp_ch = out_ch - ch_cnt;
            if (!cp_ch)
                break;
        }
        if (!in_ch || !cp_ch)
            continue;
        ch_cnt += cp_ch;
        pos = param->pos[i];
        in = param->in[i];

        for (int s = 0; s < samples; s++)
            for (int j = 0; j < cp_ch; j++)
                out[s * out_ch + j + pos] = in[s * in_ch + j % in_ch];
    }
}

#ifdef SMART_MEETING_RKAUDIO
static int rkaudio_init(void)
{
    struct dsp_work *work;
    rt_err_t ret = -RT_ERROR;

    work = libdsp_create_work(RKAUDIO_ID, RKAUDIO_CONFIG,
                              (uint32_t)cfg_param,
                              RT_ALIGN(cfg_param_size, RKDSP_CACHE_LINE_SIZE));
    if (!work)
    {
        rt_kprintf("dsp create config work fail\n");
        return -RT_ERROR;
    }

    ret = libdsp_do_work(work);
    RT_ASSERT(ret == RT_EOK);
    libdsp_destroy_work(work);

    return RT_EOK;
}

static int rkaudio_deinit(void)
{
    struct dsp_work *work;
    rt_err_t ret = -RT_ERROR;

    work = libdsp_create_work(RKAUDIO_ID, RKAUDIO_DESTROY, 0, 0);
    if (!work)
    {
        rt_kprintf("dsp create config work fail\n");
        return -RT_ERROR;
    }
    ret = libdsp_do_work(work);
    RT_ASSERT(ret == RT_EOK);
    libdsp_destroy_work(work);

    return RT_EOK;
}
#endif

static void rkaudio_process(void *arg)
{
#ifdef SMART_MEETING_RKAUDIO
    struct bf_work_param *bf_param;
    struct dsp_work *work;
    rt_err_t ret;
#endif
    struct ps_param ps_param;
    short *src_buf;
    short *buf;

#ifdef SMART_MEETING_RKAUDIO
    bf_param = dsp_bf_param_prepare();
    if (!bf_param)
    {
        rt_kprintf("create bf_param fail\n");
        goto null_bf_param;
    }
    work = libdsp_create_work(RKAUDIO_ID, RKAUDIO_PROCESS,
                              (uint32_t)bf_param,
                              sizeof(struct bf_work_param));
    if (!work)
    {
        rt_kprintf("dsp create config work fail\n");
        goto null_work;
    }
    src_buf = (short *)bf_param->in_buf;
#else
    src_buf = (short *)malloc(IN_BUF_LEN);
    if (!src_buf)
        goto null_bf_param;
#endif

    buf = malloc(out_bytes);
    if (!buf)
    {
        LOG_E("out buffer malloc failed %d", out_bytes);
        goto null_buf;
    }
    memset(buf, 0x0, out_bytes);

#ifdef SMART_MEETING_RKAUDIO
    ps_param.in[0] = (short *)bf_param->out_buf;
    ps_param.in[1] = (short *)bf_param->in_buf;
    ps_param.in_ch[0] = OUT_CH;
    ps_param.in_ch[1] = IN_CH;
    ps_param.cp_ch[0] = 2;
    ps_param.cp_ch[1] = 6;
    ps_param.pos[0] = 0;
    ps_param.pos[1] = ps_param.cp_ch[0];
    ps_param.in_paths = 2;
    ps_param.out = buf;
    ps_param.out_ch = out_ch;
    ps_param.samples = IN_SIZE;
#else
    ps_param.in[0] = src_buf;
    ps_param.in_ch[0] = IN_CH;
    ps_param.cp_ch[0] = 6;
    ps_param.pos[0] = 0;
    ps_param.in_paths = 1;
    ps_param.out = buf;
    ps_param.out_ch = out_ch;
    ps_param.samples = IN_SIZE;
#endif

    while (1)
    {
        if (reset)
        {
            reset = 0;
#ifdef SMART_MEETING_RKAUDIO
            rkaudio_deinit();
            rkaudio_init();
#endif
            audio_stream_resume(stream);
        }
        if (!rt_device_read(card, 0, (void *)src_buf, IN_SIZE))
        {
            rt_kprintf("read error\n");
            break;
        }
#ifdef SMART_MEETING_RKAUDIO
        rt_hw_cpu_dcache_ops(RT_HW_CACHE_FLUSH,
                             (void *)bf_param->in_buf, IN_BUF_LEN);
        rt_hw_cpu_dcache_ops(RT_HW_CACHE_INVALIDATE,
                             (void *)bf_param->out_buf, OUT_BUF_LEN);
        ret = libdsp_do_work(work);
        RT_ASSERT(ret == RT_EOK);
#endif
        path_select(&ps_param);

        if (vol_mute)
            memset(buf, 0, out_bytes);

        audio_stream_write(stream, (void *)buf, out_bytes);
    }

    free(buf);
null_buf:
#ifdef SMART_MEETING_RKAUDIO
    libdsp_destroy_work(work);
null_work:
    dsp_bf_param_destroy(bf_param);
#else
    free(src_buf);
#endif
null_bf_param:
    audio_stream_stop(stream);
    audio_stream_destroy(stream);

    sound_card_close();
}

void rkaudio_mute(int mute)
{
    vol_mute = mute;
}

int rkaudio_read(char *buf, int samples)
{
    int len = _samples_to_bytes(samples);
    return audio_stream_read(stream, buf, len);
}

void rkaudio_close(void)
{
    /* Do nothing here. */
}

int rkaudio_open(char *cardname, int rate, int bits, int channels)
{
    rt_thread_t tid;
    rt_err_t ret = -RT_ERROR;

    LOG_I("%s %d %d %d", cardname, rate, bits, channels);
    if (card)
    {
        rt_kprintf("rkaudio already opened, reset it\n");
        reset = 1;
        audio_stream_reset(stream);
        return RT_EOK;
    }

    out_ch = channels;
    out_bytes = IN_SIZE * out_ch * (bits >> 3);

#ifdef SMART_MEETING_RKAUDIO
    cfg_param = rkaudio_param_from_file("/librkaudio.json", &cfg_param_size);
    if (!cfg_param)
    {
        rt_kprintf("malloc cfg_param failed\n");
        goto null_param;
    }
    cfg_param->in_fs    = rate;
    cfg_param->in_size  = IN_SIZE;
    cfg_param->bits     = bits;
    cfg_param->src_chan = MIC_CH;
    cfg_param->ref_chan = REF_CH;

    ret = rkaudio_init();
    if (ret != RT_EOK)
    {
        rt_kprintf("rkaudio init failed\n");
        goto null_work;
    }
#endif

    ret = sound_card_open(cardname, rate, bits, IN_CH);
    if (ret != RT_EOK)
    {
        rt_kprintf("open card failed\n");
        goto null_work;
    }

    stream = audio_stream_create(out_bytes * 4);
    if (!stream)
    {
        rt_kprintf("audio_stream_create failed\n");
        goto null_stream;
    }
    audio_stream_start(stream);

    tid = rt_thread_create("rkaudio", rkaudio_process, NULL, 2048, 5, 10);
    if (!tid)
    {
        rt_kprintf("create thread failed\n");
        goto null_tid;
    }
    rt_thread_startup(tid);

    return RT_EOK;

null_tid:
    audio_stream_destroy(stream);
null_stream:
    sound_card_close();
null_work:
#ifdef SMART_MEETING_RKAUDIO
    rkdsp_free(cfg_param);
null_param:
#endif
    return -RT_ERROR;
}

