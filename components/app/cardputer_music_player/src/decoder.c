#include "decoder.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef DECODER_WAV_ONLY
#include <mpg123.h>
#endif

typedef struct {
    int16_t *samples;
    size_t count;
    size_t capacity;
    long rate;
    int channels;
} native_pcm_t;

static uint16_t read_le16(const unsigned char *data)
{
    return (uint16_t)data[0] | (uint16_t)((uint16_t)data[1] << 8);
}

static uint32_t read_le32(const unsigned char *data)
{
    return (uint32_t)data[0]
        | ((uint32_t)data[1] << 8)
        | ((uint32_t)data[2] << 16)
        | ((uint32_t)data[3] << 24);
}

#ifndef DECODER_WAV_ONLY
static int append_native(native_pcm_t *pcm, const unsigned char *data,
                         size_t bytes, char *error, size_t error_size)
{
    if (bytes % sizeof(int16_t) != 0) {
        snprintf(error, error_size, "解码器返回了非 16-bit PCM");
        return -1;
    }
    size_t added = bytes / sizeof(int16_t);
    if (added > SIZE_MAX - pcm->count) {
        snprintf(error, error_size, "PCM 数据过大");
        return -1;
    }
    size_t needed = pcm->count + added;
    size_t max_samples = (size_t)DECODER_MAX_SECONDS * 192000U * 2U;
    if (needed > max_samples) {
        snprintf(error, error_size, "音频时长超过 %u 分钟",
                 DECODER_MAX_SECONDS / 60U);
        return -1;
    }
    if (needed > pcm->capacity) {
        size_t capacity = pcm->capacity == 0 ? 8192U : pcm->capacity;
        while (capacity < needed) {
            if (capacity > max_samples / 2U) {
                capacity = max_samples;
                break;
            }
            capacity *= 2U;
        }
        int16_t *resized = realloc(pcm->samples,
                                   capacity * sizeof(*resized));
        if (resized == NULL) {
            snprintf(error, error_size, "PCM 内存不足");
            return -1;
        }
        pcm->samples = resized;
        pcm->capacity = capacity;
    }
    memcpy(pcm->samples + pcm->count, data, bytes);
    pcm->count = needed;
    return 0;
}
#endif

static int convert_to_output(const native_pcm_t *native,
                             decoded_audio_t *audio, char *error,
                             size_t error_size)
{
    if (native->rate < 8000 || native->rate > 192000
            || (native->channels != 1 && native->channels != 2)
            || native->count % (size_t)native->channels != 0) {
        snprintf(error, error_size, "不支持的 PCM 格式");
        return -1;
    }
    size_t input_frames = native->count / (size_t)native->channels;
    if (input_frames == 0) {
        snprintf(error, error_size, "音频没有可解码的 PCM");
        return -1;
    }
    uint64_t output_frames_64 = (uint64_t)input_frames
        * DECODER_OUTPUT_RATE / (uint64_t)native->rate;
    if (output_frames_64 == 0U || output_frames_64 > SIZE_MAX
            || output_frames_64 > (uint64_t)DECODER_MAX_SECONDS
                * DECODER_OUTPUT_RATE) {
        snprintf(error, error_size, "音频时长无效");
        return -1;
    }
    size_t output_frames = (size_t)output_frames_64;
    int16_t *output = malloc(output_frames * sizeof(*output));
    if (output == NULL) {
        snprintf(error, error_size, "PCM 内存不足");
        return -1;
    }

    for (size_t i = 0; i < output_frames; i++) {
        uint64_t numerator = (uint64_t)i * (uint64_t)native->rate;
        size_t first = (size_t)(numerator / DECODER_OUTPUT_RATE);
        unsigned fraction = (unsigned)(numerator % DECODER_OUTPUT_RATE);
        size_t second = first + 1U < input_frames ? first + 1U : first;
        int32_t first_value;
        int32_t second_value;
        if (native->channels == 1) {
            first_value = native->samples[first];
            second_value = native->samples[second];
        } else {
            first_value = ((int32_t)native->samples[first * 2U]
                + native->samples[first * 2U + 1U]) / 2;
            second_value = ((int32_t)native->samples[second * 2U]
                + native->samples[second * 2U + 1U]) / 2;
        }
        int64_t value = (int64_t)first_value
            * (DECODER_OUTPUT_RATE - fraction)
            + (int64_t)second_value * fraction;
        output[i] = (int16_t)(value / DECODER_OUTPUT_RATE);
    }
    audio->samples = output;
    audio->count = output_frames;
    audio->rate = DECODER_OUTPUT_RATE;
    return 0;
}

