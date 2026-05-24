/**
 * gl_present.h — GBM + EGL + GLESv2 硬件 GL 呈现
 *
 * 在选定的 DRM 设备上建立 GBM surface 与 EGL/GLESv2 上下文，经
 * eglSwapBuffers + DRM page flip 上屏。本模块负责"呈现底座"；LVGL 帧
 * 作为 GL 纹理的上传与全屏 quad 绘制（含旋转）在后续模块叠加。
 */
#ifndef GL_PRESENT_H
#define GL_PRESENT_H

#include <stdint.h>
#include "drm_display.h"

typedef struct gl_ctx gl_ctx_t;

/**
 * 初始化 GBM/EGL/GLESv2 上下文（基于已打开的 drm_dev_t）。
 * 成功返回 gl_ctx_t*（堆分配），失败返回 NULL（已打印诊断）。
 */
gl_ctx_t *gl_init(drm_dev_t *dev);

/** 当前帧缓冲尺寸（物理屏幕） */
uint32_t gl_width(const gl_ctx_t *gl);
uint32_t gl_height(const gl_ctx_t *gl);

/** GLES renderer 字符串（如 "PowerVR B-Series BXM-4-64"），用于系统信息展示 */
const char *gl_renderer(const gl_ctx_t *gl);

/**
 * 建立纹理呈现管线：编译着色器、创建 tex_w×tex_h 纹理、准备全屏 quad。
 * tex_w/tex_h 为 LVGL 逻辑帧缓冲尺寸（方向 0 时等于物理尺寸）。成功返回 0。
 */
int gl_present_setup(gl_ctx_t *gl, uint32_t tex_w, uint32_t tex_h);

/**
 * 设置呈现旋转（0/90/180/270 度，顺时针），在全屏 quad 的纹理映射上生效。
 * group 4 触摸坐标逆变换与此一致。
 */
void gl_present_set_rotation(gl_ctx_t *gl, int degrees);

/**
 * 重设纹理尺寸（LVGL 逻辑分辨率随方向 0↔90 交换时调用）。
 */
void gl_present_resize(gl_ctx_t *gl, uint32_t tex_w, uint32_t tex_h);

/**
 * 呈现一帧 LVGL 软渲染缓冲：上传 BGRA 像素为纹理 → 绘制全屏 quad（含旋转、
 * BGRA→RGB swizzle）→ eglSwapBuffers + page flip。成功返回 0。
 * pixels 为 LVGL 32bpp 缓冲（内存序 B,G,R,A），尺寸须为 setup 时的 tex_w×tex_h。
 */
int gl_present_frame(gl_ctx_t *gl, const void *pixels);

/**
 * 呈现当前 GL 帧：eglSwapBuffers → 锁前缓冲 → 首帧 modeset / 后续 page flip。
 * 成功返回 0。
 */
int gl_swap(gl_ctx_t *gl);

/** 释放上下文 */
void gl_deinit(gl_ctx_t *gl);

#endif /* GL_PRESENT_H */
