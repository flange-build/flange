#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

#include "netease.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NETEASE_TOKENS_MAX 2048

static int token_equals(const char *json, const jsmntok_t *token,
                        const char *value)
{
    size_t length = (size_t)(token->end - token->start);
    return token->type == JSMN_STRING
        && strlen(value) == length
        && strncmp(json + token->start, value, length) == 0;
}

static int token_after(const jsmntok_t *tokens, int count, int index)
{
    int end = tokens[index].end;
    index++;
    while (index < count && tokens[index].start < end)
        index++;
    return index;
}

static int object_value(const char *json, const jsmntok_t *tokens,
                        int count, int object, const char *key)
{
    if (object < 0 || object >= count
            || tokens[object].type != JSMN_OBJECT)
        return -1;
    int cursor = object + 1;
    while (cursor < count && tokens[cursor].start < tokens[object].end) {
        int value = cursor + 1;
        if (value >= count)
            return -1;
        if (token_equals(json, &tokens[cursor], key))
            return value;
        cursor = token_after(tokens, count, value);
    }
    return -1;
}

static int copy_string(const char *json, const jsmntok_t *token,
                       char *output, size_t size)
{
    if (token == NULL || token->type != JSMN_STRING || size == 0U)
        return -1;
    size_t written = 0U;
    for (int i = token->start; i < token->end; i++) {
        char value = json[i];
        if (value == '\\') {
            i++;
            if (i >= token->end)
                return -1;
            switch (json[i]) {
            case '"': value = '"'; break;
            case '\\': value = '\\'; break;
            case '/': value = '/'; break;
            case 'n': value = '\n'; break;
            case 'r': value = '\r'; break;
            case 't': value = '\t'; break;
            default: return -1;
            }
        }
        if (written + 1U >= size)
            return -1;
        output[written++] = value;
    }
    output[written] = '\0';
    return 0;
}

static int copy_primitive(const char *json, const jsmntok_t *token,
                          char *output, size_t size)
{
    if (token == NULL || token->type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length == 0U || length >= size)
        return -1;
    for (size_t i = 0U; i < length; i++) {
        char value = json[token->start + (int)i];
        if (value < '0' || value > '9')
            return -1;
    }
    memcpy(output, json + token->start, length);
    output[length] = '\0';
    return 0;
}

static int parse_duration(const char *json, const jsmntok_t *token,
                          uint64_t *duration_ms)
{
    char value[24];
    if (copy_primitive(json, token, value, sizeof(value)) != 0)
        return -1;
    char *end = NULL;
    unsigned long long parsed = strtoull(value, &end, 10);
    if (end == value || *end != '\0')
        return -1;
    *duration_ms = (uint64_t)parsed;
    return 0;
}

static int map_song(const char *json, const jsmntok_t *tokens,
                    int count, int object, track_t *track,
                    unsigned rank)
{
    int id = object_value(json, tokens, count, object, "id");
    int name = object_value(json, tokens, count, object, "name");
    int artists = object_value(json, tokens, count, object, "ar");
    int album = object_value(json, tokens, count, object, "al");
    int duration = object_value(json, tokens, count, object, "dt");
    if (id < 0 || name < 0 || artists < 0 || album < 0 || duration < 0
            || tokens[artists].type != JSMN_ARRAY
            || tokens[album].type != JSMN_OBJECT)
        return -1;

    int artist_object = artists + 1;
    int artist_name = object_value(json, tokens, count,
                                   artist_object, "name");
    int cover = object_value(json, tokens, count, album, "picUrl");
    if (artist_name < 0 || cover < 0)
        return -1;

    memset(track, 0, sizeof(*track));
    snprintf(track->source, sizeof(track->source), "netease");
    track->rank = rank;
    track->audio_resolved = 1;
    if (copy_primitive(json, &tokens[id], track->id,
                       sizeof(track->id)) != 0
            || copy_string(json, &tokens[name], track->title,
                           sizeof(track->title)) != 0
            || copy_string(json, &tokens[artist_name], track->artist,
                           sizeof(track->artist)) != 0
            || copy_string(json, &tokens[cover], track->cover_url,
                           sizeof(track->cover_url)) != 0
            || parse_duration(json, &tokens[duration],
                              &track->duration_ms) != 0)
        return -1;
    snprintf(track->share_url, sizeof(track->share_url),
             "https://music.163.com/song?id=%s", track->id);
    return 0;
}