int decoder_decode_wav(const unsigned char *data, size_t size,
                       decoded_audio_t *audio, char *error,
                       size_t error_size)
{
    memset(audio, 0, sizeof(*audio));
    if (data == NULL || size < 12U
            || memcmp(data, "RIFF", 4) != 0
            || memcmp(data + 8, "WAVE", 4) != 0) {
        snprintf(error, error_size, "WAV 文件头无效");
        return -1;
    }

    unsigned format = 0;
    unsigned channels = 0;
    unsigned rate = 0;
    unsigned bits = 0;
    unsigned block_align = 0;
    const unsigned char *pcm_data = NULL;
    size_t pcm_size = 0;
    for (size_t offset = 12U; offset + 8U <= size;) {
        const unsigned char *chunk = data + offset;
        size_t chunk_size = read_le32(chunk + 4);
        offset += 8U;
        if (chunk_size > size - offset) {
            snprintf(error, error_size, "WAV chunk 越界");
            return -1;
        }
        if (memcmp(chunk, "fmt ", 4) == 0) {
            if (chunk_size < 16U) {
                snprintf(error, error_size, "WAV fmt chunk 太短");
                return -1;
            }
            format = read_le16(data + offset);
            channels = read_le16(data + offset + 2U);
            rate = read_le32(data + offset + 4U);
            block_align = read_le16(data + offset + 12U);
            bits = read_le16(data + offset + 14U);
        } else if (memcmp(chunk, "data", 4) == 0) {
            pcm_data = data + offset;
            pcm_size = chunk_size;
        }
        offset += chunk_size;
        if ((chunk_size & 1U) != 0 && offset < size)
            offset++;
    }
    if (format != 1U || (channels != 1U && channels != 2U)
            || rate < 8000U || rate > 192000U
            || (bits != 8U && bits != 16U) || pcm_data == NULL
            || block_align != channels * bits / 8U
            || block_align == 0U || pcm_size % block_align != 0U) {
        snprintf(error, error_size, "仅支持 8/16-bit mono/stereo PCM WAV");
        return -1;
    }

    size_t frames = pcm_size / block_align;
    if (frames == 0U || frames > (size_t)rate * DECODER_MAX_SECONDS) {
        snprintf(error, error_size, "WAV 时长无效");
        return -1;
    }
    native_pcm_t native = {
        .count = frames * channels,
        .capacity = frames * channels,
        .rate = (long)rate,
        .channels = (int)channels,
    };
    native.samples = malloc(native.count * sizeof(*native.samples));
    if (native.samples == NULL) {
        snprintf(error, error_size, "PCM 内存不足");
        return -1;
    }
    for (size_t i = 0; i < native.count; i++) {
        if (bits == 16U)
            native.samples[i] = (int16_t)read_le16(pcm_data + i * 2U);
        else
            native.samples[i] = (int16_t)(((int)pcm_data[i] - 128) << 8);
    }
    int result = convert_to_output(&native, audio, error, error_size);
    free(native.samples);
    return result;
}

#ifndef DECODER_WAV_ONLY
static int drain_mpg123(mpg123_handle *handle, native_pcm_t *native,
                        unsigned char *buffer, size_t buffer_size,
                        char *error, size_t error_size)
{
    for (;;) {
        size_t decoded = 0;
        int result = mpg123_read(handle, buffer, buffer_size, &decoded);
        if (result == MPG123_NEW_FORMAT) {
            int encoding = 0;
            if (mpg123_getformat(handle, &native->rate,
                                 &native->channels, &encoding) != MPG123_OK
                    || mpg123_encsize(encoding) != 2
                    || (native->channels != 1 && native->channels != 2)) {
                snprintf(error, error_size, "MP3 输出格式不受支持");
                return -1;
            }
            continue;
        }
        if (decoded > 0U
                && append_native(native, buffer, decoded,
                                 error, error_size) != 0)
            return -1;
        if (result == MPG123_OK)
            continue;
        if (result == MPG123_NEED_MORE || result == MPG123_DONE)
            return 0;
        snprintf(error, error_size, "MP3 解码失败: %s",
                 mpg123_strerror(handle));
        return -1;
    }
}

int decoder_decode_mp3(const unsigned char *data, size_t size,
                       decoded_audio_t *audio, char *error,
                       size_t error_size)
{
    memset(audio, 0, sizeof(*audio));
    if (data == NULL || size == 0U) {
        snprintf(error, error_size, "MP3 数据为空");
        return -1;
    }
    if (mpg123_init() != MPG123_OK) {
        snprintf(error, error_size, "无法初始化 mpg123");
        return -1;
    }
    int mpg_error = MPG123_OK;
    mpg123_handle *handle = mpg123_new(NULL, &mpg_error);
    if (handle == NULL) {
        snprintf(error, error_size, "无法创建 mpg123 decoder");
        mpg123_exit();
        return -1;
    }
    mpg123_format_none(handle);
    const long *rates = NULL;
    size_t rate_count = 0;
    mpg123_rates(&rates, &rate_count);
    for (size_t i = 0; i < rate_count; i++) {
        mpg123_format(handle, rates[i], MPG123_MONO | MPG123_STEREO,
                      MPG123_ENC_SIGNED_16);
    }
    if (mpg123_open_feed(handle) != MPG123_OK) {
        snprintf(error, error_size, "无法启动 mpg123 feed decoder");
        mpg123_delete(handle);
        mpg123_exit();
        return -1;
    }

    size_t block_size = mpg123_outblock(handle);
    if (block_size < 4096U)
        block_size = 4096U;
    unsigned char *buffer = malloc(block_size);
    native_pcm_t native = {0};
    int result = buffer == NULL ? -1 : 0;
    if (buffer == NULL)
        snprintf(error, error_size, "MP3 解码内存不足");

    for (size_t offset = 0; result == 0 && offset < size;) {
        size_t chunk = size - offset;
        if (chunk > 16384U)
            chunk = 16384U;
        if (mpg123_feed(handle, data + offset, chunk) != MPG123_OK) {
            snprintf(error, error_size, "MP3 feed 失败: %s",
                     mpg123_strerror(handle));
            result = -1;
            break;
        }
        offset += chunk;
        result = drain_mpg123(handle, &native, buffer, block_size,
                              error, error_size);
    }
    if (result == 0 && native.count == 0U) {
        snprintf(error, error_size, "MP3 没有可解码的音频帧");
        result = -1;
    }
    if (result == 0)
        result = convert_to_output(&native, audio, error, error_size);

    free(native.samples);
    free(buffer);
    mpg123_close(handle);
    mpg123_delete(handle);
    mpg123_exit();
    return result;
}
#endif

void decoder_audio_free(decoded_audio_t *audio)
{
    free(audio->samples);
    memset(audio, 0, sizeof(*audio));
}
