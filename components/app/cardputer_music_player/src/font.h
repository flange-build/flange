#pragma once

#include <ft2build.h>
#include FT_FREETYPE_H

#include <stdint.h>

#include "framebuffer.h"

typedef struct {
    FT_Library library;
    FT_Face face;
    int ready;
    int pixel_size;
} font_renderer_t;

int font_open(font_renderer_t *font);
void font_close(font_renderer_t *font);
int font_draw_utf8(font_renderer_t *font, framebuffer_t *fb,
                   int x, int y, const char *text, uint16_t color,
                   int pixel_size, int max_width);
