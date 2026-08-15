#include "audio_frame.h"

void audio_frame_mono_to_stereo(const int16_t *mono, int16_t *stereo, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        stereo[2 * i]     = mono[i];
        stereo[2 * i + 1] = mono[i];
    }
}

void audio_frame_stereo_to_mono(const int16_t *stereo, int16_t *mono, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        /* int32 中间量：两个 int16 之和最多 ±65536，放不进 int16。
         * 右移一位相当于向下取整的除 2，见头文件里为什么刻意不用 /2。 */
        const int32_t sum = (int32_t)stereo[2 * i] + (int32_t)stereo[2 * i + 1];
        mono[i] = (int16_t)(sum >> 1);
    }
}