int netease_map_playlist(const char *json, size_t length,
                         track_list_t *tracks, char *error,
                         size_t error_size)
{
    if (json == NULL || length == 0U || length > CONFIG_MAX_BYTES * 8U) {
        snprintf(error, error_size, "网易云歌单响应大小无效");
        return -1;
    }
    jsmn_parser parser;
    jsmntok_t tokens[NETEASE_TOKENS_MAX];
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, length, tokens,
                           NETEASE_TOKENS_MAX);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "网易云歌单 JSON 无效");
        return -1;
    }
    int songs = object_value(json, tokens, count, 0, "songs");
    if (songs < 0 || tokens[songs].type != JSMN_ARRAY) {
        snprintf(error, error_size, "网易云歌单缺少 songs");
        return -1;
    }

    memset(tracks, 0, sizeof(*tracks));
    int cursor = songs + 1;
    while (cursor < count && tokens[cursor].start < tokens[songs].end
            && tracks->count < TRACK_LIST_MAX) {
        if (tokens[cursor].type != JSMN_OBJECT
                || map_song(json, tokens, count, cursor,
                            &tracks->items[tracks->count],
                            (unsigned)tracks->count + 1U) != 0) {
            snprintf(error, error_size, "网易云歌单曲目字段无效");
            return -1;
        }
        tracks->count++;
        cursor = token_after(tokens, count, cursor);
    }
    if (tracks->count == 0U) {
        snprintf(error, error_size, "网易云歌单为空");
        return -1;
    }
    return 0;
}

static int host_has_suffix(const char *host, size_t length,
                           const char *suffix)
{
    size_t suffix_length = strlen(suffix);
    return length >= suffix_length
        && strncmp(host + length - suffix_length,
                   suffix, suffix_length) == 0;
}

static int normalize_audio_url(const char *json, const jsmntok_t *token,
                               char *output, size_t size)
{
    char url[TRACK_URL_SIZE];
    if (copy_string(json, token, url, sizeof(url)) != 0)
        return -1;
    if (strncmp(url, "https://", 8) == 0) {
        snprintf(output, size, "%s", url);
        return 0;
    }
    if (strncmp(url, "http://", 7) != 0)
        return -1;
    const char *host = url + 7;
    const char *path = strchr(host, '/');
    if (path == NULL)
        return -1;
    size_t host_length = (size_t)(path - host);
    if (!host_has_suffix(host, host_length, ".music.126.net")
            && !host_has_suffix(host, host_length, ".music.163.com"))
        return -1;
    int written = snprintf(output, size, "https://%s", host);
    return written > 0 && (size_t)written < size ? 0 : -1;
}

size_t netease_map_urls(const char *json, size_t length,
                        track_list_t *tracks, char *error,
                        size_t error_size)
{
    jsmn_parser parser;
    jsmntok_t tokens[NETEASE_TOKENS_MAX];
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, length, tokens,
                           NETEASE_TOKENS_MAX);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "网易云播放地址 JSON 无效");
        return 0U;
    }
    int data = object_value(json, tokens, count, 0, "data");
    if (data < 0 || tokens[data].type != JSMN_ARRAY) {
        snprintf(error, error_size, "网易云播放地址缺少 data");
        return 0U;
    }

    size_t mapped = 0U;
    int cursor = data + 1;
    while (cursor < count && tokens[cursor].start < tokens[data].end) {
        int id = object_value(json, tokens, count, cursor, "id");
        int url = object_value(json, tokens, count, cursor, "url");
        char id_value[TRACK_ID_SIZE];
        if (id >= 0 && url >= 0 && tokens[url].type == JSMN_STRING
                && copy_primitive(json, &tokens[id], id_value,
                                  sizeof(id_value)) == 0) {
            for (size_t i = 0U; i < tracks->count; i++) {
                if (strcmp(tracks->items[i].id, id_value) != 0)
                    continue;
                if (normalize_audio_url(
                        json, &tokens[url], tracks->items[i].audio_url,
                        sizeof(tracks->items[i].audio_url)) == 0)
                    mapped++;
                break;
            }
        }
        cursor = token_after(tokens, count, cursor);
    }
    error[0] = '\0';
    return mapped;
}
