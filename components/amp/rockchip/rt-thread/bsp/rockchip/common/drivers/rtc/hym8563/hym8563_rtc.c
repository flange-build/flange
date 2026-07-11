/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#include <rtthread.h>
#include <rtdevice.h>
#include <time.h>
#include <drivers/pin.h>
#include <drivers/alarm.h>

#include "hal_base.h"
#include "board.h"

#include "lib_rtc.h"
#include "hym8563_rtc.h"

//#define HYM8563_DBG

#define BIT(nr)         ((1) << (nr))
#define BCD2BIN(n)      (((((n) >> 4) & 0x0F) * 10) + ((n) & 0x0F))
#define BIN2BCD(n)      ((((n) / 10) << 4) | ((n) % 10))

#define EVENT_ALARM_UPDATE  (0x01UL << 0)

struct hym8563_t
{
    struct rt_i2c_client      *client;

    rt_rtc_dev_t    rtc;
    rt_event_t      event;

    int init_flag;
    int alarm_or_timer_irq;
    int alarm_tm_sec;
};
static struct hym8563_t hym8563 = {0,};

static rt_err_t hym8563_write_reg(struct rt_i2c_client *dev, rt_uint8_t cmd, rt_uint8_t write_len, rt_uint8_t *write_data)
{
    struct rt_i2c_msg msgs;
    rt_uint8_t *data;

    data = (rt_uint8_t *)rt_calloc(1, write_len + HYM8563_ADDR_LENGTH);
    RT_ASSERT(data != RT_NULL);

    data[0] = cmd;
    memcpy(&data[HYM8563_ADDR_LENGTH], write_data, write_len);

    msgs.addr  = dev->client_addr;
    msgs.flags = RT_I2C_WR;
    msgs.buf   = data;
    msgs.len   = write_len + HYM8563_ADDR_LENGTH;

    if (rt_i2c_transfer(dev->bus, &msgs, 1) == 1)
    {
        rt_free(data);
        return RT_EOK;
    }
    else
    {
        rt_free(data);
        return -RT_ERROR;
    }
}

static rt_err_t hym8563_read_regs(struct rt_i2c_client *dev, rt_uint8_t cmd, rt_uint8_t read_len, rt_uint8_t *read_buf)
{
    struct rt_i2c_msg msgs[2];
    rt_uint8_t cmd_buf[HYM8563_ADDR_LENGTH];

    cmd_buf[0] = cmd;

    msgs[0].addr  = dev->client_addr;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = cmd_buf;
    msgs[0].len   = HYM8563_ADDR_LENGTH;

    msgs[1].addr  = dev->client_addr;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = read_buf;
    msgs[1].len   = read_len;

    if (rt_i2c_transfer(dev->bus, msgs, 2) == 2)
    {
        return RT_EOK;
    }
    return -RT_ERROR;
}

static void hym8563_regs_dump(uint32_t line)
{
#ifdef HYM8563_DBG
    rt_err_t ret;
    uint8_t buf[16];
    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL1, 16, buf);
    RT_ASSERT(ret == RT_EOK);

    rt_kprintf("hym8563 regs(%d): ", line);
    for (uint8_t i = 0; i < 16; i++)
    {
        rt_kprintf("%x ", buf[i]);
    }
    rt_kprintf("\n");
#endif
}

/* Read current time and date in RTC */
static int hym8563_rtc_read_time(struct tm *tm)
{
    rt_err_t ret;
    uint8_t buf[7];

    ret = hym8563_read_regs(hym8563.client, HYM8563_SEC, 7, buf);
    RT_ASSERT(ret == RT_EOK);

    tm->tm_sec = BCD2BIN(buf[0] & HYM8563_SEC_MASK);
    tm->tm_min = BCD2BIN(buf[1] & HYM8563_MIN_MASK);
    tm->tm_hour = BCD2BIN(buf[2] & HYM8563_HOUR_MASK);
    tm->tm_mday = BCD2BIN(buf[3] & HYM8563_DAY_MASK);
    tm->tm_wday = BCD2BIN(buf[4] & HYM8563_WEEKDAY_MASK); /* 0 = Sun */
    tm->tm_mon = BCD2BIN(buf[5] & HYM8563_MONTH_MASK) - 1; /* 0 = Jan */
    tm->tm_year = BCD2BIN(buf[6]) + 100;

#ifdef HYM8563_DBG
    rt_kprintf("Get-Time(UTC): %04d-%02d-%02d (%d) %02d:%02d:%02d\n",
               1900 + tm->tm_year,
               tm->tm_mon + 1,
               tm->tm_mday,
               tm->tm_wday,
               tm->tm_hour,
               tm->tm_min,
               tm->tm_sec);
#endif

    return RT_EOK;
}

