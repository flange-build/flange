/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#include "lv_port_indev.h"
#include "rtdef.h"
#include "lv_port_disp.h"
#include "lv_app_main.h"

#ifdef RT_USING_TOUCH_DRIVERS
#include "touchpanel.h"
static touch_event_t glte = {0};
static lv_disp_rot_t rot = LV_DISP_ROT_NONE;
static struct rt_touchpanel_block lvgl_touch_block;
#ifndef RT_USING_LVGL9
static lv_indev_drv_t indev_drv;
#endif
static lv_indev_t *indev;

static void touchpad_init(void)
{
    rt_memset(&glte, 0x0, sizeof(glte));
}

#ifdef RT_USING_LVGL9
static void touchpad_read(lv_indev_t *indev_drv, lv_indev_data_t *data)
#else
static void touchpad_read(lv_indev_drv_t *indev_drv, lv_indev_data_t *data)
#endif
{
    data->point.x = glte.x;
    data->point.y = glte.y;
    data->state = glte.down ? LV_INDEV_STATE_PR : LV_INDEV_STATE_REL;
}

static rt_err_t lv_port_touch_cb(struct rt_touch_data *point, rt_uint8_t num)
{
    struct rt_touch_data *p = &point[0];
    struct rt_touchpanel_block *b = &lvgl_touch_block;
    rt_int16_t x = 0, y = 0;
    rt_uint32_t range_x, range_y;

    if (RT_EOK != rt_touchpoint_is_valid(p, b))
    {
        return RT_ERROR;
    }

    if (b->event == RT_TOUCH_EVENT_DOWN)
    {
        x = p->x_coordinate - b->x;
        y = p->y_coordinate - b->y;

        glte.x = x;
        glte.y = y;
        glte.down = RT_TRUE;
        glte.event = TOUCH_EVENT_DOWN;
    }
    else if (b->event == RT_TOUCH_EVENT_MOVE)
    {
        x = p->x_coordinate - b->x;
        y = p->y_coordinate - b->y;

        glte.x = x;
        glte.y = y;
        glte.event = TOUCH_EVENT_MOVE;
    }
    else if (b->event == RT_TOUCH_EVENT_UP)
    {
        glte.down = RT_FALSE;
        glte.event = TOUCH_EVENT_UP;
    }

    if (rot && b->event != RT_TOUCH_EVENT_UP)
    {
        switch (rot)
        {
        case LV_DISP_ROT_90:
            glte.x = y;
            glte.y = LV_VER_RES - x;
            break;
        case LV_DISP_ROT_180:
            glte.x = LV_HOR_RES - x;
            glte.y = LV_VER_RES - y;
            break;
        case LV_DISP_ROT_270:
            glte.x = LV_HOR_RES - y;
            glte.y = x;
            break;
        default:
            break;
        }
    }
    //printf("%s [%d %d] -> [%d %d]\n", __func__, x, y, glte.x, glte.y);

    //TODO: dispatch the touch event.
    rt_touchpoint_get_range(&range_x, &range_y);
    if ((rot == LV_DISP_ROT_90) || (rot == LV_DISP_ROT_270))
    {
        glte.x = (rt_uint32_t)glte.x * LV_HOR_RES / range_y;
        glte.y = (rt_uint32_t)glte.y * LV_VER_RES / range_x;
    }
    else
    {
        glte.x = (rt_uint32_t)glte.x * LV_HOR_RES / range_x;
        glte.y = (rt_uint32_t)glte.y * LV_VER_RES / range_y;
    }

    if (glte.x < 0) glte.x = 0;
    if (glte.x >= LV_HOR_RES) glte.x = LV_HOR_RES - 1;
    if (glte.y < 0) glte.y = 0;
    if (glte.y >= LV_VER_RES) glte.y = LV_VER_RES - 1;

    return RT_EOK;
}

static void lv_port_touch_block_init(struct rt_touchpanel_block *block)
{
    rt_memset(block, 0, sizeof(struct rt_touchpanel_block));

    block->x = 0;
    block->y = 0;

    if ((rot == LV_DISP_ROT_90) ||
            (rot == LV_DISP_ROT_270))
    {
        block->w = LVGL_FB_HEIGHT;
        block->h = LVGL_FB_WIDTH;
    }
    else
    {
        block->w = LVGL_FB_WIDTH;
        block->h = LVGL_FB_HEIGHT;
    }

    block->name = "lvTouch";
    block->callback = lv_port_touch_cb;
}
#endif

void lv_port_indev_init(lv_disp_rot_t rotate)
{
#ifdef RT_USING_TOUCH_DRIVERS
    rot = rotate;
    touchpad_init();

#ifdef RT_USING_LVGL9
    indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, touchpad_read);
#else
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = touchpad_read;
    indev = lv_indev_drv_register(&indev_drv);
#endif

    lv_port_touch_block_init(&lvgl_touch_block);
    rt_touchpanel_block_register(&lvgl_touch_block);
#endif
}

void lv_port_indev_deinit(void)
{
#ifdef RT_USING_TOUCH_DRIVERS
    lv_indev_delete(indev);
    rt_touchpanel_block_unregister(&lvgl_touch_block);
#endif
}
