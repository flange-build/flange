#pragma once
#include "esp_err.h"

esp_err_t display_init(void);
/* 把一块 GUD 坐标系（640×360 横向）内的 RGB565 矩形送上屏。
 * pixels 为紧凑排列的 w*h 个 RGB565 像素，无 stride。 */
void display_blit(int x, int y, int w, int h, const void *pixels);

/* 面板自检：先整帧显示四象限色块（左上红/右上绿/左下蓝/右下白）加中心黑方块，
 * 2 秒后再补一个 64×64 黄块。用于确认面板时序、颜色通道与 PPA 缩放旋转的落点。 */
void display_test_pattern(void);
