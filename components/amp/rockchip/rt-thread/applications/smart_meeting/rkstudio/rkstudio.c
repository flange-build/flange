/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkstudio.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.28
  * @brief   The rkstudio demo
  ******************************************************************************
  */

#include <rtdevice.h>
#include <rtthread.h>
#include <stdint.h>

#define DBG_SECTION_NAME    "RKS"
#define DBG_LEVEL           DBG_INFO
#include "rtdbg.h"

#include "hal_base.h"

#include "drv_heap.h"
#include "libdsp.h"
#include "rk_audio.h"
#include "RK_AudioEffect_Interface.h"

#ifdef RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL
#include "pcm_plugin_provider.h"
#endif

#define PERIOD_SIZE         1536

#define MAX_DB              0
#define MIN_DB              -40

static struct rt_device *card = NULL;
static struct AUDIO_PARAMS param;
static struct audio_buf abuf;
static int    vol_percent = 100;
static int    vol_mute = 0;
#ifdef SMART_MEETING_RKSTUDIO_GAIN
static void *st;
static float mute_st_param[] = {0, 1, 6};
static float normal_st_param[] = {0, 0, 6};
static float *st_param = normal_st_param;
#endif
#ifdef SMART_MEETING_RKSTUDIO_EQDRC
struct eq_cfg_param
{
    uint32_t in_size;
    uint32_t chan;

    uint32_t audio_param;
};
struct eq_work_param
{
    uint32_t in_buf;
    uint32_t in_size;

    uint32_t out_buf;
    uint32_t out_size;
};
static struct eq_cfg_param *eq_cfg = NULL;
static uint32_t eq_cfg_size;
static float *eq_param = NULL;
static struct eq_work_param *eq_work_param = NULL;
static struct dsp_work *eq_work = NULL;
#endif

static inline int _bytes_to_samples(int bytes)
{
    return bytes / param.channels / (param.sampleBits >> 3);
}

static inline int _samples_to_bytes(int samples)
{
    return samples * param.channels * (param.sampleBits >> 3);
}

