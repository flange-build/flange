#pragma once

#include <stddef.h>
#include <stdint.h>

#include "decoder.h"
#include "image.h"

#define MEDIA_AUDIO_MAX_BYTES (32U * 1024U * 1024U)

int media_load_audio(const char *url, decoded_audio_t *audio,
                     char *error, size_t error_size);
int media_load_cover(const char *url,
                     uint16_t pixels[COVER_WIDTH * COVER_HEIGHT],
                     uint16_t *theme_color,
                     char *error, size_t error_size);
