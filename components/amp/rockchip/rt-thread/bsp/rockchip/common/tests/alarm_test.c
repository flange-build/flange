/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#include <rtdevice.h>
#include <rtthread.h>

#if defined(RT_USING_COMMON_TEST_ALARM)

#include <drivers/alarm.h>

#define EVENT_ALARM_OCCURRED  (0x01UL << 0)
#define EVENT_ALARM_MODIFY    (0x01UL << 1)

struct alarm_test_t
{
    struct rt_rtc_wkalarm wkalarm;
    rt_event_t      event;
    int state;
};
static struct alarm_test_t gt_alarm = {0,};

/* Converts calendar time to local time & setup alarm parameters */
void alarm_parameter_setup(struct tm *tm, struct rt_rtc_wkalarm *alarm)
{
    time_t timestamp = (time_t)0;

    get_timestamp(&timestamp);
    gmtime_r(&timestamp, tm);

    tm->tm_sec = alarm->tm_sec;
    tm->tm_min = alarm->tm_min;
    tm->tm_hour = alarm->tm_hour;

#if 0
    if (tm->tm_hour < tz_get())
    {
        tm->tm_hour += 24;
    }
    tm->tm_hour -= tz_get();
#else
    timestamp = mktime(tm);
    gmtime_r(&timestamp, tm);
#endif

    rt_kprintf("Alarm-Set: %02d:%02d:%02d\n",
               alarm->tm_hour,
               alarm->tm_min,
               alarm->tm_sec);
}

/* Converts local time to calendar time to local time */
void alarm_parameter_get(struct rt_rtc_wkalarm *alarm)
{
    struct tm tm;
    time_t timestamp = (time_t)0;

#if 0
    /* Converts local time to calendar time */
    alarm->tm_hour += tz_get();
    if (alarm->tm_hour >= 24)
    {
        alarm->tm_hour -= 24;
    }
#else
    /* Get calendar time */
    get_timestamp(&timestamp);
    gmtime_r(&timestamp, &tm);

    /* Copy alarm time */
    tm.tm_hour = alarm->tm_hour;
    tm.tm_min = alarm->tm_min;
    tm.tm_sec = alarm->tm_sec;

    /* Converts to local time */
    timestamp = timegm(&tm);
    localtime_r(&timestamp, &tm);

    alarm->tm_hour = tm.tm_hour;
    alarm->tm_min = tm.tm_min;
    alarm->tm_sec = tm.tm_sec;
#endif

    rt_kprintf("Alarm-Get: %02d:%02d:%02d\n",
               alarm->tm_hour,
               alarm->tm_min,
               alarm->tm_sec);
}

void rt_alarm_callback(rt_alarm_t alarm, time_t timestamp)
{
    struct tm tm;

    localtime_r(&timestamp, &tm);
    rt_kprintf("Alarm occurred at: %02d:%02d:%02d\n",
               tm.tm_hour,
               tm.tm_min,
               tm.tm_sec);

    rt_event_send(gt_alarm.event, EVENT_ALARM_OCCURRED);
}

static void alarm_test(void *param)
{
    rt_err_t ret;
    uint32_t event;

    time_t timestamp = (time_t)0;
    struct rt_alarm_setup setup;
    rt_alarm_t alm = RT_NULL;

    gt_alarm.event = rt_event_create("almt_event",
                                     RT_IPC_FLAG_FIFO);
    RT_ASSERT(gt_alarm.event != RT_NULL);

    gt_alarm.state = 1;

    setup.flag = RT_ALARM_ONESHOT;
    alarm_parameter_setup(&setup.wktime, &gt_alarm.wkalarm);

    alm = rt_alarm_create(rt_alarm_callback, &setup);
    rt_alarm_start(alm);

    while (1)
    {
        ret = rt_event_recv(gt_alarm.event, EVENT_ALARM_OCCURRED | EVENT_ALARM_MODIFY,
                            RT_EVENT_FLAG_OR | RT_EVENT_FLAG_CLEAR,
                            RT_WAITING_FOREVER, &event);
        if (ret != RT_EOK)
        {
            /* Reserved... */
        }
        if (event & EVENT_ALARM_MODIFY)
        {
            setup.flag = RT_ALARM_ONESHOT;
            alarm_parameter_setup(&setup.wktime, &gt_alarm.wkalarm);

            rt_alarm_control(alm, RT_ALARM_CTRL_MODIFY, &setup);
            rt_alarm_start(alm);
        }
        if (event & EVENT_ALARM_OCCURRED)
        {
            break;
        }
    }

    rt_alarm_delete(alm);

    rt_event_delete(gt_alarm.event);
    gt_alarm.event = RT_NULL;

    gt_alarm.state = 0;

    rt_kprintf("Alarm test end!\n");
}

static void alarm(int argc, char **argv)
{
    rt_err_t ret;

    if (argc == 1)
    {
        struct tm tm;
        time_t timestamp;
        struct rt_rtc_wkalarm wkalarm;

        if (!gt_alarm.state)
        {
            rt_kprintf("Alarm not set!\n");
            return;
        }

        rt_device_t device = rt_device_find("rtc");
        if (device == RT_NULL)
        {
            rt_kprintf("Can't find RTC device!\n");
            return;
        }
        rt_err_t ret = rt_device_control(device, RT_DEVICE_CTRL_RTC_GET_ALARM, &wkalarm);
        if (ret != RT_EOK)
        {
            rt_kprintf("Get Alarm Failed!\n");
            return;
        }
        alarm_parameter_get(&wkalarm);
    }
    else if (argc >= 4)
    {
        gt_alarm.wkalarm.tm_hour = atoi(argv[1]);
        gt_alarm.wkalarm.tm_min = atoi(argv[2]);
        gt_alarm.wkalarm.tm_sec = atoi(argv[3]);

        if (gt_alarm.wkalarm.tm_hour > 23)
        {
            rt_kprintf("hour is out of range [0-23]\n");
            return;
        }
        if (gt_alarm.wkalarm.tm_min > 59)
        {
            rt_kprintf("minute is out of range [0-59]\n");
            return;
        }
        if (gt_alarm.wkalarm.tm_sec > 60)
        {
            rt_kprintf("second is out of range [0-60]\n");
            return;
        }

        if (gt_alarm.state)
        {
            rt_event_send(gt_alarm.event, EVENT_ALARM_MODIFY);
        }
        else
        {
            rt_thread_t tid;
            tid = rt_thread_create("alarm-test", alarm_test, RT_NULL, 2048, 10, 5);
            if (tid != RT_NULL)
            {
                rt_thread_startup(tid);
            }
        }
    }
    else
    {
        rt_kprintf("please input: alarm [hour min sec] or alarm\n");
        rt_kprintf("e.g: alarm 23 59 59 or alarm\n");
    }
}

#ifdef RT_USING_FINSH
#include <finsh.h>
MSH_CMD_EXPORT(alarm, get alarm or set(local timezone) [hour min sec])
#endif

#endif
