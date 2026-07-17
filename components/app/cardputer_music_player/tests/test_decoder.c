#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "decoder.h"

static void write_le16(unsigned char *output, uint16_t value)
{
    output[0] = (unsigned char)(value & 0xffU);
    output[1] = (unsigned char)(value >> 8);
}

static void write_le32(unsigned char *output, uint32_t value)
{
    output[0] = (unsigned char)(value & 0xffU);
    output[1] = (unsigned char)((value >> 8) & 0xffU);
    output[2] = (unsigned char)((value >> 16) & 0xffU);
    output[3] = (unsigned char)(value >> 24);
}

static void test_pcm_wav(void)
{
    unsigned char wav[44 + 16] = {0};
    memcpy(wav, "RIFF", 4);
    write_le32(wav + 4, sizeof(wav) - 8U);
    memcpy(wav + 8, "WAVEfmt ", 8);
    write_le32(wav + 16, 16);
    write_le16(wav + 20, 1);
    write_le16(wav + 22, 1);
    write_le32(wav + 24, 8000);
    write_le32(wav + 28, 16000);
    write_le16(wav + 32, 2);
    write_le16(wav + 34, 16);
    memcpy(wav + 36, "data", 4);
    write_le32(wav + 40, 16);
    for (size_t i = 0; i < 8; i++)
        write_le16(wav + 44 + i * 2U, (uint16_t)(i * 1000U));

    decoded_audio_t audio;
    char error[160] = {0};
    assert(decoder_decode_wav(wav, sizeof(wav), &audio,
                              error, sizeof(error)) == 0);
    assert(audio.rate == DECODER_OUTPUT_RATE);
    assert(audio.count == 16);
    assert(audio.samples[0] == 0);
    assert(audio.samples[2] == 1000);
    decoder_audio_free(&audio);
}

static void test_invalid_wav(void)
{
    static const unsigned char invalid[] = "not a wav";
    decoded_audio_t audio;
    char error[160] = {0};
    assert(decoder_decode_wav(invalid, sizeof(invalid), &audio,
                              error, sizeof(error)) != 0);
}

static void test_long_pcm_wav(void)
{
    const uint32_t rate = 16000U;
    const uint32_t frames = rate * 20U;
    const size_t size = 44U + (size_t)frames * 2U;
    unsigned char *wav = calloc(1U, size);
    assert(wav != NULL);
    memcpy(wav, "RIFF", 4);
    write_le32(wav + 4, (uint32_t)size - 8U);
    memcpy(wav + 8, "WAVEfmt ", 8);
    write_le32(wav + 16, 16U);
    write_le16(wav + 20, 1U);
    write_le16(wav + 22, 1U);
    write_le32(wav + 24, rate);
    write_le32(wav + 28, rate * 2U);
    write_le16(wav + 32, 2U);
    write_le16(wav + 34, 16U);
    memcpy(wav + 36, "data", 4);
    write_le32(wav + 40, frames * 2U);

    decoded_audio_t audio;
    char error[160] = {0};
    assert(decoder_decode_wav(wav, size, &audio,
                              error, sizeof(error)) == 0);
    assert(audio.count == frames);
    decoder_audio_free(&audio);
    free(wav);
}

int main(void)
{
    test_pcm_wav();
    test_long_pcm_wav();
    test_invalid_wav();
    puts("decoder tests passed");
    return 0;
}
