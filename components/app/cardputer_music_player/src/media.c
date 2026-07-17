#include "media.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "http.h"
#include "track.h"

typedef struct {
    unsigned char *data;
    size_t size;
    char content_type[96];
} media_data_t;

static void media_data_free(media_data_t *media)
{
    free(media->data);
    memset(media, 0, sizeof(*media));
}

static int load_local_file(const char *path, size_t max_bytes,
                           media_data_t *media,
                           char *error, size_t error_size)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        snprintf(error, error_size, "无法打开媒体文件: %s",
                 strerror(errno));
        return -1;
    }
    media->data = malloc(max_bytes + 1U);
    if (media->data == NULL) {
        fclose(file);
        snprintf(error, error_size, "媒体内存不足");
        return -1;
    }
    media->size = fread(media->data, 1, max_bytes + 1U, file);
    int read_error = ferror(file);
    fclose(file);
    if (read_error || media->size == 0U || media->size > max_bytes) {
        media_data_free(media);
        snprintf(error, error_size, "媒体文件读取失败、为空或过大");
        return -1;
    }
    return 0;
}

static int load_media(const char *url, size_t max_bytes,
                      media_data_t *media, char *error, size_t error_size)
{
    memset(media, 0, sizeof(*media));
    if (strncmp(url, "file://", 7) == 0) {
        const char *path = url + 7;
        if (path[0] != '/') {
            snprintf(error, error_size, "本地媒体必须使用绝对路径");
            return -1;
        }
        return load_local_file(path, max_bytes, media, error, error_size);
    }
    if (strncmp(url, "https://", 8) != 0) {
        snprintf(error, error_size, "不是授权的 HTTPS/file 媒体地址");
        return -1;
    }
    http_response_t response;
    if (http_get(url, max_bytes, &response, error, error_size) != 0)
        return -1;
    media->data = response.data;
    media->size = response.size;
    snprintf(media->content_type, sizeof(media->content_type),
             "%s", response.content_type);
    response.data = NULL;
    http_response_free(&response);
    return 0;
}

int media_load_audio(const char *url, decoded_audio_t *audio,
                     char *error, size_t error_size)
{
    memset(audio, 0, sizeof(*audio));
    if (!track_audio_url_is_allowed(url)) {
        snprintf(error, error_size, "不是授权的媒体音频地址");
        return -1;
    }
    media_data_t media;
    if (load_media(url, MEDIA_AUDIO_MAX_BYTES, &media,
                   error, error_size) != 0)
        return -1;
    if (strstr(media.content_type, "text/html") != NULL) {
        media_data_free(&media);
        snprintf(error, error_size, "音频地址返回分享页而不是音频");
        return -1;
    }

    int result;
    if (media.size >= 12U && memcmp(media.data, "RIFF", 4) == 0
            && memcmp(media.data + 8, "WAVE", 4) == 0) {
        result = decoder_decode_wav(media.data, media.size, audio,
                                    error, error_size);
    } else {
        result = decoder_decode_mp3(media.data, media.size, audio,
                                    error, error_size);
    }
    media_data_free(&media);
    return result;
}

int media_load_cover(const char *url,
                     uint16_t pixels[COVER_WIDTH * COVER_HEIGHT],
                     uint16_t *theme_color,
                     char *error, size_t error_size)
{
    if (url == NULL || url[0] == '\0') {
        snprintf(error, error_size, "封面 URL 为空");
        return -1;
    }
    media_data_t media;
    if (load_media(url, COVER_MAX_BYTES, &media,
                   error, error_size) != 0)
        return -1;
    if (strstr(media.content_type, "text/html") != NULL) {
        media_data_free(&media);
        snprintf(error, error_size, "封面地址返回 HTML");
        return -1;
    }
    int result = image_decode_cover(media.data, media.size, pixels,
                                    theme_color, error, error_size);
    media_data_free(&media);
    return result;
}
