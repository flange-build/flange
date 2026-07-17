#pragma once

#include <stddef.h>
#include <pthread.h>
#include <stdint.h>

#define AUDIO_RATE 16000
#define AUDIO_CHANNELS 1
#define AUDIO_RING_SAMPLES 8192
#define AUDIO_DEVICE_NAME_SIZE 96

typedef enum {
    AUDIO_STATE_STOPPED = 0,
    AUDIO_STATE_PLAYING,
    AUDIO_STATE_PAUSED,
    AUDIO_STATE_ERROR,
} audio_state_t;

typedef struct {
    pthread_t thread;
    pthread_mutex_t lock;
    int running;
    int paused;
    void *pcm;
    char device[AUDIO_DEVICE_NAME_SIZE];
    char error[160];
    audio_state_t state;
    uint64_t sample_count;
    int16_t *media_samples;
    size_t media_count;
    size_t media_position;
    unsigned media_generation;
    int media_finished;
    unsigned gain_q15;
    int16_t ring[AUDIO_RING_SAMPLES];
    size_t ring_head;
    unsigned underruns;
    unsigned buffer_ms;
} audio_engine_t;

int audio_find_cardputer_device(char *device, size_t size);
int audio_start(audio_engine_t *audio);
int audio_play_pcm(audio_engine_t *audio, const int16_t *samples,
                   size_t count);
void audio_clear_media(audio_engine_t *audio);
void audio_fade_out(audio_engine_t *audio, unsigned duration_ms);
void audio_stop(audio_engine_t *audio);
void audio_toggle_pause(audio_engine_t *audio);
int audio_is_paused(audio_engine_t *audio);
int audio_take_finished(audio_engine_t *audio);
uint64_t audio_position_ms(audio_engine_t *audio);
void audio_recent_samples(audio_engine_t *audio, int16_t *samples, size_t count);
audio_state_t audio_get_state(audio_engine_t *audio);
unsigned audio_get_underruns(audio_engine_t *audio);
const char *audio_get_error(audio_engine_t *audio, char *buffer, size_t size);
