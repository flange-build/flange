#pragma once
#include "esp_err.h"

esp_err_t display_init(void);
/* 把一块 GUD 坐标系（640×360 横向）内的 RGB565 矩形送上屏。
 * pixels 为紧凑排列的 w*h 个 RGB565 像素，无 stride。 */
void display_blit(int x, int y, int w, int h, const void *pixels);

/* 面板自检：4 条竖直色条（红/绿/蓝/白），用于确认时序与颜色通道。 */
void display_test_pattern(void);