/* Set current time and date in RTC */
static int hym8563_rtc_set_time(struct tm *tm)
{
    rt_err_t ret;
    uint8_t buf[7];
    uint8_t data;

    /* Years >= 2100 are to far in the future, 19XX is to early */
    if (tm->tm_year < 100 || tm->tm_year >= 200)
    {
        return -RT_ERROR;
    }

#ifdef HYM8563_DBG
    rt_kprintf("Set-Time(UTC): %04d-%02d-%02d (%d) %02d:%02d:%02d\n",
               1900 + tm->tm_year,
               tm->tm_mon + 1,
               tm->tm_mday,
               tm->tm_wday,
               tm->tm_hour,
               tm->tm_min,
               tm->tm_sec);
#endif

    buf[0] = BIN2BCD(tm->tm_sec);
    buf[1] = BIN2BCD(tm->tm_min);
    buf[2] = BIN2BCD(tm->tm_hour);
    buf[3] = BIN2BCD(tm->tm_mday);
    buf[4] = BIN2BCD(tm->tm_wday);
    buf[5] = BIN2BCD(tm->tm_mon + 1);

    /*
     * While the HYM8563 has a century flag in the month register,
     * it does not seem to carry it over a subsequent write/read.
     * So we'll limit ourself to 100 years, starting at 2000 for now.
     */
    buf[6] = BIN2BCD(tm->tm_year - 100);

    /*
     * CTL1 only contains TEST-mode bits apart from stop,
     * so no need to read the value first
     */
    data = HYM8563_CTL1_STOP;
    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL1, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_write_reg(hym8563.client, HYM8563_SEC, 7, buf);
    RT_ASSERT(ret == RT_EOK);

    data = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL1, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    return RT_EOK;
}

void hym8563_rtc_alarm_clear(void)
{
    rt_err_t ret;
    uint8_t data0, data1;

    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL2, 1, &data0);
    RT_ASSERT(ret == RT_EOK);

    data0 &= ~HYM8563_CTL2_AF;
    /*clean timer irq and reset timer count down*/
    data0 &= ~HYM8563_CTL2_TF;

    data1 = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_TMR_CNT, 1, &data1);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL2, 1, &data0);
    RT_ASSERT(ret == RT_EOK);
}

static int hym8563_rtc_alarm_irq_enable(unsigned int enabled)
{
    rt_err_t ret;
    uint8_t data;

    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL2, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    if (enabled)
    {
        if (hym8563.alarm_or_timer_irq)
        {
            data |= HYM8563_CTL2_TIE;
        }
        else
        {
            data |= HYM8563_CTL2_AIE;
        }
    }
    else
    {
        data &= ~HYM8563_CTL2_TIE;
        data &= ~HYM8563_CTL2_AIE;
    }

    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL2, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    return RT_EOK;
};

