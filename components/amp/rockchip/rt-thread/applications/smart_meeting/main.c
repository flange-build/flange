/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    main.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.20
  * @brief   The smart_meeting app
  ******************************************************************************
  */

#include <rtthread.h>
#include <board.h>
#include "hal_base.h"

#include "drv_wdt.h"
#include "rkaudio.h"

#ifdef RT_USING_TOUCHKEY_DRIVERS
#include <gt308l.h>

#define TOUCHKEY_BLUETOOTH      (1 << 0)
#define TOUCHKEY_VOLUME_DOWN    (1 << 1)
#define TOUCHKEY_VOLUME_UP      (1 << 2)
#define TOUCHKEY_MIC_CONTROL    (1 << 3)
#define TOUCHKEY_POWER          (1 << 4)
#define TOUCHKEY_ALL            (TOUCHKEY_BLUETOOTH |   \
                                 TOUCHKEY_VOLUME_DOWN | \
                                 TOUCHKEY_VOLUME_UP |   \
                                 TOUCHKEY_MIC_CONTROL | \
                                 TOUCHKEY_POWER)

#define LED_BLUETOOTH           TOUCHKEY_BLUETOOTH
#define LED_VOLUME_DOWN         TOUCHKEY_VOLUME_DOWN
#define LED_VOLUME_UP           TOUCHKEY_VOLUME_UP
#define LED_MIC_CONTROL         TOUCHKEY_MIC_CONTROL
#define LED_POWER               TOUCHKEY_POWER
#define LED_ALL                 (LED_BLUETOOTH |   \
                                 LED_VOLUME_DOWN | \
                                 LED_VOLUME_UP |   \
                                 LED_MIC_CONTROL | \
                                 LED_POWER)
#endif

struct app
{
    rt_device_t touch;
    rt_uint8_t bt_on;
    rt_uint8_t mic_mute;
} g_app;

#ifdef RT_USING_TOUCHKEY_DRIVERS
static void touchkey(uint32_t mask, void *arg, rt_bool_t pressed)
{
    rt_uint8_t cmd[2];
    if (mask & TOUCHKEY_BLUETOOTH)
    {
        rt_kprintf("touchkey bt %s\n", pressed ? "pressed" : "release");
        if (!pressed)
        {
            if (!g_app.bt_on)
                WRITE_REG(GRF->OS_REG5, 0x2);
            else
                WRITE_REG(GRF->OS_REG5, 0x0);
            g_app.bt_on = !g_app.bt_on;
            cmd[0] = LED_BLUETOOTH;
            cmd[1] = (g_app.bt_on ? LED_BLUETOOTH : 0);
            rt_device_control(g_app.touch, RT_TOUCH_CTRL_SWITCH_LED, cmd);
            rt_thread_mdelay(100);
            rt_hw_cpu_reset();
        }
    }
    if (mask & TOUCHKEY_POWER)
        rt_kprintf("touchkey power %s\n", pressed ? "pressed" : "release");
    if (mask & TOUCHKEY_VOLUME_DOWN)
        rt_kprintf("touchkey vol down %s\n", pressed ? "pressed" : "release");
    if (mask & TOUCHKEY_VOLUME_UP)
        rt_kprintf("touchkey vol up %s\n", pressed ? "pressed" : "release");
    if (mask & TOUCHKEY_MIC_CONTROL)
    {
        rt_kprintf("touchkey mic ctrl %s\n", pressed ? "pressed" : "release");
        if (!pressed)
        {
            g_app.mic_mute = !g_app.mic_mute;
            rkaudio_mute(g_app.mic_mute);
            cmd[0] = LED_MIC_CONTROL;
            cmd[1] = (g_app.mic_mute ? LED_MIC_CONTROL : 0);
            rt_device_control(g_app.touch, RT_TOUCH_CTRL_SWITCH_LED, cmd);
        }
    }
}
#endif

static void app_entry(void *arg)
{
#ifdef RT_USING_TOUCHKEY_DRIVERS
    struct gt308l_hook *hook;
    rt_device_t touch;
    rt_uint8_t cmd[2];
    rt_err_t ret;

    hook = (struct gt308l_hook *)rt_malloc(sizeof(struct gt308l_hook));
    hook->hook = touchkey;
    hook->mask = 0xFF;
    hook->arg  = NULL;

    g_app.bt_on = !!READ_REG(GRF->OS_REG5);
    g_app.mic_mute = 0;
    g_app.touch = touch = rt_device_find(TOUCH_DEV_NAME);
    ret = rt_device_open(touch, RT_DEVICE_FLAG_INT_RX);
    RT_ASSERT(ret == RT_EOK);

    ret = rt_device_control(touch, RT_TOUCH_CTRL_REGISTER_HOOK, hook);
    if (ret != RT_EOK)
        rt_kprintf("register hook failed\n");
    rt_free(hook);

    cmd[0] = LED_ALL;
    cmd[1] = LED_POWER | LED_VOLUME_DOWN | LED_VOLUME_UP;
    ret = rt_device_control(touch, RT_TOUCH_CTRL_DIRECT_LED, cmd);
    if (ret != RT_EOK)
        rt_kprintf("set direct led failed\n");

    cmd[0] = LED_MIC_CONTROL | LED_BLUETOOTH;
    cmd[1] = (g_app.bt_on ? LED_BLUETOOTH : 0) |
             (g_app.mic_mute ? LED_MIC_CONTROL : 0);
    ret = rt_device_control(touch, RT_TOUCH_CTRL_SWITCH_LED, cmd);
    if (ret != RT_EOK)
        rt_kprintf("set direct led failed\n");
#endif
#ifdef SMART_MEETING_WDT_ENABLE
    int type = 1;
    uint32_t timeout = 3;
    rt_device_t wdt;
    wdt = rt_device_find("dw_wdt");
    rt_device_init(wdt);
    rt_device_control(wdt, RT_DEVICE_CTRL_WDT_SET_TIMEOUT, &timeout);
    rt_device_control(wdt, RT_DEVICE_CTRL_WDT_START, &type);
#endif
    while (1)
    {
#ifdef SMART_MEETING_WDT_ENABLE
        rt_device_control(wdt, RT_DEVICE_CTRL_WDT_KEEPALIVE, NULL);
#endif
        rt_thread_mdelay(1000);
    }
}

static int app_main(void)
{
    rt_thread_t tid;

    tid = rt_thread_create("metting", app_entry, NULL, 1024, 10, 10);
    if (tid)
        rt_thread_startup(tid);
    else
        return -RT_ERROR;

    return RT_EOK;
}
INIT_APP_EXPORT(app_main);

