/**
 * input_evdev.h — evdev 触摸输入
 *
 * 自动探测触摸设备（ABS_MT_POSITION 或 ABS_X+BTN_TOUCH），创建 LVGL 指针
 * indev；read_cb 将原始坐标按当前屏幕方向逆变换到 LVGL 逻辑坐标。
 */
#ifndef INPUT_EVDEV_H
#define INPUT_EVDEV_H

#include "lvgl.h"
#include "lvgl_port.h"

/**
 * 探测并接入触摸设备。成功返回 lv_indev_t*，失败返回 NULL（已打印诊断）。
 * port 用于查询当前方向与物理尺寸以做坐标变换。
 */
lv_indev_t *input_evdev_init(lvgl_port_t *port);

#endif /* INPUT_EVDEV_H */
