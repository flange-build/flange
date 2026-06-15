#pragma once
#include "esp_err.h"
#include <stdint.h>
#include "cardputer_pins.h" /* re-export LCD_W/LCD_H 等板级常量供调用方使用 */

/* 注意：当前实现不可重入，失败即 abort，不释放已占用的 SPI 资源 */
esp_err_t display_init(void);
/* 把 RGB565 像素块 blit 到 (x,y) 起的 w×h 区域 */
void display_blit(int x, int y, int w, int h, const void *pixels);
