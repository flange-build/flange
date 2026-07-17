#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

#include "provider.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "manifest.h"

#define PROVIDER_TOKENS_MAX 1024

typedef struct {
    char *data;
    size_t size;
    size_t capacity;
} json_builder_t;

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

static int first_object_value(const char *json, const jsmntok_t *tokens,
                              int count, int object,
                              const char *const *keys, size_t key_count)
{
    for (size_t i = 0; i < key_count; i++) {
        int value = object_value(json, tokens, count, object, keys[i]);
        if (value >= 0)
            return value;
    }
    return -1;
}

static int builder_reserve(json_builder_t *builder, size_t extra)
{
    if (extra > MANIFEST_MAX_BYTES - builder->size)
        return -1;
    size_t needed = builder->size + extra + 1U;
    if (needed <= builder->capacity)
        return 0;
    size_t capacity = builder->capacity == 0U ? 1024U : builder->capacity;
    while (capacity < needed)
        capacity *= 2U;
    if (capacity > MANIFEST_MAX_BYTES + 1U)
        capacity = MANIFEST_MAX_BYTES + 1U;
    char *resized = realloc(builder->data, capacity);
    if (resized == NULL)
        return -1;
    builder->data = resized;
    builder->capacity = capacity;
    return 0;
}

static int builder_append(json_builder_t *builder, const char *value,
                          size_t length)
{
    if (builder_reserve(builder, length) != 0)
        return -1;
    memcpy(builder->data + builder->size, value, length);
    builder->size += length;
    builder->data[builder->size] = '\0';
    return 0;
}

static int builder_printf(json_builder_t *builder, const char *format, ...)
{
    char buffer[96];
    va_list arguments;
    va_start(arguments, format);
    int written = vsnprintf(buffer, sizeof(buffer), format, arguments);
    va_end(arguments);
    if (written < 0 || (size_t)written >= sizeof(buffer))
        return -1;
    return builder_append(builder, buffer, (size_t)written);
}

static int builder_raw_string(json_builder_t *builder, const char *json,
                              const jsmntok_t *token)
{
    if (token == NULL || token->type != JSMN_STRING)
        return builder_append(builder, "\"\"", 2U);
    if (builder_append(builder, "\"", 1U) != 0
            || builder_append(builder, json + token->start,
                              (size_t)(token->end - token->start)) != 0
            || builder_append(builder, "\"", 1U) != 0)
        return -1;
    return 0;
}

static int parse_unsigned(const char *json, const jsmntok_t *token,
                          uint64_t *value)
{
    if (token == NULL || token->type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length == 0U || length >= 24U)
        return -1;
    char buffer[24];
    memcpy(buffer, json + token->start, length);
    buffer[length] = '\0';
    char *end = NULL;
    unsigned long long parsed = strtoull(buffer, &end, 10);
    if (end == buffer || *end != '\0')
        return -1;
    *value = parsed;
    return 0;
}

static const jsmntok_t *optional_token(const jsmntok_t *tokens, int index)
{
    return index >= 0 ? &tokens[index] : NULL;
}

static int append_track(json_builder_t *builder, const char *json,
                        const jsmntok_t *tokens, int count, int object,
                        size_t output_index)
{
    static const char *const id_keys[] = {"id", "music_id"};
    static const char *const title_keys[] = {"title", "music_name"};
    static const char *const artist_keys[] = {"author", "artist"};
    static const char *const cover_keys[] = {"cover", "cover_url"};
    static const char *const share_keys[] = {"share_url", "share_link"};
    int id = first_object_value(json, tokens, count, object,
                                id_keys, 2U);
    int title = first_object_value(json, tokens, count, object,
                                   title_keys, 2U);
    int artist = first_object_value(json, tokens, count, object,
                                    artist_keys, 2U);
    int cover = first_object_value(json, tokens, count, object,
                                   cover_keys, 2U);
    int share = first_object_value(json, tokens, count, object,
                                   share_keys, 2U);
    int rank = object_value(json, tokens, count, object, "rank");
    int duration = object_value(json, tokens, count, object, "duration");
    if (title < 0 || artist < 0
            || tokens[title].type != JSMN_STRING
            || tokens[artist].type != JSMN_STRING)
        return -1;

    uint64_t rank_value = output_index + 1U;
    uint64_t duration_seconds = 0;
    if (rank >= 0 && parse_unsigned(json, &tokens[rank], &rank_value) != 0)
        return -1;
    if (duration >= 0
            && parse_unsigned(json, &tokens[duration],
                              &duration_seconds) != 0)
        return -1;
    if (duration_seconds > UINT64_MAX / 1000U)
        return -1;

    if (output_index > 0U && builder_append(builder, ",", 1U) != 0)
        return -1;
    if (builder_printf(builder,
                       "{\"source\":\"douyin\",\"rank\":%llu,\"id\":",
                       (unsigned long long)rank_value) != 0
            || builder_raw_string(builder, json,
                                  optional_token(tokens, id)) != 0
            || builder_append(builder, ",\"title\":", 9U) != 0
            || builder_raw_string(builder, json, &tokens[title]) != 0
            || builder_append(builder, ",\"artist\":", 10U) != 0
            || builder_raw_string(builder, json, &tokens[artist]) != 0
            || builder_printf(builder, ",\"duration_ms\":%llu,\"cover_url\":",
                              (unsigned long long)(duration_seconds * 1000U))
                != 0
            || builder_raw_string(builder, json,
                                  optional_token(tokens, cover)) != 0
            || builder_append(builder, ",\"share_url\":", 13U) != 0
            || builder_raw_string(builder, json,
                                  optional_token(tokens, share)) != 0
            || builder_append(builder, "}", 1U) != 0)
        return -1;
    return 0;
}

