#include "audio.h"

#include <alsa/asoundlib.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "device_match.h"

#define AUDIO_CHUNK 256
#define AUDIO_LATENCY_US 500000

static void set_error(audio_engine_t *audio, const char *operation, int error)
{
    pthread_mutex_lock(&audio->lock);
    snprintf(audio->error, sizeof(audio->error), "%s: %s",
             operation, snd_strerror(error));
    audio->state = AUDIO_STATE_ERROR;
    pthread_mutex_unlock(&audio->lock);
}

int audio_find_cardputer_device(char *device, size_t size)
{
    void **hints = NULL;
    int error = snd_device_name_hint(-1, "pcm", &hints);
    if (error < 0)
        return error;

    int result = -ENOENT;
    for (void **cursor = hints; *cursor != NULL; cursor++) {
        char *name = snd_device_name_get_hint(*cursor, "NAME");
        char *description = snd_device_name_get_hint(*cursor, "DESC");
        char *io = snd_device_name_get_hint(*cursor, "IOID");
        if (name != NULL
                && device_match_cardputer_pcm(name, description, io)
                && device_make_plughw(name, device, size) == 0) {
            result = 0;
            free(name);
            free(description);
            free(io);
            break;
        }

        free(name);
        free(description);
        free(io);
    }
    snd_device_name_free_hint(hints);
    return result;
}

static void ring_write(audio_engine_t *audio, const int16_t *samples,
                       size_t count)
{
    pthread_mutex_lock(&audio->lock);
    for (size_t i = 0; i < count; i++) {
        audio->ring[audio->ring_head] = samples[i];
        audio->ring_head = (audio->ring_head + 1) % AUDIO_RING_SAMPLES;
    }
    pthread_mutex_unlock(&audio->lock);
}

static int recover_pcm(audio_engine_t *audio, int error)
{
    snd_pcm_t *pcm = audio->pcm;
    if (error == -EPIPE) {
        pthread_mutex_lock(&audio->lock);
        audio->underruns++;
        unsigned underruns = audio->underruns;
        pthread_mutex_unlock(&audio->lock);
        fprintf(stderr, "[audio] 检测到 underrun，累计 %u 次\n",
                underruns);
        return snd_pcm_prepare(pcm);
    }
    if (error == -ESTRPIPE) {
        while ((error = snd_pcm_resume(pcm)) == -EAGAIN)
            snd_pcm_wait(pcm, 100);
        if (error < 0)
            error = snd_pcm_prepare(pcm);
        return error;
    }
    return error;
}

static int write_frames(audio_engine_t *audio, const int16_t *samples,
                        snd_pcm_uframes_t frames)
{
    snd_pcm_t *pcm = audio->pcm;
    snd_pcm_uframes_t offset = 0;
    while (offset < frames) {
        snd_pcm_sframes_t written = snd_pcm_writei(
            pcm,
            samples + offset * AUDIO_CHANNELS,
            frames - offset
        );
        if (written == -EINTR)
            continue;
        if (written < 0) {
            int recovered = recover_pcm(audio, (int)written);
            if (recovered < 0)
                return recovered;
            continue;
        }
        offset += (snd_pcm_uframes_t)written;
    }
    return 0;
}