/* Read alarm time and date in RTC */
static int hym8563_rtc_read_alarm(struct rt_rtc_wkalarm *wkalarm)
{
    rt_err_t ret;
    uint8_t buf[4];
    struct tm tm;
    struct rt_rtc_wkalarm *alm_tm = wkalarm;

    ret = hym8563_rtc_read_time(&tm);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_read_regs(hym8563.client, HYM8563_ALM_MIN, 4, buf);
    RT_ASSERT(ret == RT_EOK);

    tm.tm_sec = hym8563.alarm_tm_sec;

    tm.tm_min = (buf[0] & HYM8563_ALM_BIT_DISABLE) ?
                -1 :
                BCD2BIN(buf[0] & HYM8563_MIN_MASK);
    tm.tm_hour = (buf[1] & HYM8563_ALM_BIT_DISABLE) ?
                 -1 :
                 BCD2BIN(buf[1] & HYM8563_HOUR_MASK);
    tm.tm_mday = (buf[2] & HYM8563_ALM_BIT_DISABLE) ?
                 -1 :
                 BCD2BIN(buf[2] & HYM8563_DAY_MASK);
    tm.tm_wday = (buf[3] & HYM8563_ALM_BIT_DISABLE) ?
                 -1 :
                 BCD2BIN(buf[3] & HYM8563_WEEKDAY_MASK);

    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL2, 1, &buf[0]);
    RT_ASSERT(ret == RT_EOK);

    if (buf[0] & (HYM8563_CTL2_AIE | HYM8563_CTL2_TIE))
    {
        alm_tm->enable = 1;
    }
    else
    {
        alm_tm->enable = 0;
    }

    /* Copy tm data to alarm */
    alm_tm->tm_sec  = tm.tm_sec;
    alm_tm->tm_min  = tm.tm_min;
    alm_tm->tm_hour = tm.tm_hour;

#ifdef HYM8563_DBG
    rt_kprintf("Get-Alam(UTC): %02d:%02d:%02d enable(%d)\n",
               alm_tm->tm_hour,
               alm_tm->tm_min,
               alm_tm->tm_sec,
               alm_tm->enable);
#endif

    return RT_EOK;
}

/* Set alarm time and date in RTC */
static int hym8563_rtc_set_alarm(struct rt_rtc_wkalarm *wkalarm)
{
    rt_err_t ret;
    uint8_t data, buf[4];
    struct tm tm, tm_s;
    struct rt_rtc_wkalarm *alm_tm = wkalarm;
    time64_t now, alarm, interval;

    data = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_TMR_CNT, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    data = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL2, 1, &data);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_rtc_read_time(&tm);
    RT_ASSERT(ret == RT_EOK);

    /* Copy alarm set val to struct tm */
    memcpy(&tm_s, &tm, sizeof(struct tm));
    tm_s.tm_sec  = alm_tm->tm_sec;
    tm_s.tm_min  = alm_tm->tm_min;
    tm_s.tm_hour = alm_tm->tm_hour;

    alarm = rtc_tm_to_time64(&tm_s);
    now = rtc_tm_to_time64(&tm);
    interval = alarm - now;

    /* store alarm tm_sec */
    hym8563.alarm_tm_sec = alm_tm->tm_sec;

    if (interval < HYM8563_TMR_MAXCNT)
    {
        /* set timer */
        hym8563.alarm_or_timer_irq = 1;
        data = (uint8_t)interval;
        ret = hym8563_write_reg(hym8563.client, HYM8563_TMR_CNT, 1, &data);
        RT_ASSERT(ret == RT_EOK);
    }
    else
    {
        /* set alarm */
        hym8563.alarm_or_timer_irq = 0;
        alm_tm->tm_sec = 0;
    }

    buf[0] = (tm_s.tm_min < 60 && tm_s.tm_min >= 0) ?
             BIN2BCD(tm_s.tm_min) : HYM8563_ALM_BIT_DISABLE;

    buf[1] = (tm_s.tm_hour < 24 && tm_s.tm_hour >= 0) ?
             BIN2BCD(tm_s.tm_hour) : HYM8563_ALM_BIT_DISABLE;

    buf[2] = (tm_s.tm_mday <= 31 && tm_s.tm_mday >= 1) ?
             BIN2BCD(tm.tm_mday) : HYM8563_ALM_BIT_DISABLE;

    buf[3] = (tm_s.tm_wday < 7 && tm_s.tm_wday >= 0) ?
             BIN2BCD(tm_s.tm_wday) : HYM8563_ALM_BIT_DISABLE;

    ret = hym8563_write_reg(hym8563.client, HYM8563_ALM_MIN, 4, buf);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_rtc_alarm_irq_enable(alm_tm->enable);
    RT_ASSERT(ret == RT_EOK);

#ifdef HYM8563_DBG
    rt_kprintf("Set-Alam(UTC):%02d:%02d:%02d enable(%d)\n",
               tm_s.tm_hour,
               tm_s.tm_min,
               tm_s.tm_sec,
               alm_tm->enable);
#endif

    return RT_EOK;
}

