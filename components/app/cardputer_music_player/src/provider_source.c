#include "provider.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "http.h"
#include "manifest.h"

static int read_access_token(const char *path, char *token, size_t size,
                             char *error, size_t error_size)
{
    if (path == NULL || path[0] != '/') {
        snprintf(error, error_size, "短期 token 文件必须是绝对路径");
        return -1;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        snprintf(error, error_size, "无法读取短期 token 文件: %s",
                 strerror(errno));
        return -1;
    }
    size_t length = fread(token, 1, size, file);
    int read_error = ferror(file);
    fclose(file);
    if (read_error || length == 0U || length >= size) {
        snprintf(error, error_size, "短期 token 文件为空或过大");
        return -1;
    }
    while (length > 0U && isspace((unsigned char)token[length - 1U]))
        length--;
    token[length] = '\0';
    if (length == 0U || strpbrk(token, "\r\n") != NULL) {
        snprintf(error, error_size, "短期 token 格式无效");
        return -1;
    }
    return 0;
}

int provider_load_douyin(const app_config_t *config, track_list_t *tracks,
                         char *error, size_t error_size)
{
    const char *url = config->douyin_broker_url;
    int use_token = 0;
    if (url[0] == '\0') {
        url = config->douyin_api_url;
        use_token = 1;
    }
    if (url[0] == '\0') {
        snprintf(error, error_size,
                 "未配置 douyin_broker_url 或 douyin_api_url");
        return -1;
    }

    http_response_t response;
    int result;
    if (use_token) {
        char token[2049];
        if (read_access_token(config->douyin_access_token_file,
                              token, sizeof(token),
                              error, error_size) != 0)
            return -1;
        result = http_get_access_token(url, token, MANIFEST_MAX_BYTES,
                                       &response, error, error_size);
        memset(token, 0, sizeof(token));
    } else {
        result = http_get(url, MANIFEST_MAX_BYTES, &response,
                          error, error_size);
    }
    if (result != 0)
        return -1;
    if (response.content_type[0] != '\0'
            && strstr(response.content_type, "json") == NULL) {
        snprintf(error, error_size, "抖音 provider Content-Type 不是 JSON");
        http_response_free(&response);
        return -1;
    }
    result = provider_map_douyin((const char *)response.data,
                                 response.size, tracks,
                                 error, error_size);
    http_response_free(&response);
    return result;
}

int provider_apply_resolver(const app_config_t *config,
                            track_list_t *tracks,
                            char *error, size_t error_size)
{
    if (config->resolver_url[0] == '\0')
        return 0;
    http_response_t response;
    if (http_get(config->resolver_url, MANIFEST_MAX_BYTES, &response,
                 error, error_size) != 0)
        return -1;
    if (response.content_type[0] != '\0'
            && strstr(response.content_type, "json") == NULL) {
        snprintf(error, error_size, "resolver Content-Type 不是 JSON");
        http_response_free(&response);
        return -1;
    }
    track_list_t resolutions;
    int result = manifest_parse((const char *)response.data,
                                response.size, &resolutions,
                                error, error_size);
    http_response_free(&response);
    if (result != 0)
        return -1;
    size_t merged = provider_merge_resolutions(tracks, &resolutions);
    fprintf(stderr, "[provider] resolver 授权匹配 %zu/%zu 首\n",
            merged, tracks->count);
    return 0;
}