int provider_map_douyin(const char *json, size_t length,
                        track_list_t *tracks, char *error,
                        size_t error_size)
{
    if (json == NULL || length == 0U || length > MANIFEST_MAX_BYTES) {
        snprintf(error, error_size, "抖音榜单响应大小无效");
        return -1;
    }
    jsmn_parser parser;
    jsmntok_t tokens[PROVIDER_TOKENS_MAX];
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, length, tokens,
                           PROVIDER_TOKENS_MAX);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "抖音榜单 JSON 格式无效");
        return -1;
    }
    /* 允许用户 broker 直接返回统一 Manifest，避免设备理解业务私有字段。 */
    if (object_value(json, tokens, count, 0, "tracks") >= 0)
        return manifest_parse(json, length, tracks, error, error_size);
    int data = object_value(json, tokens, count, 0, "data");
    if (data < 0 || tokens[data].type != JSMN_OBJECT) {
        snprintf(error, error_size, "抖音榜单缺少 data");
        return -1;
    }
    int list = object_value(json, tokens, count, data, "list");
    if (list < 0)
        list = object_value(json, tokens, count, data, "music_list");
    if (list < 0 || tokens[list].type != JSMN_ARRAY) {
        snprintf(error, error_size, "抖音榜单缺少 list/music_list");
        return -1;
    }

    json_builder_t builder = {0};
    int result = builder_append(&builder, "{\"tracks\":[", 11U);
    size_t output_index = 0;
    int cursor = list + 1;
    while (result == 0 && cursor < count
            && tokens[cursor].start < tokens[list].end) {
        if (output_index >= TRACK_LIST_MAX
                || tokens[cursor].type != JSMN_OBJECT
                || append_track(&builder, json, tokens, count,
                                cursor, output_index) != 0) {
            result = -1;
            break;
        }
        output_index++;
        cursor = token_after(tokens, count, cursor);
    }
    if (result == 0)
        result = builder_append(&builder, "]}", 2U);
    if (result != 0 || output_index == 0U) {
        snprintf(error, error_size, "抖音榜单曲目格式无效");
        free(builder.data);
        return -1;
    }
    result = manifest_parse(builder.data, builder.size, tracks,
                            error, error_size);
    free(builder.data);
    return result;
}

size_t provider_merge_resolutions(track_list_t *tracks,
                                  const track_list_t *resolutions)
{
    size_t merged = 0;
    for (size_t i = 0; i < tracks->count; i++) {
        track_t *track = &tracks->items[i];
        for (size_t j = 0; j < resolutions->count; j++) {
            const track_t *resolution = &resolutions->items[j];
            int id_matches = track->id[0] != '\0'
                && resolution->id[0] != '\0'
                && strcmp(track->id, resolution->id) == 0;
            int share_matches = track->share_url[0] != '\0'
                && resolution->share_url[0] != '\0'
                && strcmp(track->share_url, resolution->share_url) == 0;
            if (!id_matches && !share_matches)
                continue;
            if (track_audio_url_is_allowed(resolution->audio_url)) {
                snprintf(track->audio_url, sizeof(track->audio_url),
                         "%s", resolution->audio_url);
                merged++;
            }
            break;
        }
    }
    return merged;
}
