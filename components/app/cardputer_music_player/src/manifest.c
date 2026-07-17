#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

#include "manifest.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MANIFEST_TOKENS_MAX 1024

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
                        int count, int object_index, const char *key)
{
    if (object_index < 0 || object_index >= count
            || tokens[object_index].type != JSMN_OBJECT)
        return -1;
    int cursor = object_index + 1;
    while (cursor < count && tokens[cursor].start < tokens[object_index].end) {
        int value = cursor + 1;
        if (value >= count)
            return -1;
        if (token_equals(json, &tokens[cursor], key))
            return value;
        cursor = token_after(tokens, count, value);
    }
    return -1;
}

static int append_utf8(char *output, size_t size, size_t *written,
                       uint32_t codepoint)
{
    unsigned char encoded[4];
    size_t length;
    if (codepoint <= 0x7f) {
        encoded[0] = (unsigned char)codepoint;
        length = 1;
    } else if (codepoint <= 0x7ff) {
        encoded[0] = (unsigned char)(0xc0 | (codepoint >> 6));
        encoded[1] = (unsigned char)(0x80 | (codepoint & 0x3f));
        length = 2;
    } else if (codepoint <= 0xffff) {
        encoded[0] = (unsigned char)(0xe0 | (codepoint >> 12));
        encoded[1] = (unsigned char)(0x80 | ((codepoint >> 6) & 0x3f));
        encoded[2] = (unsigned char)(0x80 | (codepoint & 0x3f));
        length = 3;
    } else {
        encoded[0] = (unsigned char)(0xf0 | (codepoint >> 18));
        encoded[1] = (unsigned char)(0x80 | ((codepoint >> 12) & 0x3f));
        encoded[2] = (unsigned char)(0x80 | ((codepoint >> 6) & 0x3f));
        encoded[3] = (unsigned char)(0x80 | (codepoint & 0x3f));
        length = 4;
    }
    if (*written + length >= size)
        return -1;
    memcpy(output + *written, encoded, length);
    *written += length;
    return 0;
}

static int hex_digit(char value)
{
    if (value >= '0' && value <= '9')
        return value - '0';
    if (value >= 'a' && value <= 'f')
        return value - 'a' + 10;
    if (value >= 'A' && value <= 'F')
        return value - 'A' + 10;
    return -1;
}

static int copy_string(const char *json, const jsmntok_t *token,
                       char *output, size_t size)
{
    if (token->type != JSMN_STRING || size == 0)
        return -1;
    size_t written = 0;
    for (int i = token->start; i < token->end; i++) {
        unsigned char value = (unsigned char)json[i];
        if (value != '\\') {
            if (written + 1 >= size)
                return -1;
            output[written++] = (char)value;
            continue;
        }
        i++;
        if (i >= token->end)
            return -1;
        char escaped = json[i];
        if (escaped == 'u') {
            if (i + 4 >= token->end)
                return -1;
            uint32_t codepoint = 0;
            for (int digit = 0; digit < 4; digit++) {
                int parsed = hex_digit(json[++i]);
                if (parsed < 0)
                    return -1;
                codepoint = (codepoint << 4) | (uint32_t)parsed;
            }
            if (append_utf8(output, size, &written, codepoint) != 0)
                return -1;
            continue;
        }
        char decoded;
        switch (escaped) {
        case '"': decoded = '"'; break;
        case '\\': decoded = '\\'; break;
        case '/': decoded = '/'; break;
        case 'b': decoded = '\b'; break;
        case 'f': decoded = '\f'; break;
        case 'n': decoded = '\n'; break;
        case 'r': decoded = '\r'; break;
        case 't': decoded = '\t'; break;
        default: return -1;
        }
        if (written + 1 >= size)
            return -1;
        output[written++] = decoded;
    }
    output[written] = '\0';
    return 0;
}

static int parse_unsigned(const char *json, const jsmntok_t *token,
                          uint64_t *value)
{
    if (token->type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length == 0 || length >= 32)
        return -1;
    char buffer[32];
    memcpy(buffer, json + token->start, length);
    buffer[length] = '\0';
    char *end = NULL;
    errno = 0;
    unsigned long long parsed = strtoull(buffer, &end, 10);
    if (errno != 0 || end == buffer || *end != '\0')
        return -1;
    *value = (uint64_t)parsed;
    return 0;
}