static void *audio_thread(void *opaque)
{
    audio_engine_t *audio = opaque;
    int16_t samples[AUDIO_CHUNK];

    fprintf(stderr, "[audio] 播放线程已就绪 -> %s\n", audio->device);
    for (;;) {
        pthread_mutex_lock(&audio->lock);
        int running = audio->running;
        int paused = audio->paused;
        unsigned gain_q15 = audio->gain_q15;
        unsigned media_generation = audio->media_generation;
        size_t active_samples = 0U;
        if (!paused && audio->media_samples != NULL
                && audio->media_position < audio->media_count) {
            active_samples = audio->media_count - audio->media_position;
            if (active_samples > AUDIO_CHUNK)
                active_samples = AUDIO_CHUNK;
        }
        for (size_t i = 0; i < AUDIO_CHUNK; i++) {
            if (paused) {
                samples[i] = 0;
            } else if (i < active_samples) {
                samples[i] =
                    audio->media_samples[audio->media_position + i];
            } else {
                samples[i] = 0;
            }
            samples[i] = (int16_t)((int32_t)samples[i]
                * (int32_t)gain_q15 / 32768);
        }
        pthread_mutex_unlock(&audio->lock);
        if (!running)
            break;

        int error = write_frames(audio, samples, AUDIO_CHUNK);
        if (error < 0) {
            fprintf(stderr, "[audio] PCM 写入失败: %s\n",
                    snd_strerror(error));
            set_error(audio, "PCM 写入失败", error);
            break;
        }

        ring_write(audio, samples, AUDIO_CHUNK);
        if (!paused) {
            pthread_mutex_lock(&audio->lock);
            if (audio->media_generation == media_generation) {
                audio->sample_count += active_samples;
                audio->media_position += active_samples;
                if (audio->media_count > 0U
                        && audio->media_position >= audio->media_count) {
                    audio->media_finished = 1;
                    audio->state = AUDIO_STATE_STOPPED;
                }
            }
            pthread_mutex_unlock(&audio->lock);
        }
    }
    return NULL;
}

static int configure_pcm(audio_engine_t *audio)
{
    snd_pcm_t *pcm = NULL;
    int error = snd_pcm_open(
        &pcm,
        audio->device,
        SND_PCM_STREAM_PLAYBACK,
        0
    );
    if (error < 0)
        return error;

    error = snd_pcm_set_params(
        pcm,
        SND_PCM_FORMAT_S16_LE,
        SND_PCM_ACCESS_RW_INTERLEAVED,
        AUDIO_CHANNELS,
        AUDIO_RATE,
        1,
        AUDIO_LATENCY_US
    );
    if (error < 0) {
        snd_pcm_close(pcm);
        return error;
    }

    snd_pcm_uframes_t buffer_frames = 0;
    snd_pcm_uframes_t period_frames = 0;
    error = snd_pcm_get_params(pcm, &buffer_frames, &period_frames);
    if (error < 0) {
        snd_pcm_close(pcm);
        return error;
    }
    (void)period_frames;
    audio->buffer_ms = (unsigned)(buffer_frames * 1000 / AUDIO_RATE);
    if (audio->buffer_ms < 250) {
        snd_pcm_close(pcm);
        return -EINVAL;
    }

    audio->pcm = pcm;
    return 0;
}

int audio_start(audio_engine_t *audio)
{
    memset(audio, 0, sizeof(*audio));
    if (pthread_mutex_init(&audio->lock, NULL) != 0)
        return -1;

    int error = audio_find_cardputer_device(
        audio->device,
        sizeof(audio->device)
    );
    if (error < 0) {
        snprintf(audio->error, sizeof(audio->error),
                 "未找到 Cardputer UAC1 playback PCM");
        audio->state = AUDIO_STATE_ERROR;
        pthread_mutex_destroy(&audio->lock);
        fprintf(stderr, "[audio] %s\n", audio->error);
        return -1;
    }

    error = configure_pcm(audio);
    if (error < 0) {
        snprintf(audio->error, sizeof(audio->error),
                 "无法配置 %s: %s", audio->device, snd_strerror(error));
        audio->state = AUDIO_STATE_ERROR;
        pthread_mutex_destroy(&audio->lock);
        fprintf(stderr, "[audio] %s\n", audio->error);
        return -1;
    }

    audio->running = 1;
    audio->gain_q15 = 32768U;
    audio->state = AUDIO_STATE_PLAYING;
    if (pthread_create(&audio->thread, NULL, audio_thread, audio) != 0) {
        snd_pcm_close(audio->pcm);
        audio->pcm = NULL;
        pthread_mutex_destroy(&audio->lock);
        return -1;
    }
    fprintf(stderr, "[audio] 使用 %s，%u ms 缓冲\n",
            audio->device, audio->buffer_ms);
    return 0;
}