#if RTC_IRQ_PIN
static void hym8563_rtc_isr(void *param)
{
    /* enter interrupt */
    rt_interrupt_enter();

    rt_event_send(hym8563.event, EVENT_ALARM_UPDATE);

    /* leave interrupt */
    rt_interrupt_leave();
}

static void hym8563_rtc_irq_monitor(void *param)
{
    rt_err_t ret;
    uint32_t event;

    while (1)
    {
        ret = rt_event_recv(hym8563.event, EVENT_ALARM_UPDATE,
                            RT_EVENT_FLAG_OR | RT_EVENT_FLAG_CLEAR,
                            RT_WAITING_FOREVER, &event);
        if (ret != RT_EOK)
        {
            /* Reserved... */
        }
        if (event & EVENT_ALARM_UPDATE)
        {
            hym8563_rtc_alarm_clear();
#ifdef RT_USING_ALARM
            rt_alarm_update(0, 0);
#endif
        }
    }
}

/* rtc interrupt initialization function */
static void hym8563_rtc_irq_init(void)
{
    rt_thread_t tid;

    hym8563.event = rt_event_create("hym8563_event",
                                    RT_IPC_FLAG_FIFO);
    RT_ASSERT(hym8563.event != RT_NULL);

    tid = rt_thread_create("hym-monitor",
                           hym8563_rtc_irq_monitor,
                           RT_NULL, 2048, 10, 5);
    RT_ASSERT(tid != RT_NULL);
    rt_thread_startup(tid);

    /* Enable Irq pin */
    rt_pin_mode(RTC_IRQ_PIN, PIN_MODE_INPUT_PULLUP);
    rt_pin_attach_irq(RTC_IRQ_PIN, PIN_IRQ_MODE_FALLING, hym8563_rtc_isr, RT_NULL);
    rt_pin_irq_enable(RTC_IRQ_PIN, PIN_IRQ_ENABLE);
}
#endif

static int hym8563_init_device(struct i2c_client *client)
{
    rt_err_t ret;
    uint8_t buf[16];

    hym8563_regs_dump(__LINE__);

    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL1, 1, &buf[HYM8563_CTL1]);
    RT_ASSERT(ret == RT_EOK);

    /* Clear stop flag if present */
    buf[HYM8563_CTL1] = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_CTL1, 1, &buf[HYM8563_CTL1]);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_read_regs(hym8563.client, HYM8563_CTL2, 1, &buf[HYM8563_CTL2]);
    RT_ASSERT(ret == RT_EOK);

    /* Disable alarm and timer interrupts */
    buf[HYM8563_CTL2] &= ~HYM8563_CTL2_AIE;
    buf[HYM8563_CTL2] &= ~HYM8563_CTL2_TIE;

    /* Clear any pending alarm and timer flags */
    if (buf[HYM8563_CTL2] & HYM8563_CTL2_AF)
        buf[HYM8563_CTL2] &= ~HYM8563_CTL2_AF;

    if (buf[HYM8563_CTL2] & HYM8563_CTL2_TF)
        buf[HYM8563_CTL2] &= ~HYM8563_CTL2_TF;

    buf[HYM8563_CTL2] &= ~HYM8563_CTL2_TI_TP;

    /* Reset timer cnt and Set timer countdown 1s per count */
    buf[HYM8563_TMR_CNT] = 0;
    ret = hym8563_write_reg(hym8563.client, HYM8563_TMR_CNT, 1, &buf[HYM8563_TMR_CNT]);
    RT_ASSERT(ret == RT_EOK);

    buf[HYM8563_TMR_CTL] = HYM8563_TMR_CFG;
    ret = hym8563_write_reg(hym8563.client, HYM8563_TMR_CTL, 1,  &buf[HYM8563_TMR_CTL]);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_write_reg(client, HYM8563_CTL2, 1, &buf[HYM8563_CTL2]);
    RT_ASSERT(ret == RT_EOK);

    hym8563_regs_dump(__LINE__);

    return RT_EOK;
}

