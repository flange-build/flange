#pragma once

#include <stddef.h>
#include <stdint.h>

#define SPECTRUM_BANDS 16
#define SPECTRUM_SAMPLES 256

typedef struct {
    float bands[SPECTRUM_BANDS];
    float rms;
    float peak;
} spectrum_frame_t;

void spectrum_compute(const int16_t *samples, size_t count,
                      spectrum_frame_t *frame);
