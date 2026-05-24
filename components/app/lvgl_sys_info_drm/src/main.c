/**
 * main.c — lvgl_sys_info_drm 入口
 *
 * 当前里程碑（group 3）：
 *   DRM 选屏 → GBM/EGL/GLESv2 → LVGL(软渲染)→GL 纹理→全屏 quad 呈现，
 *   FreeType 加载 nothing-design 字体，显示首个静态页。
 * 后续叠加：触摸 + 旋转（group 4）、系统信息（5）、L1/L2/设置页（6/7）。
 */
#include <signal.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

#include "lvgl.h"
#include "drm_display.h"
#include "gl_present.h"
#include "lvgl_port.h"
#include "input_evdev.h"
#include "ui_theme.h"
#include "ui.h"
#include "config.h"
#include "backlight.h"

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

int main(int argc, char *argv[])
{
    (void)argc; (void)argv;

    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    drm_dev_t dev;
    if (drm_open_first_connected(&dev) != 0)
        return 1;

    gl_ctx_t *gl = gl_init(&dev);
    if (!gl) {
        drm_close(&dev);
        return 1;
    }

    lv_init();

    lvgl_port_t *port = lvgl_port_init(gl);
    if (!port) {
        gl_deinit(gl);
        drm_close(&dev);
        return 1;
    }

    /* 加载持久化配置（缺失则生成默认） */
    app_config_t cfg;
    config_load(&cfg);

    /* 背光：按配置应用初始亮度（无背光则 no-op） */
    backlight_init();
    if (cfg.brightness >= 0)
        backlight_set_percent(cfg.brightness);

    /* 按配置应用屏幕方向 */
    if (cfg.rotation != 0)
        lvgl_port_set_orientation(port, cfg.rotation);

    ui_theme_init();
    ui_create(port, gl_renderer(gl), &cfg);

    input_evdev_init(port);

    fprintf(stderr, "[app] 运行中，Ctrl-C 退出\n");

    while (!g_stop) {
        uint32_t idle = lv_timer_handler();   /* 渲染在此触发 flush → GL 呈现 */
        if (idle == LV_NO_TIMER_READY || idle > 30)
            idle = 30;                         /* 兜底 ~30ms，兼顾后续触摸响应 */
        if (idle < 1)
            idle = 1;
        usleep(idle * 1000);
    }

    fprintf(stderr, "[app] 退出，复原显示\n");
    lvgl_port_deinit(port);
    lv_deinit();
    gl_deinit(gl);
    drm_close(&dev);
    return 0;
}
