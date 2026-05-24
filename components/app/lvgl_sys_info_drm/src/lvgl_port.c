/**
 * lvgl_port.c — 见 lvgl_port.h
 */
#include "lvgl_port.h"

#include <stdio.h>
#include <stdlib.h>
#include <time.h>

struct lvgl_port {
    lv_display_t *disp;
    void         *buf;
    gl_ctx_t     *gl;
    uint32_t      phys_w;    /* 物理屏幕尺寸（方向 0）*/
    uint32_t      phys_h;
    int           rotation;  /* 当前方向 0/90/180/270 */
};

/* LVGL tick 时基：单调时钟毫秒 */
static uint32_t tick_get_cb(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

/* LVGL 刷新回调：FULL 模式下 px_map 为整屏缓冲，直接交 GL 呈现 */
static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    gl_ctx_t *gl = lv_display_get_user_data(disp);
    gl_present_frame(gl, px_map);
    lv_display_flush_ready(disp);
}

lvgl_port_t *lvgl_port_init(gl_ctx_t *gl)
{
    lvgl_port_t *port = calloc(1, sizeof(*port));
    if (!port)
        return NULL;
    port->gl = gl;

    uint32_t w = gl_width(gl);
    uint32_t h = gl_height(gl);
    port->phys_w = w;
    port->phys_h = h;
    port->rotation = 0;

    if (gl_present_setup(gl, w, h) != 0) {
        fprintf(stderr, "[port] gl_present_setup 失败\n");
        free(port);
        return NULL;
    }

    lv_tick_set_cb(tick_get_cb);

    port->disp = lv_display_create(w, h);
    if (!port->disp) {
        free(port);
        return NULL;
    }

    size_t buf_size = (size_t)w * h * 4; /* 32bpp */
    port->buf = malloc(buf_size);
    if (!port->buf) {
        lv_display_delete(port->disp);
        free(port);
        return NULL;
    }

    lv_display_set_buffers(port->disp, port->buf, NULL, buf_size,
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(port->disp, flush_cb);
    lv_display_set_user_data(port->disp, gl);

    fprintf(stderr, "[port] LVGL display %ux%u（FULL 模式）就绪\n", w, h);
    return port;
}

lv_display_t *lvgl_port_display(lvgl_port_t *port)
{
    return port ? port->disp : NULL;
}

void lvgl_port_set_orientation(lvgl_port_t *port, int degrees)
{
    int r = ((degrees % 360) + 360) % 360;
    r = (r / 90) * 90;
    port->rotation = r;

    /* 90/270 时逻辑宽高互换 */
    uint32_t lw = (r == 90 || r == 270) ? port->phys_h : port->phys_w;
    uint32_t lh = (r == 90 || r == 270) ? port->phys_w : port->phys_h;

    gl_present_set_rotation(port->gl, r);
    gl_present_resize(port->gl, lw, lh);
    lv_display_set_resolution(port->disp, lw, lh);

    fprintf(stderr, "[port] 方向 %d°，逻辑分辨率 %ux%u\n", r, lw, lh);
}

int lvgl_port_rotation(lvgl_port_t *port)  { return port ? port->rotation : 0; }
uint32_t lvgl_port_phys_w(lvgl_port_t *port) { return port ? port->phys_w : 0; }
uint32_t lvgl_port_phys_h(lvgl_port_t *port) { return port ? port->phys_h : 0; }

void lvgl_port_deinit(lvgl_port_t *port)
{
    if (!port)
        return;
    if (port->disp)
        lv_display_delete(port->disp);
    free(port->buf);
    free(port);
}
