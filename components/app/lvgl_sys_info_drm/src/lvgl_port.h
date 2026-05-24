/**
 * lvgl_port.h — LVGL 显示对接
 *
 * 把 LVGL 的软件渲染输出（FULL 模式，全屏 32bpp 缓冲）经 flush_cb 交给
 * gl_present 上传为 GL 纹理呈现。提供 tick 时基。输入接入见 input_evdev。
 */
#ifndef LVGL_PORT_H
#define LVGL_PORT_H

#include "lvgl.h"
#include "gl_present.h"

typedef struct lvgl_port lvgl_port_t;

/**
 * 初始化 LVGL display 并绑定到 gl 呈现（方向 0 逻辑分辨率取物理分辨率）。
 * 成功返回 port，失败返回 NULL。
 */
lvgl_port_t *lvgl_port_init(gl_ctx_t *gl);

/** 取得底层 lv_display_t（用于设置旋转、查询分辨率等） */
lv_display_t *lvgl_port_display(lvgl_port_t *port);

/**
 * 设置屏幕方向（0/90/180/270，顺时针）：交换 LVGL 逻辑分辨率（90/270 时
 * 宽高互换）、resize GL 纹理、设 GL 呈现旋转。触摸坐标逆变换据此进行。
 */
void lvgl_port_set_orientation(lvgl_port_t *port, int degrees);

/** 当前方向（0/90/180/270） */
int lvgl_port_rotation(lvgl_port_t *port);

/** 物理屏幕尺寸（不随方向变） */
uint32_t lvgl_port_phys_w(lvgl_port_t *port);
uint32_t lvgl_port_phys_h(lvgl_port_t *port);

void lvgl_port_deinit(lvgl_port_t *port);

#endif /* LVGL_PORT_H */
