#pragma once
#include "esp_err.h"
#include <stdint.h>

esp_err_t display_init(void);
/* 把 RGB565 像素块 blit 到 (x,y) 起的 w×h 区域 */
void display_blit(int x, int y, int w, int h, const void *pixels);