void audio_stop(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    audio->running = 0;
    pthread_mutex_unlock(&audio->lock);
    (void)pthread_join(audio->thread, NULL);
    if (audio->pcm != NULL) {
        snd_pcm_drop(audio->pcm);
        snd_pcm_close(audio->pcm);
        audio->pcm = NULL;
    }
    free(audio->media_samples);
    audio->media_samples = NULL;
    audio->media_count = 0;
    audio->state = AUDIO_STATE_STOPPED;
    pthread_mutex_destroy(&audio->lock);
}

int audio_play_pcm(audio_engine_t *audio, const int16_t *samples,
                   size_t count)
{
    if (samples == NULL || count == 0U
            || count > (size_t)AUDIO_RATE * 15U * 60U)
        return -1;
    int16_t *copy = malloc(count * sizeof(*copy));
    if (copy == NULL)
        return -1;
    memcpy(copy, samples, count * sizeof(*copy));

    pthread_mutex_lock(&audio->lock);
    int16_t *previous = audio->media_samples;
    audio->media_samples = copy;
    audio->media_count = count;
    audio->media_position = 0;
    audio->media_generation++;
    audio->media_finished = 0;
    audio->sample_count = 0;
    audio->paused = 0;
    audio->gain_q15 = 32768U;
    audio->state = AUDIO_STATE_PLAYING;
    pthread_mutex_unlock(&audio->lock);
    free(previous);
    return 0;
}

void audio_clear_media(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    int16_t *previous = audio->media_samples;
    audio->media_samples = NULL;
    audio->media_count = 0;
    audio->media_position = 0;
    audio->media_generation++;
    audio->media_finished = 0;
    audio->sample_count = 0;
    audio->paused = 0;
    audio->gain_q15 = 32768U;
    audio->state = AUDIO_STATE_STOPPED;
    pthread_mutex_unlock(&audio->lock);
    free(previous);
}

void audio_fade_out(audio_engine_t *audio, unsigned duration_ms)
{
    if (duration_ms == 0U)
        return;
    if (duration_ms > 500U)
        duration_ms = 500U;
    const unsigned steps = 8U;
    for (unsigned step = 0; step < steps; step++) {
        pthread_mutex_lock(&audio->lock);
        audio->gain_q15 = 32768U * (steps - step - 1U) / steps;
        pthread_mutex_unlock(&audio->lock);
        usleep((useconds_t)(duration_ms * 1000U / steps));
    }
}

void audio_toggle_pause(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    audio->paused = !audio->paused;
    audio->state = audio->paused
        ? AUDIO_STATE_PAUSED : AUDIO_STATE_PLAYING;
    pthread_mutex_unlock(&audio->lock);
}

int audio_is_paused(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    int paused = audio->paused;
    pthread_mutex_unlock(&audio->lock);
    return paused;
}

int audio_take_finished(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    int finished = audio->media_finished;
    audio->media_finished = 0;
    pthread_mutex_unlock(&audio->lock);
    return finished;
}

uint64_t audio_position_ms(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    uint64_t samples = audio->sample_count;
    pthread_mutex_unlock(&audio->lock);
    return samples * 1000 / AUDIO_RATE;
}

void audio_recent_samples(audio_engine_t *audio, int16_t *samples, size_t count)
{
    if (count > AUDIO_RING_SAMPLES)
        count = AUDIO_RING_SAMPLES;
    pthread_mutex_lock(&audio->lock);
    size_t start = (audio->ring_head + AUDIO_RING_SAMPLES - count)
        % AUDIO_RING_SAMPLES;
    for (size_t i = 0; i < count; i++)
        samples[i] = audio->ring[(start + i) % AUDIO_RING_SAMPLES];
    pthread_mutex_unlock(&audio->lock);
}

audio_state_t audio_get_state(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    audio_state_t state = audio->state;
    pthread_mutex_unlock(&audio->lock);
    return state;
}

unsigned audio_get_underruns(audio_engine_t *audio)
{
    pthread_mutex_lock(&audio->lock);
    unsigned underruns = audio->underruns;
    pthread_mutex_unlock(&audio->lock);
    return underruns;
}

const char *audio_get_error(audio_engine_t *audio, char *buffer, size_t size)
{
    pthread_mutex_lock(&audio->lock);
    snprintf(buffer, size, "%s", audio->error);
    pthread_mutex_unlock(&audio->lock);
    return buffer;
}
