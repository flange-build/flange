#pragma once

#include <stddef.h>
#include <stdint.h>

#include "theme.h"

typedef struct {
    int fd;
    int tty_fd;
    int tty_mode;
    char path[32];
    uint8_t *map;
    size_t map_size;
    int width;
    int height;
    int stride;
    uint16_t pixels[UI_WIDTH * UI_HEIGHT];
} framebuffer_t;

int framebuffer_open_gud(framebuffer_t *fb);
int framebuffer_restore_tty(void);
void framebuffer_close(framebuffer_t *fb);
void framebuffer_present(framebuffer_t *fb);

void gfx_clear(framebuffer_t *fb, uint16_t color);
void gfx_pixel(framebuffer_t *fb, int x, int y, uint16_t color);
void gfx_rect(framebuffer_t *fb, int x, int y, int w, int h, uint16_t color);
void gfx_line(framebuffer_t *fb, int x0, int y0, int x1, int y1,
              uint16_t color);
void gfx_text(framebuffer_t *fb, int x, int y, const char *text,
              uint16_t color, int scale);

int bmp_load_rgb565(const char *path, uint16_t *pixels, int width, int height);
