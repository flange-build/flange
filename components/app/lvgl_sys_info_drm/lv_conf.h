/**
 * lv_conf.h — LVGL 配置（lvgl_sys_info_drm 专用）
 *
 * 仅覆写本 App 关心的少量选项，其余项由 LVGL 的 lv_conf_internal.h 提供默认值。
 * 渲染路径：LVGL 软件渲染到 32-bit 内存 buffer → 上层 GL 上传为纹理呈现，
 * 故颜色深度固定 32（与 GL RGBA8888 纹理对齐）。
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* 本头会被 LVGL 的 .S 汇编源间接包含；stdint 的 typedef 不能泄漏给汇编器 */
#ifndef __ASSEMBLY__
#include <stdint.h>
#endif

/* ------- 颜色与渲染 ------- */
#define LV_COLOR_DEPTH 32
#define LV_USE_DRAW_SW 1
/* aarch64（Cortex-A）不使用 M 系 Helium/MVE 汇编；bring-up 关 SW ASM 求稳 */
#define LV_USE_DRAW_SW_ASM LV_DRAW_SW_ASM_NONE

/* ------- 内存与标准库 ------- */
#define LV_USE_STDLIB_MALLOC   LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING   LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF  LV_STDLIB_CLIB

/* ------- 操作系统抽象：单线程主循环，不启用 ------- */
#define LV_USE_OS LV_OS_NONE

/* ------- FreeType 运行时字体（nothing-design 排版命根子） ------- */
#define LV_USE_FREETYPE 1

/* ------- 内置回退字体（FreeType 字体缺失时兜底） ------- */
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_DEFAULT &lv_font_montserrat_14

/* ------- 日志 ------- */
#define LV_USE_LOG 1
#if LV_USE_LOG
    #define LV_LOG_LEVEL LV_LOG_LEVEL_WARN
    #define LV_LOG_PRINTF 1
#endif

/* ------- 关闭演示/示例，精简体积 ------- */
#define LV_BUILD_EXAMPLES 0
#define LV_USE_DEMO_WIDGETS 0

#endif /* LV_CONF_H */
