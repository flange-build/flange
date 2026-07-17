#include "spectrum.h"

#include <math.h>
#include <string.h>

#define TWO_PI 6.28318530717958647692

static void fft(float real[SPECTRUM_SAMPLES],
                float imag[SPECTRUM_SAMPLES])
{
    for (unsigned i = 1, j = 0; i < SPECTRUM_SAMPLES; i++) {
        unsigned bit = SPECTRUM_SAMPLES >> 1;
        while ((j & bit) != 0) {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if (i < j) {
            float tmp = real[i];
            real[i] = real[j];
            real[j] = tmp;
            tmp = imag[i];
            imag[i] = imag[j];
            imag[j] = tmp;
        }
    }

    for (unsigned length = 2; length <= SPECTRUM_SAMPLES; length <<= 1) {
        float angle = (float)(-TWO_PI / length);
        float step_real = cosf(angle);
        float step_imag = sinf(angle);
        for (unsigned start = 0; start < SPECTRUM_SAMPLES;
             start += length) {
            float twiddle_real = 1.0f;
            float twiddle_imag = 0.0f;
            unsigned half = length >> 1;
            for (unsigned offset = 0; offset < half; offset++) {
                unsigned even = start + offset;
                unsigned odd = even + half;
                float odd_real = real[odd] * twiddle_real
                    - imag[odd] * twiddle_imag;
                float odd_imag = real[odd] * twiddle_imag
                    + imag[odd] * twiddle_real;
                real[odd] = real[even] - odd_real;
                imag[odd] = imag[even] - odd_imag;
                real[even] += odd_real;
                imag[even] += odd_imag;

                float next_real = twiddle_real * step_real
                    - twiddle_imag * step_imag;
                twiddle_imag = twiddle_real * step_imag
                    + twiddle_imag * step_real;
                twiddle_real = next_real;
            }
        }
    }
}

void spectrum_compute(const int16_t *samples, size_t count,
                      spectrum_frame_t *frame)
{
    static const unsigned upper_bins[SPECTRUM_BANDS] = {
        2, 3, 4, 5, 7, 9, 12, 16,
        21, 28, 37, 49, 65, 84, 106, 128
    };
    float real[SPECTRUM_SAMPLES] = {0};
    float imag[SPECTRUM_SAMPLES] = {0};
    double square_sum = 0.0;
    float peak = 0.0f;

    memset(frame, 0, sizeof(*frame));
    if (count > SPECTRUM_SAMPLES)
        count = SPECTRUM_SAMPLES;
    if (count == 0)
        return;

    for (size_t i = 0; i < count; i++) {
        float sample = samples[i] / 32768.0f;
        float absolute = fabsf(sample);
        if (absolute > peak)
            peak = absolute;
        square_sum += (double)sample * sample;
        float window = count > 1
            ? 0.5f - 0.5f * cosf((float)(TWO_PI * i / (count - 1)))
            : 1.0f;
        real[i] = sample * window;
    }
    frame->rms = (float)sqrt(square_sum / count);
    frame->peak = peak;

    fft(real, imag);

    unsigned lower = 1;
    for (unsigned band = 0; band < SPECTRUM_BANDS; band++) {
        unsigned upper = upper_bins[band];
        float energy = 0.0f;
        unsigned bins = 0;
        for (unsigned bin = lower; bin < upper; bin++) {
            float magnitude = hypotf(real[bin], imag[bin])
                / (SPECTRUM_SAMPLES / 2.0f);
            energy += magnitude * magnitude;
            bins++;
        }
        float magnitude = bins > 0 ? sqrtf(energy / bins) : 0.0f;
        float normalized = log10f(1.0f + magnitude * 40.0f)
            / log10f(41.0f);
        if (normalized > 1.0f)
            normalized = 1.0f;
        frame->bands[band] = normalized;
        lower = upper;
    }
}
