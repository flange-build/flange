#pragma once

#include <stddef.h>
#include <stdint.h>

#define DECODER_OUTPUT_RATE 16000U
#define DECODER_MAX_SECONDS (15U * 60U)

typedef struct {
    int16_t *samples;
    size_t count;
    unsigned rate;
} decoded_audio_t;

int decoder_decode_wav(const unsigned char *data, size_t size,
                       decoded_audio_t *audio, char *error,
                       size_t error_size);
int decoder_decode_mp3(const unsigned char *data, size_t size,
                       decoded_audio_t *audio, char *error,
                       size_t error_size);
void decoder_audio_free(decoded_audio_t *audio);
