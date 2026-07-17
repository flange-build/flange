#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CONFIG_TOKENS_MAX 128

static int token_equals(const char *json, const jsmntok_t *token,
                        const char *value)
{
    size_t length = (size_t)(token->end - token->start);
    return token->type == JSMN_STRING && strlen(value) == length
        && strncmp(json + token->start, value, length) == 0;
}

static int object_value(const char *json, const jsmntok_t *tokens,
                        int count, const char *key)
{
    if (count < 1 || tokens[0].type != JSMN_OBJECT)
        return -1;
    for (int cursor = 1; cursor + 1 < count;) {
        int value = cursor + 1;
        if (token_equals(json, &tokens[cursor], key))
            return value;
        int end = tokens[value].end;
        cursor = value + 1;
        while (cursor < count && tokens[cursor].start < end)
            cursor++;
    }
    return -1;
}

static int copy_string(const char *json, const jsmntok_t *token,
                       char *output, size_t size)
{
    if (token->type != JSMN_STRING || size == 0U)
        return -1;
    size_t written = 0;
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

static int optional_string(const char *json, const jsmntok_t *tokens,
                           int count, const char *key,
                           char *output, size_t size)
{
    int value = object_value(json, tokens, count, key);
    if (value < 0)
        return 0;
    return copy_string(json, &tokens[value], output, size);
}

static int parse_fps(const char *json, const jsmntok_t *tokens,
                     int count, unsigned *fps)
{
    int value = object_value(json, tokens, count, "fps");
    if (value < 0)
        return 0;
    if (tokens[value].type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(tokens[value].end - tokens[value].start);
    if (length == 0U || length >= 8U)
        return -1;
    char buffer[8];
    memcpy(buffer, json + tokens[value].start, length);
    buffer[length] = '\0';
    char *end = NULL;
    unsigned long parsed = strtoul(buffer, &end, 10);
    if (end == buffer || *end != '\0' || parsed < 5U || parsed > 12U)
        return -1;
    *fps = (unsigned)parsed;
    return 0;
}

static int empty_or_https(const char *value)
{
    return value[0] == '\0' || strncmp(value, "https://", 8) == 0;
}

static int valid_manifest_source(const char *value)
{
    return value[0] == '\0' || value[0] == '/'
        || strncmp(value, "file://", 7) == 0
        || strncmp(value, "https://", 8) == 0;
}

void config_defaults(app_config_t *config)
{
    memset(config, 0, sizeof(*config));
    snprintf(config->provider, sizeof(config->provider),
             "netease_official");
    snprintf(config->netease_session_file,
             sizeof(config->netease_session_file),
             "/var/lib/cardputer_music_player/netease-session.json");
    snprintf(config->framebuffer_name, sizeof(config->framebuffer_name),
             "guddrmfb");
    snprintf(config->input_name, sizeof(config->input_name),
             "Cardputer GUD Display");
    snprintf(config->alsa_device, sizeof(config->alsa_device),
             "plughw:CARD=Display,DEV=0");
    snprintf(config->visualizer, sizeof(config->visualizer), "spectrum");
    config->fps = 10U;
}

int config_parse(const char *json, size_t length, app_config_t *config,
                 char *error, size_t error_size)
{
    config_defaults(config);
    if (json == NULL || length == 0U || length > CONFIG_MAX_BYTES) {
        snprintf(error, error_size, "配置文件大小无效");
        return -1;
    }
    jsmn_parser parser;
    jsmntok_t tokens[CONFIG_TOKENS_MAX];
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, length, tokens,
                           CONFIG_TOKENS_MAX);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "配置 JSON 格式无效");
        return -1;
    }
    for (int i = 1; i < count; i++) {
        if (token_equals(json, &tokens[i], "client_secret")) {
            snprintf(error, error_size, "设备配置禁止包含 client_secret");
            return -1;
        }
    }
    if (optional_string(json, tokens, count, "provider",
                        config->provider, sizeof(config->provider)) != 0
            || optional_string(json, tokens, count, "manifest_url",
                               config->manifest_url,
                               sizeof(config->manifest_url)) != 0
            || optional_string(json, tokens, count, "douyin_broker_url",
                               config->douyin_broker_url,
                               sizeof(config->douyin_broker_url)) != 0
            || optional_string(json, tokens, count, "douyin_api_url",
                               config->douyin_api_url,
                               sizeof(config->douyin_api_url)) != 0
            || optional_string(json, tokens, count,
                               "douyin_access_token_file",
                               config->douyin_access_token_file,
                               sizeof(config->douyin_access_token_file)) != 0
            || optional_string(json, tokens, count, "resolver_url",
                               config->resolver_url,
                               sizeof(config->resolver_url)) != 0
            || optional_string(json, tokens, count, "netease_api_url",
                               config->netease_api_url,
                               sizeof(config->netease_api_url)) != 0
            || optional_string(json, tokens, count,
                               "netease_playlist_id",
                               config->netease_playlist_id,
                               sizeof(config->netease_playlist_id)) != 0
            || optional_string(json, tokens, count, "netease_app_id",
                               config->netease_app_id,
                               sizeof(config->netease_app_id)) != 0
            || optional_string(json, tokens, count,
                               "netease_private_key_file",
                               config->netease_private_key_file,
                               sizeof(config->netease_private_key_file)) != 0
            || optional_string(json, tokens, count,
                               "netease_session_file",
                               config->netease_session_file,
                               sizeof(config->netease_session_file)) != 0
            || optional_string(json, tokens, count, "framebuffer_name",
                               config->framebuffer_name,
                               sizeof(config->framebuffer_name)) != 0
            || optional_string(json, tokens, count, "input_name",
                               config->input_name,
                               sizeof(config->input_name)) != 0
            || optional_string(json, tokens, count, "alsa_device",
                               config->alsa_device,
                               sizeof(config->alsa_device)) != 0
            || optional_string(json, tokens, count, "visualizer",
                               config->visualizer,
                               sizeof(config->visualizer)) != 0
            || parse_fps(json, tokens, count, &config->fps) != 0) {
        snprintf(error, error_size, "配置字段类型、长度或 fps 无效");
        return -1;
    }
    if (!valid_manifest_source(config->manifest_url)
            || !empty_or_https(config->douyin_broker_url)
            || !empty_or_https(config->douyin_api_url)
            || !empty_or_https(config->resolver_url)
            || !empty_or_https(config->netease_api_url)
            || (config->netease_private_key_file[0] != '\0'
                && config->netease_private_key_file[0] != '/')
            || config->netease_session_file[0] != '/'
            || (config->douyin_access_token_file[0] != '\0'
                && config->douyin_access_token_file[0] != '/')
            || (strcmp(config->visualizer, "spectrum") != 0
                && strcmp(config->visualizer, "waveform") != 0)) {
        snprintf(error, error_size, "配置 URL、token 路径或可视化模式无效");
        return -1;
    }
    if (config->netease_playlist_id[0] != '\0') {
        for (const char *cursor = config->netease_playlist_id;
             *cursor != '\0'; cursor++) {
            if (*cursor < '0' || *cursor > '9') {
                snprintf(error, error_size,
                         "netease_playlist_id 必须是十进制数字");
                return -1;
            }
        }
    }
    return 0;
}

int config_load_file(const char *path, app_config_t *config,
                     char *error, size_t error_size)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        snprintf(error, error_size, "无法打开配置: %s", strerror(errno));
        return -1;
    }
    char *buffer = malloc(CONFIG_MAX_BYTES + 1U);
    if (buffer == NULL) {
        fclose(file);
        snprintf(error, error_size, "配置内存不足");
        return -1;
    }
    size_t length = fread(buffer, 1, CONFIG_MAX_BYTES + 1U, file);
    int read_error = ferror(file);
    fclose(file);
    if (read_error || length == 0U || length > CONFIG_MAX_BYTES) {
        free(buffer);
        snprintf(error, error_size, "配置文件读取失败或过大");
        return -1;
    }
    buffer[length] = '\0';
    int result = config_parse(buffer, length, config, error, error_size);
    free(buffer);
    return result;
}
