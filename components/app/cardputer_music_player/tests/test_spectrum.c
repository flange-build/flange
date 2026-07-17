#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>

#include "spectrum.h"

#define TEST_RATE 16000
#define TWO_PI 6.28318530717958647692

static unsigned strongest_band(const spectrum_frame_t *frame)
{
    unsigned strongest = 0;
    for (unsigned i = 1; i < SPECTRUM_BANDS; i++) {
        if (frame->bands[i] > frame->bands[strongest])
            strongest = i;
    }
    return strongest;
}

static void make_sine(int16_t samples[SPECTRUM_SAMPLES],
                      double frequency, double amplitude)
{
    for (size_t i = 0; i < SPECTRUM_SAMPLES; i++) {
        samples[i] = (int16_t)(sin(TWO_PI * frequency * i / TEST_RATE)
                               * amplitude * 32767.0);
    }
}

static void test_silence(void)
{
    int16_t samples[SPECTRUM_SAMPLES] = {0};
    spectrum_frame_t frame;
    spectrum_compute(samples, SPECTRUM_SAMPLES, &frame);
    assert(frame.rms == 0.0f);
    assert(frame.peak == 0.0f);
    for (unsigned i = 0; i < SPECTRUM_BANDS; i++)
        assert(frame.bands[i] == 0.0f);
}

static void test_level_metrics(void)
{
    int16_t samples[SPECTRUM_SAMPLES];
    spectrum_frame_t frame;
    make_sine(samples, 250.0, 0.5);
    spectrum_compute(samples, SPECTRUM_SAMPLES, &frame);
    assert(fabsf(frame.rms - 0.3535f) < 0.015f);
    assert(fabsf(frame.peak - 0.5f) < 0.01f);
}

static void test_frequency_response(void)
{
    int16_t samples[SPECTRUM_SAMPLES];
    spectrum_frame_t low;
    spectrum_frame_t high;

    make_sine(samples, 250.0, 0.8);
    spectrum_compute(samples, SPECTRUM_SAMPLES, &low);
    make_sine(samples, 4000.0, 0.8);
    spectrum_compute(samples, SPECTRUM_SAMPLES, &high);

    assert(strongest_band(&low) == 3);
    assert(strongest_band(&high) == 12);
    assert(strongest_band(&low) < strongest_band(&high));
}

int main(void)
{
    test_silence();
    test_level_metrics();
    test_frequency_response();
    puts("spectrum tests passed");
    return 0;
}
