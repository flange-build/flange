/**
 * input_evdev.c — 见 input_evdev.h
 */
#include "input_evdev.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/input.h>

#define BITS_PER_LONG (sizeof(long) * 8)
#define NBITS(x)      ((((x) - 1) / BITS_PER_LONG) + 1)
#define test_bit(bit, array) (((array)[(bit) / BITS_PER_LONG] >> ((bit) % BITS_PER_LONG)) & 1)

typedef struct {
    int            fd;
    lvgl_port_t   *port;

    int            use_mt;        /* 是否用 ABS_MT_POSITION_* */
    int            has_btn_touch; /* 是否上报 BTN_TOUCH */
    struct input_absinfo abs_x;
    struct input_absinfo abs_y;

    /* 当前累积状态（跨 read_cb 保持） */
    int32_t        raw_x;
    int32_t        raw_y;
    int            pressed;
    int            mt_down;       /* MT tracking id >=0 */
    int            btn_down;      /* BTN_TOUCH */
} evdev_ctx_t;

/* 检测某 event 设备是否为触摸屏；是则填充 ctx 的能力信息返回 1 */
static int probe_touch(int fd, evdev_ctx_t *ctx)
{
    unsigned long abs_bits[NBITS(ABS_CNT)] = {0};
    unsigned long key_bits[NBITS(KEY_CNT)] = {0};
    if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(abs_bits)), abs_bits) < 0)
        return 0;
    ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(key_bits)), key_bits);

    int has_mt = test_bit(ABS_MT_POSITION_X, abs_bits) &&
                 test_bit(ABS_MT_POSITION_Y, abs_bits);
    int has_st = test_bit(ABS_X, abs_bits) && test_bit(ABS_Y, abs_bits);
    if (!has_mt && !has_st)
        return 0;

    ctx->use_mt        = has_mt;
    ctx->has_btn_touch = test_bit(BTN_TOUCH, key_bits);

    int x_code = has_mt ? ABS_MT_POSITION_X : ABS_X;
    int y_code = has_mt ? ABS_MT_POSITION_Y : ABS_Y;
    ioctl(fd, EVIOCGABS(x_code), &ctx->abs_x);
    ioctl(fd, EVIOCGABS(y_code), &ctx->abs_y);
    if (ctx->abs_x.maximum <= ctx->abs_x.minimum ||
        ctx->abs_y.maximum <= ctx->abs_y.minimum)
        return 0;
    return 1;
}

/* 原始坐标 → 物理像素 → 按方向逆变换到 LVGL 逻辑坐标 */
static void transform(evdev_ctx_t *ctx, lv_point_t *out)
{
    float u = (float)(ctx->raw_x - ctx->abs_x.minimum) /
              (float)(ctx->abs_x.maximum - ctx->abs_x.minimum);
    float v = (float)(ctx->raw_y - ctx->abs_y.minimum) /
              (float)(ctx->abs_y.maximum - ctx->abs_y.minimum);
    if (u < 0) u = 0;
    else if (u > 1) u = 1;
    if (v < 0) v = 0;
    else if (v > 1) v = 1;

    lv_display_t *d = lvgl_port_display(ctx->port);
    float Lw = (float)lv_display_get_horizontal_resolution(d);
    float Lh = (float)lv_display_get_vertical_resolution(d);

    float lx = 0, ly = 0;
    switch (lvgl_port_rotation(ctx->port)) {
    case 0:   lx = u * Lw;        ly = v * Lh;        break;
    case 90:  lx = v * Lw;        ly = (1 - u) * Lh;  break;
    case 180: lx = (1 - u) * Lw;  ly = (1 - v) * Lh;  break;
    case 270: lx = (1 - v) * Lw;  ly = u * Lh;        break;
    }
    out->x = (int32_t)lx;
    out->y = (int32_t)ly;
}

static void read_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    evdev_ctx_t *ctx = lv_indev_get_user_data(indev);

    struct input_event ev;
    ssize_t n;
    while ((n = read(ctx->fd, &ev, sizeof(ev))) == (ssize_t)sizeof(ev)) {
        switch (ev.type) {
        case EV_ABS:
            if (ev.code == ABS_X || ev.code == ABS_MT_POSITION_X)
                ctx->raw_x = ev.value;
            else if (ev.code == ABS_Y || ev.code == ABS_MT_POSITION_Y)
                ctx->raw_y = ev.value;
            else if (ev.code == ABS_MT_TRACKING_ID)
                ctx->mt_down = (ev.value >= 0);
            break;
        case EV_KEY:
            if (ev.code == BTN_TOUCH)
                ctx->btn_down = (ev.value != 0);
            break;
        case EV_SYN:
            if (ev.code == SYN_REPORT)
                ctx->pressed = ctx->has_btn_touch ? ctx->btn_down : ctx->mt_down;
            break;
        default:
            break;
        }
    }

    static lv_point_t last = {0, 0};
    if (ctx->pressed)
        transform(ctx, &last);
    data->point = last;            /* 释放时沿用最后坐标（LVGL 约定） */
    data->state = ctx->pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

lv_indev_t *input_evdev_init(lvgl_port_t *port)
{
    evdev_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx)
        return NULL;
    ctx->port = port;
    ctx->fd = -1;

    char path[32];
    for (int i = 0; i < 32; i++) {
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0)
            continue;
        if (probe_touch(fd, ctx)) {
            ctx->fd = fd;
            fprintf(stderr, "[input] 触摸设备 %s（%s, btn_touch=%d, X[%d,%d] Y[%d,%d]）\n",
                    path, ctx->use_mt ? "MT" : "ST", ctx->has_btn_touch,
                    ctx->abs_x.minimum, ctx->abs_x.maximum,
                    ctx->abs_y.minimum, ctx->abs_y.maximum);
            break;
        }
        close(fd);
    }
    if (ctx->fd < 0) {
        fprintf(stderr, "[input] 警告：未找到触摸设备，触摸禁用\n");
        free(ctx);
        return NULL;
    }

    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, read_cb);
    lv_indev_set_user_data(indev, ctx);
    lv_indev_set_display(indev, lvgl_port_display(port));
    return indev;
}
