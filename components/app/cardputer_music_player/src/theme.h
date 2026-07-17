#pragma once

#include <stdint.h>

#define UI_WIDTH 240
#define UI_HEIGHT 135
#define UI_FPS 10

#define UI_COLOR_BG       rgb565(9, 9, 11)
#define UI_COLOR_SURFACE  rgb565(26, 27, 31)
#define UI_COLOR_BORDER   rgb565(57, 59, 66)
#define UI_COLOR_TEXT     rgb565(245, 245, 247)
#define UI_COLOR_MUTED    rgb565(154, 154, 162)
#define UI_COLOR_ACCENT   rgb565(255, 91, 97)
#define UI_COLOR_ACCENT_2 rgb565(173, 61, 69)

static inline uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b)
{
    return (uint16_t)(((uint16_t)(r & 0xf8) << 8)
        | ((uint16_t)(g & 0xfc) << 3)
        | ((uint16_t)b >> 3));
}
