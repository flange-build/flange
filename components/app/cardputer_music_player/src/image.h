#pragma once

#include <stddef.h>
#include <stdint.h>

#define COVER_WIDTH 96
#define COVER_HEIGHT 96
#define COVER_MAX_BYTES (2U * 1024U * 1024U)
#define COVER_MAX_DIMENSION 2048

int image_decode_cover(const unsigned char *data, size_t size,
                       uint16_t *pixels, uint16_t *theme_color,
                       char *error, size_t error_size);