static int sound_card_open(char *cardname, int rate, int bits, int channels)
{
    int size;
    rt_err_t ret = RT_ERROR;

    card = rt_device_find(cardname);
    if (!card ||
            (RT_EOK != rt_device_open(card, RT_DEVICE_OFLAG_WRONLY)))
    {
        rt_kprintf("open %s failed\n", cardname);
        goto no_card;
    }

    abuf.period_size = PERIOD_SIZE;
    abuf.buf_size = PERIOD_SIZE * 4;
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

    ret = rt_device_control(card, RK_AUDIO_CTL_PCM_PREPARE, &abuf);
    RT_ASSERT(ret == RT_EOK);
#ifdef RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL
    snd_pcm_type_t type = SND_PCM_TYPE_SOFTVOL;
    ret = rt_device_control(card, RK_AUDIO_CTL_PLUGIN_PREPARE, (void *)type);
    RT_ASSERT(ret == RT_EOK);
#endif
    ret = rt_device_control(card, RK_AUDIO_CTL_HW_PARAMS, &param);
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

int rkstudio_get_volume(void)
{
    return !!vol_mute ? 0 : vol_percent;
}

int rkstudio_set_volume(int percent)
{
    rt_kprintf("set volume, %d => %d\n", vol_percent, percent);
    vol_percent = percent;
#ifdef SMART_MEETING_RKSTUDIO_GAIN
    normal_st_param[0] = (MAX_DB - MIN_DB) * percent / 100 + MIN_DB;

    if (percent == 0)
        st_param = mute_st_param;
    else
        st_param = normal_st_param;

    if (!st)
        return 0;

    return AudioPost_GainSlew_SetParam(st, st_param);
#elif defined(RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL)
    snd_softvol_t softvol;

    if (!card)
        return 0;

    softvol.vol_l = percent;
    softvol.vol_r = percent;
    rt_kprintf("Set softvol: %d, %d\n", softvol.vol_l, softvol.vol_r);
    return rt_device_control(card, RK_AUDIO_CTL_PLUGIN_SET_SOFTVOL, &softvol);
#else
    struct AUDIO_GAIN_INFO info;
    struct AUDIO_DB_CONFIG db_config;
    int ret;

    if (!card)
        return 0;

    ret = rt_device_control(card, RK_AUDIO_CTL_GET_GAIN_INFO, &info);
    RT_ASSERT(ret == RT_EOK);
    ret = rt_device_control(card, RK_AUDIO_CTL_GET_GAIN, &db_config);
    RT_ASSERT(ret == RT_EOK);

    db_config.dB = info.mindB + percent * (info.maxdB - info.mindB) / 100;
    db_config.dB = db_config.dB - db_config.dB % info.step;
    rt_kprintf("db_config.dB = %d\n", db_config.dB);
    return rt_device_control(card, RK_AUDIO_CTL_SET_GAIN, &db_config);
#endif
}

int rkstudio_set_mute(int mute)
{
    rt_kprintf("set mute %d\n", mute);
    vol_mute = mute;
#ifdef SMART_MEETING_RKSTUDIO_GAIN
    if (mute)
        st_param = mute_st_param;
    else
        st_param = normal_st_param;

    if (!st)
        return 0;

    return AudioPost_GainSlew_SetParam(st, st_param);
#elif defined(RT_USING_DRIVER_AUDIO_PCM_PLUGIN_SOFTVOL)
    if (mute && card)
    {
        snd_softvol_t softvol;
        softvol.vol_l = 0;
        softvol.vol_r = 0;
        rt_kprintf("Set softvol: %d, %d\n", softvol.vol_l, softvol.vol_r);
        return rt_device_control(card, RK_AUDIO_CTL_PLUGIN_SET_SOFTVOL, &softvol);
    }

    return RT_EOK;
#else
    if (mute && card)
    {
        struct AUDIO_GAIN_INFO info;
        struct AUDIO_DB_CONFIG db_config;
        int ret;

        ret = rt_device_control(card, RK_AUDIO_CTL_GET_GAIN_INFO, &info);
        RT_ASSERT(ret == RT_EOK);
        ret = rt_device_control(card, RK_AUDIO_CTL_GET_GAIN, &db_config);
        RT_ASSERT(ret == RT_EOK);
        db_config.dB = info.mindB;
        rt_kprintf("db_config.dB = %d\n", db_config.dB);
        return rt_device_control(card, RK_AUDIO_CTL_SET_GAIN, &db_config);
    }

    return RT_EOK;
#endif
}

static int rkstudio_process(short *in, short *out, int samples)
{
    int ret = RT_EOK;

#ifdef SMART_MEETING_RKSTUDIO_EQDRC
    if (eq_work)
    {
        eq_work_param->in_buf = (uint32_t)in;
        eq_work_param->in_size = (uint32_t)_samples_to_bytes(samples);
        eq_work_param->out_buf = (uint32_t)out;
        eq_work_param->out_size = (uint32_t)_samples_to_bytes(samples);
        rt_hw_cpu_dcache_ops(RT_HW_CACHE_FLUSH | RT_HW_CACHE_INVALIDATE,
                             (void *)in, eq_work_param->in_size);

        eq_work->algo_type = RKSTUDIO_EQ_PROCESS;
        eq_work->param = (uint32_t)eq_work_param;
        eq_work->param_size = sizeof(struct eq_work_param);
        libdsp_do_work(eq_work);
    }
#endif

#ifdef SMART_MEETING_RKSTUDIO_GAIN
    if (st)
        ret = AudioPost_GainSlew_Process(st, in, out);
    if (ret != RT_EOK)
        return ret;
#endif
    return ret;
}

int rkstudio_write(char *buf, int samples)
{
    rkstudio_process((short *)buf, (short *)buf, samples);

    return rt_device_write(card, 0, buf, samples);
}

void rkstudio_close(void)
{
#ifdef SMART_MEETING_RKSTUDIO_GAIN
    if (st)
        AudioPost_GainSlew_Destroy(st);
    st = NULL;
#endif
#ifdef SMART_MEETING_RKSTUDIO_EQDRC
    if (eq_work)
    {
        eq_work->algo_type = RKSTUDIO_EQ_DESTROY;
        eq_work->param = 0;
        eq_work->param_size = 0;
        libdsp_do_work(eq_work);
        libdsp_destroy_work(eq_work);
        eq_work = NULL;
    }
    if (eq_work_param)
    {
        rkdsp_free(eq_work_param);
        eq_work_param = NULL;
    }
#endif
    sound_card_close();
}

int rkstudio_open(char *cardname, int rate, int bits, int channels)
{
    rt_err_t ret = -RT_ERROR;

    LOG_I("%s %d %d %d", cardname, rate, bits, channels);
    ret = sound_card_open(cardname, rate, bits, channels);
    if (ret != RT_EOK)
    {
        LOG_E("open card failed");
        return -RT_ERROR;
    }

#ifdef SMART_MEETING_RKSTUDIO_GAIN
    st = AudioPost_GainSlew_Init(rate, channels, PERIOD_SIZE);
    if (!st)
    {
        LOG_E("Init GainSlew failed");
        goto null_st;
    }

    AudioPost_GainSlew_SetParam(st, st_param);
#endif
#ifdef SMART_MEETING_RKSTUDIO_EQDRC
    if (!eq_cfg)
    {
        FILE *fd;
        eq_cfg_size = sizeof(struct eq_cfg_param) + sizeof(float) * 500;
        eq_cfg = rkdsp_malloc(eq_cfg_size);
        if (eq_cfg)
        {
            eq_param = (float *)((char *)eq_cfg + sizeof(struct eq_cfg_param));
            fd = fopen("/eqdrc.bin", "rb");
            if (fd)
            {
                fread(eq_param, sizeof(float), 500, fd);
                fclose(fd);
            }
            else
            {
                LOG_E("open eqdrc.bin failed");
                rkdsp_free(eq_cfg);
                eq_cfg = NULL;
                goto null_eqdrc;
            }
        }
        else
        {
            LOG_E("malloc eqdrc param failed");
            goto null_eqdrc;
        }
    }
    if (eq_cfg)
    {
        eq_work_param = rkdsp_malloc(sizeof(struct eq_work_param));
        if (!eq_work_param)
        {
            LOG_E("init eq work failed");
            rkdsp_free(eq_cfg);
            eq_cfg = NULL;
            goto null_eqdrc;
        }

        eq_cfg->audio_param = (uint32_t)eq_param;
        eq_cfg->chan = 2;
        eq_cfg->in_size = _samples_to_bytes(PERIOD_SIZE);
        eq_work = libdsp_create_work(RKAUDIO_ID, RKSTUDIO_EQ_CONFIG,
                                     (uint32_t)eq_cfg,
                                     RT_ALIGN(eq_cfg_size,
                                              RKDSP_CACHE_LINE_SIZE));
        if (!eq_work)
        {
            LOG_E("init eqdrc failed");
            rkdsp_free(eq_cfg);
            eq_cfg = NULL;
            rkdsp_free(eq_work_param);
            eq_work_param = NULL;
            goto null_eqdrc;
        }
        ret = libdsp_do_work(eq_work);
    }
#endif

    return RT_EOK;

#ifdef SMART_MEETING_RKSTUDIO_EQDRC
null_eqdrc:
#endif
#ifdef SMART_MEETING_RKSTUDIO_GAIN
    if (st)
        AudioPost_GainSlew_Destroy(st);
    st = NULL;
null_st:
#endif
    sound_card_close();

    return -RT_ERROR;
}