static rt_err_t _rtc_init(void)
{
    rt_err_t ret;
    uint8_t buf[16];
    /*
     * hym8563 initial time(2021_1_1_12:00:00),
     * avoid hym8563 read time error
     */
    struct tm tm_read, tm =
    {
        .tm_wday = 0,
        .tm_year = 121,
        .tm_mon = 0,
        .tm_mday = 1,
        .tm_hour = 12,
        .tm_min = 0,
        .tm_sec = 0,
    };

    /* Check RTC initialed */
    if (hym8563.init_flag)
    {
        return RT_EOK;
    }
    hym8563.init_flag = 1;

    /* i2c interface bus */
    hym8563.client = (struct rt_i2c_client *)rt_calloc(1, sizeof(struct rt_i2c_client));
    hym8563.client->client_addr = HYM8563_ADDRESS;
    hym8563.client->bus = (struct rt_i2c_bus_device *)rt_device_find(RTC_I2C_DEV);
    RT_ASSERT(hym8563.client->bus != RT_NULL);

    ret = rt_device_open((rt_device_t)hym8563.client->bus, RT_DEVICE_FLAG_RDWR);
    RT_ASSERT(ret == RT_EOK);

    ret = hym8563_init_device(hym8563.client);
    RT_ASSERT(ret == RT_EOK);

    /* check state of calendar information */
    ret = hym8563_read_regs(hym8563.client, HYM8563_SEC, 1, &buf[HYM8563_SEC]);
    RT_ASSERT(ret == RT_EOK);
    hym8563_regs_dump(__LINE__);

    hym8563_rtc_read_time(&tm_read);
    if ((buf[HYM8563_SEC] & HYM8563_SEC_VL) ||
            (tm_read.tm_year < 70) ||
            (tm_read.tm_year > 200) ||
            (tm_read.tm_mon == -1) ||
            (rtc_valid_tm(&tm_read) != 0))
    {
        hym8563_rtc_set_time(&tm);
    }

#if RTC_IRQ_PIN
    hym8563_rtc_irq_init();
#endif

    return RT_EOK;
}

static rt_err_t _rtc_get_secs(time_t *sec)
{
    struct tm tm;

    if (!hym8563.init_flag)
    {
        _rtc_init();
    }

    hym8563_rtc_read_time(&tm);
    *sec = timegm(&tm);

    return RT_EOK;
}
static rt_err_t _rtc_set_secs(time_t *sec)
{
    struct tm *tm;

    if (!hym8563.init_flag)
    {
        _rtc_init();
    }

    tm = gmtime(sec);
    hym8563_rtc_set_time(tm);

    return RT_EOK;
}
static rt_err_t _rtc_get_alarm(struct rt_rtc_wkalarm *alarm)
{
    if (!hym8563.init_flag)
    {
        _rtc_init();
    }
    hym8563_rtc_read_alarm(alarm);

    return RT_EOK;
}
static rt_err_t _rtc_set_alarm(struct rt_rtc_wkalarm *alarm)
{
    if (!hym8563.init_flag)
    {
        _rtc_init();
    }

    hym8563_rtc_set_alarm(alarm);

    return RT_EOK;
}
static rt_err_t _rtc_get_timeval(struct timeval *tv)
{
    struct tm tm;

    if (!hym8563.init_flag)
    {
        _rtc_init();
    }

    hym8563_rtc_read_time(&tm);
    tv->tv_sec = timegm(&tm);

    return RT_EOK;
}
static rt_err_t _rtc_set_timeval(struct timeval *tv)
{
    struct tm *tm;

    if (!hym8563.init_flag)
    {
        _rtc_init();
    }

    tm = gmtime(tv->tv_sec);
    hym8563_rtc_set_time(tm);

    return RT_EOK;
}

static const struct rt_rtc_ops _rtc_ops =
{
    _rtc_init,
    _rtc_get_secs,
    _rtc_set_secs,
    _rtc_get_alarm,
    _rtc_set_alarm,
    _rtc_get_timeval,
    _rtc_set_timeval,
};

int rt_hw_rtc_init(void)
{
    rt_err_t result;
    hym8563.rtc.ops = &_rtc_ops;
    result = rt_hw_rtc_register(&hym8563.rtc, "rtc", RT_DEVICE_FLAG_RDWR, RT_NULL);
    if (result != RT_EOK)
    {
        rt_kprintf("rtc register err code: %d", result);
        return result;
    }
    return RT_EOK;
}
INIT_DEVICE_EXPORT(rt_hw_rtc_init);