static int optional_string(const char *json, const jsmntok_t *tokens,
                           int count, int object, const char *key,
                           char *output, size_t size)
{
    int value = object_value(json, tokens, count, object, key);
    if (value < 0) {
        output[0] = '\0';
        return 0;
    }
    return copy_string(json, &tokens[value], output, size);
}

static int parse_track(const char *json, const jsmntok_t *tokens,
                       int count, int object, track_t *track)
{
    memset(track, 0, sizeof(*track));
    if (optional_string(json, tokens, count, object, "id",
                        track->id, sizeof(track->id)) != 0
            || optional_string(json, tokens, count, object, "source",
                               track->source, sizeof(track->source)) != 0
            || optional_string(json, tokens, count, object, "title",
                               track->title, sizeof(track->title)) != 0
            || optional_string(json, tokens, count, object, "artist",
                               track->artist, sizeof(track->artist)) != 0
            || optional_string(json, tokens, count, object, "cover_url",
                               track->cover_url,
                               sizeof(track->cover_url)) != 0
            || optional_string(json, tokens, count, object, "audio_url",
                               track->audio_url,
                               sizeof(track->audio_url)) != 0
            || optional_string(json, tokens, count, object, "share_url",
                               track->share_url,
                               sizeof(track->share_url)) != 0)
        return -1;

    if (track->source[0] == '\0' || track->title[0] == '\0'
            || track->artist[0] == '\0')
        return -1;
    if (track->audio_url[0] != '\0'
            && !track_audio_url_is_allowed(track->audio_url))
        return -1;

    int rank = object_value(json, tokens, count, object, "rank");
    if (rank >= 0) {
        uint64_t parsed = 0;
        if (parse_unsigned(json, &tokens[rank], &parsed) != 0
                || parsed > 1000000)
            return -1;
        track->rank = (unsigned)parsed;
    }
    int duration = object_value(json, tokens, count, object, "duration_ms");
    if (duration >= 0
            && parse_unsigned(json, &tokens[duration],
                              &track->duration_ms) != 0)
        return -1;
    track->audio_resolved = 1;
    return 0;
}

int manifest_parse(const char *json, size_t length, track_list_t *tracks,
                   char *error, size_t error_size)
{
    jsmn_parser parser;
    jsmntok_t tokens[MANIFEST_TOKENS_MAX];
    memset(tracks, 0, sizeof(*tracks));
    if (length == 0 || length > MANIFEST_MAX_BYTES) {
        snprintf(error, error_size, "Manifest 大小无效");
        return -1;
    }

    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, length, tokens,
                           MANIFEST_TOKENS_MAX);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "Manifest JSON 格式无效");
        return -1;
    }
    int array = object_value(json, tokens, count, 0, "tracks");
    if (array < 0 || tokens[array].type != JSMN_ARRAY) {
        snprintf(error, error_size, "Manifest 缺少 tracks 数组");
        return -1;
    }

    int cursor = array + 1;
    while (cursor < count && tokens[cursor].start < tokens[array].end) {
        if (tracks->count >= TRACK_LIST_MAX) {
            snprintf(error, error_size, "Manifest 曲目超过 %d 首",
                     TRACK_LIST_MAX);
            return -1;
        }
        if (tokens[cursor].type != JSMN_OBJECT
                || parse_track(json, tokens, count, cursor,
                               &tracks->items[tracks->count]) != 0) {
            snprintf(error, error_size, "Manifest 第 %zu 首曲目无效",
                     tracks->count + 1);
            return -1;
        }
        tracks->count++;
        cursor = token_after(tokens, count, cursor);
    }
    if (tracks->count == 0) {
        snprintf(error, error_size, "Manifest tracks 不能为空");
        return -1;
    }
    return 0;
}

int manifest_load_file(const char *path, track_list_t *tracks,
                       char *error, size_t error_size)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        snprintf(error, error_size, "无法打开 Manifest: %s",
                 strerror(errno));
        return -1;
    }
    char *buffer = malloc(MANIFEST_MAX_BYTES + 1);
    if (buffer == NULL) {
        fclose(file);
        snprintf(error, error_size, "Manifest 内存不足");
        return -1;
    }
    size_t length = fread(buffer, 1, MANIFEST_MAX_BYTES + 1, file);
    int read_error = ferror(file);
    fclose(file);
    if (read_error || length > MANIFEST_MAX_BYTES) {
        free(buffer);
        snprintf(error, error_size, "Manifest 读取失败或超过 64 KiB");
        return -1;
    }
    buffer[length] = '\0';
    int result = manifest_parse(buffer, length, tracks, error, error_size);
    free(buffer);
    return result;
}
