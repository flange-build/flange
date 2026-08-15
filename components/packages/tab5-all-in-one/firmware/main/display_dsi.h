#pragma once
#include "esp_err.h"
#include <stdint.h>

esp_err_t display_init(void);
/* 把一块 GUD 坐标系（640×360 横向）内的 RGB565 矩形送上屏。
 * pixels 为紧凑排列的 w*h 个 RGB565 像素，无 stride。 */
void display_blit(int x, int y, int w, int h, const void *pixels);

/* 待机画面（"NO SIGNAL" OSD）：host 没送帧时显示，并起一个后台任务做等待点动画。
 * 收到第一帧 GUD 后动画停止退出，屏幕完全交给 host。
 * 顺带验证面板时序、颜色通道与 PPA 缩放旋转的落点（文字方向即方向判据）。 */
void display_standby_screen(void);
